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

# T1-88c — die Rueckrichtung: dispatch_id → Trade.
#
# Fuer eine Zustandsmeldung genuegt `orderId → dispatch_id`. Ein Storno
# braucht das Gegenteil: zu einer dispatch_id den Auftrag, den man IBKR
# hinhalten kann. Beide Ablagen stehen unter demselben Schloss, damit sie
# nicht auseinanderlaufen.
_TRADES_BY_DISPATCH: dict[str, Any] = {}

# Praefix, mit dem jeder Auftrag seine dispatch_id bei IBKR hinterlegt
# (`orderRef = "ot-<dispatchId>"`). Bis T1-88c wurde er gesetzt und nie
# gelesen — dabei ist er die einzige Angabe, die einen Neustart der Bridge
# ueberlebt: `orderId` ist sitzungsgebunden, die Ablagen oben sind fluechtig.
ORDER_REF_PREFIX = "ot-"


def dispatch_id_from_order_ref(order_ref: str | None) -> str | None:
    """Liest die dispatch_id aus dem Auftragsvermerk, oder `None`.

    Fremde Auftraege im selben Konto — von Hand gestellt oder von einem
    anderen Werkzeug — tragen den Vermerk nicht und werden hier
    stillschweigend uebergangen. Sie gehoeren uns nicht.
    """
    if not order_ref or not order_ref.startswith(ORDER_REF_PREFIX):
        return None
    dispatch_id = order_ref[len(ORDER_REF_PREFIX) :].strip()
    return dispatch_id or None


def register_trade(
    dispatch_id_map: dict[int, str], dispatch_id: str, trade: Any
) -> None:
    """Haelt einen Auftrag in beiden Richtungen fest."""
    order_id = int(getattr(trade.order, "orderId", 0) or 0)
    with _DISPATCH_MAP_LOCK:
        if order_id:
            dispatch_id_map[order_id] = dispatch_id
        _TRADES_BY_DISPATCH[dispatch_id] = trade


def trade_for_dispatch(dispatch_id: str) -> Any | None:
    with _DISPATCH_MAP_LOCK:
        return _TRADES_BY_DISPATCH.get(dispatch_id)


def rebuild_dispatch_map(ibkr: Any, dispatch_id_map: dict[int, str]) -> int:
    """T1-88c — die Zuordnung nach einem Neustart wiederherstellen.

    ## Warum das vor dem Stornoweg kommt und nicht danach

    Beide Ablagen leben im Arbeitsspeicher. Startet die Bridge neu — und sie
    startet neu, weil IBKR TWS taeglich gegen 05:00 MEZ abmeldet —, ist jeder
    vorher abgesendete Auftrag unauffindbar. Ohne diesen Wiederaufbau koennte
    ein Storno den Auftrag nicht finden und muesste antworten: „nicht
    gefunden". Genau die Sorte Antwort, aus der der Phantom-Storno entstanden
    ist.

    Der Vermerk `ot-<dispatchId>` steht seit T1-56 an jedem Auftrag und wurde
    nie zurueckgelesen. Er ist die einzige Angabe, die IBKR fuer uns aufbewahrt.
    """
    try:
        trades = ibkr.open_trades()
    except Exception as exc:
        log.error(
            "Could not query open orders: %s. A cancel might not find an order "
            "that was submitted before this restart.",
            exc,
        )
        return 0

    wiederhergestellt = 0
    for trade in trades:
        dispatch_id = dispatch_id_from_order_ref(
            getattr(getattr(trade, "order", None), "orderRef", None)
        )
        if not dispatch_id:
            continue
        register_trade(dispatch_id_map, dispatch_id, trade)
        wiederhergestellt += 1

    if wiederhergestellt:
        log.info(
            "Re-mapped %d open orders via their order reference.",
            wiederhergestellt,
        )
    else:
        log.info("No open orders of ours at IBKR.")
    return wiederhergestellt

# T1-88b F3 — was zu einem Dispatch bereits als Endzustand gemeldet wurde.
#
# Frueher eine Menge von dispatch_ids: einmal drin, nie wieder gemeldet. Das
# war als Schutz gegen doppelte Meldungen gedacht und wurde am 2026-08-13 zur
# Falle. Die Kette: ib_insync erklaert einen lebenden Auftrag faelschlich fuer
# storniert, die Bridge meldet `cancelled` und traegt den Dispatch ein — und
# eine SPAETERE echte Ausfuehrung waere danach unmeldbar gewesen. Die Position
# entstuende im Depot, kaeme nie in die Buecher, und der Modell-Ausstieg wuerde
# sie nie anfassen.
#
# Jetzt merkt sich die Ablage, WAS gemeldet wurde, und eine Ausfuehrung darf
# eine Stornierung ueberschreiben. Andersherum nicht: was gefuellt ist, bleibt
# gefuellt.
_LAST_REPORTED: dict[str, str] = {}

# Rangfolge der Endzustaende. Ein Endzustand darf einen bereits gemeldeten nur
# ersetzen, wenn er hoeher steht. Eine Ausfuehrung ist die staerkste Aussage,
# die es gibt: sie ist am Konto passiert und laesst sich nicht widerrufen.
_TERMINAL_RANK = {"expired": 1, "cancelled": 1, "rejected": 1, "partial": 2, "filled": 3}


def should_report(dispatch_id: str, mapped: str) -> bool:
    """Ist dieser Zustand eine neue Aussage, die gemeldet werden muss?

    Vier Regeln, jede aus einem konkreten Schaden hergeleitet:

    1. Derselbe Zustand zweimal ist keine neue Aussage — spart den Rueckweg.
    2. Nach einer Ausfuehrung ist Schluss. Sie ist am Konto passiert.
    3. Ein Endzustand ersetzt einen anderen nur nach Rang. Damit darf eine
       Ausfuehrung eine gemeldete Stornierung ueberschreiben — der Fall, der am
       2026-08-13 eine Position unsichtbar gemacht haette — aber nicht umgekehrt.
    4. Alles andere ist ein Fortschritt und wird gemeldet. Insbesondere darf
       ein lebender Zustand eine faelschlich gemeldete Stornierung widerrufen.

    Oeffentlich und ohne Broker-Bezug, damit die Zusicherungen die Rangfolge
    ohne TWS pruefen koennen.
    """
    with _REPORTED_LOCK:
        vorher = _LAST_REPORTED.get(dispatch_id)
        if vorher == mapped:
            return False
        if vorher == "filled":
            return False
        if vorher in _TERMINAL_RANK and mapped in _TERMINAL_RANK:
            if _TERMINAL_RANK[mapped] <= _TERMINAL_RANK[vorher]:
                return False
        _LAST_REPORTED[dispatch_id] = mapped
        return True

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
        # T1-88b F7 — der zweite von zwei Riegeln.
        #
        # Der erste sitzt serverseitig in der WHERE-Klausel des Abholpfads.
        # Dieser hier greift, falls die Plattform einmal doch eine Zeile mit
        # Storno-Wunsch ausliefert: dann wird sie NICHT abgeschickt. Ohne ihn
        # ginge der Auftrag raus und die Bridge protokollierte im selben
        # Durchlauf, dass er storniert werden solle.
        if getattr(order, "cancel_requested", False):
            log.info(
                "Dispatch %s carries a cancel request — not submitting it.",
                order.dispatch_id,
            )
            continue

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
            #
            # T1-88c: haelt jetzt beide Richtungen fest — die Rueckrichtung
            # braucht der Storno, um den Auftrag ueberhaupt zu finden.
            register_trade(dispatch_id_map, order.dispatch_id, trade)
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
        _handle_cancel(ibkr, dispatch_id)


# Dispatches, fuer die schon ein Storno an IBKR ging. Die Plattform liefert
# sie bei jedem Abruf erneut aus, bis der Broker bestaetigt hat — ohne diese
# Merkung ginge alle fuenf Sekunden ein weiterer Storno raus.
_CANCEL_SENT: set[str] = set()
# Dispatches, zu denen kein Auftrag auffindbar war. Nur damit die Warnung
# einmal erscheint statt im Fuenf-Sekunden-Takt.
_CANCEL_UNRESOLVED: set[str] = set()


def _handle_cancel(ibkr: Any, dispatch_id: str) -> None:
    """T1-88c — einen Storno an IBKR schicken. Und sonst nichts.

    Es wird bewusst NICHTS an die Plattform gemeldet. Ob aus der Anfrage eine
    Stornierung wird, entscheidet IBKR; die Antwort kommt als
    Zustandsereignis mit Fehlercode 202 und laeuft durch dieselbe Pruefung,
    die seit T1-88b den Phantom-Storno abfaengt. Hier einen Erfolg zu melden
    waere derselbe Fehler mit umgekehrtem Vorzeichen.
    """
    if dispatch_id in _CANCEL_SENT:
        return

    trade = trade_for_dispatch(dispatch_id)
    if trade is None:
        if dispatch_id not in _CANCEL_UNRESOLVED:
            _CANCEL_UNRESOLVED.add(dispatch_id)
            log.warning(
                "Cancel requested for dispatch %s, but no matching order was "
                "found. It is probably no longer open at IBKR. If it still is, "
                "please cancel it in TWS.",
                dispatch_id,
            )
        return

    try:
        ibkr.cancel_order(trade.order)
        _CANCEL_SENT.add(dispatch_id)
        log.info(
            "Cancel for dispatch %s sent to IBKR. It is reported only once the "
            "broker confirms it.",
            dispatch_id,
        )
    except Exception as exc:
        log.error(
            "Cancel for dispatch %s failed: %s. It will be retried on the next "
            "poll.",
            dispatch_id,
            exc,
        )


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

# ── T1-88b F4: die Abbildung der IBKR-Zustaende ──────────────────────────────
#
# Vorher kannte diese Tabelle fuenf von neun Werten. Die vier fehlenden waren
# ausgerechnet die, die einen LEBENDEN Auftrag beschreiben — der Widerruf des
# Phantom-Stornos vom 2026-08-13 (`PreSubmitted`, dann `Submitted`) lag also
# im Prozess vor und wurde stillschweigend weggeworfen.
#
# Ein lebender Auftrag muss die Plattform als `working` erreichen. Dann haelt
# ihr Riegel gegen Doppelauftraege von allein, ohne dass irgendwo eine zweite
# Sonderregel noetig waere.
_STATUS_MAP: dict[str, str] = {
    # Unterwegs, noch nicht am Markt.
    "PendingSubmit": "submitting",
    "ApiPending": "submitting",
    # Am Markt, lebendig.
    "PreSubmitted": "working",
    "Submitted": "working",
    "PendingCancel": "working",
    # T1-88b F4: `Inactive` steht NICHT in `OrderStatus.DoneStates` und ist
    # mehrdeutig — IBKR benutzt es sowohl fuer abgelehnt als auch fuer
    # "angenommen, aber nicht ausfuehrbar". Es als `rejected` zu melden hiesse,
    # im Zweifel den Riegel zu oeffnen, und ein faelschlich geoeffneter Riegel
    # kostet einen zweiten Echtauftrag. Ein faelschlich geschlossener kostet
    # einen Klick. Deshalb nicht-terminal, und laut protokolliert.
    "Inactive": "working",
    # Endzustaende.
    "Filled": "filled",
    "PartiallyFilled": "partial",
    "Cancelled": "cancelled",
    "ApiCancelled": "cancelled",
}

# Zustaende, die einen lebenden Auftrag beschreiben. Nur informativ fuer die
# Plattform — aber genau diese Information hat am 2026-08-13 gefehlt.
_LIVE_STATES = {"submitting", "working"}

# ── T1-88b F2: welche Stornierung von IBKR kommt und welche erfunden ist ─────
#
# ib_insync setzt bei JEDEM Fehlercode ausserhalb seiner Warnliste
# `trade.orderStatus.status = Cancelled` — eine Zuweisung an ein
# Python-Objekt, ohne dass je ein `cancelOrder` ueber die Leitung geht
# (wrapper.py:1122-1134, `grep cancelOrder wrapper.py` ist leer).
#
# Am 2026-08-13 traf das den Hinweis 10349 ("Gueltigkeitsdauer auf DAY
# gesetzt"). Eine Sekunde spaeter meldete IBKR `PreSubmitted` und `Submitted`
# — der Auftrag hatte nie aufgehoert zu leben.
#
# Bewusst KEINE Ausnahmeliste fuer 10349. Die Fehlerklasse ist allgemein:
# jeder Code ausserhalb von ib_insyncs Warnliste loest dieselbe Kette aus, und
# welche Codes IBKR morgen ergaenzt, weiss hier niemand. Umgekehrt gedacht:
# eine Stornierung gilt nur dann sofort, wenn ihr Protokolleintrag sie als
# echte Stornierung ausweist.
#
#   202   Order cancelled — die regulaere Stornobestaetigung
#   10148 Auftrag konnte nicht storniert werden, weil bereits storniert
#   0     kein Fehler, also eine Zustandsmeldung von IBKR selbst
_GENUINE_CANCEL_CODES = {0, 202, 10148}

# Wie lange eine verdaechtige Stornierung nachbeobachtet wird, bevor sie als
# echt gilt. Im Vorfall lag zwischen erfundenem `Cancelled` und echtem
# `Submitted` eine Sekunde; drei sind Reserve, ohne eine echte Stornierung
# spuerbar zu verzoegern.
CANCEL_CONFIRM_DELAY_S = 3.0

# dispatch_id → (trade, faellig_ab). Wird ausschliesslich aus der Hauptschleife
# und dem Rueckruf angefasst, beide auf demselben Thread (siehe Modulkopf) —
# das Schloss schuetzt gegen den Ausfuehrungs-Thread von ib_insync.
_PENDING_CANCEL_CHECKS: dict[str, tuple[Any, float]] = {}
_PENDING_CANCEL_LOCK = threading.Lock()


def _derive_reason_code(
    mapped: str, filled: float, order_type: str, trade: Any = None
) -> str | None:
    """Warum kam die Order NICHT zustande?

    `status` allein wirft Dinge zusammen, die für den Nutzer sehr
    Verschiedenes bedeuten: eine nicht erreichte Limit-Order ist Marktalltag,
    eine Ablehnung ist ein Problem. Ohne diese Unterscheidung steht am Ende
    des Tages nur "cancelled" in der Oberfläche und niemand weiss, ob etwas
    kaputt ist.

    T1-88b: `limit_not_reached` wurde bisher allein aus dem Ordertyp geraten.
    Am 2026-08-13 stand es an einem Auftrag, der sieben Stunden vor
    Boersenoeffnung storniert wurde — ein Limit, das nie eine Chance hatte,
    erreicht zu werden. Der Grund gilt jetzt nur noch, wenn der Auftrag
    ueberhaupt einmal am Markt war.
    """
    if mapped == "rejected":
        return "rejected_by_broker"
    if mapped in ("cancelled", "expired") and filled == 0:
        if order_type in _LIMIT_ORDER_TYPES and _was_ever_live(trade):
            return "limit_not_reached"
        return "expired" if mapped == "expired" else "cancelled_by_user"
    return None


def _was_ever_live(trade: Any) -> bool:
    """Stand dieser Auftrag jemals am Markt?

    Ohne Auftrag keine Aussage — dann gilt die alte Annahme weiter, damit sich
    fuer die bestehenden Aufrufstellen nichts aendert.
    """
    if trade is None:
        return True
    entries = getattr(trade, "log", None) or []
    return any(
        _STATUS_MAP.get(str(getattr(e, "status", ""))) in _LIVE_STATES
        for e in entries
    )


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
        raw = getattr(trade.orderStatus, "status", "")
        mapped = _STATUS_MAP.get(raw)
        if mapped is None:
            # T1-88b F4: nichts faellt mehr stillschweigend heraus. Ein
            # unbekannter Zustand ist entweder eine Ergaenzung der Bibliothek
            # oder ein Tippfehler in der Tabelle — beides will man sehen.
            log.warning(
                "Unknown IBKR order status %r — not reported. Please report "
                "this, the status table is incomplete.",
                raw,
            )
            return

        order_id = int(getattr(trade.order, "orderId", 0))
        with _DISPATCH_MAP_LOCK:
            dispatch_id = dispatch_id_map.get(order_id)
        if not dispatch_id:
            return

        # Lebt oder hat gefuellt: eine schwebende Storno-Nachbeobachtung ist
        # damit beantwortet und faellt weg.
        if mapped in _LIVE_STATES or mapped in ("filled", "partial"):
            _forget_pending_cancel(dispatch_id)

        # T1-88b F2: eine Stornierung ohne Stornobegruendung wird nicht sofort
        # geglaubt. Sie kann von ib_insync stammen statt von IBKR.
        if mapped == "cancelled" and not cancel_is_genuine(trade):
            _defer_cancel_check(dispatch_id, trade)
            return

        _report_status(api, dispatch_id, trade, mapped)

    return on_status


def cancel_is_genuine(trade: Any) -> bool:
    """Stammt diese Stornierung von IBKR oder von ib_insync?

    Der letzte Protokolleintrag des Auftrags traegt den Code, der den Zustand
    ausgeloest hat. Steht dort eine echte Stornobestaetigung, ist die Sache
    klar. Steht dort irgendein anderer Fehlercode, hat ib_insync den Zustand
    selbst gesetzt (wrapper.py:1122-1134) und IBKR weiss nichts davon.

    Kein Protokolleintrag heisst: keine Begruendung, also nachbeobachten.
    Im Zweifel nicht glauben — ein zu frueh gemeldeter Storno oeffnet den
    Riegel der Plattform und kostet einen zweiten Echtauftrag.
    """
    entries = getattr(trade, "log", None) or []
    if not entries:
        return False
    code = getattr(entries[-1], "errorCode", None)
    return code in _GENUINE_CANCEL_CODES


def _defer_cancel_check(dispatch_id: str, trade: Any) -> None:
    """Merkt eine verdaechtige Stornierung zur Nachbeobachtung vor."""
    with _PENDING_CANCEL_LOCK:
        if dispatch_id in _PENDING_CANCEL_CHECKS:
            return
        _PENDING_CANCEL_CHECKS[dispatch_id] = (
            trade,
            time.monotonic() + CANCEL_CONFIRM_DELAY_S,
        )
    entries = getattr(trade, "log", None) or []
    code = getattr(entries[-1], "errorCode", None) if entries else None
    log.warning(
        "Cancellation for dispatch %s arrived with error code %s instead of a "
        "cancel confirmation. That is the signature of a phantom cancel from "
        "ib_insync — holding the report for %.0fs and re-reading the state "
        "afterwards.",
        dispatch_id,
        code,
        CANCEL_CONFIRM_DELAY_S,
    )


def _forget_pending_cancel(dispatch_id: str) -> None:
    with _PENDING_CANCEL_LOCK:
        _PENDING_CANCEL_CHECKS.pop(dispatch_id, None)


def handle_deferred_cancels(
    api: OrdertuneApiClient,
    *,
    monotonic: Callable[[], float] = time.monotonic,
) -> None:
    """Loest die zurueckgehaltenen Stornierungen auf. Laeuft in der Hauptschleife.

    Der Auftrag ist derselbe Python-Gegenstand, den ib_insync fortschreibt —
    ein erneutes Lesen von `orderStatus.status` liefert also den inzwischen
    eingetroffenen echten Zustand. Genau der stand am 2026-08-13 eine Sekunde
    spaeter da und wurde nie angesehen.
    """
    faellig: list[tuple[str, Any]] = []
    with _PENDING_CANCEL_LOCK:
        for dispatch_id, (trade, deadline) in list(_PENDING_CANCEL_CHECKS.items()):
            if monotonic() >= deadline:
                faellig.append((dispatch_id, trade))
                del _PENDING_CANCEL_CHECKS[dispatch_id]

    for dispatch_id, trade in faellig:
        raw = getattr(trade.orderStatus, "status", "")
        mapped = _STATUS_MAP.get(raw)
        if mapped is None:
            log.warning(
                "Re-check for dispatch %s: unknown status %r, nothing "
                "reported.",
                dispatch_id,
                raw,
            )
            continue

        if mapped == "cancelled":
            log.info(
                "Re-check for dispatch %s: the order is still cancelled. "
                "Reporting it now.",
                dispatch_id,
            )
        else:
            log.warning(
                "Phantom cancel for dispatch %s resolved: IBKR reports %r. "
                "The order is alive — reporting %s, not cancelled.",
                dispatch_id,
                raw,
                mapped,
            )
        _report_status(api, dispatch_id, trade, mapped)


def _report_status(
    api: OrdertuneApiClient, dispatch_id: str, trade: Any, mapped: str
) -> None:
    """Meldet einen Zustand an die Plattform, wenn er eine neue Aussage ist."""
    if not should_report(dispatch_id, mapped):
        return

    filled = float(getattr(trade.orderStatus, "filled", 0) or 0)
    avg_price = float(getattr(trade.orderStatus, "avgFillPrice", 0) or 0)
    order_type = str(getattr(trade.order, "orderType", "") or "")
    order_id = int(getattr(trade.order, "orderId", 0))

    # T1-96 B-2: der Nachweis reist mit.
    #
    # `cancel_is_genuine` unterscheidet seit T1-88b die Stornierung, die IBKR
    # gesetzt hat, von der, die ib_insync sich ausgedacht hat — und das
    # Ergebnis wurde bisher weggeworfen. Auf der Leitung stand nur
    # `status: "cancelled"`, und die Plattform musste daraus raten, ob das Ende
    # dieses Auftrags belegt ist. Ihr Riegel gegen Doppelauftraege haengt an
    # genau dieser Frage; ohne Antwort blieb er zu, und ein Signal ging
    # verloren.
    #
    # Nur bei `cancelled`. Fuer die anderen Endzustaende ist diese Pruefung
    # nicht gemacht, und ein Feld, das mehr behauptet als es geprueft hat,
    # waere derselbe Fehler in Gruen. Nichts gesendet heisst auf der Plattform
    # „keine Aussage", und keine Aussage laesst den Riegel zu.
    confirmed_end = cancel_is_genuine(trade) if mapped == "cancelled" else None

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
            reason_code=_derive_reason_code(mapped, filled, order_type, trade),
            broker_order_id=order_id or None,
            broker_confirmed_end=confirmed_end,
        )
        log.info(
            "Result reported for dispatch %s: %s (filled=%s, confirmed_end=%s)",
            dispatch_id,
            mapped,
            filled,
            confirmed_end,
        )
    except Exception as exc:
        log.error("result_order failed for %s: %s", dispatch_id, exc)
        # Die Merkung zuruecknehmen, damit der naechste Versuch durchkommt.
        with _REPORTED_LOCK:
            _LAST_REPORTED.pop(dispatch_id, None)


def run_loop(
    ibkr: Any,
    heartbeat: Callable[[], None],
    pending: Callable[[], None],
    stop: threading.Event,
    *,
    on_tick: Callable[[], None] | None = None,
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
        # T1-88b F2: laeuft in JEDEM Durchgang, nicht nach Intervall. Eine
        # zurueckgehaltene Stornierung soll nach drei Sekunden aufgeloest sein
        # und nicht bis zum naechsten Abruf warten.
        if on_tick is not None:
            on_tick()

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

    # T1-88c: VOR der Schleife. Ohne diesen Schritt ist nach jedem Neustart
    # jeder vorher abgesendete Auftrag unauffindbar — und IBKR meldet TWS
    # taeglich gegen 05:00 MEZ zwangsweise ab.
    rebuild_dispatch_map(ibkr, dispatch_id_map)

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
            on_tick=lambda: handle_deferred_cancels(api),
        )
    finally:
        ibkr.disconnect()
        api.close()

    log.info("Bridge exited normally.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
