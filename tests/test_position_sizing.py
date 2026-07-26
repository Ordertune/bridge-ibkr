from ordertune_bridge_ibkr.position_sizing import (
    SizingConfig,
    recompute_qty,
    sizing_drift_exceeds_threshold,
)


def test_recompute_full_equity():
    cfg = SizingConfig(equity_mode="full_equity", position_size_pct=3.0, base_equity_amount=None)
    # 415000 * 0.03 / 226.5 ≈ 55
    assert recompute_qty(cfg, entry_price=226.5, live_equity=415_000) == 55


def test_recompute_fixed_base_ignores_live_equity():
    cfg = SizingConfig(equity_mode="fixed_base", position_size_pct=3.0, base_equity_amount=50_000)
    # 50000 * 0.03 / 100 = 15 (ignoriert live_equity)
    assert recompute_qty(cfg, entry_price=100, live_equity=999_999) == 15


def test_recompute_zero_price_returns_zero():
    cfg = SizingConfig(equity_mode="full_equity", position_size_pct=3.0, base_equity_amount=None)
    assert recompute_qty(cfg, entry_price=0, live_equity=100_000) == 0


def test_drift_within_threshold():
    assert not sizing_drift_exceeds_threshold(server_qty=100, recomputed_qty=104)
    assert not sizing_drift_exceeds_threshold(server_qty=100, recomputed_qty=96)


def test_drift_exceeds_threshold():
    assert sizing_drift_exceeds_threshold(server_qty=100, recomputed_qty=106)
    assert sizing_drift_exceeds_threshold(server_qty=100, recomputed_qty=94)


def test_drift_zero_server_qty():
    # Server sagt 0 aber Bridge computet nicht-0 → drift = True
    assert sizing_drift_exceeds_threshold(server_qty=0, recomputed_qty=5)
    assert not sizing_drift_exceeds_threshold(server_qty=0, recomputed_qty=0)
