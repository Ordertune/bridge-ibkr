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
    order.tif = order.tif or DEFAULT_TIF

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

    return order


# OCA-Typ 1 = „cancel remaining on any fill", ohne Ueberfuellungsschutz.
#
# Bewusst nicht 2 oder 3: die stornieren zwar ebenfalls, reduzieren aber
# zusaetzlich die Menge der verbleibenden Auftraege. Bei einem Ausstieg, dessen
# Beine ohnehin dieselbe Stueckzahl tragen, ist das ohne Wirkung — bei einer
# Teilfuellung waere es eine stille Mengenaenderung, die die Plattform nicht
# mitbekommt.
DEFAULT_OCA_TYPE = 1


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
        lmt = float(intent["lmtPrice"])
        return LimitOrder(action, qty, lmt)

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
