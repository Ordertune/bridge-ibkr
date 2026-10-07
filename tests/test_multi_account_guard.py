"""T1-306: ein Login mit mehreren Depots handelt nicht ins falsche Konto.

## Woher dieser Test kommt

Owner-Frage 2026-10-07 auf der Plattformseite: was passiert, wenn ein
Vermoegensverwalter einen Zugang kauft und die Signale auf eine beliebige
Anzahl Kundendepots anwendet? Ein IBKR-FA-Login traegt ein Master-Login mit N
Kundenkonten darunter.

Beim Nachsehen stellte sich heraus: **der Riegel existiert schon, aber als
Nebenwirkung.** `place_order` gibt den Auftrag weiter, ohne `order.account` zu
setzen; bei einem Login mit mehreren verwalteten Konten verlangt IBKR eines,
die Order laeuft also ins Leere statt in ein fremdes Depot. Und
`_trading_account` antwortet bei mehreren Konten `None` statt zu raten.

Beides ist richtig — aber nichts hat es festgehalten. Eine spaetere
Bequemlichkeit („setzen wir halt das erste Konto") haette den Riegel
geraeuschlos entfernt, und die erste Order waere in ein Depot gegangen, das dem
Kunden nicht gehoert.

Diese Zusicherungen nageln beide Haelften fest. Sie gehoeren **hierher** und
nicht in den Pruefstand der Plattform: T1-178 hat belegt, dass ein Blick aus
dem Plattform-Repo nach `../ordertune-bridge-ibkr/…` in CI mit `ENOENT` stirbt,
weil dort nur das eine Repo ausgecheckt ist. Jede Seite sichert ihren eigenen
Code zu. Das Gegenstueck heisst
`scripts/verify-t1-306-die-signale-gelten-fuer-den-kunden-selbst.ts`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ordertune_bridge_ibkr.ibkr_client import IbkrClient


@dataclass
class FakeContract:
    symbol: str
    conId: int = 1


@dataclass
class FakeOrder:
    """Die beiden Felder, auf die es hier ankommt.

    `account` traegt denselben Vorgabewert wie `ib_insync.Order`: den leeren
    String. „Nicht gesetzt" ist deshalb pruefbar, ohne das echte Paket zu
    brauchen.
    """

    action: str = "BUY"
    totalQuantity: float = 1.0
    orderType: str = "MKT"
    account: str = ""


@dataclass
class FakeIB:
    """Nur die Methoden, die der Riegel anfasst."""

    _accounts: list[str] = field(default_factory=lambda: ["U23076419"])
    #: Was `placeOrder` zu sehen bekam — darauf zielt die Zusicherung.
    placed: list[tuple[Any, Any]] = field(default_factory=list)

    def managedAccounts(self) -> list[str]:
        return self._accounts

    def placeOrder(self, contract: Any, order: Any) -> str:
        self.placed.append((contract, order))
        return "trade"

    def isConnected(self) -> bool:
        return True


def _client(ib: FakeIB) -> IbkrClient:
    c = IbkrClient(host="127.0.0.1", port=7496, client_id=17)
    c._ib = ib  # type: ignore[assignment]
    return c


def test_a_single_managed_account_is_the_trading_account() -> None:
    """Der Normalfall bleibt unberuehrt — sonst waere der Riegel eine Sperre."""
    client = _client(FakeIB(_accounts=["U23076419"]))
    assert client.trading_account() == "U23076419"


def test_trading_account_is_undecidable_with_several() -> None:
    """Zwei Konten unter einem Login: `None`, nicht das erste.

    `None` heisst „nicht zu entscheiden" und ausdruecklich nicht „keins". Das
    erste zu nehmen waere ein stiller Faktor auf jede Bestandszahl — niemand
    saehe es an den Zahlen.
    """
    client = _client(FakeIB(_accounts=["U23076419", "U99999999"]))
    assert client.trading_account() is None


def test_an_advisory_login_with_many_mandates_is_also_undecidable() -> None:
    """Der eigentliche Anlass: ein FA-Login mit vielen Mandaten."""
    client = _client(FakeIB(_accounts=[f"U{n:08d}" for n in range(50)]))
    assert client.trading_account() is None


def test_orders_carry_no_target_account() -> None:
    """`place_order` setzt KEIN Zielkonto — der Riegel, um den es geht.

    Faellt dieser Test, ist jemand dazu uebergegangen, das Konto an den Auftrag
    zu schreiben. Bei einem Login mit mehreren Depots waere das der Moment, in
    dem eine Order in ein Depot geht, das dem Kunden nicht gehoert.
    """
    ib = FakeIB(_accounts=["U23076419"])
    order = FakeOrder()
    _client(ib).place_order(FakeContract(symbol="AAPL"), order)

    assert len(ib.placed) == 1
    _, gesehen = ib.placed[0]
    assert gesehen.account == "", (
        "place_order hat ein Zielkonto gesetzt — siehe Docstring dieses Tests"
    )
    assert order.account == "", "der Auftrag wurde unterwegs veraendert"


def test_orders_carry_no_target_account_with_several_accounts() -> None:
    """Dieselbe Zusicherung fuer den Mehrkonten-Fall.

    Hier waere das Raten am verlockendsten — die Kontoliste liegt vor, und
    `_trading_account` hat gerade `None` gesagt.
    """
    ib = FakeIB(_accounts=["U23076419", "U99999999"])
    order = FakeOrder()
    _client(ib).place_order(FakeContract(symbol="AAPL"), order)

    _, gesehen = ib.placed[0]
    assert gesehen.account == ""
