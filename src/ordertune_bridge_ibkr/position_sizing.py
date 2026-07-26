"""T1-56: Position-Sizing Recompute-Check.

Server sendet pre-computed qty + sizing_config. Bridge recomputet mit
frischer Live-Equity aus IBKR und rejected wenn Drift > 5%.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass
class SizingConfig:
    equity_mode: Literal["fixed_base", "full_equity"]
    position_size_pct: float
    base_equity_amount: float | None


def recompute_qty(config: SizingConfig, entry_price: float, live_equity: float) -> int:
    """Berechne die Qty aus Sizing-Config + Entry-Price + Live-Equity."""
    if entry_price <= 0:
        return 0
    if config.equity_mode == "fixed_base":
        equity = config.base_equity_amount or 0.0
    else:
        equity = live_equity

    notional = equity * (config.position_size_pct / 100.0)
    if notional <= 0:
        return 0
    return round(notional / entry_price)


def sizing_drift_exceeds_threshold(
    server_qty: int, recomputed_qty: int, threshold: float = 0.05
) -> bool:
    """True wenn die Drift zwischen Server-Qty und Bridge-Recompute > threshold."""
    if server_qty == 0:
        return recomputed_qty != 0
    return abs(recomputed_qty - server_qty) / abs(server_qty) > threshold
