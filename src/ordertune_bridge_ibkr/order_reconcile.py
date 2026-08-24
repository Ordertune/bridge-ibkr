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

from .order_vocabulary import (
    IBKR_TO_WIRE_STATUS,
    LIVE_IBKR_STATES as _LIVE_IBKR_STATES,
    LIVE_WIRE_STATES,
)


@dataclass(frozen=True)
class UnresolvedDispatch:
    """Was die Plattform als offen fuehrt."""

    dispatch_id: str
    symbol: str
    #: ISO-Zeitpunkt des Absendens, oder None.
    submitted_at: datetime | None
    #: T1-119 — in welchem Depot dieser Auftrag abgesetzt wurde, roh.
    #:
    #: `None` heisst „die Plattform sagt es nicht": eine Fassung vor T1-119,
    #: oder ein Auftrag von vor T1-116. Dann gilt der Abgleich wie bisher.
    account_id: str | None = None


@dataclass(frozen=True)
class DispatchFill:
    """T1-105 — was IBKRs Ausfuehrungsberichte ueber einen Dispatch sagen.

    Zusammengefasst ueber alle Teilausfuehrungen eines Auftrags: die Menge
    addiert sich, der Kurs ist der mengengewichtete Durchschnitt, die Gebuehr
    die Summe der gemeldeten.
    """

    qty: float
    #: Mengengewichteter Durchschnittskurs, oder None wenn keiner ermittelbar.
    price: float | None
    #: Summe der gemeldeten Gebuehren, oder None wenn IBKR keine geliefert hat.
    commission: float | None


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
    fills_by_ref: dict[str, DispatchFill] | None = None,
    connected_account: str | None = None,
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

    ## T1-119 — Fall 5: der Auftrag gehoert zu einem anderen Depot

    Owner am 2026-08-24, nach einem Wechsel von Echtgeld auf Papier in TWS:
    drei Auftraege standen auf t1 als `unknown`. Sie lagen die ganze Zeit
    gesund im Buch des anderen Kontos — diese Funktion konnte es nur nicht
    wissen. Sie fragte IBKR nach Auftraegen, die in der laufenden Sitzung gar
    nicht auffindbar sein KOENNEN, und las die Antwort „kenne ich nicht" als
    Aussage ueber den Auftrag statt als Aussage ueber die Sitzung.

    Der Vergleich braucht beide Kennungen. Fehlt eine, wird wie bisher
    entschieden: eine Plattform vor T1-119 liefert `account_id` nicht, ein
    Auftrag von vor T1-116 traegt keine, und ein Login mit mehreren
    verwalteten Konten laesst `connected_account` offen. In allen drei Faellen
    waere ein Ueberspringen die schlechtere Wahl — es hiesse, einen wirklich
    verschollenen Auftrag nicht mehr zu melden.

    Verglichen wird ROH. Die Plattform maskiert erst am Ausgang, und maskiert
    verglichen fielen `U12345678` und `U99995678` zusammen (T1-107).
    """
    if open_query_failed:
        return []

    fills = fills_by_ref or {}
    aktionen: list[ReconcileAction] = []

    for d in unresolved:
        # T1-119 — Fall 5, und er steht bewusst VOR jedem Beleg aus dem Buch.
        #
        # Nicht dahinter: was IBKR in DIESER Sitzung ueber einen Auftrag eines
        # ANDEREN Depots meldet, ist keine Auskunft ueber ihn. Eine
        # Auftragsnummer ist je Konto vergeben, und ein zufaellig gleicher
        # Vermerk aus dem verbundenen Depot wuerde hier sonst dem fremden
        # Auftrag zugeschrieben — mit einem Endzustand als Ergebnis.
        #
        # T1-120: das gilt auch fuer den OFFENEN Auftrag darunter. Ein `working`
        # ueber ein Depot, in das wir nicht sehen, ist dieselbe Behauptung wie
        # ein `cancelled` — nur mit freundlicherem Vorzeichen.
        if (
            d.account_id is not None
            and connected_account is not None
            and d.account_id != connected_account
        ):
            continue

        fill = fills.get(d.dispatch_id)

        # ── T1-120 — Fall 1 meldet jetzt, statt zu schweigen ────────────────
        #
        # Hier stand `if d.dispatch_id in open_by_ref: continue`, begruendet
        # mit „Der Auftrag lebt, die Plattform weiss es bereits". Der zweite
        # Halbsatz ist falsch, und zwar immer: eine Zeile steht ueberhaupt nur
        # dann in dieser Liste, wenn die Plattform ihren Zustand als NICHT
        # abgeschlossen fuehrt — und `unknown` gehoert dazu. Sie fragt, WEIL
        # sie es nicht weiss.
        #
        # Owner-Protokoll vom 2026-08-24, 12:59, verbunden mit dem Echtgeldkonto:
        #
        #     Re-mapped 5 open orders via their order reference.
        #     Reconciled dispatch 6e68f237… -> unknown (not_known_at_broker)
        #
        # Die Bridge sah alle fuenf Auftraege offen im Buch — `Submitted`,
        # `account='U23076419'` — und meldete darueber nichts. Auf t1 standen
        # sie weiter auf `unknown`, aus einem Kontowechsel Stunden zuvor.
        #
        # `unresolved-dispatches.ts` behauptet seit T1-103 B das Gegenteil:
        # „nachdem der Owner zurueck auf das Live-Konto gewechselt hatte und
        # IBKR sie wieder kannte — mit dem Eintrag hier heilt genau dieser Fall
        # von selbst." Er heilte nie. Der Eintrag sorgte dafuer, dass weiter
        # GEFRAGT wird; die Antwort wurde verworfen.
        #
        # Sichtbar wird der Fehler nur nach einem `unknown`. Sonst fuehrt die
        # Plattform ohnehin einen lebenden Zustand, und die ausgelassene
        # Meldung haette nichts geaendert — deshalb ist er ueber vier Specs
        # hinweg niemandem aufgefallen.
        offen = open_by_ref.get(d.dispatch_id)
        if offen is not None:
            aktion = _from_open(d, offen, fill)
            if aktion is not None:
                aktionen.append(aktion)
            continue

        trade = completed_by_ref.get(d.dispatch_id)
        if trade is not None:
            aktionen.append(_from_completed(d, trade, fill))
            continue

        # T1-105 — Fall 2b: IBKR fuehrt den Auftrag nicht mehr, aber seine
        # Ausfuehrung liegt vor.
        #
        # `reqCompletedOrders` haelt nur den laufenden Tag vor und ist ausserdem
        # nicht verlaesslich vollstaendig. Der Ausfuehrungsbericht dagegen ist
        # eine Tatsache ueber das Konto: er existiert, weil Stuecke den Besitzer
        # gewechselt haben. Ihn zu ignorieren und `unknown` zu melden hiesse,
        # eine belegte Position ungebucht zu lassen — genau der Zustand, der am
        # 2026-08-19 unter „Held outside Ordertune" stand.
        if fill is not None:
            aktionen.append(_from_fill(d, fill))
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


def _from_open(
    d: UnresolvedDispatch, trade: Any, fill: DispatchFill | None
) -> ReconcileAction | None:
    """T1-120 — der Auftrag lebt bei IBKR. Das ist die Auskunft.

    ## Warum nicht pauschal `working`

    IBKR unterscheidet „unterwegs" von „am Markt", und der Unterschied steht
    im Auftrag. Ihn einzuebnen waere dieselbe Sorte Vergroeberung, die T1-91
    fuer den Verfall zurueckgenommen hat.

    ## Warum eine Teilfuellung mitgemeldet wird

    Ein offener Auftrag kann bereits Stuecke bekommen haben. Meldeten wir hier
    `working`, ueberschriebe das ein `partial` mit der schwaecheren Aussage —
    `should_report` laesst das durch, weil beide nicht-terminal sind. Die
    Menge steht im Auftrag; sie wegzulassen hiesse, sie zu verlieren.

    Die Plattform bucht seit T1-103 J nur den ZUWACHS gegenueber
    `fill_booked_qty`. Eine zweite Meldung derselben Menge bewegt den Bestand
    nicht.

    ## Warum ein Widerspruch schweigt

    Steht der Auftrag in der Liste der OFFENEN und meldet trotzdem einen
    Endzustand, ist eine der beiden Angaben falsch, und es ist nicht
    entscheidbar welche. `None` heisst dann: dieser Durchgang sagt nichts, und
    der naechste fragt erneut. Behaupten ist hier teurer als zugeben —
    dieselbe Linie wie in `_from_completed`.
    """
    status = _status_of(trade)
    wire = IBKR_TO_WIRE_STATUS.get(status or "")
    if wire is None or wire not in LIVE_WIRE_STATES:
        return None

    menge = _filled_qty(trade)
    if menge is not None and menge > 0:
        return ReconcileAction(
            dispatch_id=d.dispatch_id,
            status="partial",
            reason_code=None,
            error_message=None,
            fill_qty=menge,
            fill_price=_avg_fill_price(trade)
            or (fill.price if fill is not None else None),
            commission_usd=_commission(trade)
            if _commission(trade) is not None
            else (fill.commission if fill is not None else None),
        )

    return ReconcileAction(
        dispatch_id=d.dispatch_id,
        status=wire,
        reason_code=None,
        error_message=None,
    )


def _from_fill(d: UnresolvedDispatch, fill: DispatchFill) -> ReconcileAction:
    """T1-105 — die Ausfuehrung allein traegt die Meldung.

    Gemeldet wird `filled`, nicht `partial`: ob noch etwas aussteht, sagt der
    Auftrag, und den kennt IBKR hier nicht mehr. Eine Teilausfuehrung, deren
    Auftrag noch lebt, kaeme gar nicht bis hierher — sie stuende in
    `open_by_ref` und wuerde uebersprungen.
    """
    return ReconcileAction(
        dispatch_id=d.dispatch_id,
        status="filled",
        reason_code=None,
        error_message=None,
        fill_qty=fill.qty,
        fill_price=fill.price,
        commission_usd=fill.commission,
    )


def _from_completed(
    d: UnresolvedDispatch, trade: Any, fill: DispatchFill | None = None
) -> ReconcileAction:
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
        # T1-105 — zuerst der Auftrag, dann der Ausfuehrungsbericht.
        #
        # T1-104 hat nur den Auftrag gefragt. Am 2026-08-19 gemessen: IBKR
        # meldet ueber `reqCompletedOrders` den Zustand `Filled` und laesst die
        # Mengenfelder leer. Der Riegel hielt richtig — und die Position blieb
        # trotzdem ohne Zuordnung. Der Ausfuehrungsbericht kennt die Zahlen.
        menge = _filled_qty(trade)
        if (menge is None or menge <= 0) and fill is not None:
            return _from_fill(d, fill)
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
            # Auch hier faellt jedes einzelne Feld auf den Ausfuehrungsbericht
            # zurueck. Eine Menge ohne Kurs ist eine unbewertete Position; sie
            # zu vermeiden kostet nichts, wenn die Zahl ohnehin vorliegt.
            fill_price=_avg_fill_price(trade)
            or (fill.price if fill is not None else None),
            commission_usd=_commission(trade)
            if _commission(trade) is not None
            else (fill.commission if fill is not None else None),
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


# ── T1-105: die Ausfuehrungsberichte als Quelle der Zahlen ───────────────────
#
# ## Warum es diesen Weg braucht
#
# T1-104 hat die Zahlen am abgeschlossenen Auftrag gesucht — `orderStatus.filled`
# und `avgFillPrice`. Am 2026-08-19 an drei echten Ausfuehrungen gemessen:
# **dort stehen sie nicht.** IBKR meldet ueber `reqCompletedOrders` den Zustand
# `Filled`, laesst die Mengenfelder aber leer. Die Bridge tat daraufhin genau
# das Richtige und buchte nichts — nur blieb die Position damit weiter ohne
# Strategiezuordnung.
#
# Die Zahlen stehen im Ausfuehrungsbericht, und der wird laengst abgeholt:
# `external_executions.py` fragt ihn in jedem Herzschlag ab, um FREMDE Handel
# zu erkennen — und wirft die eigenen weg (`if is_ours(...): continue`). Der
# Vermerk `ot-<dispatchId>`, an dem dort „nicht unserer" entschieden wird, ist
# derselbe, an dem hier „unserer, und hier sind die Zahlen" entschieden wird.
#
# ## Warum nach execId entdoppelt wird
#
# `ib.fills()` sammelt die Ausfuehrungen des Tages im Speicher. Eine
# Korrekturmeldung von IBKR trifft unter derselben Kennung ein; ohne
# Entdopplung addierte sich die Menge ein zweites Mal — und aus einem
# Buchungsdetail wuerde ein zu grosser Bestand und ein zu grosser Ausstieg.

from .order_reference import (  # noqa: F401
    ORDER_REF_PREFIX,
    dispatch_id_from_order_ref,
)


def dispatch_id_from_ref(order_ref: Any) -> str | None:
    """`ot-...<dispatchId>` → `<dispatchId>`, sonst nichts.

    T1-109: liest jetzt dieselbe Regel wie `main`, statt eine eigene zweite zu
    fuehren. Seit ein Etikett zwischen Praefix und Kennung stehen kann, ist
    „alles nach dem Praefix" falsch — und diese Stelle entscheidet, welcher
    Auftrag welche Fuellung bekommt.
    """
    if order_ref is None:
        return None
    return dispatch_id_from_order_ref(str(order_ref))


def fills_by_dispatch(fills: Iterable[Any]) -> dict[str, DispatchFill]:
    """Die Ausfuehrungen des Tages, zusammengefasst je Dispatch.

    Nur, was unseren Auftragsvermerk traegt. Alles andere gehoert dem Nutzer
    und laeuft ueber den Weg aus T1-94.
    """
    roh: dict[str, dict[str, Any]] = {}
    gesehen: set[str] = set()

    for fill in fills or []:
        ex = getattr(fill, "execution", None)
        if ex is None:
            continue

        kennung = dispatch_id_from_ref(getattr(ex, "orderRef", None))
        if kennung is None:
            continue

        exec_id = str(getattr(ex, "execId", "") or "")
        if not exec_id or exec_id in gesehen:
            continue
        gesehen.add(exec_id)

        menge = _num(getattr(ex, "shares", None))
        if menge is None or menge <= 0:
            continue
        kurs = _num(getattr(ex, "price", None))

        eintrag = roh.setdefault(
            kennung, {"qty": 0.0, "wert": 0.0, "bewertet": 0.0, "gebuehr": None}
        )
        eintrag["qty"] += menge
        if kurs is not None and kurs > 0:
            eintrag["wert"] += menge * kurs
            eintrag["bewertet"] += menge

        # Die Gebuehr nur, wenn ein echter Bericht vorliegt. ib_insync legt das
        # Feld mit 0.0 an, bevor IBKR es fuellt — dieselbe Falle, die
        # `external_executions.has_commission_report` beschreibt.
        report = getattr(fill, "commissionReport", None)
        if report is not None and str(getattr(report, "execId", "") or ""):
            gebuehr = _num(getattr(report, "commission", None))
            if gebuehr is not None:
                eintrag["gebuehr"] = (eintrag["gebuehr"] or 0.0) + gebuehr

    ergebnis: dict[str, DispatchFill] = {}
    for kennung, e in roh.items():
        if e["qty"] <= 0:
            continue
        ergebnis[kennung] = DispatchFill(
            qty=e["qty"],
            price=(e["wert"] / e["bewertet"]) if e["bewertet"] > 0 else None,
            commission=e["gebuehr"],
        )
    return ergebnis
