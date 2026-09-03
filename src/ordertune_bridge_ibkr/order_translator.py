"""Wandelt Ordertune OrderIntent in ib_insync-Order-Objekte.

Unterstützt 4 Kern-Order-Types aus router-interface.ts (day_limit, loc, moc,
market). Bracket + OCA-Handling gemäß IBKR-Semantik.
"""
from __future__ import annotations

from typing import Any

from ib_insync import Contract, LimitOrder, MarketOrder, Order, Stock


def make_contract(symbol: str) -> Contract:
    """SMART US-Equity als Default."""
    return Stock(symbol, "SMART", "USD")


# T1-88b F1 — die Gueltigkeitsdauer, die jede Order tragen muss.
#
# Bleibt `tif` leer, ergaenzt TWS sie aus den Order-Voreinstellungen des
# Kontos und quittiert das mit Meldung 10349. Das ist ein Hinweis, kein
# Fehler — aber ib_insync 0.9.86 fuehrt 10349 nicht in seiner Liste harmloser
# Codes (`warningCodes = {110, 165, 202, 399, 404, 434, 492, 10167}`) und
# erklaert die Order daraufhin im eigenen Arbeitsspeicher fuer storniert.
#
# Am 2026-08-13 hat das auf einem Echtgeldkonto zwei lebende Auftraege
# erzeugt, die die Plattform beide fuer storniert hielt.
DEFAULT_TIF = "DAY"


# T1-144 — Ordertypen, die keine Frist tragen koennen.
#
# Eine Auktionsorder ist an EIN Ereignis gebunden — die Eroeffnungs- oder die
# Schlussauktion ihrer Sitzung. Eine Frist beschreibt einen Zeitraum, und ein
# Zeitraum an einem Zeitpunkt ergibt keine Aussage. IBKR lehnt das ab, fuer
# `MOC` am 2026-09-03 gemessen (Fehler 201).
#
# ## Warum hier eine Sperrliste steht und auf der Plattform eine Erlaubnisliste
#
# Es sind zwei verschiedene Fragen, und deshalb duerfen es nicht zwei Fassungen
# derselben Liste sein:
#
#   Plattform: welche Ordertypen wollen WIR mit einer Frist versehen?
#              Eine Richtlinie. Erlaubnisliste, damit ein neuer Typ nicht durch
#              Unterlassen durchkommt.
#   Hier:      welche Ordertypen kann IBKR mit einer Frist gar nicht annehmen?
#              Eine Tatsache ueber den Broker. Sperrliste, damit ein neuer Typ
#              nicht faelschlich abgelehnt wird, nur weil diese Datei ihn noch
#              nicht kennt.
#
# Waeren beide Erlaubnislisten, muesste Stufe 1 (`STP`) sie im Gleichschritt
# aendern — und ein vergessener Gleichschritt ist in diesem Repo schon mehrfach
# die Ursache gewesen.
#
# `loc` steht mit drin, obwohl es nicht gemessen ist: es ist dieselbe Bauform
# wie `moc`, an dieselbe eine Auktion gebunden. Gemessen ist etwas anderes, und
# es macht den Einschluss folgenlos — ueber alle `signals` traegt keine einzige
# LOC-Zeile ein `good_until` (0 von 736, Stand 2026-09-03). Faellt der Riegel
# hier je, ist das eine Auskunft ueber eine neue Signalform und kein Ausfall.
FRIST_UNMOEGLICH = frozenset({"moc", "loc"})


def _text_or_none(roh: Any) -> str | None:
    """Eine nicht-leere Zeichenkette, oder nichts.

    T1-135. Ein leerer String ist keine Gueltigkeitsdauer — er wuerde die
    `or`-Kette unterbrechen und den Rueckfall auf DAY erzwingen, ohne dass
    irgendwo eine Absicht dahinterstuende.
    """
    if not isinstance(roh, str):
        return None
    wert = roh.strip().upper()
    return wert or None


def translate_intent(intent: dict[str, Any]) -> Order:
    """OrderIntent → ib_insync.Order (single-leg)."""
    side = intent["side"].upper()  # 'BUY' | 'SELL'
    qty = float(intent["qty"])
    order_type = intent["orderType"]

    action = "BUY" if side == "BUY" else "SELL"

    order = _build_order(intent, order_type, action, qty)

    # T1-88b F1: bewusst NACH der Verzweigung und fuer alle Zweige gemeinsam.
    #
    # Vorher setzten nur `loc` und `moc` eine Gueltigkeitsdauer, `day_limit`
    # und `market` gingen ohne raus. Genau das war der Ausloeser. Haette man
    # die beiden fehlenden Zweige einzeln nachgezogen, waere derselbe Fehler
    # beim fuenften Ordertyp zurueckgekommen — hier kann er es nicht mehr.
    #
    # `or` und nicht bedingungsloses Setzen: ein Zweig, der bewusst eine
    # andere Dauer braucht, behaelt sie.
    #
    # T1-135 — die Gueltigkeitsdauer der Signalquelle kommt VOR dem Rueckfall.
    #
    # Bis 0.19.0 stand hier nur `or DEFAULT_TIF`, und `signals.time_in_force`
    # erreichte diese Datei nie: die Plattform las die Spalte ausschliesslich
    # fuer den Korb-Export. Jede Order ging damit als `DAY` hinaus. Bei `DAY`
    # faellt das nicht auf; bei `OPG` wird aus einem Eroeffnungsauftrag ein
    # Tageslimit, das bis zum Schluss lebt — eine andere Order als die, fuer
    # die das Modell entschieden hat.
    #
    # Die Plattform prueft den Wert bereits gegen ihre Erlaubnisliste (`DAY`,
    # `OPG`, `GTD`; `GTC` ausdruecklich nicht). Hier wird deshalb nicht ein
    # zweites Mal geprueft, sondern nur uebernommen, was ankommt — zwei
    # Fassungen derselben Liste liefen beim naechsten Wert auseinander.
    order.tif = _text_or_none(intent.get("timeInForce")) or order.tif or DEFAULT_TIF

    # T1-106 — die OCA-Verknuepfung, und zwar HIER statt beim Aufrufer.
    #
    # `apply_oca_group` liegt seit dem ersten Wurf in dieser Datei und hatte
    # ausser einem Test nie einen Aufrufer: `main.py` uebersetzt Auftrag fuer
    # Auftrag, und eine Funktion, die eine LISTE von Orders gruppiert, hat in
    # einem Einzelweg keine Stelle. Damit gingen zwei Beine desselben Paars als
    # zwei UNVERKNUEPFTE Auftraege hinaus — fuellen beide, ist die Position
    # zweimal verkauft.
    #
    # Die Gruppe steht deshalb am Intent und wird je Auftrag gesetzt. Die
    # Verknuepfung entsteht bei IBKR dadurch, dass zwei Auftraege denselben
    # `ocaGroup`-Namen tragen; sie muessen dafuer weder zusammen noch in einem
    # Aufruf abgesendet werden.
    gruppe = intent.get("ocaGroup")
    if isinstance(gruppe, str) and gruppe:
        apply_oca_group([order], gruppe, _oca_type(intent))

    # T1-106 Nachtrag — die Zeitfenster der Signalquelle.
    #
    # Ein OCA-Paar ist SEQUENZIELL gedacht: ein Bein gilt untertags, das andere
    # erst ab 15:59 US/Eastern, also fuer die Schlussauktion. Gehen beide sofort
    # scharf hinaus, liegen sie gleichzeitig am Markt — und auf einem Cash-Konto
    # sind zwei Verkaeufe gegen eine gehaltene Position ein moeglicher
    # Leerverkauf. Am 2026-08-20 hat IBKR daraufhin eines der Beine storniert.
    #
    # Die Werte gehen UNVERAENDERT durch. Sie stammen aus `signals.good_after`
    # bzw. `good_until` und tragen dort bereits IBKRs Format
    # (`20260820 15:59:00 US/Eastern`); die Plattform prueft die Deutbarkeit,
    # bevor sie sie mitgibt.
    nach = intent.get("goodAfterTime")
    if isinstance(nach, str) and nach:
        order.goodAfterTime = nach
    bis = intent.get("goodTillDate")
    if isinstance(bis, str) and bis:
        # T1-144 — der letzte Riegel, bevor die Frist an den Draht geht.
        #
        # Am 2026-09-03 gingen beide Breakout-Hunter-Auftraege sofort wieder
        # zurueck, Einstieg wie Ausstieg. IBKR im Protokoll:
        #
        #   Error 201, reqId 624: Order abgewiesen - Grund: Unzulaessige
        #   Gueltigkeitsdauer fuer eine At-the-Closing-Order.
        #
        # Das angehaengte Ausstiegsbein war ein `MOC` und trug trotzdem `GTD`,
        # weil die Zeile darunter die Dauer BEDINGUNGSLOS gesetzt hat — ohne den
        # Ordertyp anzusehen. Die Plattform schickt seit T1-144 keine Frist mehr
        # an einen Auftrag, der sie nicht tragen kann; hier steht der Riegel ein
        # zweites Mal, damit die naechste Fassung derselben Frage nicht wieder
        # an genau dieser Zeile auseinanderlaeuft.
        # Kleingeschrieben verglichen: die Plattform schickt `moc`, aber ein
        # Vergleich, der an der Schreibweise haengt, ist ein Riegel, der beim
        # ersten `MOC` still aufgeht.
        if str(order_type or "").strip().lower() in FRIST_UNMOEGLICH:
            raise ValueError(
                f"{order_type} vertraegt keine Frist "
                f"(goodTillDate={bis!r}) — IBKR fuehrt fuer eine "
                f"Auktionsorder ausschliesslich DAY"
            )
        order.goodTillDate = bis
        # IBKR verlangt fuer eine Frist die Gueltigkeitsdauer GTD. Bleibt hier
        # DAY stehen, wird `goodTillDate` stillschweigend ignoriert — und der
        # Auftrag lebt bis zum Schluss statt bis zu seiner Frist.
        order.tif = "GTD"

    return order


# OCA-Typ 3 = „reduce, non-block".
#
# v0.11.0 setzte hier 1 („cancel remaining on any fill") mit der Begruendung,
# die Reduktion sei bei Beinen gleicher Stueckzahl ohne Wirkung. Die Produktion
# hat das binnen acht Sekunden widerlegt:
#
#   Warning 202, reqId 148: Order storniert - Grund: Leerverkaufs-Aktien-
#   positionen koennen ausschliesslich in einem Marginkonto gehalten werden
#   (Sie haben ein Cash-Konto).
#
# Es geht nicht um Teilfuellungen, sondern um IBKRs VORAB-Risikopruefung: zwei
# Verkaeufe ueber je 1 Stueck gegen 1 gehaltenes sind auf einem Cash-Konto ein
# moeglicher Leerverkauf. Typ 1 laesst beide in voller Groesse stehen; 2 und 3
# reduzieren die verbleibenden, und genau das ist der Ueberfuellungsschutz, den
# die Pruefung sehen will.
DEFAULT_OCA_TYPE = 3


def _oca_type(intent: dict[str, Any]) -> int:
    roh = intent.get("ocaType")
    return roh if isinstance(roh, int) and roh in (1, 2, 3) else DEFAULT_OCA_TYPE


def _build_order(
    intent: dict[str, Any], order_type: str, action: str, qty: float
) -> Order:
    """Der ordertyp-spezifische Teil. Alles Gemeinsame steht beim Aufrufer."""
    if order_type == "market":
        return MarketOrder(action, qty)

    if order_type == "day_limit":
        # T1-135: ausdruecklich statt `float(None)`.
        #
        # Seit `LOO` auf diesen Zweig abbildet, kann ein Auftrag hier ohne
        # Limitpreis ankommen, wenn die Signalquelle einmal keinen mitgibt
        # (heute tut sie es bei allen 11 LOO-Zeilen). `float(None)` wirft einen
        # TypeError ohne Bezug zum Auftrag; `main.py` protokolliert ihn dann als
        # nackten Fehlschlag. Ein limitierter Auftrag ohne Limit darf nicht als
        # Marktauftrag hinausgehen — das war der Fehler, den dieser Spec behebt.
        roh = intent.get("lmtPrice")
        if roh is None:
            raise ValueError("day_limit ohne lmtPrice")
        return LimitOrder(action, qty, float(roh))

    if order_type == "loc":
        o = Order()
        o.orderType = "LOC"
        o.action = action
        o.totalQuantity = qty
        if intent.get("lmtPrice") is not None:
            o.lmtPrice = float(intent["lmtPrice"])
        return o

    if order_type == "moc":
        o = Order()
        o.orderType = "MOC"
        o.action = action
        o.totalQuantity = qty
        return o

    raise ValueError(f"Unsupported orderType: {order_type}")


def apply_bracket_transmit_flags(orders: list[Order]) -> None:
    """Set transmit=False für alle außer der letzten (IBKR-Bracket-Pattern)."""
    for i, order in enumerate(orders):
        order.transmit = i == len(orders) - 1


def apply_oca_group(orders: list[Order], group_name: str, oca_type: int = 1) -> None:
    """Alle Orders in derselben OCA-Group. oca_type=1 = cancel remaining on any fill."""
    for order in orders:
        order.ocaGroup = group_name
        order.ocaType = oca_type
