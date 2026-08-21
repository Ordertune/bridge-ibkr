"""T1-94 — was sieht diese Verbindung von Auftraegen, die nicht von uns sind?

## Woher das kommt

Am 2026-08-15 hat der Owner in TWS die Master API client ID auf 17 gesetzt,
neu gestartet und von Hand eine Order gestellt. Im Protokoll der Bridge stand
danach **nichts** — auch keine Fehlermeldung. `wrapper.orderStatus` wuerde eine
schreiben, wenn ein Zustand zu einem unbekannten Auftrag eintraefe
(`orderStatus: No order found for orderId ... and clientId ...`). Sie fehlt.
Es kam also nichts an, statt dass etwas ankam und verworfen wurde.

Ob das am Wochenende lag oder daran, dass der Master-Weg manuelle TWS-Auftraege
gar nicht traegt, laesst sich aus der Dokumentation nicht entscheiden. Der
Docstring von `wrapper.openOrder` listet beides nebeneinander:

    * feed in open orders or order updates from other clients and TWS
      if clientId=master id
    * feed in manual orders and order updates from TWS if clientId=0

## Was diese Sonde tut

Sie horcht nicht, sie fragt. Drei dokumentierte Abrufe, alle nur lesend:

    reqAllOpenOrders()              alle offenen Auftraege ueber alle Clients
    reqCompletedOrders(False)       abgeschlossene des Tages; `apiOnly=False`
                                    schliesst die von Hand in TWS gestellten
                                    ausdruecklich ein
    reqExecutions()                 die Ausfuehrungen des Tages

Kommt der manuelle Auftrag in einem davon zurueck, ist die Auskunft erreichbar
und nur die Zustellung fehlt — dann baut T1-94 auf einem Abruf statt auf einem
Ereignis. Kommt er nirgends zurueck, ist diese Verbindung fuer fremde Auftraege
blind, und der Weg ueber die Master-Client-ID traegt nicht.

**Es geht kein Auftrag hinaus und keiner wird veraendert.** Die Sonde verbindet
sich, liest, schreibt auf und beendet sich.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

PROBE_FLAG = "--probe-foreign"

from .order_reference import ORDER_REF_PREFIX, is_ours  # noqa: F401

# Wie lange nach dem Abruf auf die Gebuehrenabrechnung gewartet wird. Gemessen
# am 2026-08-17 traf sie im selben Sekundenbruchteil ein; zwei Sekunden sind
# reichlich Reserve fuer eine Diagnose, die ohnehin nur einmal laeuft.
COMMISSION_GRACE_S = 2.0


def probe_requested(argv: list[str]) -> bool:
    """Steht die Sonde auf der Befehlszeile?

    Als reine Funktion, damit die Zusicherung sie ohne Prozess pruefen kann.
    """
    return PROBE_FLAG in argv




def describe_trade(trade: Any) -> str:
    """Eine Zeile je Auftrag, mit den Angaben, an denen T1-94 haengt."""
    order = getattr(trade, "order", None)
    status = getattr(trade, "orderStatus", None)
    contract = getattr(trade, "contract", None)
    ref = getattr(order, "orderRef", None)
    herkunft = "OURS " if is_ours(ref) else "FOREIGN"
    return (
        f"  [{herkunft}] {getattr(contract, 'symbol', '?'):<6} "
        f"{getattr(order, 'action', '?'):<4} "
        f"{getattr(order, 'orderType', '?'):<4} "
        f"qty={getattr(order, 'totalQuantity', '?')} "
        f"lmt={getattr(order, 'lmtPrice', '?')} "
        f"tif={getattr(order, 'tif', '?')} "
        f"status={getattr(status, 'status', '?')} "
        f"filled={getattr(status, 'filled', '?')} "
        f"orderId={getattr(order, 'orderId', '?')} "
        f"clientId={getattr(order, 'clientId', '?')} "
        f"permId={getattr(order, 'permId', '?')} "
        f"orderRef={ref!r}"
    )


def describe_fill(fill: Any) -> str:
    """Eine Zeile je Ausfuehrung.

    Menge, Preis und Zeitpunkt sind das, woraus eine externe Zeile ueberhaupt
    entstehen koennte; `orderRef` sagt, ob sie von uns stammt. Die Gebuehr
    steht im `commissionReport` und trifft gelegentlich spaeter ein.
    """
    ex = getattr(fill, "execution", None)
    contract = getattr(fill, "contract", None)
    report = getattr(fill, "commissionReport", None)
    ref = getattr(ex, "orderRef", None)
    herkunft = "OURS " if is_ours(ref) else "FOREIGN"
    return (
        f"  [{herkunft}] {getattr(contract, 'symbol', '?'):<6} "
        f"{getattr(ex, 'side', '?'):<4} "
        f"shares={getattr(ex, 'shares', '?')} "
        f"price={getattr(ex, 'price', '?')} "
        f"time={getattr(ex, 'time', '?')} "
        f"orderId={getattr(ex, 'orderId', '?')} "
        f"clientId={getattr(ex, 'clientId', '?')} "
        f"permId={getattr(ex, 'permId', '?')} "
        f"execId={getattr(ex, 'execId', '?')} "
        f"commission={getattr(report, 'commission', None)} "
        f"orderRef={ref!r}"
    )


def _abschnitt(titel: str, zeilen: list[str], hinweis: str) -> None:
    log.info("")
    log.info("=== %s ===", titel)
    log.info("%s", hinweis)
    if not zeilen:
        log.info("  (nichts zurueckgekommen)")
        return
    fremd = sum(1 for z in zeilen if "[FOREIGN]" in z)
    for z in zeilen:
        log.info("%s", z)
    log.info("  -> %d Zeilen, davon %d fremd", len(zeilen), fremd)


def run_probe(ibkr: Any) -> None:
    """Fragt die drei Kanaele ab und schreibt auf, was zurueckkommt.

    Jeder Abruf ist einzeln gekapselt: faellt einer aus — etwa weil TWS ihn
    fuer diese Verbindung verweigert —, sollen die anderen trotzdem antworten.
    Genau diese Verweigerung waere ja ein Ergebnis.
    """
    log.info("T1-94-PROBE: frage ab, was diese Verbindung von fremden "
             "Auftraegen sieht. Es geht nichts hinaus.")

    try:
        offen = ibkr.all_open_trades()
        _abschnitt(
            "reqAllOpenOrders — offene Auftraege ueber alle Clients",
            [describe_trade(t) for t in offen],
            "Erwartung, falls der Weg traegt: ein von Hand gestellter, noch "
            "offener Auftrag steht hier als FOREIGN.",
        )
    except Exception as exc:
        log.error("reqAllOpenOrders ist gescheitert: %s", exc)

    try:
        fertig = ibkr.completed_trades(api_only=False)
        _abschnitt(
            "reqCompletedOrders(apiOnly=False) — abgeschlossene des Tages",
            [describe_trade(t) for t in fertig],
            "Der Parameter schliesst von Hand in TWS gestellte Auftraege "
            "ausdruecklich ein. Ein heute stornierter manueller Auftrag "
            "muesste hier auftauchen.",
        )
    except Exception as exc:
        log.error("reqCompletedOrders ist gescheitert: %s", exc)

    try:
        # Der Abruf holt die Ausfuehrungen. Die Gebuehr haengt danach noch
        # nicht daran: `wrapper.commissionReport` schreibt sie als eigenes,
        # spaeteres Ereignis in dasselbe Fill-Objekt. Am 2026-08-17 stand in
        # dieser Zeile deshalb `commission=0.0`, waehrend zwei Zeilen darueber
        # im Protokoll `commission=1.9` zu lesen war — kein Messwert, sondern
        # ein Feld-Default.
        #
        # Dieselbe Staffelung zeigt sich an drei Stellen desselben Vorgangs:
        # die Ausfuehrung kommt zuerst, die Gebuehr danach, und IBKR schreibt
        # sogar `Position.avgCost` nach (157.21 wurde zu 159.11 = Kurs plus
        # Gebuehr). Wer zu frueh liest, bekommt jedes Mal eine Zahl, die
        # richtig aussieht.
        ibkr.executions()
        ibkr.sleep(COMMISSION_GRACE_S)
        fills = ibkr.fills()
        _abschnitt(
            "reqExecutions — Ausfuehrungen des Tages",
            [describe_fill(f) for f in fills],
            f"Die Quelle fuer Herkunft, Uhrzeit, Kurs und Gebuehr. Gelesen "
            f"{COMMISSION_GRACE_S:.0f}s nach dem Abruf, damit die "
            f"Gebuehrenabrechnung eintreffen konnte. IBKR haelt nur den "
            f"laufenden Tag vor.",
        )
    except Exception as exc:
        log.error("reqExecutions ist gescheitert: %s", exc)

    log.info("")
    log.info("T1-94-PROBE: fertig. Bitte die drei Abschnitte oben schicken.")
