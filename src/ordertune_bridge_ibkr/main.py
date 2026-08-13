"""ordertune-bridge-ibkr Entry-Point.

Startup:
  1. Load bridge.env
  2. Setup logging
  3. Update-check
  4. Compute hardware-fingerprint
  5. Connect to IBKR TWS/Gateway
  6. Handshake against Ordertune server
  7. Run one loop on THIS thread: heartbeat (60s) + pending-poll (5s market
     / 60s off), until SIGINT/SIGTERM

## Warum eine Schleife und kein Zeitgeber (T1-88)

Bis 0.3.0 liefen Heartbeat und Auftragsabruf in einem `BackgroundScheduler`,
also in Arbeiter-Threads. `ib_insync` haengt aber an einer asyncio-Schleife,
und die gehoert dem Thread, der sie startet — hier dem Hauptthread. Ein
Auftrag aus einem Arbeiter-Thread findet sie nicht:

    [ERROR] submit failed for dispatch 11b415a3-...:
    There is no current event loop in thread 'ThreadPoolExecutor-0_0'.

Aufgefallen ist es erst am 2026-08-13, beim allerersten echten Absenden. Der
Heartbeat war die ganze Zeit gruen, weil `accountValues()` und `portfolio()`
nur zwischengespeicherten Zustand lesen und die Schleife gar nicht anfassen;
das Abholen offener Auftraege ist reines HTTP. **Nur das Absenden** fasst
IBKR wirklich an — und genau dieser eine Weg war nie gegangen worden.

Es ist deshalb kein Fehler, den man an der Absendestelle repariert. Solange
IBKR-Arbeit ueberhaupt in fremden Threads stattfinden kann, entsteht er beim
naechsten Aufruf wieder. Die Schleife hier ist die Bauweise, die `ib_insync`
vorsieht: ein Thread, eine Schleife, alle Broker-Aufrufe darin.

Der Preis ist bekannt und klein: die HTTP-Aufrufe halten die Schleife kurz an,
in dieser Zeit werden Rueckmeldungen von IBKR nicht verarbeitet. Sie gehen
nicht verloren — sie warten im Socket und kommen beim naechsten `sleep()`.
"""
from __future__ import annotations

import logging
import signal
import sys
import threading
import time
from datetime import datetime, time as dt_time, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

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


HEARTBEAT_INTERVAL_S = 60.0
PENDING_INTERVAL_MARKET_S = 5.0
PENDING_INTERVAL_OFF_S = 60.0

# Wie fein die Schleife tickt. Klein genug, dass ein 5-Sekunden-Abruf nicht
# merklich spaeter kommt; gross genug, dass Leerlauf nichts kostet. Waehrend
# dieses Aufrufs laeuft die ib_insync-Schleife — das ist der Moment, in dem
# Rueckmeldungen von IBKR verarbeitet werden.
LOOP_TICK_S = 0.25


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

# Was diese Bridge gegenüber IBKR kann. Die Feldnamen sind der Vertrag mit der
# Plattform (capabilitiesSchema) — v0.1.0 schickte hier vier andere Schlüssel,
# zwei davon existierten serverseitig überhaupt nicht.
#
# fractionalQtyPrecision=0: es werden ganze Stücke gehandelt. Steht die Zahl
# falsch, rundet die Plattform Ordermengen auf Bruchteile, die IBKR ablehnt.
IBKR_CAPABILITIES: dict[str, Any] = {
    "supportsFractionalShares": False,
    "fractionalQtyPrecision": 0,
    "minNotionalUsd": None,
    "supportsBulkSend": True,
}
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
                        reason_code="sizing_drift",
                        error_message=(
                            f"Server-Menge {server_qty}, hier neu berechnet "
                            f"{recomputed} bei Depotwert {live_equity:.2f}."
                        ),
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
                broker_order_id=ib_order_id,
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
                    reason_code="rejected_by_broker",
                    error_message=f"submit_error: {exc}",
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
            cash=snap.cash,
            equity=snap.equity,
            currency=snap.currency,
            positions=snap.positions,
            gateway_status=snap.gateway_status,
            capabilities=IBKR_CAPABILITIES,
        )
    except Exception as exc:
        log.warning("heartbeat push failed: %s", exc)


TERMINAL_STATES = {"filled", "cancelled", "rejected", "expired"}

# Order-Typen, bei denen ein Nicht-Zustandekommen normales Marktverhalten ist
# und kein Fehler: der Limitpreis wurde schlicht nicht erreicht.
_LIMIT_ORDER_TYPES = {"LMT", "LOC", "MOC"}


def _derive_reason_code(mapped: str, filled: float, order_type: str) -> str | None:
    """Warum kam die Order NICHT zustande?

    `status` allein wirft Dinge zusammen, die für den Nutzer sehr
    Verschiedenes bedeuten: eine nicht erreichte Limit-Order ist Marktalltag,
    eine Ablehnung ist ein Problem. Ohne diese Unterscheidung steht am Ende
    des Tages nur "cancelled" in der Oberfläche und niemand weiss, ob etwas
    kaputt ist.
    """
    if mapped == "rejected":
        return "rejected_by_broker"
    if mapped in ("cancelled", "expired") and filled == 0:
        if order_type in _LIMIT_ORDER_TYPES:
            return "limit_not_reached"
        return "expired" if mapped == "expired" else "cancelled_by_user"
    return None


def _sum_commission(trade: Any) -> float | None:
    """Summe der Broker-Gebühren dieser Order, falls IBKR sie schon gemeldet hat.

    Menge mal Preis ist der Brutto-Betrag, nicht das, was das Konto verlassen
    hat. Die Gebühr kommt über den commissionReport der einzelnen Fills und
    trifft gelegentlich später ein als der Status — dann bleibt es None und
    die Plattform trägt nichts Falsches ein.
    """
    try:
        fills = getattr(trade, "fills", None) or []
        total = 0.0
        seen = False
        for f in fills:
            report = getattr(f, "commissionReport", None)
            value = getattr(report, "commission", None) if report else None
            if value is None:
                continue
            total += float(value)
            seen = True
        return total if seen else None
    except Exception:  # pragma: no cover - defensiv, nie handelskritisch
        return None


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

        filled = float(getattr(trade.orderStatus, "filled", 0) or 0)
        avg_price = float(getattr(trade.orderStatus, "avgFillPrice", 0) or 0)
        order_type = str(getattr(trade.order, "orderType", "") or "")

        try:
            api.result_order(
                dispatch_id,
                status=mapped,
                # Diese Zahl trägt die Bestandsführung je Strategie. Ohne sie
                # weiss die Plattform nicht, wie viele Stücke einer Strategie
                # gehören, und ein späterer Exit verkauft die falsche Menge.
                fill_qty=filled,
                # 0.0 wäre eine Preisbehauptung für einen Handel, den es nicht
                # gab. Nichts gefüllt heisst: kein Preis.
                fill_price=avg_price if filled > 0 else None,
                commission_usd=_sum_commission(trade),
                filled_at=datetime.now(timezone.utc).isoformat(),
                reason_code=_derive_reason_code(mapped, filled, order_type),
                broker_order_id=order_id or None,
            )
            log.info(
                "Result reported for dispatch %s: %s (filled=%s)",
                dispatch_id,
                mapped,
                filled,
            )
        except Exception as exc:
            log.error("result_order failed for %s: %s", dispatch_id, exc)
            # Roll back the "reported" marker so a retry can happen next tick.
            if mapped in TERMINAL_STATES:
                with _REPORTED_LOCK:
                    _REPORTED_TERMINAL.discard(dispatch_id)

    return on_status


def run_loop(
    ibkr: Any,
    heartbeat: Callable[[], None],
    pending: Callable[[], None],
    stop: threading.Event,
    *,
    market_hours: Callable[[], bool] = is_us_market_hours,
    tick_s: float = LOOP_TICK_S,
    monotonic: Callable[[], float] = time.monotonic,
) -> None:
    """Der einzige Thread, der IBKR anfassen darf.

    Beide Aufgaben laufen hier, nicht in einem Zeitgeber — die Begruendung
    steht im Kopf dieses Moduls. Als eigene Funktion, damit die Zusicherungen
    sie ohne TWS gegen Attrappen fahren koennen; das ist die einzige Art, den
    Fehler von 0.3.0 dauerhaft festzunageln.

    Die naechste Faelligkeit wird NACH dem Aufruf gestellt, nicht davor. Sonst
    laesst ein HTTP-Aufruf, der laenger dauert als das Intervall, die Aufgabe
    sofort erneut feuern — und ein haengender Server wuerde die Schleife in
    eine Dauerschleife ziehen, statt sie nur zu verzoegern.
    """
    next_heartbeat = 0.0
    next_pending = 0.0

    while ibkr.is_connected() and not stop.is_set():
        if monotonic() >= next_heartbeat:
            heartbeat()
            next_heartbeat = monotonic() + HEARTBEAT_INTERVAL_S

        if monotonic() >= next_pending:
            pending()
            next_pending = monotonic() + (
                PENDING_INTERVAL_MARKET_S
                if market_hours()
                else PENDING_INTERVAL_OFF_S
            )

        # Pumpt die ib_insync-Schleife. Ein blosses time.sleep() wuerde hier
        # die Rueckmeldungen von IBKR aussperren.
        ibkr.sleep(tick_s)


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
        api.handshake(capabilities=IBKR_CAPABILITIES)
        log.info("Handshake successful — Bridge is active.")
    except Exception as exc:
        log.error("Handshake failed: %s", exc)
        ibkr.disconnect()
        return 1

    dispatch_id_map: dict[int, str] = {}
    ibkr.subscribe_execution_callback(_make_on_order_status(api, dispatch_id_map))

    stop = threading.Event()

    # Der Handler setzt nur eine Fahne. Frueher rief er `sys.exit(0)` und raeumte
    # gleich selbst auf — mitten in einem Signal, also potenziell mitten in einem
    # laufenden Absendevorgang. Jetzt laeuft das Aufraeumen dort, wo es hingehoert:
    # im `finally` der Schleife, nachdem der aktuelle Durchgang zu Ende ist.
    def _shutdown(signum: int, frame: Any) -> None:
        log.info("Shutdown signal received (%d) — finishing current tick", signum)
        stop.set()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    log.info(
        "Loop started on the main thread (heartbeat %.0fs, pending %.0fs/%.0fs).",
        HEARTBEAT_INTERVAL_S,
        PENDING_INTERVAL_MARKET_S,
        PENDING_INTERVAL_OFF_S,
    )

    try:
        run_loop(
            ibkr,
            heartbeat=lambda: _handle_heartbeat(api, ibkr),
            pending=lambda: _handle_pending(api, ibkr, dispatch_id_map),
            stop=stop,
        )
    finally:
        ibkr.disconnect()
        api.close()

    log.info("Bridge exited normally.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
