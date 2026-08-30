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
from pathlib import Path
from typing import Any, Callable, Iterable
from zoneinfo import ZoneInfo

from . import __version__, console, failures, order_vocabulary, port_probe
from .api_client import OrdertuneApiClient
from .config import load_config
from .fingerprint import compute_fingerprint
from .ibkr_client import IbkrClient
from .external_executions import (
    external_execution_bodies,
    order_types_by_perm_id,
)
from .logging_setup import setup_logging
from .probe import probe_requested, run_probe
from .submitted_store import SubmittedStore
from .order_reconcile import (
    fills_by_dispatch,
    UnresolvedDispatch,
    reconcile_open_dispatches,
)
from .order_translator import (
    apply_bracket_transmit_flags,
    make_contract,
    translate_intent,
)
from .order_vocabulary import IBKR_TO_WIRE_STATUS, LIVE_WIRE_STATES
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
from .order_reference import (  # noqa: F401  (Weiterverwendung durch Importeure)
    ORDER_REF_PREFIX,
    build_order_ref,
    dispatch_id_from_order_ref,
    wire_open_orders,
)


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

# T1-103 H — Auftraege, die bei IBKR liegen, deren Bestaetigung die Plattform
# aber nicht erreicht hat. dispatch_id → IBKR-Auftragsnummer. Wird beim
# naechsten Abruf nachgeholt; ueberlebt bewusst nur die Sitzung, denn nach
# einem Neustart liefert `rebuild_dispatch_map` die Nummer aus dem Vermerk am
# Auftrag selbst.
_ACK_PENDING: dict[str, int] = {}
_ACK_LOCK = threading.Lock()

# Rangfolge der Endzustaende. Ein Endzustand darf einen bereits gemeldeten nur
# ersetzen, wenn er hoeher steht. Eine Ausfuehrung ist die staerkste Aussage,
# die es gibt: sie ist am Konto passiert und laesst sich nicht widerrufen.
# T1-98 / BUG-98-1: `unknown` steht mit Rang 0 UNTER allem anderen.
#
# Ohne Eintrag hier fiel es aus der Rangfolge heraus, und `should_report`
# liess es jeden bereits gemeldeten Endzustand ueberschreiben — eine
# bestaetigte Stornierung waere durch ein "wir wissen es nicht" ersetzt
# worden. Genau die Richtung, gegen die die Rangfolge nach dem 2026-08-13
# ueberhaupt eingefuehrt wurde: was belegt ist, bleibt belegt.
#
# Umgekehrt gilt weiter: eine spaetere Ausfuehrung darf ein `unknown`
# ueberschreiben. Sie ist am Konto passiert.
_TERMINAL_RANK = {
    "unknown": 0,
    "expired": 1,
    "cancelled": 1,
    "rejected": 1,
    "partial": 2,
    "filled": 3,
}


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


def _dispatch_ist_abgelaufen(
    expires_at: Any, *, jetzt: datetime | None = None
) -> bool:
    """Ist die Frist dieser Freigabe verstrichen?

    Ohne Angabe wird NICHT abgelaufen: eine Plattform vor T1-103 sendet das
    Feld moeglicherweise nicht, und eine fehlende Angabe als „abgelaufen" zu
    lesen hiesse, jeden Auftrag zu verschlucken. Der Riegel auf der Plattform
    greift in dem Fall ohnehin.
    """
    if not expires_at:
        return False
    frist = _parse_iso(expires_at)
    if frist is None:
        return False
    return frist <= (jetzt or datetime.now(timezone.utc))


def _handle_pending(
    api: OrdertuneApiClient,
    ibkr: IbkrClient,
    dispatch_id_map: dict[int, str],
    submitted: SubmittedStore,
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

        # T1-103 H — der Riegel gegen den zweiten Echtauftrag.
        #
        # Die Plattform liefert einen Dispatch so lange aus, bis sie eine
        # Bestaetigung hat. Kam die Bestaetigung nicht durch — Zeitueberschrei-
        # tung, 502, Neustart —, steht dieselbe Zeile beim naechsten Abruf
        # wieder da, obwohl der Auftrag bei IBKR laengst liegt. Ohne diese
        # Abfrage ginge er ein zweites Mal hinaus.
        #
        # Statt abzusenden wird die Bestaetigung nachgeholt. Das ist der
        # Schritt, der wirklich fehlt.
        # T1-103 I — der zweite Riegel gegen den Auftrag von vorgestern.
        #
        # Der erste sitzt seit T1-103 in der WHERE-Klausel des Abholpfads. Wie
        # beim Storno-Riegel steht hier ein zweiter, und aus demselben Grund:
        # ein Versehen an dieser Stelle bewegt echtes Geld. Uhrenunterschiede
        # spielen keine Rolle — die Frist ist auf Sitzungsschluss plus halbe
        # Stunde gelegt, und so genau geht keine Rechneruhr daneben.
        if _dispatch_ist_abgelaufen(order.expires_at):
            log.warning(
                "Dispatch %s expired at %s and is not being submitted. A "
                "release is only good for its own trading session.",
                order.dispatch_id,
                order.expires_at,
            )
            continue

        if submitted.bereits_abgeschickt(order.dispatch_id):
            log.warning(
                "Dispatch %s was already sent to IBKR in this or an earlier "
                "session — not sending it again. Retrying the acknowledgement "
                "to Ordertune instead.",
                order.dispatch_id,
            )
            _retry_acknowledge(api, order.dispatch_id, dispatch_id_map)
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
        #
        # T1-103 H — zwei Schritte, zwei Fehlerbehandlungen.
        #
        # Bis hierher lagen `place_order` und `ack_order` in EINEM try-Block mit
        # EINEM except, und dieses except meldete `rejected`. Damit hatte ein
        # Netzfehler beim Bestaetigen zwei Wirkungen, beide falsch:
        #
        #   - Die Plattform trug einen lebenden Auftrag als abgelehnt ein. Der
        #     Nutzer las „Rejected", haelt aber eine echte Position.
        #   - `rejected` ist ein Endzustand und gibt die Wiederfreigabe frei.
        #     Ein zweiter Klick — und zwei Auftraege auf dieselbe Position.
        #
        # Getrennt behandelt bedeutet jeder Fehler das, was er ist: Scheitert
        # das Absenden, liegt nichts beim Broker und `rejected` ist richtig.
        # Scheitert nur die Bestaetigung, liegt der Auftrag da und die Bridge
        # sagt darueber gar nichts — der naechste Abruf holt die Bestaetigung
        # nach, und der Vermerk oben verhindert das zweite Absenden.
        # T1-136 — das angehaengte Ausstiegsbein, sofern die Plattform eines
        # mitgibt. `None` heisst: gewoehnlicher Einzelauftrag wie bisher.
        kind = _attached_exit(intent)

        try:
            contract = make_contract(intent["symbol"])
            ib_order = translate_intent(intent)
            # T1-109 — mit sprechendem Etikett, wenn die Plattform eines mitgibt.
            # Ohne Etikett entsteht exakt das Format von vorher.
            ib_order.orderRef = build_order_ref(
                order.dispatch_id, intent.get("orderRefLabel")
            )

            kind_order = None
            if kind is not None:
                # Das Symbol steht nur am Elternteil — beide Beine handeln
                # denselben Wert, und es zweimal ueber die Leitung zu schicken
                # hiesse, zwei Quellen fuer dieselbe Aussage zu haben.
                kind_order = translate_intent({**kind, "symbol": intent["symbol"]})
                kind_order.orderRef = build_order_ref(
                    kind["dispatchId"], kind.get("orderRefLabel")
                )
                # IBKRs Bracket-Muster: der Parent geht ungesendet hinaus, das
                # Kind zuletzt und mit `transmit=True`. Erst dann uebertraegt
                # TWS beide zusammen.
                #
                # Die Reihenfolge ist kein Stilfrage. Ginge der Parent sofort
                # scharf hinaus und fuellte, bevor das Kind bei IBKR ist, lehnte
                # IBKR das Kind ab — der Auftrag, an den es sich haengen soll,
                # ist dann schon abgeschlossen. Bei einem Limit, das im Geld
                # liegt, sind das Millisekunden.
                apply_bracket_transmit_flags([ib_order, kind_order])

            # Der Vermerk steht VOR dem Absenden. Ein Vermerk ohne Auftrag
            # kostet eine ausgelassene Order — die der Nutzer erneut freigeben
            # kann. Ein Auftrag ohne Vermerk kostet einen zweiten Echtauftrag.
            submitted.vermerken(order.dispatch_id)
            if kind is not None:
                submitted.vermerken(kind["dispatchId"])
            trade = ibkr.place_order(contract, ib_order)

            if kind_order is not None and kind is not None:
                kind_order.parentId = int(getattr(trade.order, "orderId", 0))
                try:
                    kind_trade = ibkr.place_order(contract, kind_order)
                except Exception as kind_exc:
                    # Der Parent liegt bei TWS und ist NICHT uebertragen — ohne
                    # das Kind wird er es auch nie. Ein Auftrag, den die
                    # Plattform fuer lebend haelt und der nie an den Markt geht,
                    # ist der schlimmste der moeglichen Ausgaenge: er ist
                    # unsichtbar. Also beide zuruecknehmen und beide melden.
                    log.error(
                        "attached exit failed for dispatch %s (parent %s): %s — "
                        "cancelling the staged parent",
                        kind["dispatchId"],
                        order.dispatch_id,
                        kind_exc,
                    )
                    try:
                        ibkr.cancel_order(trade.order)
                    except Exception as storno_exc:
                        log.error(
                            "could not cancel the staged parent %s: %s",
                            order.dispatch_id,
                            storno_exc,
                        )
                    submitted.vergessen(order.dispatch_id)
                    submitted.vergessen(kind["dispatchId"])
                    _report_rejected(
                        api,
                        order.dispatch_id,
                        f"attached_exit_failed: {kind_exc}",
                    )
                    # Das Kind MUSS als abgeschlossen gemeldet werden. Bleibt
                    # seine Zeile auf `submitting`, liest `describeLotExit` sie
                    # als `in_flight` und der Roundtrip fasst das Lot nie wieder
                    # an — die Position haette dauerhaft keinen Ausstieg. Genau
                    # der Schaden, gegen den dieses Spec gebaut ist.
                    _report_rejected(
                        api,
                        kind["dispatchId"],
                        f"attached_exit_failed: {kind_exc}",
                    )
                    continue

                kind_ib_order_id = int(getattr(kind_trade.order, "orderId", 0))
                register_trade(dispatch_id_map, kind["dispatchId"], kind_trade)
                _acknowledge(api, kind["dispatchId"], kind_ib_order_id)
                log.info(
                    "Attached exit for dispatch %s: %s %s x%s — ib_order_id=%s, "
                    "parentId=%s",
                    kind["dispatchId"],
                    intent["symbol"],
                    kind["side"],
                    kind["qty"],
                    kind_ib_order_id,
                    kind_order.parentId,
                )
        except Exception as exc:
            # Nichts ist hinausgegangen: der Vermerk faellt wieder weg, damit
            # ein spaeterer Versuch moeglich bleibt.
            submitted.vergessen(order.dispatch_id)
            log.error("submit failed for dispatch %s: %s", order.dispatch_id, exc)
            _report_rejected(api, order.dispatch_id, f"submit_error: {exc}")
            # T1-136: das Kind faellt mit. Es ist nie hinausgegangen, und seine
            # Zeile darf nicht auf `submitting` stehen bleiben — sonst haelt sie
            # den Roundtrip fuer dieses Lot dauerhaft zurueck.
            if kind is not None:
                submitted.vergessen(kind["dispatchId"])
                _report_rejected(
                    api, kind["dispatchId"], f"parent_submit_error: {exc}"
                )
            continue

        ib_order_id = int(getattr(trade.order, "orderId", 0))
        # HB-1: Register mapping BEFORE ack so the status-callback can
        # find the dispatch_id if IBKR fires a fill-event faster than
        # our ack-round-trip.
        #
        # T1-88c: haelt jetzt beide Richtungen fest — die Rueckrichtung
        # braucht der Storno, um den Auftrag ueberhaupt zu finden.
        register_trade(dispatch_id_map, order.dispatch_id, trade)
        _acknowledge(api, order.dispatch_id, ib_order_id)
        log.info(
            "Submitted dispatch %s (%s %s x%s) — ib_order_id=%s",
            order.dispatch_id,
            intent["symbol"],
            intent["side"],
            intent["qty"],
            ib_order_id,
        )

    for dispatch_id in resp.cancelling:
        _handle_cancel(ibkr, dispatch_id)


# Dispatches, fuer die schon ein Storno an IBKR ging. Die Plattform liefert
# sie bei jedem Abruf erneut aus, bis der Broker bestaetigt hat — ohne diese
# Merkung ginge alle fuenf Sekunden ein weiterer Storno raus.
_CANCEL_SENT: set[str] = set()
# Dispatches, zu denen kein Auftrag auffindbar war. Nur damit die Warnung
# einmal erscheint statt im Fuenf-Sekunden-Takt.
_CANCEL_UNRESOLVED: set[str] = set()


def _attached_exit(intent: dict[str, Any]) -> dict[str, Any] | None:
    """T1-136 — das angehaengte Ausstiegsbein aus dem Intent, oder nichts.

    Eng geprueft statt wahrheitswertig: `order_intent` ist ungetyptes `jsonb`,
    und ein halb gefuelltes Feld waere hier schlimmer als ein fehlendes. Ohne
    `dispatchId` liesse sich das Bein weder bestaetigen noch melden — es ginge
    an den Markt und niemand koennte es zuordnen.
    """
    roh = intent.get("attachedExit")
    if not isinstance(roh, dict):
        return None
    if not isinstance(roh.get("dispatchId"), str) or not roh["dispatchId"]:
        return None
    if not isinstance(roh.get("orderType"), str) or not roh.get("side"):
        return None
    return roh


def _report_rejected(
    api: OrdertuneApiClient, dispatch_id: str, error_message: str
) -> None:
    """Meldet einen Auftrag als abgelehnt und ueberlebt das Scheitern dabei.

    Herausgezogen fuer T1-136: der Fall gibt es jetzt an drei Stellen (Parent
    gescheitert, Kind gescheitert, Kind mit dem Parent gefallen), und drei
    Abschriften desselben try/except waeren die Stelle, an der sie
    auseinanderlaufen.
    """
    try:
        api.result_order(
            dispatch_id,
            status="rejected",
            reason_code="rejected_by_broker",
            error_message=error_message,
        )
    except Exception as melde_fehler:
        log.error(
            "Could not report the failed submit for dispatch %s: %s. "
            "Ordertune will keep this row open until the reconcile "
            "round resolves it.",
            dispatch_id,
            melde_fehler,
        )


def _acknowledge(
    api: OrdertuneApiClient, dispatch_id: str, ib_order_id: int
) -> None:
    """T1-103 H — die Bestaetigung. Ihr Scheitern sagt nichts ueber den Auftrag.

    Der Auftrag liegt an dieser Stelle bereits bei IBKR. Geht die Bestaetigung
    nicht durch, ist das ein Problem der Leitung und keines des Handels — und
    die einzig richtige Antwort ist, es spaeter erneut zu versuchen. Was hier
    NICHT passieren darf, ist eine Aussage ueber den Auftrag: `rejected` waere
    gelogen, und die Luege gaebe die Wiederfreigabe frei.
    """
    try:
        api.ack_order(
            dispatch_id,
            broker_order_id=ib_order_id,
            submitted_at=datetime.now(timezone.utc).isoformat(),
        )
        with _ACK_LOCK:
            _ACK_PENDING.pop(dispatch_id, None)
    except Exception as exc:
        with _ACK_LOCK:
            _ACK_PENDING[dispatch_id] = ib_order_id
        log.error(
            "The order for dispatch %s IS at your broker (IBKR order %s), but "
            "Ordertune could not be told: %s. The order is untouched. The next "
            "poll retries the acknowledgement — no second order will be sent.",
            dispatch_id,
            ib_order_id,
            exc,
        )


def _retry_acknowledge(
    api: OrdertuneApiClient,
    dispatch_id: str,
    dispatch_id_map: dict[int, str],
) -> None:
    """Holt eine ausgebliebene Bestaetigung nach.

    Die Broker-Auftragsnummer kommt aus zwei Quellen, in dieser Reihenfolge:
    der gemerkten Fehlschlagliste dieser Sitzung, sonst der nach einem Neustart
    wiederhergestellten Zuordnung. Findet sich keine, bleibt es beim Vermerk —
    dann klaert der Abgleich (`/orders/unresolved`) den Fall, und ein zweites
    Absenden bleibt in jedem Fall aus.
    """
    with _ACK_LOCK:
        ib_order_id = _ACK_PENDING.get(dispatch_id)

    if ib_order_id is None:
        trade = trade_for_dispatch(dispatch_id)
        if trade is not None:
            ib_order_id = int(getattr(getattr(trade, "order", None), "orderId", 0)) or None
    if ib_order_id is None:
        with _DISPATCH_MAP_LOCK:
            for order_id, kennung in dispatch_id_map.items():
                if kennung == dispatch_id:
                    ib_order_id = order_id
                    break

    if ib_order_id is None:
        log.warning(
            "No IBKR order number known for dispatch %s — the reconcile round "
            "will resolve it. Not sending a second order.",
            dispatch_id,
        )
        return

    _acknowledge(api, dispatch_id, ib_order_id)


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


# T1-94: welche fremden Ausfuehrungen diese Sitzung schon gemeldet hat.
#
# Reine Sparsamkeit, KEINE Sicherung: der Abruf laeuft im Minutentakt und
# lieferte sonst dieselbe Ausfuehrung sechzigmal pro Stunde. Nach einem Neustart
# ist die Menge leer und alles wird erneut gemeldet — die Entdopplung liegt
# deshalb auf dem Server, denn nur er ueberlebt den Neustart.
_REPORTED_EXTERNAL: set[str] = set()

# Wie lange nach dem Abruf auf die Gebuehrenabrechnung gewartet wird. Sie
# trifft als eigenes, spaeteres Ereignis ein und wird nachtraeglich in dasselbe
# Fill-Objekt geschrieben; gemessen am 2026-08-17 im selben Sekundenbruchteil.
EXTERNAL_COMMISSION_GRACE_S = 2.0


def _handle_external_executions(api: OrdertuneApiClient, ibkr: IbkrClient) -> None:
    """Fragt nach Ausfuehrungen, die nicht von uns sind, und meldet sie.

    Laeuft im Heartbeat-Takt. Der Takt existiert ohnehin, und ein Abruf pro
    Minute ist der billigste Ausloeser, den es gibt.

    Bewusst NICHT an eine Positionsaenderung gekoppelt: Kauf und Verkauf
    zwischen zwei Takten heben sich im Bestand auf, und beide Zeilen waeren
    verloren.

    Faengt alles ab. Der Heartbeat ist das Lebenszeichen der Bridge; ein
    Fehlschlag hier darf ihn unter keinen Umstaenden mitreissen.
    """
    try:
        ibkr.executions()
        ibkr.sleep(EXTERNAL_COMMISSION_GRACE_S)
        fills = ibkr.fills()
        if not fills:
            return

        # Der Ordertyp haengt am Auftrag, nicht an der Ausfuehrung. Ueber die
        # permId laesst er sich dazuholen — aus offenen wie abgeschlossenen.
        order_types = order_types_by_perm_id(
            ibkr.all_open_trades() + ibkr.completed_trades(api_only=False)
        )

        bodies = external_execution_bodies(
            fills, order_types, _REPORTED_EXTERNAL
        )
    except Exception as exc:
        log.warning("Could not collect external executions: %s", exc)
        return

    for body in bodies:
        try:
            stored = api.report_external_execution(body)
        except Exception as exc:
            # Nicht vermerken: beim naechsten Takt erneut versuchen.
            log.warning(
                "Could not report external execution %s: %s",
                body["brokerExecId"],
                exc,
            )
            continue

        _REPORTED_EXTERNAL.add(body["brokerExecId"])
        if stored:
            log.info(
                "External execution recorded: %s %s %s @ %s (execId %s)",
                body["symbol"],
                body["side"],
                body["qty"],
                body["price"],
                body["brokerExecId"],
            )


def _handle_order_reconcile(
    api: OrdertuneApiClient,
    ibkr: IbkrClient,
    session_connected_at: datetime,
) -> None:
    """T1-98 — was die Plattform als offen fuehrt, gegen das, was IBKR kennt.

    Faengt alles ab. Der Abgleich ist eine Zusatzleistung; sein Fehlschlag darf
    weder den Heartbeat noch den Sendeweg beruehren.

    Die Zuordnung laeuft ueber den Auftragsvermerk `ot-<dispatchId>` und NICHT
    ueber die Auftragsnummer: die wechselt mit der Client-Kennung, der Vermerk
    nicht. Genau deshalb funktioniert der Wiederaufbau nach einem Neustart
    ueberhaupt.
    """
    try:
        rows = api.get_unresolved()
    except Exception as exc:
        # Auch ein 404 landet hier — eine Plattform vor T1-98 kennt den Weg
        # nicht. Ohne Sollmenge wird nichts entschieden, und das ist richtig.
        log.debug("Could not fetch unresolved dispatches: %s", exc)
        return

    if not rows:
        return

    unresolved = [
        UnresolvedDispatch(
            dispatch_id=row["dispatchId"],
            symbol=row.get("symbol", ""),
            submitted_at=_parse_iso(row.get("submittedAt")),
            # T1-119: wonach hier ueberhaupt gesucht wird. Eine Plattform vor
            # T1-119 liefert das Feld nicht — dann bleibt es None und der
            # Abgleich entscheidet wie bisher.
            account_id=row.get("accountId") or None,
        )
        for row in rows
        if row.get("dispatchId")
    ]

    open_query_failed = False
    try:
        open_by_ref = _by_dispatch_ref(ibkr.open_trades())
    except Exception as exc:
        # Eine leere Ablage aus einem Abfragefehler saehe aus wie ein leeres
        # Buch — und daraus wuerde die Aussage "IBKR kennt keinen deiner
        # Auftraege mehr". Dieselbe Unterscheidung wie bei den Positionen in
        # T1-99: kein Eintrag ist etwas anderes als keine Antwort.
        log.warning("Could not query open orders for reconcile: %s", exc)
        open_by_ref = {}
        open_query_failed = True

    completed_by_ref: dict[str, Any] = {}
    if not open_query_failed:
        try:
            completed_by_ref = _by_dispatch_ref(
                ibkr.completed_trades(api_only=False)
            )
        except Exception as exc:
            # Der Grund fehlt dann, der Abgleich laeuft trotzdem: ohne die
            # abgeschlossenen Auftraege wird ein verschollener Auftrag als
            # ungeklaert gemeldet statt als abgelehnt. Das ist die schwaechere,
            # aber nie die falsche Aussage.
            log.warning("Could not query completed orders: %s", exc)

    # T1-105: die Ausfuehrungsberichte des Tages. Sie tragen die Zahlen, die
    # der abgeschlossene Auftrag nicht traegt — gemessen am 2026-08-19 an drei
    # echten Ausfuehrungen. Derselbe Abruf, den `external_executions` fuer die
    # FREMDEN Handel macht; hier wird die andere Haelfte gelesen.
    fills_by_ref: dict[str, Any] = {}
    try:
        fills_by_ref = fills_by_dispatch(ibkr.fills())
    except Exception as exc:
        # Ohne sie faellt der Abgleich auf das Verhalten von 0.9.1 zurueck:
        # ein Auftrag ohne Mengenangabe bleibt ungeklaert. Schwaecher, nie
        # falsch.
        log.warning("Could not read executions for reconcile: %s", exc)

    # T1-119 — mit welchem Depot diese Sitzung verbunden ist.
    #
    # `None` bei mehreren verwalteten Konten; dann wird nicht entschieden und
    # der Abgleich laeuft wie vor T1-119. Faengt alles ab: ein Fehlschlag hier
    # darf den Abgleich nicht mitreissen, und ohne Kennung ist er weiterhin
    # gueltig, nur weniger genau.
    try:
        verbundenes_konto = ibkr.trading_account()
    except Exception as exc:  # pragma: no cover - defensiv
        log.debug("Could not resolve the connected account: %s", exc)
        verbundenes_konto = None

    actions = reconcile_open_dispatches(
        unresolved=unresolved,
        open_by_ref=open_by_ref,
        completed_by_ref=completed_by_ref,
        session_connected_at=session_connected_at,
        open_query_failed=open_query_failed,
        fills_by_ref=fills_by_ref,
        connected_account=verbundenes_konto,
    )

    for action in actions:
        if not should_report(action.dispatch_id, action.status):
            continue
        try:
            # T1-104: die Zahlen einer nachgeholten Ausfuehrung reisen mit.
            # Ohne sie war `filled` fuer die Plattform wertlos — der Bestand
            # entsteht aus der Menge, nicht aus dem Wort.
            api.result_order(
                action.dispatch_id,
                status=action.status,
                fill_qty=action.fill_qty,
                fill_price=action.fill_price,
                commission_usd=action.commission_usd,
                filled_at=(
                    datetime.now(timezone.utc).isoformat()
                    if action.fill_qty
                    else None
                ),
                reason_code=action.reason_code,
                error_message=action.error_message,
            )
            if action.fill_qty:
                log.info(
                    "Reconciled dispatch %s -> %s, %s shares at %s. This "
                    "execution happened while the Bridge was not connected; "
                    "Ordertune has it now.",
                    action.dispatch_id,
                    action.status,
                    action.fill_qty,
                    action.fill_price,
                )
            else:
                log.info(
                    "Reconciled dispatch %s -> %s (%s)",
                    action.dispatch_id,
                    action.status,
                    action.reason_code,
                )
        except Exception as exc:
            log.warning(
                "Could not report reconciled dispatch %s: %s",
                action.dispatch_id,
                exc,
            )


def _by_dispatch_ref(trades: Iterable[Any]) -> dict[str, Any]:
    """Auftragsliste -> Ablage nach Dispatch-Kennung.

    Auftraege ohne unseren Vermerk fallen weg: was ohne `ot-`-Kennung im Buch
    liegt, hat der Nutzer selbst gestellt und geht uns nichts an. Dieselbe
    Grenze wie bei den fremden Positionen in T1-94.
    """
    out: dict[str, Any] = {}
    for trade in trades:
        dispatch_id = dispatch_id_from_order_ref(
            getattr(getattr(trade, "order", None), "orderRef", None)
        )
        if dispatch_id:
            out[dispatch_id] = trade
    return out


def _parse_iso(value: Any) -> datetime | None:
    """ISO-Zeitpunkt von der Leitung, oder nichts.

    `None` heisst hier "kein Absendezeitpunkt bekannt", und der Abgleich
    entscheidet daraufhin nichts — ohne ihn laesst sich der Riegel gegen das
    Phantom nicht stellen.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _open_orders_fuer_bericht(ibkr: IbkrClient) -> list[dict[str, Any]] | None:
    """Die eigenen offenen Auftraege fuer den Rueckbericht, oder `None`.

    `None` heisst „nicht erhoben" und laesst das Feld auf der Leitung weg. Das
    ist wichtig: eine leere Liste ist die Aussage „nichts offen", und die
    Plattform darf daraus schliessen duerfen. Scheitert die Abfrage, sagen wir
    lieber nichts als etwas Falsches.
    """
    try:
        return wire_open_orders(ibkr.open_trades())
    except Exception as exc:  # pragma: no cover — Verbindungsfehler
        log.debug("open-order report skipped: %s", exc)
        return None


def _handle_heartbeat(
    api: OrdertuneApiClient, ibkr: IbkrClient
) -> tuple[Any | None, Exception | None]:
    """T1-101 B-1/B-4: die gesendete Momentaufnahme und, falls es schiefging, warum.

    Rein additiv — am Verhalten des Herzschlags aendert sich nichts. Der
    Rueckgabewert speist den Zustandsblock des Cockpits, ohne dass dafuer ein
    zweites Mal bei IBKR angefragt werden muesste.

    Die Ausnahme wird mitgegeben, weil „der Herzschlag kam nicht durch" auf der
    Flaeche zu wenig ist: ein widerrufener Token und ein ausgefallenes Netz
    sehen gleich aus und verlangen Verschiedenes. Zugeordnet wird sie in
    `failures.py`, wo auch die Startfehler zugeordnet werden (E-6).
    """
    if not ibkr.is_connected():
        log.warning("heartbeat: IBKR disconnected — skipping snapshot push")
        return None, None
    try:
        snap = ibkr.account_snapshot()
        # T1-99: der Heartbeat geht auch ohne Depotauskunft raus — er ist
        # zuerst ein Lebenszeichen. Ohne ihn hielte der Offline-Erkenner die
        # Bridge fuer tot, und der Nutzer suchte den Fehler an der falschen
        # Stelle. Die fehlende Liste sagt der Plattform genau das, was der
        # Fall ist: Verbindung steht, Depot noch unbekannt.
        if snap.positions is None:
            log.warning(
                "heartbeat: portfolio still unknown — sending a plain "
                "liveness beat without positions. Ordertune will not book any "
                "position as sold while this lasts."
            )
        api.heartbeat(
            cash=snap.cash,
            equity=snap.equity,
            currency=snap.currency,
            positions=snap.positions,
            gateway_status=snap.gateway_status,
            capabilities=IBKR_CAPABILITIES,
            # T1-107: die Kennung wurde seit T1-103 O erhoben und nie
            # uebertragen. `None` bei mehreren verwalteten Konten — dann laesst
            # `heartbeat` das Feld weg, und die Plattform behandelt den
            # Snapshot als nicht identifiziert.
            account=snap.account,
            # T1-114: die Antwort auf `reqOpenOrders`, die bis hierher nur als
            # Ja/Nein fuer die Schreibrechte ausgewertet und dann verworfen
            # wurde. Sie beantwortet die Frage, die der Owner an drei Tagen in
            # drei Formen gestellt hat: liegt beim Broker wirklich das, was wir
            # gesendet haben?
            open_orders=_open_orders_fuer_bericht(ibkr),
        )
        return snap, None
    except Exception as exc:
        log.warning("heartbeat push failed: %s", exc)
        return None, exc


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
# T1-120 — die Abbildung liegt jetzt in `order_vocabulary`.
#
# Sie stand hier, und `order_reconcile` fuehrte daneben eine Teilmenge mit dem
# Vermerk „wortgleich zur Abbildung in main._STATUS_MAP". Der Abgleich braucht
# seit T1-120 die volle Abbildung; eine dritte Kopie waere die Stelle gewesen,
# an der die drei auseinanderlaufen.
_STATUS_MAP = IBKR_TO_WIRE_STATUS

# Zustaende, die einen lebenden Auftrag beschreiben. Nur informativ fuer die
# Plattform — aber genau diese Information hat am 2026-08-13 gefehlt.
_LIVE_STATES = LIVE_WIRE_STATES

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

# ── T1-102 A: eine Ablehnung ist keine Warnung ───────────────────────────────
#
# Die Regel darueber liest jeden Fehlercode ausserhalb der Storno-Liste als
# "verdaechtig" und haelt den Auftrag im Zweifel fuer lebend. Fuer den Hinweis
# 10349 vom 2026-08-13 war das richtig — er ist eine Warnung, und der Auftrag
# lebte weiter.
#
# Am 2026-08-18 traf dieselbe Regel den Code 201:
#
#   Error 201, reqId 330: Order abgewiesen - Grund:Verfuegbare Mittel in
#   Basiswaehrung: 1037.11 USD Barmittel fuer diese und weitere offene Orders
#   benoetigt: 1418.40 USD
#
# 201 ist IBKRs Wort fuer "abgelehnt". Der Auftrag ist tot, und zwar auf
# Ansage. Die Nachbeobachtung las danach `Inactive`, bildete das auf `working`
# ab, und CRWD stand auf t1 als "AT BROKER" ueber einem Auftrag, den IBKR nie
# angenommen hat.
#
# Bewusst eine ENGE, belegte Liste und keine Heuristik ueber Zahlenbereiche:
# was hier falsch geraten wird, kostet entweder einen Echtauftrag oder ein
# verlorenes Signal. Neue Codes kommen dazu, wenn sie beobachtet wurden — nicht
# vorher.
#
#   201  Order rejected — IBKR weist den Auftrag ab, mit Begruendung im Text
_REJECTION_CODES = {201}

# ── T1-103 G: die Liste war der Fehler, nicht ihre Laenge ────────────────────
#
# `_REJECTION_CODES = {201}` ist eine Positivliste, und eine Positivliste ueber
# fremde Fehlercodes ist immer unvollstaendig. Am 2026-08-19 traf es NBIS: TWS
# hat den Auftrag abgelehnt, der Code stand nicht in der Liste, und die Bridge
# meldete `cancelled`. Auf t1 stand danach „Cancelled" an einem Auftrag, den
# niemand storniert hatte — und die Wiederfreigabe war gesperrt, weil ein
# unbestaetigtes Ende den Riegel schliesst.
#
# Die Frage laesst sich auch andersherum stellen, und dann wird sie
# vollstaendig: WELCHE Codes bedeuten, dass der Auftrag noch lebt oder
# ordentlich storniert wurde? Das sind genau zwei Gruppen, und beide sind
# bekannt:
#
#   1. Die echten Stornobestaetigungen — `_GENUINE_CANCEL_CODES`, seit T1-88b.
#      Code 0 gehoert dazu: ein Protokolleintrag ohne Fehlercode ist ein
#      blosser Zustandswechsel.
#   2. Die Warnungen. IBKR dokumentiert den Block 2100–2199 als „Warning
#      Message"; sie beenden keinen Auftrag. Genau aus dieser Klasse stammt
#      der Vorfall vom 2026-08-13.
#
# Alles andere, was am Ende des Protokolls eines endgueltig toten Auftrags
# steht, ist eine Ablehnung. Diese Richtung ist auch die sichere: der Irrtum
# faellt auf `rejected` statt auf `cancelled`, und `rejected` ist der Zustand,
# der NICHTS beim Broker behauptet — er kann keinen zweiten Echtauftrag
# ausloesen, er gibt nur die Wiederfreigabe frei.
_WARNING_CODE_MIN = 2100
_WARNING_CODE_MAX = 2200

# Warnungen ausserhalb des 2100er-Blocks, die uns nachweislich begegnet sind.
# 10349 ist der Ausloeser von T1-88b: „Gueltigkeitsdauer auf DAY gesetzt" —
# eine Anpassung, keine Ablehnung, und ib_insync macht daraus trotzdem ein
# erfundenes `Cancelled`. Die Liste ist bewusst kurz und waechst nur mit
# gemessenen Faellen.
_KNOWN_WARNING_CODES = {10349}


def _is_warning_code(code: int) -> bool:
    """Ist das eine Warnung von IBKR und damit kein Ende des Auftrags?"""
    if code in _KNOWN_WARNING_CODES:
        return True
    return _WARNING_CODE_MIN <= code < _WARNING_CODE_MAX


def rejection_reason(trade: Any) -> str | None:
    """Der Wortlaut, mit dem IBKR diesen Auftrag abgelehnt hat, oder nichts.

    Zwei Wege zur selben Antwort:

    1. Ein Code aus `_REJECTION_CODES` irgendwo im Protokoll. Das ist der
       belegte Fall und bleibt unveraendert.
    2. Der allgemeine Fall (T1-103 G): der LETZTE Protokolleintrag traegt einen
       Fehlercode, der weder eine Stornobestaetigung noch eine Warnung ist.
       Der letzte Eintrag ist der, der den aktuellen Zustand ausgeloest hat —
       dieselbe Stelle, an der `cancel_is_genuine` seit T1-88b nachsieht.

    Der zweite Weg wird nur beschritten, wenn nichts gefuellt wurde. Eine
    Ausfuehrung ist am Konto passiert; was danach im Protokoll steht, kann sie
    nicht mehr zu einer Ablehnung machen.

    `None` heisst „keine Ablehnung gefunden" — und dann bleibt es bei der
    Vorsicht aus T1-88b.
    """
    entries = list(getattr(trade, "log", None) or [])

    for entry in reversed(entries):
        if getattr(entry, "errorCode", 0) in _REJECTION_CODES:
            message = (getattr(entry, "message", "") or "").strip()
            return message or "Rejected by IBKR."

    if not entries:
        return None

    # Der allgemeine Weg deutet einen als storniert gemeldeten Auftrag um. Er
    # gilt deshalb NUR dort, wo genau das vorliegt: der Auftrag steht jetzt auf
    # `Cancelled`. Lebt er noch — und das ist der Verlauf des Vorfalls vom
    # 2026-08-13, wo eine Sekunde spaeter `Submitted` kam —, ist hier nichts zu
    # entscheiden. Ohne Zustandsangabe wird ebenfalls nichts behauptet.
    status = getattr(getattr(trade, "orderStatus", None), "status", "")
    if _STATUS_MAP.get(str(status)) != "cancelled":
        return None

    filled = float(getattr(getattr(trade, "orderStatus", None), "filled", 0) or 0)
    if filled != 0:
        return None

    letzter = entries[-1]
    code = getattr(letzter, "errorCode", None)
    if code is None:
        return None
    # Code 0 steckt bereits in `_GENUINE_CANCEL_CODES` — ein Eintrag ohne
    # Fehlercode ist ein Zustandswechsel und sagt nichts ueber eine Ablehnung.
    if code in _GENUINE_CANCEL_CODES:
        return None
    if _is_warning_code(code):
        return None

    message = (getattr(letzter, "message", "") or "").strip()
    return message or "Rejected by IBKR."

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
        # T1-102 A: zuerst die Frage, ob IBKR ueberhaupt abgelehnt hat. Sie
        # schlaegt die Zustandsabbildung, weil ein `Inactive` nach einer
        # Ablehnung kein lebender Auftrag ist, sondern die Leiche.
        grund = rejection_reason(trade)
        if grund is not None:
            log.warning(
                "Re-check for dispatch %s: IBKR rejected this order — %s. "
                "Reporting it as rejected, not as alive.",
                dispatch_id,
                grund,
            )
            if should_report(dispatch_id, "rejected"):
                try:
                    api.result_order(
                        dispatch_id,
                        status="rejected",
                        reason_code="rejected_by_broker",
                        error_message=grund[:500],
                        broker_confirmed_end=True,
                    )
                except Exception as exc:
                    log.warning(
                        "Could not report rejection for dispatch %s: %s",
                        dispatch_id,
                        exc,
                    )
            continue

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


ENV_FILE = "bridge.env"


# ── T1-101 B-1: die vier Beruehrpunkte zum Cockpit ───────────────────────────
#
# Bewusst als vier kleine Funktionen und nicht als Objekt, das durch die
# Schleife gereicht wird: der Kern soll das Cockpit nicht kennen muessen. Jede
# von ihnen faengt alles ab, was schiefgehen kann. **Das Cockpit ist Beiwerk,
# die Schleife ist es nicht** — ein Fehler in der Anzeige darf nie einen
# Heartbeat kosten, und ein Heartbeat ist das Einzige, woran die Plattform
# erkennt, dass diese Bridge lebt.


def start_cockpit(
    argv: list[str],
    *,
    config: Any,
    version: str,
    fingerprint: str,
    log_file: Path | None,
    session_connected_at: datetime,
    write_access: Any,
) -> Any | None:
    """Startet das Cockpit — ausser unter `--headless`."""
    if console.headless_requested(argv):
        return None
    try:
        from .cockpit import CockpitServer, CockpitState, StateStore
        from .cockpit import runfile

        store = StateStore(
            CockpitState(
                bridge_version=version,
                client_id=config.ibkr_client_id,
                gateway_host=config.ibkr_gateway_host,
                gateway_port=config.ibkr_gateway_port,
                fingerprint_prefix=fingerprint[:16],
                log_path=str(log_file) if log_file else "",
                api_base=str(config.ordertune_api_base),
                tws_connected=True,
                ordertune_ok=True,
                session_connected_at=session_connected_at.isoformat(),
                write_access=write_access.state,
                write_access_detail=write_access.detail,
            )
        )
        from .cockpit import journal as journal_mod
        from .cockpit import window as window_mod
        from .logging_setup import LOG_FORMAT

        journal = journal_mod.attach(LOG_FORMAT)

        def diagnostics() -> dict[str, Any]:
            """T1-101 B-5 — was der Support braucht, ohne das, was er nicht darf.

            Kein Token, keine Connection-ID: „Copy diagnostics" landet als
            Naechstes in einem Chat oder einer E-Mail.
            """
            state, _ = store.get()
            return {
                "bridgeVersion": version,
                "endpoint": f"{config.ibkr_gateway_host}:{config.ibkr_gateway_port}",
                "clientId": config.ibkr_client_id,
                "fingerprintPrefix": fingerprint[:16],
                "logPath": str(log_file) if log_file else "",
                "apiBase": str(config.ordertune_api_base),
                "logLevel": config.log_level,
                "writeAccess": state.write_access,
                "lastHeartbeatAt": state.last_heartbeat_at,
                "failureCode": state.failure_code,
            }

        from .cockpit import SetupActions

        server = CockpitServer(
            store,
            journal=journal,
            diagnostics=diagnostics,
            setup=SetupActions(
                Path(ENV_FILE).resolve(),
                store=store,
                orders_in_flight=orders_in_flight,
                api_base=str(config.ordertune_api_base),
            ),
        )
        url = server.start()
        runfile.write(config.ibkr_client_id, url)
        log.info("Cockpit window: %s", window_mod.open_window(url))
        return server
    except Exception as exc:
        log.warning("Cockpit could not start (the bridge keeps running): %s", exc)
        return None


def orders_for_cockpit() -> list[dict[str, Any]]:
    """T1-101 B-3 — was diese Bridge gerade ueber ihre Auftraege weiss.

    Quelle ist die lokale Ablage `_TRADES_BY_DISPATCH`. Sie ueberlebt einen
    Neustart, weil `rebuild_dispatch_map` sie aus dem Auftragsvermerk bei IBKR
    wieder aufbaut (T1-88c) — und sie traegt den Zustand, den IBKR **jetzt**
    meldet, nicht den, den die Plattform zuletzt gespeichert hat.

    Das Vokabular kommt aus T1-100 (D14): dieselben Worte wie im Order
    Management, damit nicht zwei Flaechen ueber dieselbe Sache verschieden
    reden. Ein abgelehnter Auftrag traegt IBKRs eigenen Wortlaut (T1-102, D16)
    — der Satz, der die Frage des Nutzers vollstaendig beantwortet und bisher
    nur im Protokoll stand.
    """
    with _DISPATCH_MAP_LOCK:
        paare = list(_TRADES_BY_DISPATCH.items())

    zeilen: list[dict[str, Any]] = []
    for dispatch_id, trade in paare:
        order = getattr(trade, "order", None)
        contract = getattr(trade, "contract", None)
        roh = _status_of_trade(trade)
        grund = rejection_reason(trade)
        zeilen.append(
            {
                "dispatchId": dispatch_id,
                "symbol": getattr(contract, "symbol", None) or "?",
                "action": getattr(order, "action", None) or "?",
                "qty": getattr(order, "totalQuantity", None),
                "status": order_vocabulary.label(
                    "rejected" if grund else _STATUS_MAP.get(roh or "", roh)
                ),
                "reason": grund,
            }
        )
    zeilen.sort(key=lambda z: (str(z["symbol"]), str(z["dispatchId"])))
    return zeilen


def _status_of_trade(trade: Any) -> str | None:
    return getattr(getattr(trade, "orderStatus", None), "status", None)


def orders_in_flight() -> bool:
    """T1-101 C-5 — ist gerade ein Auftrag unquittiert unterwegs?

    Der Riegel vor dem Speichern: eine geaenderte Client-ID oder ein
    geaenderter Port waehrend eines lebenden Auftrags heisst beim naechsten
    Start, dass die Verbindung ihn nicht mehr findet.
    """
    with _DISPATCH_MAP_LOCK:
        trades = list(_TRADES_BY_DISPATCH.values())
    return any(
        _STATUS_MAP.get(_status_of_trade(t) or "", "") in _LIVE_STATES for t in trades
    )


# Wie oft der Assistent nachsieht, ob `bridge.env` inzwischen ladbar ist.
SETUP_POLL_S = 2.0


def run_setup_cockpit(
    failure: failures.Failure,
    env_path: Path,
    argv: list[str],
) -> bool:
    """T1-101 C-1 / D3 — die Oberflaeche startet vor der Konfiguration.

    Bis hierher endete der Start bei einer fehlenden oder kaputten
    `bridge.env` mit `return 1`. Ein Fenster, das nur erscheint, wenn schon
    alles funktioniert, loest aber nichts — es muss genau dann da sein, wenn
    nichts funktioniert.

    Deshalb dreht sich die Reihenfolge: Fenster hoch, Assistent, und erst wenn
    die Datei ladbar ist, geht es weiter. Der Rueckgabewert sagt, ob es
    weitergeht.

    Der Assistent geht nur auf, wenn auch jemand da ist, der etwas eintraegt —
    dieselbe Bedingung wie beim Halt aus A-1. Sonst waere es kein Assistent,
    sondern ein haengender Vorgang.
    """
    if not console.setup_wanted(argv):
        return False

    try:
        from .cockpit import CockpitServer, CockpitState, SetupActions, StateStore
        from .cockpit import runfile
        from .cockpit import window as window_mod

        store = StateStore(
            CockpitState(
                bridge_version=__version__,
                setup_mode=True,
                failure_code=failure.code,
                failure_headline=failure.headline,
                failure_detail=list(failure.detail),
                failure_action=list(failure.action),
            )
        )
        server = CockpitServer(
            store, setup=SetupActions(env_path, store=store)
        )
        url = server.start()
        runfile.write(0, url)
        window_mod.open_window(url)
        print(f"\n  A setup window has opened: {url}\n", flush=True)
    except Exception as exc:
        log.debug("Setup cockpit could not start: %s", exc)
        return False

    try:
        while True:
            time.sleep(SETUP_POLL_S)
            try:
                load_config()
            except Exception:
                continue
            log.info("bridge.env is readable now — continuing startup.")
            return True
    except KeyboardInterrupt:
        return False
    finally:
        server.stop()
        runfile.remove(0)


def mask_account(account: str | None) -> str | None:
    """T1-103 O — die Kontokennung, so weit gekuerzt, dass sie noch unterscheidet.

    Der Zweck ist, ein Live- von einem Papierkonto zu unterscheiden, nicht die
    Nummer auszuweisen. IBKR-Papierkonten beginnen mit `D`, Livekonten mit `U`
    — der erste Buchstabe und die letzten beiden Stellen reichen dafuer, und
    mehr gehoert nicht in eine Anzeige, die ueber HTTP ausgeliefert wird.

    Die Zusage aus T1-97 lautet, dass die vollstaendige Nummer den Prozess nur
    maskiert verlaesst. Das Cockpit ist ein Prozessausgang.
    """
    if not account:
        return None
    kennung = str(account).strip()
    if len(kennung) <= 3:
        return kennung
    return f"{kennung[0]}***{kennung[-2:]}"


def report_heartbeat(
    cockpit: Any | None,
    tws_connected: bool,
    snap: Any | None,
    error: Exception | None = None,
    api_base: str | None = None,
) -> None:
    """Traegt das Ergebnis eines Herzschlags in den Zustandsblock."""
    if cockpit is None:
        return
    try:
        changes: dict[str, Any] = {
            "last_heartbeat_at": datetime.now(timezone.utc).isoformat(),
            "tws_connected": tws_connected,
            "ordertune_ok": snap is not None,
            # Ohne Verbindung ist die Ablage nicht leer, sondern ohne Aussage.
            "orders": orders_for_cockpit() if tws_connected else None,
        }
        # B-4: dieselbe Zuordnung wie beim Start, damit Konsole und Flaeche
        # ueber dieselbe Stoerung dasselbe sagen (E-6).
        if error is not None:
            f = failures.classify_handshake_error(error, api_base)
            changes.update(
                failure_code=f.code,
                failure_headline=f.headline,
                failure_detail=list(f.detail),
                failure_action=list(f.action),
            )
        elif snap is not None:
            changes.update(
                failure_code=None,
                failure_headline=None,
                failure_detail=[],
                failure_action=[],
            )
        if snap is not None:
            changes.update(
                cash=snap.cash,
                equity=snap.equity,
                currency=snap.currency,
                positions=snap.positions,
                # T1-99 woertlich: die Positionsliste ist die einzige Quelle
                # dafuer, ob ueberhaupt eine Depotauskunft vorliegt. `None`
                # heisst „noch nichts gehoert", nicht „nichts im Depot".
                account_known=snap.positions is not None,
                account_masked=mask_account(getattr(snap, "account", None)),
            )
        cockpit.store.update(**changes)
    except Exception as exc:  # pragma: no cover - defensiv
        log.debug("Cockpit state update failed: %s", exc)


def report_poll(cockpit: Any | None) -> None:
    if cockpit is None:
        return
    try:
        cockpit.store.update(
            last_pending_poll_at=datetime.now(timezone.utc).isoformat()
        )
    except Exception as exc:  # pragma: no cover - defensiv
        log.debug("Cockpit state update failed: %s", exc)


def stop_cockpit(cockpit: Any | None, client_id: int) -> None:
    if cockpit is None:
        return
    try:
        from .cockpit import runfile

        cockpit.stop()
        runfile.remove(client_id)
    except Exception as exc:  # pragma: no cover - defensiv
        log.debug("Cockpit shutdown failed: %s", exc)


def _abort(
    failure: failures.Failure,
    log_file: Path | None,
    argv: list[str],
) -> int:
    """T1-101 A-1 — der eine Ausgang fuer jeden Startfehler.

    Bis 0.7.0 hatte jede der drei Abbruchstellen ihre eigene Ausgabe, und keine
    ueberlebte den Doppelklick: gebaut wird mit `--console`, und Windows
    schliesst das Fenster zusammen mit dem Vorgang. Hier laeuft alles zusammen:
    gerahmter Klartext nach `stderr`, eine Zeile ins Protokoll fuer den Support,
    und erst danach das Warten — damit die Meldung noch da ist, wenn jemand
    hinsieht.

    Der Rueckgabewert bleibt 1, wie vorher an allen drei Stellen.
    """
    print(
        failures.render(failure, str(log_file) if log_file else None),
        file=sys.stderr,
        flush=True,
    )
    if log_file is not None:
        # Nur Kennung und Satz, nicht der ganze Block: die Wurzel haengt an der
        # Konsole, sonst stuende alles doppelt auf dem Bildschirm.
        log.error("Startup aborted (%s): %s", failure.code, failure.headline)
    console.hold(argv)
    return 1


def main() -> int:
    argv = sys.argv[1:]

    # Aufgeloest, bevor irgendetwas schiefgeht: bei einem Doppelklick ist das
    # Arbeitsverzeichnis nicht zwingend der Ordner der EXE, und „Datei nicht
    # gefunden" ohne Suchort ist keine Auskunft.
    env_path = Path(ENV_FILE).resolve()

    try:
        config = load_config()
    except Exception as exc:
        failure = failures.classify_config_error(
            exc, str(env_path), env_path.exists()
        )
        # T1-101 C-1 / D3: erst der Assistent, dann der Abbruch. Der gerahmte
        # Block steht trotzdem in der Konsole — wer ohne Fenster arbeitet, soll
        # dieselbe Auskunft bekommen.
        print(failures.render(failure), file=sys.stderr, flush=True)
        if not run_setup_cockpit(failure, env_path, argv):
            console.hold(argv)
            return 1
        try:
            config = load_config()
        except Exception as zweiter:
            return _abort(
                failures.classify_config_error(
                    zweiter, str(env_path), env_path.exists()
                ),
                None,
                argv,
            )

    log_file = setup_logging(level=config.log_level)
    log.info("Log file: %s", log_file)
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
        # T1-98: der Zeitpunkt, ab dem diese Sitzung die Ereignisse von IBKR
        # mitbekommt. Alles, was VORHER abgesendet wurde, kann sie nicht
        # gesehen haben — und nur darauf darf der Abgleich ein Urteil faellen.
        session_connected_at = datetime.now(timezone.utc)
    except Exception as exc:
        # T1-101 A-3: die Portsuche laeuft ausschliesslich hier — im
        # Normalbetrieb wird kein zusaetzlicher Socket geoeffnet.
        answering = port_probe.scan(config.ibkr_gateway_host)
        return _abort(
            failures.classify_connect_error(
                config.ibkr_gateway_host,
                config.ibkr_gateway_port,
                exc,
                answering,
                config.ibkr_client_id,
            ),
            log_file,
            argv,
        )

    # T1-94-Sonde: nur lesen, nichts absenden, dann beenden. Steht hier und
    # nicht frueher, weil sie die Verbindung braucht — und hier, weil ab der
    # naechsten Zeile die Plattform ins Spiel kaeme, die sie nicht braucht.
    if probe_requested(sys.argv[1:]):
        try:
            run_probe(ibkr)
        finally:
            ibkr.disconnect()
        return 0

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
        ibkr.disconnect()
        return _abort(
            failures.classify_handshake_error(
                exc, str(config.ordertune_api_base)
            ),
            log_file,
            argv,
        )

    dispatch_id_map: dict[int, str] = {}
    ibkr.subscribe_order_status_callback(_make_on_order_status(api, dispatch_id_map))

    # T1-88c: VOR der Schleife. Ohne diesen Schritt ist nach jedem Neustart
    # jeder vorher abgesendete Auftrag unauffindbar — und IBKR meldet TWS
    # taeglich gegen 05:00 MEZ zwangsweise ab.
    rebuild_dispatch_map(ibkr, dispatch_id_map)

    # T1-103 H: der Riegel gegen den zweiten Echtauftrag. Er muss vor dem
    # ersten Abruf stehen und ueberlebt als Datei den Neustart, gegen den er
    # schuetzt.
    submitted = SubmittedStore()
    if not submitted.schreibbar:
        log.warning(
            "The bridge cannot remember which orders it already sent. Trading "
            "continues, but a restart between sending an order and confirming "
            "it to Ordertune could send that order twice."
        )

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

    # T1-101 B-1 — das Cockpit. Beiwerk, und wird auch so behandelt: ein
    # Fehler beim Starten kostet die Anzeige, nie den Handel.
    cockpit = start_cockpit(
        argv,
        config=config,
        version=__version__,
        fingerprint=fingerprint,
        log_file=log_file,
        session_connected_at=session_connected_at,
        write_access=ibkr.write_access(),
    )

    try:
        def _beat() -> None:
            # Zuerst das Lebenszeichen, dann die Fremdsicht. Umgekehrt haette
            # ein langsamer Abruf den Heartbeat verzoegert, und der ist das
            # Einzige, woran die Plattform erkennt, dass die Bridge lebt.
            snap, beat_error = _handle_heartbeat(api, ibkr)
            _handle_external_executions(api, ibkr)
            # T1-98: der Rueckweg. Laeuft NACH dem Lebenszeichen und nach der
            # Fremdsicht — er ist die langsamste der drei Aufgaben und die
            # einzige, deren Ausbleiben nichts kaputt macht.
            _handle_order_reconcile(api, ibkr, session_connected_at)
            # Ganz zuletzt, und nur lesend: der Zustandsblock. Er darf keinen
            # der drei Wege oben aufhalten.
            report_heartbeat(
                cockpit,
                ibkr.is_connected(),
                snap,
                beat_error,
                str(config.ordertune_api_base),
            )

        def _poll() -> None:
            _handle_pending(api, ibkr, dispatch_id_map, submitted)
            report_poll(cockpit)

        run_loop(
            ibkr,
            heartbeat=_beat,
            pending=_poll,
            stop=stop,
            on_tick=lambda: handle_deferred_cancels(api),
        )
    finally:
        stop_cockpit(cockpit, config.ibkr_client_id)
        ibkr.disconnect()
        api.close()

    log.info("Bridge exited normally.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
