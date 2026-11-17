"""T1-421 — Kurs und Marktwert auch bei mehreren Konten im Login.

Fall 2026-11-17 (Paper-Login mit sechs Konten, Bridge 0.36.0): Handelskonto
gewählt, 16 Positionen gemeldet, aber ohne `marketValueUsd` und `lastPrice`.
ib_insync abonniert `reqAccountUpdates` beim Verbinden nur bei genau EINEM
Konto; bei mehreren läuft nur der Multi-Kanal, und der füllt `portfolio()`
nicht. Ohne Portfolio-Zeilen fehlt die Anreicherung, und die Plattform zeigt
Wert, Gewicht und unrealisiertes Ergebnis als „—“.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from ordertune_bridge_ibkr.ibkr_client import IbkrClient

KONTO = "DUR349111"
ANDERES = "DUR349112"


def _pos(konto: str, symbol: str, con_id: int, menge: float) -> Any:
    return SimpleNamespace(
        account=konto,
        contract=SimpleNamespace(symbol=symbol, conId=con_id, currency="USD"),
        position=menge,
        avgCost=100.0,
    )


def _item(konto: str, con_id: int, preis: float, wert: float) -> Any:
    return SimpleNamespace(
        account=konto,
        contract=SimpleNamespace(conId=con_id),
        marketPrice=preis,
        marketValue=wert,
        unrealizedPNL=1.0,
    )


class _FakeIB:
    """Wie ib_insync: `portfolio(konto)` liest nur, was `reqAccountUpdates` füllte."""

    def __init__(self, abonniert: bool = False) -> None:
        self.abos: list[str] = []
        self._portfolio: dict[str, list[Any]] = {}
        self._verfuegbar = {
            KONTO: [_item(KONTO, 1, 120.0, 960.0)],
            ANDERES: [_item(ANDERES, 1, 999.0, 99_900.0)],
        }
        if abonniert:
            self._portfolio[KONTO] = self._verfuegbar[KONTO]

    def managedAccounts(self) -> list[str]:
        return [KONTO, ANDERES]

    def positions(self, account: str = "") -> list[Any]:
        alle = [_pos(KONTO, "BBY", 1, 8), _pos(ANDERES, "BBY", 1, 100)]
        return [p for p in alle if not account or p.account == account]

    def portfolio(self, account: str = "") -> list[Any]:
        if account:
            return list(self._portfolio.get(account, []))
        return [i for liste in self._portfolio.values() for i in liste]

    async def reqAccountUpdatesAsync(self, account: str) -> None:
        self.abos.append(account)
        self._portfolio[account] = self._verfuegbar[account]

    def run(self, aw: Any, timeout: float | None = None) -> Any:
        try:
            aw.send(None)
        except StopIteration as stop:
            return stop.value
        return None


def _client(fake: _FakeIB) -> IbkrClient:
    c = IbkrClient.__new__(IbkrClient)
    c._ib = fake  # type: ignore[assignment]
    c._vorgabe_konto = KONTO
    c._vorgabe_gewarnt = None
    c._positions_known = True
    c._multi_account_warned = False
    c._portfolio_abo_konto = None
    return c


def test_mehrere_konten_ohne_abo_holt_das_portfolio_des_handelskontos() -> None:
    fake = _FakeIB(abonniert=False)
    rows = _client(fake)._positions()
    assert rows is not None and len(rows) == 1
    assert rows[0]["market_value"] == 960.0, "Marktwert fehlt ohne Konto-Abo"
    assert rows[0]["market_price"] == 120.0
    assert fake.abos == [KONTO]


def test_anreicherung_nur_aus_dem_handelskonto() -> None:
    fake = _FakeIB(abonniert=True)
    fake._portfolio[ANDERES] = fake._verfuegbar[ANDERES]
    rows = _client(fake)._positions()
    assert rows is not None
    assert rows[0]["market_value"] == 960.0, "gleiche conId im anderen Konto darf nicht gewinnen"


def test_abo_nur_einmal_je_konto() -> None:
    fake = _FakeIB(abonniert=False)
    fake._verfuegbar[KONTO] = []
    c = _client(fake)
    c._positions()
    c._positions()
    assert fake.abos == [KONTO]
