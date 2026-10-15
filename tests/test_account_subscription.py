"""Ein leeres Konto-Abo wird neu angefragt, nicht bis zum Neustart getragen.

## Woher dieser Test kommt

Am 2026-10-14 meldete die Bridge des Owners ueber Stunden:

    [WARNING] ordertune_bridge_ibkr.ibkr_client: No account values received
    from TWS yet. The account subscription may not have delivered; ...

Die Verbindung stand, der Herzschlag ging raus — mit Waehrung `null` und
Depotwert 0. Auf der Plattform hiess das „The Bridge could not determine your
account currency", und `full_equity` konnte keine Stueckzahl bilden. ib_insync
fragt das Konto-Abo nur in `connect()` an; laeuft es dort ins Leere, bleibt es
leer bis zur naechsten Wiederverbindung.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from ordertune_bridge_ibkr import ibkr_client
from ordertune_bridge_ibkr.ibkr_client import IbkrClient


@dataclass
class FakeAccountValue:
    tag: str
    value: str
    currency: str
    account: str = "U23076419"
    modelCode: str = ""


EUR_KONTO = [
    FakeAccountValue("NetLiquidation", "50000.00", "EUR"),
    FakeAccountValue("TotalCashValue", "1000.00", "EUR"),
]


@dataclass
class FakeIB:
    _accounts: list[str] = field(default_factory=lambda: ["U23076419"])
    _account_values: list[Any] = field(default_factory=list)
    #: Was TWS auf eine neue Anfrage liefert. `None`: TWS schweigt.
    liefert: list[Any] | None = field(default_factory=lambda: list(EUR_KONTO))
    anfragen: list[tuple[str, str]] = field(default_factory=list)

    def managedAccounts(self) -> list[str]:
        return self._accounts

    def accountValues(self) -> list[Any]:
        return self._account_values

    def reqAccountUpdatesAsync(self, account: str) -> tuple[str, str]:
        self.anfragen.append(("single", account))
        return ("single", account)

    def reqAccountUpdatesMultiAsync(self, account: str) -> tuple[str, str]:
        self.anfragen.append(("multi", account))
        return ("multi", account)

    def run(self, _awaitable: Any, timeout: float | None = None) -> None:
        if self.liefert is None:
            raise TimeoutError("account updates request timed out")
        self._account_values = list(self.liefert)

    def positions(self, account: str = "") -> list[Any]:
        return []

    def isConnected(self) -> bool:
        return True


def _client(ib: FakeIB) -> IbkrClient:
    c = IbkrClient(host="127.0.0.1", port=7496, client_id=17)
    c._ib = ib  # type: ignore[assignment]
    c._positions_known = True
    return c


def test_ein_leeres_abo_wird_im_herzschlag_neu_angefragt() -> None:
    """Der gemessene Fall: verbunden, aber keine Kontowerte."""
    ib = FakeIB()
    snap = _client(ib).account_snapshot()

    assert ib.anfragen == [("single", "U23076419")]
    assert snap.currency == "EUR"
    assert snap.equity == 50000.0


def test_volle_kontowerte_loesen_keine_anfrage_aus() -> None:
    ib = FakeIB(_account_values=list(EUR_KONTO))
    _client(ib).account_snapshot()
    assert ib.anfragen == []


def test_die_neue_anfrage_ist_gedrosselt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Schweigt TWS weiter, wird nicht in jedem Herzschlag erneut gefragt."""
    uhr = [1000.0]
    monkeypatch.setattr(ibkr_client.time, "monotonic", lambda: uhr[0])
    ib = FakeIB(liefert=None)
    client = _client(ib)

    snap = client.account_snapshot()
    assert snap.currency is None
    assert len(ib.anfragen) == 1

    uhr[0] += 60.0
    client.account_snapshot()
    assert len(ib.anfragen) == 1, "eine Minute spaeter noch nicht erneut"

    uhr[0] += ibkr_client.ACCOUNT_RESUBSCRIBE_INTERVAL_S
    ib.liefert = list(EUR_KONTO)
    snap = client.account_snapshot()
    assert len(ib.anfragen) == 2
    assert snap.currency == "EUR"


def test_mehrere_konten_gehen_ueber_den_multi_kanal() -> None:
    ib = FakeIB(_accounts=["U1", "U2"])
    _client(ib).account_snapshot()
    assert ib.anfragen == [("multi", "U1"), ("multi", "U2")]


def test_ohne_kontokennung_wird_nicht_geraten() -> None:
    ib = FakeIB(_accounts=[])
    snap = _client(ib).account_snapshot()
    assert ib.anfragen == []
    assert snap.currency is None


def test_nach_dem_verbinden_wird_das_abo_geprueft() -> None:
    """`connect()` prueft das Abo sofort, unabhaengig von der Drossel."""
    ib = FakeIB()
    client = _client(ib)
    client._account_resubscribed_at = 0.0
    client._confirm_account_subscription()
    assert ib.anfragen == [("single", "U23076419")]
    assert ib.accountValues() == EUR_KONTO
