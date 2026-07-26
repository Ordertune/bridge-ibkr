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
