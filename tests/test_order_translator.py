from ordertune_bridge_ibkr.order_translator import (
    apply_bracket_transmit_flags,
    apply_oca_group,
    make_contract,
    translate_intent,
)


def test_make_contract_smart_us_equity():
    c = make_contract("AAPL")
    assert c.symbol == "AAPL"
    assert c.exchange == "SMART"
    assert c.currency == "USD"


def test_translate_market_order():
    intent = {"symbol": "AAPL", "side": "buy", "orderType": "market", "qty": 10, "lmtPrice": None}
    o = translate_intent(intent)
    assert o.orderType == "MKT"
    assert o.action == "BUY"
    assert float(o.totalQuantity) == 10


def test_translate_limit_order():
    intent = {"symbol": "AAPL", "side": "sell", "orderType": "day_limit", "qty": 5, "lmtPrice": 200.0}
    o = translate_intent(intent)
    assert o.orderType == "LMT"
    assert o.action == "SELL"
    assert float(o.lmtPrice) == 200.0


def test_translate_loc_order():
    intent = {"symbol": "AAPL", "side": "buy", "orderType": "loc", "qty": 3, "lmtPrice": 150.0}
    o = translate_intent(intent)
    assert o.orderType == "LOC"
    assert o.tif == "DAY"
    assert float(o.lmtPrice) == 150.0


def test_translate_moc_order():
    intent = {"symbol": "AAPL", "side": "sell", "orderType": "moc", "qty": 7, "lmtPrice": None}
    o = translate_intent(intent)
    assert o.orderType == "MOC"
    assert o.tif == "DAY"


def test_bracket_transmit_flags_last_only():
    from ib_insync import MarketOrder
    orders = [MarketOrder("BUY", 1), MarketOrder("SELL", 1), MarketOrder("SELL", 1)]
    apply_bracket_transmit_flags(orders)
    assert orders[0].transmit is False
    assert orders[1].transmit is False
    assert orders[2].transmit is True


def test_oca_group_applied_to_all():
    from ib_insync import MarketOrder
    orders = [MarketOrder("SELL", 1), MarketOrder("SELL", 1)]
    apply_oca_group(orders, "oca-1")
    assert orders[0].ocaGroup == "oca-1"
    assert orders[1].ocaGroup == "oca-1"
    assert orders[0].ocaType == 1
    assert orders[1].ocaType == 1


# ── T1-88b F1: die Gueltigkeitsdauer ────────────────────────────────────────
#
# Bleibt `tif` leer, ergaenzt TWS sie aus den Order-Voreinstellungen und
# quittiert das mit Meldung 10349. ib_insync 0.9.86 fuehrt 10349 nicht in
# seiner Warnliste und erklaert die Order daraufhin im eigenen Arbeitsspeicher
# fuer storniert — am 2026-08-13 der Ausloeser fuer zwei Echtauftraege, die die
# Plattform beide fuer storniert hielt.

import pytest as _pytest

from ordertune_bridge_ibkr.order_translator import DEFAULT_TIF


@_pytest.mark.parametrize(
    "intent",
    [
        {"side": "buy", "qty": 2, "orderType": "market"},
        {"side": "buy", "qty": 2, "orderType": "day_limit", "lmtPrice": 166.38},
        {"side": "sell", "qty": 2, "orderType": "loc", "lmtPrice": 166.38},
        {"side": "sell", "qty": 2, "orderType": "moc"},
    ],
)
def test_every_order_type_carries_a_time_in_force(intent) -> None:
    """Jeder Ordertyp, nicht nur die beiden, die es schon hatten.

    Vorher setzten ausschliesslich `loc` und `moc` eine Gueltigkeitsdauer.
    Diese Zusicherung faellt auch dann, wenn jemand einen fuenften Ordertyp
    ergaenzt und ihn wieder vergisst.
    """
    order = translate_intent(intent)
    assert order.tif, f"{intent['orderType']} geht ohne Gueltigkeitsdauer raus"
    assert order.tif == DEFAULT_TIF


# ── T1-106: die OCA-Gruppe reist am Intent ─────────────────────────────────
#
# `apply_oca_group` lag seit dem ersten Wurf in der Datei und hatte ausser dem
# Test darueber nie einen Aufrufer. Zwei Beine desselben Paars gingen deshalb
# als zwei UNVERKNUEPFTE Auftraege hinaus — fuellen beide, ist die Position
# zweimal verkauft. Die Verknuepfung entsteht bei IBKR ueber den gemeinsamen
# Gruppennamen; die Beine muessen dafuer weder zusammen noch in einem Aufruf
# abgesendet werden.


def test_oca_group_from_intent():
    intent = {
        "symbol": "ALAB",
        "side": "sell",
        "orderType": "day_limit",
        "qty": 1,
        "lmtPrice": 304.18,
        "ocaGroup": "OCA_ALAB_2026-08-20_Peak_Reload",
    }
    o = translate_intent(intent)
    assert o.ocaGroup == "OCA_ALAB_2026-08-20_Peak_Reload"
    assert o.ocaType == 1


def test_oca_group_both_legs_share_the_name():
    """Zwei getrennte Uebersetzungen, eine Gruppe — so laeuft es in main.py."""
    gemeinsam = "OCA_CSCO_2026-08-20_Peak_Reload"
    beine = [
        translate_intent(
            {
                "symbol": "CSCO",
                "side": "sell",
                "orderType": "day_limit",
                "qty": 1,
                "lmtPrice": preis,
                "ocaGroup": gemeinsam,
            }
        )
        for preis in (116.40, 111.61)
    ]
    assert {b.ocaGroup for b in beine} == {gemeinsam}
    assert all(b.ocaType == 1 for b in beine)


def test_ohne_gruppe_bleibt_die_order_unveraendert():
    """Der Normalfall. Ein einzelner Ausstieg darf keine Gruppe bekommen."""
    intent = {"symbol": "INTC", "side": "sell", "orderType": "moc", "qty": 1, "lmtPrice": None}
    o = translate_intent(intent)
    assert not o.ocaGroup


def test_leere_gruppe_zaehlt_nicht_als_gruppe():
    """`""` und `None` sind keine Verknuepfung, sondern ihr Fehlen."""
    for leer in ("", None):
        o = translate_intent(
            {
                "symbol": "INTC",
                "side": "sell",
                "orderType": "moc",
                "qty": 1,
                "lmtPrice": None,
                "ocaGroup": leer,
            }
        )
        assert not o.ocaGroup


def test_unbrauchbarer_oca_typ_faellt_auf_1_zurueck():
    """Der Typ kommt von aussen. 2 und 3 aendern still die Menge — nur 1, 2, 3
    sind ueberhaupt gueltig, alles andere ist ein Fehler und keine Absicht."""
    for roh in (0, 4, "1", None, 1.0):
        o = translate_intent(
            {
                "symbol": "INTC",
                "side": "sell",
                "orderType": "moc",
                "qty": 1,
                "lmtPrice": None,
                "ocaGroup": "g",
                "ocaType": roh,
            }
        )
        assert o.ocaType == 1
