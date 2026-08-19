"""T1-98 — der Rueckweg schliesst sich: was IBKR nicht kennt, wird gemeldet.

## Der Befund

Am 2026-08-18 gingen fuenf Auftraege raus. IBKR nahm vier an und verweigerte den
fuenften (SHOP, orderId 226 — annahmegemaess Netto-Liquiditaet ueberschritten).
Auf t1 stehen bis heute fuenf, alle als `working`.

Die Bridge hat es gesehen und nicht gesagt. Ihr eigenes Protokoll:

    Re-mapped 4 open orders via their order reference.

Vier. Nur gab es nichts, wogegen sie diese Vier vergleichen konnte:
`rebuild_dispatch_map` liest `open_trades()` und stellt daraus wieder her, was
noch lebt. Was zwischen zwei Sitzungen terminal wurde, taucht dort nicht auf und
existiert fuer die Bridge nicht mehr.

Die Ablehnung fiel ausserdem in die Ereignisse der VORHERIGEN Sitzung: die
Auftraege gingen 08:44-08:45 raus, die protokollierte Sitzung verband sich erst
08:51:15. Zwei Alltagswege fuehren dorthin — die taegliche TWS-Abmeldung gegen
05:00 MEZ und jeder Neustart durch den Nutzer.

## Warum das hier als reine Funktion steht

Dieselbe Ueberlegung wie bei `user-trades-math.ts` auf der Plattform: die
teuerste Entscheidung dieses Specs — gilt ein Auftrag als verschollen? — soll
ohne TWS pruefbar sein. Ein falsch positiver Befund macht eine lebende Order
endgueltig und damit wieder freigebbar, und aus einem Anzeigefehler wuerde ein
zweiter Echtauftrag.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

# Zustaende, die IBKR fuer einen lebenden Auftrag meldet. Wortgleich zur
# Abbildung in `main._STATUS_MAP` — hier noch einmal, weil diese Datei ohne
# ib_insync auskommen soll.
_LIVE_IBKR_STATES = {
    "PendingSubmit",
    "ApiPending",
    "PreSubmitted",
    "Submitted",
    "PendingCancel",
    "Inactive",
}


@dataclass(frozen=True)
class UnresolvedDispatch:
    """Was die Plattform als offen fuehrt."""

    dispatch_id: str
    symbol: str
    #: ISO-Zeitpunkt des Absendens, oder None.
    submitted_at: datetime | None


@dataclass(frozen=True)
class ReconcileAction:
    """Was der Bridge daraus zu melden hat."""

    dispatch_id: str
    #: Draht-Zustand fuer den Ergebnisweg.
    status: str
    reason_code: str | None
    error_message: str | None
    # T1-104 — die Zahlen einer nachgeholten Ausfuehrung.
    #
    # `None` heisst „keine Angabe" und wird auf der Leitung weggelassen; die
    # Plattform laesst ein nicht gesendetes Feld seit T1-78 ausdruecklich in
    # Ruhe, statt es zu nullen.
    fill_qty: float | None = None
    fill_price: float | None = None
    commission_usd: float | None = None


def reconcile_open_dispatches(
    *,
    unresolved: Iterable[UnresolvedDispatch],
    open_by_ref: dict[str, Any],
    completed_by_ref: dict[str, Any],
    session_connected_at: datetime,
    open_query_failed: bool = False,
) -> list[ReconcileAction]:
    """Der Abgleich, als Entscheidung ohne Nebenwirkung.

    ## Die vier Faelle

    1. **Offen bei IBKR** — nichts zu tun. Der Auftrag lebt, die Plattform
       weiss es bereits.
    2. **Abgeschlossen bei IBKR** — Endzustand melden, samt Grund, wenn einer
       dasteht. IBKR haelt die abgeschlossenen Auftraege des laufenden Tages
       vor; das ist die einzige Stelle, an der nach einem Neustart noch ein
       Grund zu holen ist.
    3. **Nirgends bekannt, und vor dieser Sitzung abgesendet** — ungeklaert.
       Der gemessene Fall.
    4. **Nirgends bekannt, aber NACH dem Verbinden abgesendet** — nichts tun.

    ## Warum Fall 4 der wichtigste ist

    Ohne ihn erklaert der Abgleich einen Auftrag fuer verschollen, der gerade
    erst unterwegs ist: die Plattform hat die Zeile geschrieben, IBKR hat sie
    noch nicht bestaetigt, und der naechste Takt kommt dazwischen. Aus einem
    Anzeigefehler wuerde ein Endzustand, aus dem Endzustand eine wieder
    freigebbare Zeile, und aus der ein zweiter Echtauftrag.

    Das ist dieselbe Fehlerklasse wie der Phantom-Storno vom 2026-08-13, nur
    mit umgekehrtem Vorzeichen.

    ## Warum ein Abfragefehler alles anhaelt

    Schlaegt die Abfrage der offenen Auftraege fehl, liefert sie eine leere
    Ablage — und die sieht aus wie ein leeres Buch. Aus einem Netzwerkfehler
    wuerde dann die Aussage „IBKR kennt keinen deiner Auftraege mehr", und der
    Abgleich schriebe jede laufende Order auf ungeklaert.

    Wortgleich zu der Unterscheidung, die T1-99 fuer die Positionsmeldung
    zieht: kein Eintrag ist etwas anderes als keine Antwort.
    """
    if open_query_failed:
        return []

    aktionen: list[ReconcileAction] = []

    for d in unresolved:
        if d.dispatch_id in open_by_ref:
            continue

        trade = completed_by_ref.get(d.dispatch_id)
        if trade is not None:
            aktionen.append(_from_completed(d, trade))
            continue

        # Fall 4 — der Riegel gegen das Phantom in der Gegenrichtung.
        if d.submitted_at is None or d.submitted_at >= session_connected_at:
            continue

        aktionen.append(
            ReconcileAction(
                dispatch_id=d.dispatch_id,
                status="unknown",
                reason_code="not_known_at_broker",
                error_message=(
                    "IBKR knows this order neither as open nor as completed. "
                    "It was most likely never accepted, or it ended while the "
                    "Bridge was not running."
                ),
            )
        )

    return aktionen


def _from_completed(d: UnresolvedDispatch, trade: Any) -> ReconcileAction:
    """Ein abgeschlossener Auftrag — mit dem Grund, den IBKR dazu liefert.

    Ein noch lebender Zustand in der Liste der abgeschlossenen Auftraege ist ein
    Widerspruch; er wird als ungeklaert gemeldet statt als Endzustand
    ausgelegt. Behaupten ist hier teurer als zugeben.
    """
    status = _status_of(trade)
    if status in _LIVE_IBKR_STATES or status is None:
        return ReconcileAction(
            dispatch_id=d.dispatch_id,
            status="unknown",
            reason_code="not_known_at_broker",
            error_message=(
                "IBKR lists this order as completed but reports a live state "
                f"({status or 'none'}). Ordertune will not guess which one holds."
            ),
        )

    grund = _reason_of(trade)
    if status in ("Filled", "PartiallyFilled"):
        # ── T1-104 — die Fuellung wird jetzt gemeldet, samt Zahlen ──────────
        #
        # ## Was hier stand
        #
        # „Eine Fuellung wird hier NICHT gemeldet. Sie gehoert in den
        # Ergebnisweg mit Preis, Menge und Gebuehr — und den bedient der
        # Ereignispfad. Hier stuende sie ohne Zahlen und wuerde einen
        # vollstaendigen Bericht ueberschreiben."
        #
        # Die Sorge war richtig, die Annahme falsch. Der Auftrag aus
        # `reqCompletedOrders` TRAEGT die Zahlen: `orderStatus.filled`,
        # `orderStatus.avgFillPrice`, und die Gebuehr an den Ausfuehrungen.
        # Sie mussten nur gelesen werden.
        #
        # ## Was die alte Fassung gekostet hat
        #
        # Gemessen am 2026-08-19: INTC (zwei Auftraege) und ALAB wurden
        # ausgefuehrt, waehrend die Bridge nicht verbunden war. Der Abgleich
        # fand sie bei IBKR als `Filled` — und meldete `unknown`. Auf t1
        # tauchten die Stuecke daraufhin unter „Held outside Ordertune" auf:
        # der Broker meldet sie, aber kein Lot ordnet sie einer Strategie zu.
        #
        # Damit ist der Ereignispfad die EINZIGE Stelle, an der eine Fuellung
        # je in die Buecher kam — und er laeuft nur, wenn die Bridge im Moment
        # der Ausfuehrung verbunden ist. Ein Notebook, das zuklappt, kostete
        # die Zuordnung endgueltig. Das ist keine Randlage, sondern der
        # Normalfall einer Anwendung auf einem privaten Rechner.
        #
        # ## Warum das Ueberschreiben heute sicher ist
        #
        # Zwei Riegel, die es damals noch nicht gab:
        #
        #   - `should_report` fuehrt seit T1-98 eine Rangfolge. `filled` steht
        #     mit Rang 3 an der Spitze und kann nur Schwaecheres ersetzen,
        #     nie umgekehrt.
        #   - Die Plattform bucht seit T1-103 nur den ZUWACHS gegenueber
        #     `fill_booked_qty`. Eine zweite Meldung derselben Menge bewegt
        #     den Bestand nicht mehr.
        #
        # ## Und wenn die Zahlen doch fehlen
        #
        # Dann bleibt es bei der ehrlichen Antwort. Eine Fuellung ohne Menge
        # waere genau die Meldung, vor der der alte Kommentar gewarnt hat.
        menge = _filled_qty(trade)
        if menge is None or menge <= 0:
            return ReconcileAction(
                dispatch_id=d.dispatch_id,
                status="unknown",
                reason_code="not_known_at_broker",
                error_message=(
                    "IBKR reports this order as filled but gives no quantity. "
                    "Ordertune will not book a position it cannot measure — "
                    "check the trade in TWS."
                ),
            )

        return ReconcileAction(
            dispatch_id=d.dispatch_id,
            status="filled" if status == "Filled" else "partial",
            reason_code=None,
            error_message=None,
            fill_qty=menge,
            fill_price=_avg_fill_price(trade),
            commission_usd=_commission(trade),
        )

    if status in ("Cancelled", "ApiCancelled"):
        return ReconcileAction(
            dispatch_id=d.dispatch_id,
            status="cancelled",
            reason_code="cancelled_by_user",
            error_message=grund,
        )

    return ReconcileAction(
        dispatch_id=d.dispatch_id,
        status="rejected",
        reason_code="rejected_by_broker",
        error_message=grund,
    )


def _status_of(trade: Any) -> str | None:
    st = getattr(trade, "orderStatus", None)
    status = getattr(st, "status", None)
    return status if isinstance(status, str) and status else None


def _reason_of(trade: Any) -> str | None:
    """Die letzte Protokollzeile mit einem Fehlercode, sonst nichts.

    Bewusst kein Ersatztext: was ib_insync nicht weiss, darf die Bridge nicht
    behaupten. Dieselbe Grenze, die schon beim Storno gilt — ein Verfall zum
    Boersenschluss und ein Storno in TWS sind dort ununterscheidbar.
    """
    log = getattr(trade, "log", None) or []
    for eintrag in reversed(list(log)):
        code = getattr(eintrag, "errorCode", 0)
        message = getattr(eintrag, "message", "") or ""
        if code and message:
            return f"{message} (IBKR {code})"
    advanced = getattr(trade, "advancedError", "") or ""
    return advanced or None


# ── T1-104: die Zahlen einer nachgeholten Ausfuehrung ────────────────────────
#
# Alle drei lesen den Auftrag rein ueber `getattr`, wie `_status_of` und
# `_reason_of` daneben: dieses Modul kommt bewusst ohne ib_insync aus, damit
# die Zusicherungen es ohne TWS fahren koennen.
#
# Jede von ihnen antwortet `None` statt einer erfundenen Null. Eine 0 waere an
# dieser Stelle keine fehlende Angabe, sondern eine Aussage — und zwar eine
# ueber Geld.


def _num(value: Any) -> float | None:
    """Eine Zahl, oder nichts. NaN zaehlt als nichts."""
    if value is None:
        return None
    try:
        zahl = float(value)
    except (TypeError, ValueError):
        return None
    if zahl != zahl:  # NaN
        return None
    return zahl


def _filled_qty(trade: Any) -> float | None:
    """Die kumulierte Fuellmenge, so wie der Ereignispfad sie auch meldet."""
    return _num(getattr(getattr(trade, "orderStatus", None), "filled", None))


def _avg_fill_price(trade: Any) -> float | None:
    """Der Durchschnittskurs. Ohne Fuellung gibt es keinen."""
    preis = _num(getattr(getattr(trade, "orderStatus", None), "avgFillPrice", None))
    if preis is None or preis <= 0:
        return None
    return preis


def _commission(trade: Any) -> float | None:
    """Summe der Broker-Gebuehren, falls IBKR sie schon gemeldet hat.

    Wortgleich zu `main._sum_commission`. Hier noch einmal, aus demselben
    Grund wie `_LIVE_IBKR_STATES`: dieses Modul soll ohne den Rest laufen.
    """
    fills = getattr(trade, "fills", None) or []
    summe = 0.0
    gesehen = False
    for f in fills:
        report = getattr(f, "commissionReport", None)
        wert = _num(getattr(report, "commission", None)) if report else None
        if wert is None:
            continue
        summe += wert
        gesehen = True
    return summe if gesehen else None
