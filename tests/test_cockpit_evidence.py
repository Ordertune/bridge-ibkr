"""T1-101 B-3 bis B-5 — Belegspur, Fehlerkarte, Diagnose.

Drei Zusagen, die hier belegt werden:

  * Die Auftragsliste spricht das Vokabular von T1-100 und traegt IBKRs
    eigenen Ablehnungsgrund aus T1-102.
  * Eine Stoerung im Betrieb wird genauso zugeordnet wie eine beim Start —
    Konsole und Flaeche sagen ueber dieselbe Sache dasselbe.
  * Die Diagnose enthaelt kein Geheimnis. Sie ist zum Weiterschicken gedacht.
"""
from __future__ import annotations

import json
import logging
import urllib.request
from types import SimpleNamespace

import httpx
import pytest

from ordertune_bridge_ibkr import main as m
from ordertune_bridge_ibkr.cockpit import CockpitServer, CockpitState, StateStore
from ordertune_bridge_ibkr.cockpit import journal as journal_mod

# ── B-3: die Auftragsliste ───────────────────────────────────────────────────


def _trade(symbol: str, status: str, action: str = "BUY", qty: float = 2,
           log_entries=()) -> SimpleNamespace:
    return SimpleNamespace(
        order=SimpleNamespace(action=action, totalQuantity=qty, orderId=1, orderRef=""),
        contract=SimpleNamespace(symbol=symbol),
        orderStatus=SimpleNamespace(status=status),
        log=list(log_entries),
    )


@pytest.fixture(autouse=True)
def _leere_ablage():
    m._TRADES_BY_DISPATCH.clear()
    yield
    m._TRADES_BY_DISPATCH.clear()


def test_the_order_list_speaks_the_t1_vocabulary() -> None:
    m._TRADES_BY_DISPATCH["9948c645-c094-4477-84f4-c7acdbeb2bb6"] = _trade("MU", "Submitted")

    zeile = m.orders_for_cockpit()[0]

    assert zeile["status"] == "At broker", (
        "IBKR sagt `Submitted`, t1 sagt `At broker`. Zwei Flaechen, die ueber "
        "dieselbe Sache verschieden reden, sind genau der Zustand, den T1-100 "
        "beseitigt hat."
    )
    assert zeile["symbol"] == "MU"
    assert zeile["action"] == "BUY"


def test_a_rejection_carries_ibkrs_own_words() -> None:
    """T1-102: der Satz, der die Frage des Nutzers vollstaendig beantwortet."""
    grund = (
        "Order abgewiesen - Grund:Verfuegbare Mittel in Basiswaehrung: 1037.11 "
        "USD Barmittel fuer diese und weitere offene Orders benoetigt: 1418.40 USD"
    )
    m._TRADES_BY_DISPATCH["9948c645-c094-4477-84f4-c7acdbeb2bb6"] = _trade(
        "CRWD", "Inactive",
        log_entries=[SimpleNamespace(errorCode=201, message=grund)],
    )

    zeile = m.orders_for_cockpit()[0]

    assert zeile["status"] == "Rejected", (
        "Ein `Inactive` nach einer Ablehnung ist kein lebender Auftrag, "
        "sondern die Leiche — genau der Befund aus T1-102 A."
    )
    assert zeile["reason"] == grund


def test_an_unknown_ibkr_state_never_leaks_as_jargon() -> None:
    m._TRADES_BY_DISPATCH["9948c645-c094-4477-84f4-c7acdbeb2bb6"] = _trade("AVGO", "IrgendwasNeues")
    assert m.orders_for_cockpit()[0]["status"] == "Unknown"


def test_without_a_connection_the_list_is_absent_not_empty() -> None:
    """Dieselbe Unterscheidung wie bei den Positionen in T1-99."""
    store = StateStore()
    m.report_heartbeat(SimpleNamespace(store=store), False, None)
    assert store.get()[0].orders is None


def test_with_a_connection_and_no_orders_the_list_is_empty() -> None:
    store = StateStore()
    m.report_heartbeat(
        SimpleNamespace(store=store), True,
        SimpleNamespace(cash=1.0, equity=2.0, currency="USD", positions=[]),
    )
    assert store.get()[0].orders == []


# ── B-4: die Fehlerkarte ─────────────────────────────────────────────────────


def _http_error(status: int, code: str) -> httpx.HTTPStatusError:
    request = httpx.Request("PUT", "https://t1.ordertune.com/api/bridge/v1/heartbeat")
    response = httpx.Response(
        status, text=json.dumps({"error": {"code": code, "message": "x"}}), request=request
    )
    return httpx.HTTPStatusError("boom", request=request, response=response)


def test_a_revoked_token_at_runtime_is_told_apart_from_a_dead_network() -> None:
    """Beide sehen als „der Herzschlag kam nicht durch" gleich aus und
    verlangen Verschiedenes."""
    store_a, store_b = StateStore(), StateStore()

    m.report_heartbeat(SimpleNamespace(store=store_a), True, None,
                       _http_error(401, "connection_revoked"))
    m.report_heartbeat(SimpleNamespace(store=store_b), True, None,
                       httpx.ConnectError("no route"))

    assert store_a.get()[0].failure_code == "connection_revoked"
    assert store_b.get()[0].failure_code == "platform_unreachable"


def test_the_card_carries_a_sentence_and_an_action() -> None:
    store = StateStore()
    m.report_heartbeat(SimpleNamespace(store=store), True, None,
                       _http_error(403, "fingerprint_mismatch"))

    state, _ = store.get()
    assert "different hardware" in state.failure_headline
    assert any("Rotate the token" in z for z in state.failure_action)


def test_a_recovered_heartbeat_clears_the_card() -> None:
    """Sonst bleibt eine Stoerung stehen, die es nicht mehr gibt."""
    store = StateStore(CockpitState(failure_code="platform_unreachable",
                                    failure_headline="alt"))
    m.report_heartbeat(
        SimpleNamespace(store=store), True,
        SimpleNamespace(cash=1.0, equity=2.0, currency="USD", positions=[]),
    )
    assert store.get()[0].failure_code is None


# ── B-5: Protokoll und Diagnose ──────────────────────────────────────────────


def test_the_journal_is_capped() -> None:
    """`LOG_LEVEL=DEBUG` ueber Tage darf kein Speicherleck sein."""
    j = journal_mod.Journal(maxlen=10)
    j.setFormatter(logging.Formatter("%(message)s"))
    for i in range(50):
        j.emit(logging.LogRecord("x", logging.INFO, "f", 1, "Zeile %d", (i,), None))
    assert len(j.lines()) == 10
    assert j.lines()[-1] == "Zeile 49"


def test_the_journal_never_throws_upwards() -> None:
    """Es haengt an der Wurzel und saehe damit jeden `log.*`-Aufruf im Programm."""
    j = journal_mod.Journal()
    j.setFormatter(logging.Formatter("%(kaputt)s"))
    j.emit(logging.LogRecord("x", logging.INFO, "f", 1, "hallo", (), None))


def test_the_log_and_diagnostics_are_served_without_secrets() -> None:
    j = journal_mod.Journal()
    j.setFormatter(logging.Formatter("%(message)s"))
    j.emit(logging.LogRecord("x", logging.INFO, "f", 1, "eine Zeile", (), None))

    srv = CockpitServer(
        StateStore(CockpitState(bridge_version="0.8.0")),
        journal=j,
        diagnostics=lambda: {"bridgeVersion": "0.8.0", "clientId": 17},
    )
    srv.start()
    try:
        def hole(pfad: str) -> dict:
            url = f"http://127.0.0.1:{srv.port}{pfad}?t={srv.token}"
            with urllib.request.urlopen(url, timeout=5) as r:
                return json.loads(r.read().decode())

        assert hole("/log")["lines"] == ["eine Zeile"]

        diag = hole("/diagnostics")
        assert diag["clientId"] == 17
        assert diag["log"] == ["eine Zeile"]

        roh = json.dumps(diag)
        assert srv.token not in roh, (
            "Copy diagnostics landet als Naechstes in einem Chat oder einer "
            "E-Mail. Ein Geheimnis, das den Weg nimmt, ist keins mehr."
        )
        assert "ordertune_bridge_token" not in roh
    finally:
        srv.stop()
