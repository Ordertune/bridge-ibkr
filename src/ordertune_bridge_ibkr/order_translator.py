"""Wandelt Ordertune OrderIntent in ib_insync-Order-Objekte.

Unterstützt 4 Kern-Order-Types aus router-interface.ts (day_limit, loc, moc,
market). Bracket + OCA-Handling gemäß IBKR-Semantik.
"""
from __future__ import annotations

from typing import Any

from ib_insync import Contract, LimitOrder, MarketOrder, Order, Stock


def make_contract(symbol: str) -> Contract:
    """SMART US-Equity als Default."""
    return Stock(symbol, "SMART", "USD")


def translate_intent(intent: dict[str, Any]) -> Order:
    """OrderIntent → ib_insync.Order (single-leg)."""
    side = intent["side"].upper()  # 'BUY' | 'SELL'
    qty = float(intent["qty"])
    order_type = intent["orderType"]

    action = "BUY" if side == "BUY" else "SELL"

    if order_type == "market":
        return MarketOrder(action, qty)

    if order_type == "day_limit":
        lmt = float(intent["lmtPrice"])
        return LimitOrder(action, qty, lmt)

    if order_type == "loc":
        o = Order()
        o.orderType = "LOC"
        o.action = action
        o.totalQuantity = qty
        o.tif = "DAY"
        if intent.get("lmtPrice") is not None:
            o.lmtPrice = float(intent["lmtPrice"])
        return o

    if order_type == "moc":
        o = Order()
        o.orderType = "MOC"
        o.action = action
        o.totalQuantity = qty
        o.tif = "DAY"
        return o

    raise ValueError(f"Unsupported orderType: {order_type}")


def apply_bracket_transmit_flags(orders: list[Order]) -> None:
    """Set transmit=False für alle außer der letzten (IBKR-Bracket-Pattern)."""
    for i, order in enumerate(orders):
        order.transmit = i == len(orders) - 1


def apply_oca_group(orders: list[Order], group_name: str, oca_type: int = 1) -> None:
    """Alle Orders in derselben OCA-Group. oca_type=1 = cancel remaining on any fill."""
    for order in orders:
        order.ocaGroup = group_name
        order.ocaType = oca_type
