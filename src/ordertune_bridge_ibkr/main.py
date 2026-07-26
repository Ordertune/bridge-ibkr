"""ordertune-bridge-ibkr Entry-Point.

Startup:
  1. Load bridge.env
  2. Setup logging
  3. Update-check
  4. Compute hardware-fingerprint
  5. Connect to IBKR TWS/Gateway
  6. Handshake against Ordertune server
  7. Schedule heartbeat (60s) + pending-poll (5s market / 60s off)
  8. Run event loop forever until SIGINT/SIGTERM
"""
from __future__ import annotations

import logging
import signal
import sys
import threading
from datetime import datetime, time as dt_time, timezone
from typing import Any
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler

from . import __version__
from .api_client import OrdertuneApiClient
from .config import load_config
from .fingerprint import compute_fingerprint
from .ibkr_client import IbkrClient
from .logging_setup import setup_logging
from .order_translator import make_contract, translate_intent
from .position_sizing import (
    SizingConfig,
    recompute_qty,
    sizing_drift_exceeds_threshold,
)
from .update_check import emit_update_warning_if_any

log = logging.getLogger(__name__)

# ── NYSE-Marktzeiten in America/New_York (DST-aware). ─────────────────
# 30-Min-Puffer vor Open (09:00 ET) + 30-Min-Puffer nach Close (16:30 ET)
NYSE_TZ = ZoneInfo("America/New_York")
NYSE_POLL_START = dt_time(9, 0)   # 30 Min vor Open
NYSE_POLL_END = dt_time(16, 30)   # 30 Min nach Close


def is_us_market_hours(now_utc: datetime | None = None) -> bool:
    now = now_utc or datetime.now(timezone.utc)
    ny = now.astimezone(NYSE_TZ)
    if ny.weekday() >= 5:  # Sa/So
        return False
    t = ny.time()
    return NYSE_POLL_START <= t <= NYSE_POLL_END


# Thread-safe mapping ib_order_id → dispatch_id für Order-Status-Callbacks.
# `_handle_pending` (Scheduler-Thread) writes; `on_status` (ib_insync
# event-thread) reads. Lock schützt gegen Race während parallel-submits.
_DISPATCH_MAP_LOCK = threading.Lock()

# Set von bereits-final-reporteten dispatch_ids — verhindert Duplicate
# result_order-Requests bei mehrfachem orderStatusEvent (partial → filled etc.).
_REPORTED_TERMINAL: set[str] = set()
_REPORTED_LOCK = threading.Lock()


def _handle_pending(
    api: OrdertuneApiClient,
    ibkr: IbkrClient,
    dispatch_id_map: dict[int, str],
) -> None:
    """Poll pending dispatches und submit die konformen an IBKR."""
    try:
        resp = api.get_pending()
    except Exception as exc:
        log.warning("get_pending failed: %s", exc)
        return

    if not resp.pending and not resp.cancelling:
        return

    live_equity = ibkr.get_live_equity()

    for order in resp.pending:
        intent = order.order_intent
        # ── Sizing-Recompute-Check ────────────────────────────────────
        sizing_conf = intent.get("bridgeSizingConfig")
        if sizing_conf and live_equity > 0:
            server_qty = int(intent.get("qty", 0))
            cfg = SizingConfig(
                equity_mode=sizing_conf["equityMode"],
                position_size_pct=float(sizing_conf["positionSizePct"]),
                base_equity_amount=(
                    float(sizing_conf["baseEquityAmount"])
                    if sizing_conf.get("baseEquityAmount") is not None
                    else None
                ),
            )
            entry_ref = float(sizing_conf["entryPriceReference"])
            recomputed = recompute_qty(cfg, entry_ref, live_equity)
            if sizing_drift_exceeds_threshold(server_qty, recomputed):
                log.warning(
                    "Sizing drift for dispatch %s: server_qty=%d recomputed=%d (live_equity=%.2f). Rejecting.",
                    order.dispatch_id,
                    server_qty,
                    recomputed,
                    live_equity,
                )
                try:
                    api.result_order(
                        order.dispatch_id,
                        status="rejected",
                        reason="sizing_drift_exceeds_5pct",
                    )
                except Exception as exc:
                    log.error("result_order failed for %s: %s", order.dispatch_id, exc)
                continue

        # ── Submit via IBKR ───────────────────────────────────────────
        try:
            contract = make_contract(intent["symbol"])
            ib_order = translate_intent(intent)
            ib_order.orderRef = f"ot-{order.dispatch_id}"
            trade = ibkr.place_order(contract, ib_order)
            ib_order_id = int(getattr(trade.order, "orderId", 0))
            # HB-1: Register mapping BEFORE ack so the status-callback can
            # find the dispatch_id if IBKR fires a fill-event faster than
            # our ack-round-trip.
            with _DISPATCH_MAP_LOCK:
                dispatch_id_map[ib_order_id] = order.dispatch_id
            api.ack_order(
                order.dispatch_id,
                ib_order_id=ib_order_id,
                submitted_at=datetime.now(timezone.utc).isoformat(),
            )
            log.info(
                "Submitted dispatch %s (%s %s x%s) — ib_order_id=%s",
                order.dispatch_id,
                intent["symbol"],
                intent["side"],
                intent["qty"],
                ib_order_id,
            )
        except Exception as exc:
            log.error("submit failed for dispatch %s: %s", order.dispatch_id, exc)
            try:
                api.result_order(
                    order.dispatch_id,
                    status="rejected",
                    reason=f"submit_error: {exc}",
                )
            except Exception:
                pass

    for dispatch_id in resp.cancelling:
        # TODO(T1-56-Phase2): implement cancel via ib_insync
        log.info("Cancel requested for dispatch %s (not yet implemented)", dispatch_id)


def _handle_heartbeat(api: OrdertuneApiClient, ibkr: IbkrClient) -> None:
    if not ibkr.is_connected():
        log.warning("heartbeat: IBKR disconnected — skipping snapshot push")
        return
    try:
        snap = ibkr.account_snapshot()
        api.heartbeat(
            {
                "cash": snap.cash_usd,
                "equity": snap.equity_usd,
                "positions": snap.positions,
                "gateway_status": snap.gateway_status,
                "bridge_version": __version__,
            }
        )
    except Exception as exc:
        log.warning("heartbeat push failed: %s", exc)


TERMINAL_STATES = {"filled", "cancelled", "rejected"}


def _make_on_order_status(api: OrdertuneApiClient, dispatch_id_map: dict[int, str]):
    """Callback für ib_insync order-status-events → /orders/{id}/result.

    ib_insync fires orderStatusEvent MULTIPLE TIMES per order (submitted,
    working, partial, filled). We report only terminal transitions
    (filled/cancelled/rejected) — plus partials which are informational.
    Terminal-state idempotency via _REPORTED_TERMINAL set to prevent
    duplicate result_order calls if the same terminal event fires twice.
    """

    def on_status(trade: Any) -> None:
        status_map = {
            "Filled": "filled",
            "PartiallyFilled": "partial",
            "Cancelled": "cancelled",
            "ApiCancelled": "cancelled",
            "Inactive": "rejected",
        }
        raw = getattr(trade.orderStatus, "status", "")
        mapped = status_map.get(raw)
        if mapped is None:
            return
        order_id = int(getattr(trade.order, "orderId", 0))
        with _DISPATCH_MAP_LOCK:
            dispatch_id = dispatch_id_map.get(order_id)
        if not dispatch_id:
            return

        # Idempotency: terminal events are reported only once. Server-side
        # /result is idempotent too (applyResult), but we skip anyway to
        # save the round-trip.
        if mapped in TERMINAL_STATES:
            with _REPORTED_LOCK:
                if dispatch_id in _REPORTED_TERMINAL:
                    return
                _REPORTED_TERMINAL.add(dispatch_id)

        try:
            api.result_order(
                dispatch_id,
                status=mapped,
                filled_qty=float(trade.orderStatus.filled or 0),
                avg_fill_price=float(trade.orderStatus.avgFillPrice or 0),
                filled_at=datetime.now(timezone.utc).isoformat(),
            )
            log.info(
                "Result reported for dispatch %s: %s (filled=%s)",
                dispatch_id,
                mapped,
                trade.orderStatus.filled,
            )
        except Exception as exc:
            log.error("result_order failed for %s: %s", dispatch_id, exc)
            # Roll back the "reported" marker so a retry can happen next tick.
            if mapped in TERMINAL_STATES:
                with _REPORTED_LOCK:
                    _REPORTED_TERMINAL.discard(dispatch_id)

    return on_status


def main() -> int:
    try:
        config = load_config()
    except Exception as exc:
        print(f"[FATAL] bridge.env invalid: {exc}", file=sys.stderr)
        return 1

    setup_logging(level=config.log_level)
    log.info("ordertune-bridge-ibkr v%s starting up", __version__)

    if config.update_check_enabled:
        emit_update_warning_if_any(__version__)

    fingerprint = compute_fingerprint()
    log.info("Hardware fingerprint: %s...", fingerprint[:16])

    ibkr = IbkrClient(
        host=config.ibkr_gateway_host,
        port=config.ibkr_gateway_port,
        client_id=config.ibkr_client_id,
    )
    try:
        ibkr.connect()
    except Exception as exc:
        log.error(
            "Failed to connect to IBKR TWS/Gateway at %s:%d — %s",
            config.ibkr_gateway_host,
            config.ibkr_gateway_port,
            exc,
        )
        return 1

    api = OrdertuneApiClient(
        base_url=str(config.ordertune_api_base),
        token=config.ordertune_bridge_token,
        connection_id=config.ordertune_bridge_connection_id,
        fingerprint=fingerprint,
    )

    try:
        api.handshake(
            capabilities={
                "supports_fractional_shares": False,
                "supports_bulk_send": True,
                "supports_bracket": True,
                "supports_oca": True,
            }
        )
        log.info("Handshake successful — Bridge is active.")
    except Exception as exc:
        log.error("Handshake failed: %s", exc)
        ibkr.disconnect()
        return 1

    dispatch_id_map: dict[int, str] = {}
    ibkr.subscribe_execution_callback(_make_on_order_status(api, dispatch_id_map))

    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(
        lambda: _handle_heartbeat(api, ibkr),
        "interval",
        seconds=60,
        id="heartbeat",
        replace_existing=True,
    )

    def _pending_tick() -> None:
        interval_s = 5 if is_us_market_hours() else 60
        _handle_pending(api, ibkr, dispatch_id_map)
        # Re-schedule dynamically: adjust job-interval according to market hours
        job = scheduler.get_job("pending")
        if job:
            current = job.trigger.interval.total_seconds()  # type: ignore[attr-defined]
            if int(current) != interval_s:
                scheduler.reschedule_job(
                    "pending", trigger="interval", seconds=interval_s
                )

    scheduler.add_job(_pending_tick, "interval", seconds=5, id="pending")
    scheduler.start()
    log.info("Scheduler started (heartbeat 60s, pending 5s/60s).")

    # SIGINT/SIGTERM Handler
    def _shutdown(signum: int, frame: Any) -> None:
        log.info("Shutdown signal received (%d)", signum)
        scheduler.shutdown(wait=False)
        ibkr.disconnect()
        api.close()
        log.info("Shutdown complete.")
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # ib_insync's loop — keeps callbacks alive
    try:
        while ibkr.is_connected():
            ibkr.sleep(1.0)
    finally:
        scheduler.shutdown(wait=False)
        ibkr.disconnect()
        api.close()

    log.info("Bridge exited normally.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
