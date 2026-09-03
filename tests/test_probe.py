"""T1-94-Sonde: sie fragt, sie horcht nicht — und sie schickt nichts.

Am 2026-08-15 blieb das Protokoll leer, nachdem die Master API client ID auf 17
stand und der Owner von Hand eine Order gestellt hatte. Nicht einmal eine
Fehlermeldung. Die Sonde klaert, ob die Auskunft ueberhaupt erreichbar ist,
wenn man danach fragt statt darauf zu warten.

Geprueft wird hier alles, was ohne TWS pruefbar ist: die Erkennung des
Schalters, die Zuordnung eigener gegen fremde Auftraege, die Angaben, an denen
T1-94 haengt, und die Zusage, dass ein ausgefallener Abruf die anderen nicht
mitreisst.
"""
from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import pytest

from ordertune_bridge_ibkr import main as m
from ordertune_bridge_ibkr import probe


# ── Der Schalter ─────────────────────────────────────────────────────────────


def test_the_flag_is_recognised() -> None:
    assert probe.probe_requested(["--probe-foreign"]) is True
    assert probe.probe_requested(["--verbose", "--probe-foreign"]) is True


def test_without_the_flag_the_bridge_runs_normally() -> None:
    assert probe.probe_requested([]) is False
    assert probe.probe_requested(["--probe"]) is False, (
        "Eine Teilzeichenkette darf die Sonde nicht ausloesen — sonst startet "
        "jemand die Bridge und sie liest nur."
    )


# ── Eigen gegen fremd ────────────────────────────────────────────────────────


def test_our_own_orders_carry_the_mark() -> None:
    assert probe.is_ours("ot-8f1d2c3e-4a5b-6c7d-8e9f-0a1b2c3d4e5f") is True


@pytest.mark.parametrize("ref", [None, "", "manual", "OT-gross", "xot-1"])
def test_everything_else_is_foreign(ref: Any) -> None:
    """Ohne unseren Vermerk gehoert der Auftrag uns nicht.

    Auch die Grossschreibung nicht: `orderRef` wird von uns kleingeschrieben
    gesetzt, und eine grosszuegige Pruefung wuerde einen fremden Auftrag als
    eigenen ausweisen — genau die Verwechslung, die T1-94 vermeiden muss.
    """
    assert probe.is_ours(ref) is False


# ── Die Angaben, an denen T1-94 haengt ───────────────────────────────────────


def _fremder_auftrag() -> SimpleNamespace:
    return SimpleNamespace(
        contract=SimpleNamespace(symbol="TXN"),
        order=SimpleNamespace(
            action="BUY", orderType="MKT", totalQuantity=1.0, lmtPrice=0.0,
            tif="DAY", orderId=61, clientId=0, permId=421610881, orderRef="",
        ),
        orderStatus=SimpleNamespace(status="Cancelled", filled=0.0),
    )


def test_a_foreign_order_is_marked_as_foreign() -> None:
    zeile = probe.describe_trade(_fremder_auftrag())
    assert "[FOREIGN]" in zeile
    assert "TXN" in zeile
    # Ohne diese vier ist eine fremde Zeile nicht buchbar.
    for feld in ("qty=1.0", "status=Cancelled", "orderId=61", "permId=421610881"):
        assert feld in zeile, feld


def test_one_of_ours_is_marked_as_ours() -> None:
    auftrag = _fremder_auftrag()
    auftrag.order.orderRef = "ot-5b394724-9b7c-4928-8fc3-16850bd06534"
    assert "[OURS" in probe.describe_trade(auftrag)


def _fremde_ausfuehrung(commission: float = 1.9) -> SimpleNamespace:
    """Die gemessene FTNT-Ausfuehrung vom 2026-08-17."""
    return SimpleNamespace(
        contract=SimpleNamespace(symbol="FTNT"),
        execution=SimpleNamespace(
            side="BOT", shares=1.0, price=157.21,
            time="2026-08-17 13:49:53+00:00",
            orderId=0, clientId=0, permId=1433603962,
            execId="00015963.6a82ffde.01.01", orderRef="",
        ),
        commissionReport=SimpleNamespace(commission=commission),
    )


def test_a_fill_carries_what_an_external_row_would_need() -> None:
    """Herkunft, Menge, Kurs, Zeitpunkt, Gebuehr."""
    zeile = probe.describe_fill(_fremde_ausfuehrung())
    assert "[FOREIGN]" in zeile
    for feld in ("shares=1.0", "price=157.21", "time=", "commission=1.9"):
        assert feld in zeile, feld


def test_the_commission_is_read_after_the_grace_period() -> None:
    """Der Fehler vom 2026-08-17: `commission=0.0` war kein Messwert.

    `reqExecutions()` liefert die Ausfuehrung, die Gebuehrenabrechnung kommt
    als eigenes, spaeteres Ereignis und wird von `wrapper.commissionReport`
    nachtraeglich in dasselbe Fill-Objekt geschrieben. Wer sofort liest, sieht
    den Feld-Default 0.0 und haelt ihn fuer eine gemessene Null.

    Die Sonde ruft deshalb ab, wartet, und liest dann aus `fills()`.
    """
    ibkr = FakeIbkr()
    probe.run_probe(ibkr)

    assert ibkr.geschlafen == probe.COMMISSION_GRACE_S
    assert ibkr.aufgerufen.index("sleep") > ibkr.aufgerufen.index("executions")
    assert ibkr.aufgerufen.index("fills") > ibkr.aufgerufen.index("sleep")


# ── Verhalten der Sonde ──────────────────────────────────────────────────────


class FakeIbkr:
    """Antwortet auf die drei Abrufe. `fehler` laesst einen davon ausfallen."""

    def __init__(self, fehler: str | None = None) -> None:
        self.fehler = fehler
        self.aufgerufen: list[str] = []
        self.api_only_wert: Any = "nicht aufgerufen"
        self.geschlafen: float | None = None

    def _vielleicht(self, name: str) -> None:
        self.aufgerufen.append(name)
        if self.fehler == name:
            raise RuntimeError(f"TWS verweigert {name}")

    def all_open_trades(self) -> list[Any]:
        self._vielleicht("all_open_trades")
        return [_fremder_auftrag()]

    def completed_trades(self, api_only: bool = False) -> list[Any]:
        self._vielleicht("completed_trades")
        self.api_only_wert = api_only
        return []

    def executions(self) -> list[Any]:
        self._vielleicht("executions")
        # Wie bei IBKR: der Abruf liefert die Ausfuehrung OHNE Gebuehr.
        return [_fremde_ausfuehrung(commission=0.0)]

    def sleep(self, seconds: float) -> None:
        self._vielleicht("sleep")
        self.geschlafen = seconds

    def fills(self) -> list[Any]:
        self._vielleicht("fills")
        # Und danach steht sie daran — dasselbe Objekt, nachtraeglich befuellt.
        return [_fremde_ausfuehrung(commission=1.9)]


def test_the_probe_asks_all_three_channels(caplog: pytest.LogCaptureFixture) -> None:
    ibkr = FakeIbkr()
    with caplog.at_level(logging.INFO):
        probe.run_probe(ibkr)

    assert ibkr.aufgerufen == [
        "all_open_trades",
        "completed_trades",
        "executions",
        "sleep",
        "fills",
    ]
    assert ibkr.api_only_wert is False, (
        "Mit apiOnly=True fielen genau die von Hand gestellten Auftraege heraus "
        "— also das, wonach gesucht wird."
    )


def test_a_refused_channel_does_not_take_the_others_down(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Eine Verweigerung ist selbst ein Ergebnis und darf den Rest nicht kosten."""
    ibkr = FakeIbkr(fehler="all_open_trades")
    with caplog.at_level(logging.INFO):
        probe.run_probe(ibkr)

    assert ibkr.aufgerufen[:3] == ["all_open_trades", "completed_trades", "executions"]
    assert any("ist gescheitert" in r.getMessage() for r in caplog.records)


def test_the_probe_never_sends_anything() -> None:
    """Die Zusage, die den ganzen Entwurf traegt: nur lesen.

    Ein Fake ohne Schreibmethoden. Griffe die Sonde nach `place_order` oder
    `cancel_order`, schluege der Aufruf hier fehl statt in der Produktion.
    """
    ibkr = FakeIbkr()
    probe.run_probe(ibkr)
    assert not hasattr(ibkr, "place_order")
    assert not hasattr(ibkr, "cancel_order")


# ── Was die Messung vom 2026-08-15 zugesichert haben will ────────────────────
#
# Der von Hand gestellte TXN-Auftrag kam so zurueck:
#
#   [FOREIGN] TXN BUY MKT qty=1.0 status=PendingCancel
#             orderId=0 clientId=0 permId=1960849477 orderRef=''
#
# **orderId 0.** TWS vergibt fuer fremde Auftraege keine API-Auftragsnummer.
# Damit traegt JEDER fremde Auftrag dieselbe 0 — und `dispatch_id_map` ist
# genau darueber geschluesselt. Stuende die 0 je als Schluessel darin, zeigte
# jeder fremde Auftrag auf denselben Dispatch, und eine fremde Ausfuehrung
# wuerde gegen ein Signal von uns gemeldet. Mit Echtgeld.
#
# `register_trade` haelt die 0 heraus. Das war bisher eine beilaeufige
# Bedingung ohne Zusicherung; seit der Messung ist es die tragende.


def _fremder_trade_wie_gemessen() -> SimpleNamespace:
    return SimpleNamespace(
        order=SimpleNamespace(orderId=0, clientId=0, permId=1960849477, orderRef=""),
        orderStatus=SimpleNamespace(
            status="PendingCancel", filled=0.0, avgFillPrice=0.0
        ),
        log=[SimpleNamespace(status="PendingCancel", message="", errorCode=0)],
        fills=[],
    )


def test_zero_never_becomes_a_key_in_the_dispatch_map() -> None:
    dispatch_id_map: dict[int, str] = {}
    m.register_trade(dispatch_id_map, "disp-1", _fremder_trade_wie_gemessen())

    assert 0 not in dispatch_id_map, (
        "Jeder fremde TWS-Auftrag traegt orderId 0. Als Schluessel wuerde die 0 "
        "sie alle auf denselben Dispatch zeigen lassen."
    )


def test_a_foreign_order_status_is_reported_to_nobody() -> None:
    """Die Zusage aus der Sonde: fremde Auftraege werden nicht gemeldet.

    Waehrend der Messung hat `reqAllOpenOrders` ein `orderStatus`-Ereignis fuer
    den fremden Auftrag ausgeloest. Mit laufender Bridge waere es beim Rueckruf
    angekommen — und muss dort folgenlos bleiben, solange T1-94 nicht gebaut
    ist.
    """
    api = FakeApi()
    on_status = m._make_on_order_status(api, None, {59: "d-eigen"})

    on_status(_fremder_trade_wie_gemessen())

    assert api.calls == []


class FakeApi:
    def __init__(self) -> None:
        self.calls: list[Any] = []

    def result_order(self, dispatch_id: str, **kwargs: Any) -> None:
        self.calls.append({"dispatchId": dispatch_id, **kwargs})
