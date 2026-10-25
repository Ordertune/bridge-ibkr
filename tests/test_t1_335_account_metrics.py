"""T1-335 — Margin und Tagesergebnis fuer die Portfolio-Seite.

Die Bridge liest die Margin-Tags aus demselben Konto-Abo wie `NetLiquidation`
und das Tagesergebnis aus `reqPnL`. Geprueft wird, dass nur Werte in der
Kontowaehrung mitreisen, dass `nan` wegfaellt statt 0 zu werden, und dass bei
mehreren Konten nichts gemeldet wird.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ordertune_bridge_ibkr.ibkr_client import IbkrClient


@dataclass
class FakeAccountValue:
    tag: str
    value: str
    currency: str
    account: str = "U1"
    modelCode: str = ""


@dataclass
class FakePnL:
    account: str
    dailyPnL: float = float("nan")
    unrealizedPnL: float = float("nan")
    realizedPnL: float = float("nan")
    modelCode: str = ""


EUR_KONTO = [
    FakeAccountValue("NetLiquidation", "90372.29", "EUR"),
    FakeAccountValue("TotalCashValue", "22300.00", "EUR"),
    FakeAccountValue("InitMarginReq", "31250.50", "EUR"),
    FakeAccountValue("MaintMarginReq", "28410.00", "EUR"),
    FakeAccountValue("ExcessLiquidity", "61962.29", "EUR"),
    FakeAccountValue("AvailableFunds", "59121.79", "EUR"),
    FakeAccountValue("BuyingPower", "236487.16", "EUR"),
    FakeAccountValue("GrossPositionValue", "68072.29", "EUR"),
    FakeAccountValue("Cushion", "0.42", ""),
    # Segmentzeilen und andere Waehrungen duerfen nie hinein.
    FakeAccountValue("InitMarginReq-S", "1.00", "EUR"),
    FakeAccountValue("BuyingPower", "999.00", "USD"),
]


@dataclass
class FakeIB:
    accounts: list[str] = field(default_factory=lambda: ["U1"])
    values: list[Any] = field(default_factory=lambda: list(EUR_KONTO))
    pnl_rows: list[FakePnL] = field(default_factory=list)
    pnl_requests: list[str] = field(default_factory=list)
    pnl_raises: bool = False

    def managedAccounts(self) -> list[str]:
        return self.accounts

    def accountValues(self) -> list[Any]:
        return self.values

    def positions(self, account: str = "") -> list[Any]:
        return []

    def portfolio(self, account: str = "") -> list[Any]:
        return []

    def isConnected(self) -> bool:
        return True

    def reqPnL(self, account: str, modelCode: str = "") -> FakePnL:
        if self.pnl_raises:
            raise AssertionError("PnL request already made")
        self.pnl_requests.append(account)
        return FakePnL(account)

    def pnl(self, account: str = "", modelCode: str = "") -> list[FakePnL]:
        return [p for p in self.pnl_rows if not account or p.account == account]


def _client(ib: FakeIB) -> IbkrClient:
    c = IbkrClient(host="127.0.0.1", port=7496, client_id=17)
    c._ib = ib  # type: ignore[assignment]
    c._positions_known = True
    return c


def test_margin_tags_in_account_currency() -> None:
    snap = _client(FakeIB()).account_snapshot()
    assert snap.metrics == {
        "initMargin": 31250.5,
        "maintMargin": 28410.0,
        "excessLiquidity": 61962.29,
        "availableFunds": 59121.79,
        "buyingPower": 236487.16,
        "grossPositionValue": 68072.29,
        "cushion": 0.42,
    }


def test_pnl_subscribed_once_and_nan_dropped() -> None:
    ib = FakeIB()
    client = _client(ib)
    # Erster Herzschlag: Abo gestellt, noch keine Werte.
    snap = client.account_snapshot()
    assert ib.pnl_requests == ["U1"]
    assert "dailyPnl" not in (snap.metrics or {})

    ib.pnl_rows = [FakePnL("U1", dailyPnL=-412.37, unrealizedPnL=1834.9)]
    snap = client.account_snapshot()
    assert ib.pnl_requests == ["U1"], "kein zweites Abo in derselben Sitzung"
    assert snap.metrics is not None
    assert snap.metrics["dailyPnl"] == -412.37
    assert snap.metrics["unrealizedPnl"] == 1834.9
    assert "realizedPnl" not in snap.metrics


def test_pnl_resubscribed_after_reconnect() -> None:
    ib = FakeIB()
    client = _client(ib)
    client.account_snapshot()
    # Was `connect()` je Sitzung zuruecksetzt.
    client._pnl_account = None
    client.account_snapshot()
    assert ib.pnl_requests == ["U1", "U1"]


def test_pnl_failure_keeps_margin() -> None:
    snap = _client(FakeIB(pnl_raises=True)).account_snapshot()
    assert snap.metrics is not None
    assert snap.metrics["initMargin"] == 31250.5
    assert "dailyPnl" not in snap.metrics


def test_no_metrics_for_several_accounts() -> None:
    ib = FakeIB(accounts=["U1", "U2"])
    snap = _client(ib).account_snapshot()
    assert snap.metrics is None
    assert ib.pnl_requests == []


def test_other_accounts_rows_ignored() -> None:
    values = list(EUR_KONTO) + [FakeAccountValue("InitMarginReq", "5.00", "EUR", account="U9")]
    snap = _client(FakeIB(values=values)).account_snapshot()
    assert snap.metrics is not None
    assert snap.metrics["initMargin"] == 31250.5


def test_nothing_known_means_none() -> None:
    values = [
        FakeAccountValue("NetLiquidation", "100.00", "USD"),
        FakeAccountValue("TotalCashValue", "100.00", "USD"),
        FakeAccountValue("InitMarginReq", "nan", "USD"),
    ]
    snap = _client(FakeIB(values=values)).account_snapshot()
    assert snap.metrics is None
