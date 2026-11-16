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
from types import SimpleNamespace
from typing import Any

from ordertune_bridge_ibkr.external_executions import external_execution_bodies
from ordertune_bridge_ibkr.ibkr_client import IbkrClient
from ordertune_bridge_ibkr.trading_account import (
    antwort_aus_json,
    maskiere,
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
    assert pruefe_zielkonto(None, None) is None  # Plattform vor T1-414
    assert pruefe_zielkonto("DUR349111", "DUR349111") is None
    assert pruefe_zielkonto("DUR349111", "U7712482") is not None
    assert pruefe_zielkonto("DUR349111", None) is not None


def test_ablehnungstext_maskiert() -> None:
    text = pruefe_zielkonto("DUR349111", "U7712482") or ""
    assert "DUR349111" not in text and "U7712482" not in text
    assert maskiere("DUR349111") == "DUR…9111"


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
