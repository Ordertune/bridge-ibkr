"""T1-109 — der Auftragsvermerk, den ein Mensch lesen kann.

## Wofuer es das gibt

In TWS steht in der Spalte `Order-Referenz` bislang `ot-68b51461-05e6-4c...`.
Fuer die Bridge ist dieser Vermerk die wichtigste Angabe ueberhaupt: er ist das
einzige, was einen Neustart ueberlebt, weil `orderId` sitzungsgebunden ist und
die Ablagen im Speicher fluechtig sind. Fuer den Nutzer ist er vollkommen stumm.

Owner am 2026-08-21, beim Gegenlesen seiner OCA-Beine in TWS: „Kann man hinter
`ot-` auch Signal-ID, Strategie und Symbol und dann die Zahlenreihe setzen, die
da schon ist?"

Ergebnis:

    ot-ALAB-7808-Peak_Reload-68b51461-05e6-4c8a-...
       ^^^^^^^^^^^^^^^^^^^^^ Etikett von der Plattform
                             ^^^^^^^^^^^^^^^^^^^^^^^ dispatch_id, wie bisher

Der lesbare Teil steht VORNE, weil TWS die Spalte rechts abschneidet. Hinter
einer 36-stelligen UUID waere er in der Anzeige genauso stumm wie vorher.

## Warum das Lesen von HINTEN geschieht

`dispatch_id_from_order_ref` nahm bisher „alles nach dem Praefix". Mit einem
Etikett dazwischen traegt diese Regel nicht mehr. Die dispatch_id ist eine
UUID und damit an ihrer Form erkennbar — sie wird am ENDE gesucht.

Das ist zugleich die Abwaertskompatibilitaet: bei `ot-<uuid>` steht die UUID
ebenfalls am Ende. Ein Auftrag, den eine aeltere Fassung gestellt hat, wird von
der neuen Regel unveraendert gefunden.

**Der umgekehrte Weg gilt nicht.** Eine aeltere Bridge findet in einem neuen
Vermerk ihre dispatch_id nicht und verliert den Auftrag nach einem Neustart aus
den Augen. Falsch gebucht wird nichts — `is_ours()` prueft nur das Praefix und
sagt weiterhin „gehoert uns" —, aber das Ergebnis kaeme nicht zurueck. Ein
Rueckschritt der Bridge-Fassung ist deshalb nach diesem Spec nicht folgenlos.
"""

from __future__ import annotations

import re

#: Praefix, mit dem jeder Auftrag von uns bei IBKR hinterlegt ist.
ORDER_REF_PREFIX = "ot-"

#: Obergrenze fuer den GESAMTEN Vermerk.
#:
#: 64 ist keine von IBKR dokumentierte Grenze, sondern eine bewusst
#: konservative Wahl: die tatsaechliche Laenge von `Order.orderRef` ist nicht
#: belastbar dokumentiert, und ein Auftrag, den der Broker wegen eines zu
#: langen Vermerks ablehnt, kostet einen Ausstieg im Echtgeld.
#:
#: Reicht der Platz nicht, faellt das ETIKETT weg — nie die dispatch_id.
#: Lieber ein stummer Vermerk als ein unauffindbarer Auftrag.
ORDER_REF_MAX_LEN = 64

#: Die Form einer UUID, verankert am Ende der Zeichenkette.
_UUID_AM_ENDE = re.compile(
    r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$"
)

#: Was in einem Etikett stehen darf. `-` ist das Trennzeichen und deshalb
#: ausgeschlossen; Punkt und Unterstrich bleiben, damit `BRK.B` und
#: `Peak_Reload` ihre vertraute Schreibweise behalten.
_ETIKETT_ERLAUBT = re.compile(r"[^A-Za-z0-9_.\-]")


def build_order_ref(dispatch_id: str, label: str | None) -> str:
    """Setzt den Auftragsvermerk zusammen.

    Ohne Etikett — oder wenn es nicht hineinpasst — entsteht exakt das Format
    von vor T1-109. Der Rueckfall ist damit kein Sonderfall, sondern der
    bisherige Normalfall.
    """
    basis = f"{ORDER_REF_PREFIX}{dispatch_id}"
    if not label:
        return basis

    sauber = _ETIKETT_ERLAUBT.sub("", str(label).strip())
    if not sauber:
        return basis

    zusammen = f"{ORDER_REF_PREFIX}{sauber}-{dispatch_id}"
    if len(zusammen) > ORDER_REF_MAX_LEN:
        # Das Etikett wird NICHT beschnitten, um es doch noch unterzubringen.
        # Die Plattform hat es bereits auf ihre Grenze gekuerzt; passt es hier
        # trotzdem nicht, stimmt eine Annahme nicht, und dann ist Schweigen die
        # sichere Antwort.
        return basis
    return zusammen


def dispatch_id_from_order_ref(order_ref: str | None) -> str | None:
    """Liest die dispatch_id aus dem Auftragsvermerk, oder `None`.

    Fremde Auftraege im selben Konto — von Hand gestellt oder von einem anderen
    Werkzeug — tragen den Vermerk nicht und werden stillschweigend uebergangen.
    Sie gehoeren uns nicht.

    Gelesen wird die UUID am ENDE. Damit deckt dieselbe Regel beide Formate ab:
    `ot-<uuid>` und `ot-<etikett>-<uuid>`.
    """
    if not order_ref:
        return None

    # Erst saeubern, dann pruefen. Die Fassung in `order_reconcile` tat das,
    # die in `main` nicht — beim Zusammenlegen gewinnt die tolerantere: ein
    # Vermerk mit Leerraum drumherum ist derselbe Vermerk.
    text = str(order_ref).strip()
    if not text.startswith(ORDER_REF_PREFIX):
        return None

    treffer = _UUID_AM_ENDE.search(text)
    if treffer:
        return treffer.group(1)

    # T1-115 — KEIN Rueckfall mehr auf „alles nach dem Praefix".
    #
    # Bis hierher gab es einen, gedacht fuer Tests und eine Zeit vor der
    # UUID-Vergabe. In der Produktion existiert dieser Fall nicht:
    # `bridge_order_dispatch.id` ist eine uuid-Spalte, und jeder Auftrag, den
    # Ordertune je gestellt hat, traegt eine.
    #
    # Der Rueckfall hatte aber eine Wirkung, die er nicht haben sollte: er
    # loeste einen VON HAND getippten Vermerk wie `ot-INTC-7690-Day_Ripper` zu
    # einer Kennung auf, die es nicht gibt. Zusammen mit `is_ours`, das nur das
    # Praefix prueft, fiel die Fuellung damit durch beide Buchungswege.
    #
    # Die Zusicherung `test_die_beiden_haelften_der_orderref_regel_stimmen_
    # ueberein` sagt genau das seit T1-94: „Laufen sie auseinander, faellt eine
    # Ausfuehrung entweder durch beide Raster — dann fehlt sie ueberall — oder
    # durch keines, und dann steht sie zweimal."
    #
    # Beide Haelften verlangen deshalb jetzt denselben Nachweis.
    return None


def is_ours(order_ref: object) -> bool:
    """Traegt dieser Vermerk unsere Handschrift — mit Nachweis?

    ## Warum das Praefix allein nicht genuegt

    Bis T1-115 stand hier nur `startswith("ot-")`. Das war ein
    **Besitzanspruch ohne Nachweis**: jeder kann ihn in TWS eintippen, und die
    Bridge glaubte ihn.

    Der Owner hat das am 2026-08-21 versehentlich vorgefuehrt. Er stellte zwei
    MOC-Orders von Hand und trug `ot-INTC-7690-Day_Ripper` als Vermerk ein, um
    die Zuordnung zu erleichtern. Wirkung:

      * `is_ours` sagte „gehoert uns"  → die Fuellung wurde NICHT als fremde
        Ausfuehrung gemeldet (`external_executions` ueberspringt eigene);
      * eine aufloesbare Vorgangskennung gab es nicht → auch der eigene Weg
        ueber `/orders/{id}/result` fand nichts.

    Die Fuellung fiel durch BEIDE Wege und tauchte nirgends auf. Ohne den
    Vermerk waere sie sauber als fremde Ausfuehrung im Buch gelandet — der
    gutgemeinte Zusatz machte die Buchfuehrung schlechter.

    ## Der Nachweis

    Ein Auftrag gehoert uns, wenn hinter dem Praefix eine **UUID** steht. Das
    ist keine Formalie: `bridge_order_dispatch.id` ist eine uuid-Spalte, und
    jeder Auftrag, den Ordertune je gestellt hat, traegt eine. Wer den Vermerk
    von Hand tippt, trifft sie nicht.

    ## Die Richtung des Irrtums ist gewaehlt

    Im Zweifel „nicht unserer". Ein fremder Auftrag, den wir faelschlich fuer
    eigen halten, faellt aus beiden Buchungswegen — genau der Fall oben. Ein
    eigener, den wir faelschlich fuer fremd halten, wird als externe
    Ausfuehrung gebucht: sichtbar, mit Menge und Preis, nur ohne
    Signalzuordnung. Ein sichtbarer Fehler ist besser als ein unsichtbarer.
    """
    if not order_ref:
        return False
    text = str(order_ref).strip()
    if not text.startswith(ORDER_REF_PREFIX):
        return False
    return dispatch_id_from_order_ref(text) is not None


# ── T1-114: der Rueckbericht ────────────────────────────────────────────────
#
# ## Warum es das gibt
#
# Die Flaeche auf t1 zeigte bis hierher, was ORDERTUNE GESENDET hat — nicht,
# was der Broker haelt. Der Owner hat dieselbe Frage an drei Tagen in drei
# Formen gestellt:
#
#   * „Wie kann ich pruefen, dass die OCA-Orders korrekt uebermittelt wurden?"
#   * „Hat das in TWS geaenderte Limit Einfluss auf die Zuordnung?"
#   * „Unklar ist, ob die Order als saubere OCA eingestellt wurde, bei der eine
#      erst ab 15:59 gueltig ist."
#
# Jedes Mal lautete die ehrliche Antwort: sieh in TWS nach. Die Bridge fragt
# IBKR bei jedem Herzschlag ohnehin nach den offenen Auftraegen
# (`reqOpenOrders`, fuer die Schreibrechte-Erkennung) und wirft die Antwort
# weg. Sie mitzuschicken kostet nichts und beantwortet alle drei Fragen.
#
# ## Es ist eine MESSUNG, keine Wiederholung unserer Absicht
#
# Jedes Feld hier stammt aus dem Auftrag, wie IBKR ihn fuehrt. Genau deshalb
# ist er brauchbar: weicht er von dem ab, was wir gesendet haben, ist das der
# Befund — ein in TWS geaendertes Limit, eine verschluckte OCA-Gruppe, eine
# weggefallene Zeitbedingung.

#: Wie viele Auftraege hoechstens mitgehen. Der Herzschlag ist ein
#: Lebenszeichen und darf nicht an einer langen Liste haengen.
MAX_OPEN_ORDERS_REPORTED = 50


def _als_zahl(wert: object) -> float | None:
    """Nur echte Zahlen. IBKR schreibt `0.0` fuer „kein Limit"."""
    try:
        zahl = float(wert)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if zahl != zahl:  # NaN
        return None
    return zahl


def _text(wert: object) -> str | None:
    """Leerstring heisst bei IBKR „nicht gesetzt" und darf nicht als Wert gelten."""
    if wert is None:
        return None
    s = str(wert).strip()
    return s or None


def wire_open_orders(trades: object) -> list[dict[str, object]]:
    """Die offenen Auftraege, die UNS gehoeren, im Drahtformat.

    Fremde Auftraege im selben Konto bleiben draussen — sie gehen die
    Plattform nichts an, und `is_ours` ist die Regel, die das ueberall sonst
    schon entscheidet.

    Der Vermerk reist als `dispatchId` mit, damit die Plattform ohne Rateweg
    zuordnen kann. Ein Auftrag, dessen Vermerk sich nicht aufloesen laesst,
    faellt weg: ohne Zuordnung ist die Zeile eine Behauptung ohne Adresse.
    """
    out: list[dict[str, object]] = []
    for trade in list(trades or [])[:MAX_OPEN_ORDERS_REPORTED]:
        order = getattr(trade, "order", None)
        if order is None:
            continue
        # T1-115: dieselbe Regel wie ueberall. Ein von Hand getippter Vermerk
        # ist kein eigener Auftrag und gehoert nicht in den Bericht.
        dispatch_id = dispatch_id_from_order_ref(getattr(order, "orderRef", None))
        if dispatch_id is None:
            continue
        status = getattr(getattr(trade, "orderStatus", None), "status", None)
        out.append(
            {
                "dispatchId": dispatch_id,
                "brokerOrderId": str(getattr(order, "orderId", "") or ""),
                "status": _text(status) or "unknown",
                # Die drei Felder, um die der Owner dreimal gefragt hat.
                "ocaGroup": _text(getattr(order, "ocaGroup", None)),
                "ocaType": (
                    int(getattr(order, "ocaType", 0) or 0)
                    if getattr(order, "ocaType", None)
                    else None
                ),
                "goodAfterTime": _text(getattr(order, "goodAfterTime", None)),
                "goodTillDate": _text(getattr(order, "goodTillDate", None)),
                # Damit ein in TWS geaendertes Limit sichtbar wird.
                "lmtPrice": _als_zahl(getattr(order, "lmtPrice", None)) or None,
                "orderType": _text(getattr(order, "orderType", None)),
                "tif": _text(getattr(order, "tif", None)),
                "totalQuantity": _als_zahl(getattr(order, "totalQuantity", None)),
            }
        )
    return out
