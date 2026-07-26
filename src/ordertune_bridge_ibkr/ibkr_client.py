"""ib_insync-Wrapper für TWS/Gateway.

Async-first, aber gewrappt in sync-Interface für den Scheduler-basierten
Poll-Loop. ib_insync erlaubt beides via internem util.run().
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from ib_insync import IB, AccountValue, Contract, Order, PortfolioItem

log = logging.getLogger(__name__)


@dataclass
class AccountSnapshot:
    cash_usd: float
    equity_usd: float
    positions: list[dict[str, Any]]
    gateway_status: str


class IbkrClient:
    def __init__(self, host: str, port: int, client_id: int) -> None:
        self._host = host
        self._port = port
        self._client_id = client_id
        self._ib = IB()

    def connect(self) -> None:
        log.info("Connecting to IBKR TWS/Gateway at %s:%d (client-id=%d)",
                 self._host, self._port, self._client_id)
        self._ib.connect(self._host, self._port, clientId=self._client_id)
        log.info("Connected to IBKR TWS/Gateway.")

    def disconnect(self) -> None:
        if self._ib.isConnected():
            self._ib.disconnect()

    def is_connected(self) -> bool:
        return self._ib.isConnected()

    def account_snapshot(self) -> AccountSnapshot:
        """Read cash, equity, positions from IBKR."""
        acct_values: list[AccountValue] = self._ib.accountValues()
        cash = 0.0
        equity = 0.0
        for v in acct_values:
            if v.tag == "TotalCashValue" and v.currency == "USD":
                cash = float(v.value)
            elif v.tag == "NetLiquidation" and v.currency == "USD":
                equity = float(v.value)

        portfolio: list[PortfolioItem] = self._ib.portfolio()
        positions = [
            {
                "symbol": p.contract.symbol,
                "qty": float(p.position),
                "avg_cost": float(p.averageCost),
                "market_price": float(p.marketPrice or 0),
                "market_value": float(p.marketValue or 0),
                "unrealized_pnl": float(p.unrealizedPNL or 0),
            }
            for p in portfolio
        ]

        return AccountSnapshot(
            cash_usd=cash,
            equity_usd=equity,
            positions=positions,
            gateway_status="connected" if self._ib.isConnected() else "disconnected",
        )

    def get_live_equity(self) -> float:
        """Shortcut für Sizing-Recompute."""
        for v in self._ib.accountValues():
            if v.tag == "NetLiquidation" and v.currency == "USD":
                return float(v.value)
        return 0.0

    def place_order(self, contract: Contract, order: Order) -> Any:
        """Submit an order via ib_insync. Returns Trade object."""
        trade = self._ib.placeOrder(contract, order)
        return trade

    def subscribe_execution_callback(self, cb: Any) -> None:
        """Register callback for order status updates."""
        self._ib.execDetailsEvent += cb  # type: ignore[operator]
        self._ib.orderStatusEvent += cb  # type: ignore[operator]

    def sleep(self, seconds: float) -> None:
        """ib_insync-native sleep that keeps event-loop running."""
        self._ib.sleep(seconds)
