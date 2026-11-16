"""T1-414 — ein Handelskonto je Verbindung.

Fall 2026-11-16: ein Login mit sechs Konten. Der Depotwert kam aus dem zuletzt
gelesenen Konto (1 Mio. EUR), die Order ging ohne `order.account` ins
TWS-Standardkonto (rund 50.000 EUR). Diese Zusicherungen halten fest:

- die Bridge liest Kapital und Positionen nur aus dem Handelskonto,
- sie setzt `order.account`, sobald eines feststeht,
- sie fuehrt keinen Auftrag aus, der fuer ein anderes Konto gerechnet wurde,
- fremde Ausfuehrungen anderer Konten meldet sie nicht,
- ohne Vorgabe bleibt alles wie bisher (T1-306: bei mehreren Konten wird nie
  geraten).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from ordertune_bridge_ibkr import main as m
from ordertune_bridge_ibkr.external_executions import external_execution_bodies
from ordertune_bridge_ibkr.ibkr_client import IbkrClient
from ordertune_bridge_ibkr.submitted_store import SubmittedStore
from ordertune_bridge_ibkr.trading_account import (
    ZIEL_ABWEISEN,
    ZIEL_WARTEN,
    antwort_aus_json,
    pruefe_zielkonto,
    waehle_handelskonto,
)

SECHS = ["DUR349111", "DUR349112", "DUR349113", "DUR349114", "DUR349115", "DUR349116"]


# ── reine Regeln ─────────────────────────────────────────────────────────────


def test_ohne_vorgabe_bei_mehreren_konten_wird_nicht_geraten() -> None:
    assert waehle_handelskonto(SECHS, None) is None


def test_ein_konto_ohne_vorgabe_ist_dieses() -> None:
    assert waehle_handelskonto(["U7712482"], None) == "U7712482"


def test_vorgabe_im_login_gilt() -> None:
    assert waehle_handelskonto(SECHS, "DUR349111") == "DUR349111"


def test_vorgabe_nicht_im_login_faellt_auf_die_alte_regel_zurueck() -> None:
    assert waehle_handelskonto(SECHS, "U7712482") is None
    assert waehle_handelskonto(["U7712482"], "DUR349111") == "U7712482"


def test_heartbeat_antwort_unterscheidet_schweigen_und_null() -> None:
    assert antwort_aus_json({"ok": True}).konto_gemeldet is False
    leer = antwort_aus_json({"ok": True, "tradingAccountId": None})
    assert leer.konto_gemeldet is True and leer.konto is None
    gesetzt = antwort_aus_json({"tradingAccountId": "DUR349111"})
    assert gesetzt.konto == "DUR349111"
    assert antwort_aus_json(None).konto_gemeldet is False


def test_zielkonto() -> None:
    assert pruefe_zielkonto(None, None)[0] is None  # Plattform vor T1-414
    assert pruefe_zielkonto("DUR349111", "DUR349111")[0] is None
    assert pruefe_zielkonto("DUR349111", "U7712482")[0] == ZIEL_ABWEISEN
    assert pruefe_zielkonto("DUR349111", None)[0] == ZIEL_WARTEN


def test_ablehnungstext_maskiert() -> None:
    _, text = pruefe_zielkonto("DUR349111", "U7712482")
    assert "DUR349111" not in text and "U7712482" not in text


# ── IbkrClient liest nur das Handelskonto ────────────────────────────────────


@dataclass
class _Wert:
    account: str
    tag: str
    value: str
    currency: str


class _FakeIB:
    def __init__(self) -> None:
        self.werte = [
            _Wert("DUR349111", "NetLiquidation", "52320", "EUR"),
            _Wert("DUR349111", "TotalCashValue", "31040", "EUR"),
            _Wert("DUR349112", "NetLiquidation", "1000055", "EUR"),
            _Wert("DUR349112", "TotalCashValue", "1000055", "EUR"),
        ]
        self.positionen_abgefragt_fuer: list[Any] = []

    def managedAccounts(self) -> list[str]:
        return ["DUR349111", "DUR349112"]

    def accountValues(self) -> list[_Wert]:
        return list(self.werte)

    def isConnected(self) -> bool:
        return True


def _client(fake: _FakeIB) -> IbkrClient:
    c = IbkrClient.__new__(IbkrClient)
    c._ib = fake  # type: ignore[assignment]
    c._vorgabe_konto = None
    c._vorgabe_gewarnt = None
    return c


def test_trading_account_folgt_der_vorgabe() -> None:
    c = _client(_FakeIB())
    assert c.trading_account() is None
    c.set_trading_account("DUR349111")
    assert c.trading_account() == "DUR349111"
    c.set_trading_account(None)
    assert c.trading_account() is None


def test_kontowerte_nur_aus_dem_handelskonto(monkeypatch: Any) -> None:
    fake = _FakeIB()
    c = _client(fake)
    c.set_trading_account("DUR349111")
    gesehen: list[list[_Wert]] = []

    def _waehrung(werte: list[_Wert]) -> str:
        gesehen.append(werte)
        return "EUR"

    monkeypatch.setattr("ordertune_bridge_ibkr.ibkr_client.resolve_account_currency", _waehrung)
    monkeypatch.setattr(
        "ordertune_bridge_ibkr.ibkr_client.loese_kurs_auf",
        lambda werte, waehrung: SimpleNamespace(kurs=1.08),
    )
    monkeypatch.setattr(IbkrClient, "_log_account_currency", lambda *a, **k: None)
    monkeypatch.setattr(IbkrClient, "_log_fx", lambda *a, **k: None)
    monkeypatch.setattr(IbkrClient, "_positions", lambda self: [])
    monkeypatch.setattr(IbkrClient, "_account_metrics", lambda *a, **k: None)

    snap = c.account_snapshot()

    assert snap.equity == 52320.0, "Depotwert muss aus dem Handelskonto kommen"
    assert snap.cash == 31040.0
    assert snap.account == "DUR349111"
    assert all(w.account == "DUR349111" for w in gesehen[0])


# ── fremde Ausfuehrungen ─────────────────────────────────────────────────────


def _fill(exec_id: str, konto: str) -> Any:
    return SimpleNamespace(
        execution=SimpleNamespace(
            execId=exec_id,
            permId=f"p{exec_id}",
            acctNumber=konto,
            side="BOT",
            shares=10,
            price=100.0,
            time="2026-11-16T15:00:00+00:00",
            orderRef="",
        ),
        contract=SimpleNamespace(symbol="NBIS"),
        commissionReport=SimpleNamespace(commission=1.0, execId=exec_id),
    )


def test_fremde_ausfuehrungen_nur_des_handelskontos() -> None:
    fills = [_fill("e1", "DUR349111"), _fill("e2", "DUR349112")]
    alle = external_execution_bodies(fills, {}, set())
    nur = external_execution_bodies(fills, {}, set(), nur_konto="DUR349111")
    assert len(alle) == 2, "ohne Handelskonto wie bisher alle Konten"
    assert [b["brokerAccountId"] for b in nur] == ["DUR349111"]


# ── Sendeweg ─────────────────────────────────────────────────────────────────


class _Ibkr:
    def __init__(self, konto: str | None) -> None:
        self.konto = konto
        self.platziert: list[Any] = []

    def trading_account(self) -> str | None:
        return self.konto

    def get_live_equity(self) -> float:
        return 0.0

    def place_order(self, contract: Any, order: Any) -> Any:
        self.platziert.append(order)
        return SimpleNamespace(
            order=SimpleNamespace(orderId=4711 + len(self.platziert)),
            orderStatus=SimpleNamespace(status="PreSubmitted", filled=0),
            log=[],
        )


def _api(intent: dict[str, Any]):
    results: list[dict[str, Any]] = []

    class Api:
        def get_pending(self):
            return SimpleNamespace(
                server_time="",
                pending=[
                    SimpleNamespace(
                        dispatch_id="disp-1",
                        order_intent=intent,
                        expires_at=None,
                        cancel_requested=False,
                    )
                ],
                cancelling=[],
            )

        def ack_order(self, dispatch_id, *, broker_order_id, submitted_at):
            pass

        def result_order(self, dispatch_id, **kwargs):
            results.append({"dispatchId": dispatch_id, **kwargs})

    return Api(), results


_INTENT = {
    "symbol": "NBIS",
    "side": "buy",
    "qty": 1,
    "orderType": "day_limit",
    "lmtPrice": 98.5,
}


def test_order_traegt_das_handelskonto(tmp_path: Any) -> None:
    api, results = _api({**_INTENT, "targetAccountId": "DUR349111"})
    ibkr = _Ibkr("DUR349111")
    m._handle_pending(api, ibkr, {}, SubmittedStore(tmp_path))
    assert len(ibkr.platziert) == 1
    assert ibkr.platziert[0].account == "DUR349111"
    assert results == []


def test_order_fuer_anderes_konto_wird_abgewiesen_samt_kindern(tmp_path: Any) -> None:
    intent = {
        **_INTENT,
        "targetAccountId": "DUR349111",
        "attachedExits": [
            {
                "dispatchId": "kind-1",
                "side": "sell",
                "orderType": "stop",
                "qty": 1,
                "lmtPrice": 90.0,
            },
        ],
    }
    api, results = _api(intent)
    ibkr = _Ibkr("U7712482")
    m._handle_pending(api, ibkr, {}, SubmittedStore(tmp_path))
    assert ibkr.platziert == []
    assert {r["dispatchId"] for r in results} == {"disp-1", "kind-1"}
    assert all(r["status"] == "rejected" for r in results)
    assert all("account_mismatch" in r["error_message"] for r in results)


def test_unbekanntes_handelskonto_haelt_den_auftrag(tmp_path: Any) -> None:
    api, results = _api({**_INTENT, "targetAccountId": "DUR349111"})
    ibkr = _Ibkr(None)
    m._handle_pending(api, ibkr, {}, SubmittedStore(tmp_path))
    assert ibkr.platziert == []
    assert results == [], "keine endgueltige Ablehnung, nur liegen lassen"


def test_alte_plattform_ohne_zielkonto_wie_bisher(tmp_path: Any) -> None:
    api, _results = _api(dict(_INTENT))
    ibkr = _Ibkr(None)
    m._handle_pending(api, ibkr, {}, SubmittedStore(tmp_path))
    assert len(ibkr.platziert) == 1
    assert ibkr.platziert[0].account == "", "ohne Handelskonto kein order.account (T1-306)"


def test_heartbeat_antwort_setzt_das_handelskonto() -> None:
    gesetzt: list[str | None] = []
    ibkr = SimpleNamespace(set_trading_account=gesetzt.append)
    for antwort in (antwort_aus_json({}), antwort_aus_json({"tradingAccountId": "DUR349111"})):
        if antwort.konto_gemeldet:
            ibkr.set_trading_account(antwort.konto)
    assert gesetzt == ["DUR349111"]
    src = Path(m.__file__).read_text(encoding="utf-8")
    assert "if antwort.konto_gemeldet:\n            ibkr.set_trading_account(antwort.konto)" in src
