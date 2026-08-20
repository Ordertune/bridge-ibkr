"""T1-99: der Depotbestand kommt aus der Quelle, die nicht schweigt.

## Woher dieser Test kommt

Am 2026-08-18 standen im Order Management zwei ueber Ordertune entstandene
Positionen (CSCO, MU) unter „Held outside Ordertune". Sie standen dort nicht,
weil die Anzeige falsch sortierte, sondern weil ihre Lots geschlossen worden
waren — als „extern verkauft", eine Minute bevor sich die Bridge verband.

Die Kette: `account_snapshot` las das Depot aus `portfolio()`, gespeist aus dem
Konto-Abo. Genau dieses Abo lief in einen Zeitueberlauf:

    [ERROR] ib_insync.ib: account updates for U23076419 request timed out

`positions()` — ein anderer Kanal, gespeist aus `reqPositions` — war zu diesem
Zeitpunkt gefuellt. Die Bridge las ausgerechnet den leeren, meldete eine leere
Positionsliste, und die Plattform las das regelkonform als „das Konto haelt
nichts".

Diese Zusicherungen nageln beide Haelften fest: die Quelle, und den
Unterschied zwischen „leer" und „unbekannt".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ordertune_bridge_ibkr.ibkr_client import IbkrClient


@dataclass
class FakeContract:
    symbol: str
    conId: int


@dataclass
class FakePosition:
    contract: FakeContract
    position: float
    avgCost: float
    account: str = "U23076419"


@dataclass
class FakePortfolioItem:
    contract: FakeContract
    position: float
    averageCost: float
    marketPrice: float
    marketValue: float
    unrealizedPNL: float


@dataclass
class FakeIB:
    """Nur die Methoden, die der Schnappschuss anfasst."""

    _positions: list[FakePosition] = field(default_factory=list)
    _portfolio: list[FakePortfolioItem] = field(default_factory=list)
    _account_values: list[Any] = field(default_factory=list)
    _accounts: list[str] = field(default_factory=lambda: ["U23076419"])
    portfolio_raises: bool = False
    #: Womit `positions()` aufgerufen wurde — BUG-99-1 prueft genau das.
    positions_called_with: list[str] = field(default_factory=list)

    def managedAccounts(self) -> list[str]:
        return self._accounts

    def positions(self, account: str = "") -> list[FakePosition]:
        self.positions_called_with.append(account)
        if account:
            return [p for p in self._positions if p.account == account]
        return self._positions

    def portfolio(self) -> list[FakePortfolioItem]:
        if self.portfolio_raises:
            raise RuntimeError("account updates request timed out")
        return self._portfolio

    def accountValues(self) -> list[Any]:
        return self._account_values

    def isConnected(self) -> bool:
        return True


MU = FakeContract(symbol="MU", conId=9939)
CSCO = FakeContract(symbol="CSCO", conId=268084)


def _client(ib: FakeIB, *, positions_known: bool = True) -> IbkrClient:
    c = IbkrClient(host="127.0.0.1", port=7496, client_id=17)
    c._ib = ib  # type: ignore[assignment]
    c._positions_known = positions_known
    return c


def test_positions_survive_a_silent_account_subscription() -> None:
    """Der gemessene Fall: `portfolio()` leer, `positions()` gefuellt.

    Vor T1-99 ergab das eine leere Liste — und daraus zwei geschlossene Lots.
    """
    ib = FakeIB(
        _positions=[
            FakePosition(contract=MU, position=1.0, avgCost=955.2995),
            FakePosition(contract=CSCO, position=1.0, avgCost=111.8),
        ],
        _portfolio=[],
    )
    snap = _client(ib).account_snapshot()

    assert snap.positions is not None
    assert {p["symbol"] for p in snap.positions} == {"MU", "CSCO"}
    assert [p["qty"] for p in snap.positions] == [1.0, 1.0]


def test_the_entry_price_comes_from_the_position_not_the_portfolio() -> None:
    ib = FakeIB(
        _positions=[FakePosition(contract=MU, position=1.0, avgCost=955.2995)],
        _portfolio=[],
    )
    snap = _client(ib).account_snapshot()
    assert snap.positions is not None
    assert snap.positions[0]["avg_cost"] == 955.2995


def test_missing_enrichment_is_none_and_never_zero() -> None:
    """Ein Marktwert von 0 fuer eine Position, die es gibt, waere falsch.

    Die Plattform zieht aus diesen Zahlen Schluesse; eine erfundene Null ist
    eine Aussage und kein fehlender Wert.
    """
    ib = FakeIB(
        _positions=[FakePosition(contract=MU, position=1.0, avgCost=955.2995)],
        _portfolio=[],
    )
    snap = _client(ib).account_snapshot()
    assert snap.positions is not None
    row = snap.positions[0]
    assert row["market_value"] is None
    assert row["unrealized_pnl"] is None


def test_enrichment_is_used_when_the_account_subscription_works() -> None:
    ib = FakeIB(
        _positions=[FakePosition(contract=MU, position=1.0, avgCost=955.2995)],
        _portfolio=[
            FakePortfolioItem(
                contract=MU,
                position=1.0,
                averageCost=955.2995,
                marketPrice=962.0,
                marketValue=962.0,
                unrealizedPNL=6.7,
            )
        ],
    )
    snap = _client(ib).account_snapshot()
    assert snap.positions is not None
    assert snap.positions[0]["market_value"] == 962.0
    assert snap.positions[0]["unrealized_pnl"] == 6.7


def test_a_throwing_portfolio_does_not_take_the_positions_down() -> None:
    ib = FakeIB(
        _positions=[FakePosition(contract=MU, position=1.0, avgCost=955.2995)],
        portfolio_raises=True,
    )
    snap = _client(ib).account_snapshot()
    assert snap.positions is not None
    assert snap.positions[0]["symbol"] == "MU"
    assert snap.positions[0]["market_value"] is None


def test_unconfirmed_subscription_reports_unknown_not_empty() -> None:
    """Der Kern des Specs.

    Solange die Positionsabfrage nicht geantwortet hat, gibt es keine Aussage
    ueber das Depot. `None` sagt das; eine leere Liste wuerde behaupten, das
    Konto sei leer — und die Plattform schliesst darauf Positionen.
    """
    ib = FakeIB(_positions=[], _portfolio=[])
    snap = _client(ib, positions_known=False).account_snapshot()
    assert snap.positions is None


def test_a_confirmed_but_empty_account_stays_sayable() -> None:
    """Die Gegenprobe.

    Wuerde ein leeres Depot ebenfalls als „unbekannt" gemeldet, koennte ein
    Lot, das der Nutzer tatsaechlich verkauft hat, nie geschlossen werden —
    und T1-95 waere ausgehebelt.
    """
    ib = FakeIB(_positions=[], _portfolio=[])
    snap = _client(ib, positions_known=True).account_snapshot()
    assert snap.positions == []


def test_positions_are_scoped_to_the_single_trading_account() -> None:
    """BUG-99-1 — `positions()` liefert ohne Grenze ALLE Konten des Logins.

    `portfolio()` war ueber `reqAccountUpdates` immer auf ein einzelnes Konto
    begrenzt. Ohne dieselbe Grenze summiert die Plattform die Mengen je Symbol
    ueber alle Konten, und `exitBudgetAllows` gibt ein Budget frei, das das
    Handelskonto gar nicht deckt — die Leerposition aus T1-95, nur durch die
    Hintertuer.
    """
    ib = FakeIB(
        _positions=[
            FakePosition(contract=MU, position=1.0, avgCost=955.0),
            FakePosition(
                contract=MU, position=4.0, avgCost=900.0, account="U99999999"
            ),
        ],
        _accounts=["U23076419"],
    )
    snap = _client(ib).account_snapshot()

    assert ib.positions_called_with == ["U23076419"]
    assert snap.positions is not None
    assert len(snap.positions) == 1
    assert snap.positions[0]["qty"] == 1.0


def test_several_managed_accounts_are_not_guessed() -> None:
    """Bei mehreren Konten wird nicht das erste genommen.

    Eine falsche Kontowahl waere ein stiller Faktor auf jede Bestandszahl.
    Gemeldet wird dann alles, und das Protokoll sagt es laut — dieselbe
    Entscheidung wie bei der Waehrungsaufloesung in T1-85.
    """
    ib = FakeIB(
        _positions=[
            FakePosition(contract=MU, position=1.0, avgCost=955.0),
            FakePosition(
                contract=CSCO, position=2.0, avgCost=110.0, account="U99999999"
            ),
        ],
        _accounts=["U23076419", "U99999999"],
    )
    snap = _client(ib).account_snapshot()

    assert ib.positions_called_with == [""]
    assert snap.positions is not None
    assert len(snap.positions) == 2

    # T1-107: die Entscheidung dreht sich nicht um — geraten wird weiterhin
    # nicht, und `account` am Snapshot bleibt leer. Neu ist, dass JEDE Zeile
    # ihr eigenes Konto traegt. Damit kann die Plattform den Koerper als in
    # sich widerspruechlich erkennen, statt wie bisher ueber Konten hinweg zu
    # summieren und ein zu grosses Ausstiegsbudget freizugeben (BUG-99-1).
    assert snap.account is None
    konten = {p["account"] for p in snap.positions}
    assert konten == {"U23076419", "U99999999"}, (
        "Ohne die Zeilenkennung sieht ein Zwei-Konten-Koerper aus wie ein "
        "vollstaendiges Depot — und ist keins."
    )


def test_every_position_row_carries_its_account() -> None:
    """T1-107: das Konto haengt an der Zeile, nicht nur am Snapshot.

    Eine Positionsliste ohne Kontokennung ist nicht als die eines bestimmten
    Depots erkennbar. Wer zwischen zwei Konten wechselt, schickt damit zwei
    Listen, die der Empfaenger nicht auseinanderhalten kann.
    """
    ib = FakeIB(
        _positions=[
            FakePosition(contract=MU, position=1.0, avgCost=955.0, account="U11111111")
        ],
        _accounts=["U11111111"],
    )
    snap = _client(ib).account_snapshot()

    assert snap.account == "U11111111"
    assert snap.positions is not None
    assert snap.positions[0]["account"] == "U11111111"


def test_enrichment_matches_on_contract_id_not_symbol() -> None:
    """Bei mehreren Boersen ist das Symbol nicht eindeutig, die Kennung schon."""
    other_mu = FakeContract(symbol="MU", conId=999999)
    ib = FakeIB(
        _positions=[FakePosition(contract=MU, position=1.0, avgCost=955.2995)],
        _portfolio=[
            FakePortfolioItem(
                contract=other_mu,
                position=7.0,
                averageCost=1.0,
                marketPrice=1.0,
                marketValue=7.0,
                unrealizedPNL=0.0,
            )
        ],
    )
    snap = _client(ib).account_snapshot()
    assert snap.positions is not None
    assert snap.positions[0]["market_value"] is None
