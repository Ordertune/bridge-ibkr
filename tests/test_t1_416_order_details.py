"""T1-416 — die Auftragsliste im Cockpit sagt, wozu ein Auftrag gehoert.

Owner 2026-11-16: „Heute sieht man in der Bridge nur eine verkuerzte
Darstellung der Orders. Stelle eine ausfuehrliche nachvollziehbare Ansicht
sicher, damit man begreift, zu welcher Strategie, Preis und Bedingung eine
Order gehoert."
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from ordertune_bridge_ibkr import main as m
from ordertune_bridge_ibkr import order_details as d

UNSET = 1.7976931348623157e308
DISPATCH = "9948c645-c094-4477-84f4-c7acdbeb2bb6"


def _order(**over):
    base = dict(
        action="BUY",
        totalQuantity=15,
        orderId=7,
        orderType="LMT",
        lmtPrice=709.8,
        auxPrice=UNSET,
        tif="DAY",
        goodAfterTime="",
        goodTillDate="",
        ocaGroup="",
        outsideRth=False,
        orderRef=f"ot-SNDK-8123-Fear_Shield-{DISPATCH}",
    )
    base.update(over)
    return SimpleNamespace(**base)


def _trade(order=None, status="Submitted", filled=0.0, avg=0.0, log=()):
    return SimpleNamespace(
        order=order or _order(),
        contract=SimpleNamespace(symbol="SNDK"),
        orderStatus=SimpleNamespace(
            status=status, filled=filled, remaining=15 - filled, avgFillPrice=avg
        ),
        log=list(log),
    )


@pytest.fixture(autouse=True)
def _leer():
    m._TRADES_BY_DISPATCH.clear()
    d.clear()
    yield
    m._TRADES_BY_DISPATCH.clear()
    d.clear()


def test_strategie_aus_dem_auftragsvermerk() -> None:
    assert d.strategy_from_order_ref(f"ot-SNDK-8123-Fear_Shield-{DISPATCH}") == "Fear Shield"
    assert d.strategy_from_order_ref(f"ot-{DISPATCH}") is None
    assert d.strategy_from_order_ref(f"ot-SNDK-8123-{DISPATCH}") is None
    assert d.strategy_from_order_ref(None) is None


def test_voller_name_von_der_plattform_schlaegt_den_vermerk() -> None:
    d.remember(DISPATCH, {"strategyName": "S&P 500 Fear Shield", "intent": "exit"})
    zeile = d.describe(DISPATCH, _trade())
    assert zeile["strategy"] == "S&P 500 Fear Shield"
    assert zeile["purpose"] == "Exit"


def test_limit_mit_preis_und_bedingungen() -> None:
    zeile = d.describe(
        DISPATCH,
        _trade(_order(goodAfterTime="20261112 15:59:00 US/Eastern", ocaGroup="ot-oca-1")),
    )
    assert zeile["strategy"] == "Fear Shield"
    assert zeile["orderType"] == "Limit"
    assert zeile["price"] == "Limit 709.80"
    assert "Day order" in zeile["conditions"]
    assert "Active from 12 Nov 15:59 ET" in zeile["conditions"]
    assert "One-cancels-all group" in zeile["conditions"]


def test_markt_ohne_preis_und_unset_wird_nie_angezeigt() -> None:
    zeile = d.describe(DISPATCH, _trade(_order(orderType="MKT", lmtPrice=UNSET)))
    assert zeile["orderType"] == "Market"
    assert zeile["price"] == "At market"
    assert "1.79" not in str(zeile)


def test_stop_limit_zeigt_beide_preise() -> None:
    zeile = d.describe(DISPATCH, _trade(_order(orderType="STP LMT", lmtPrice=95.0, auxPrice=96.5)))
    assert zeile["price"] == "Stop 96.50 · Limit 95.00"


def test_moc_und_frist() -> None:
    zeile = d.describe(
        DISPATCH,
        _trade(
            _order(
                orderType="MOC",
                lmtPrice=UNSET,
                tif="GTD",
                goodTillDate="20261112 16:00:00 US/Eastern",
            )
        ),
    )
    assert zeile["orderType"] == "Market on close"
    assert "Valid until 12 Nov 16:00 ET" in zeile["conditions"]


def test_fuellung_und_zeitpunkt() -> None:
    zeit = datetime(2026, 11, 12, 20, 59, tzinfo=timezone.utc)
    zeile = d.describe(
        DISPATCH,
        _trade(
            status="Filled",
            filled=15,
            avg=702.4,
            log=[SimpleNamespace(time=zeit, errorCode=0, message="")],
        ),
    )
    assert zeile["filled"] == "15 @ 702.40"
    assert zeile["placedAt"] == zeit.isoformat()


def test_cockpit_zeile_traegt_die_angaben() -> None:
    m._TRADES_BY_DISPATCH[DISPATCH] = _trade()
    zeile = m.orders_for_cockpit()[0]
    assert zeile["strategy"] == "Fear Shield"
    assert zeile["price"] == "Limit 709.80"
    # Die alten Felder bleiben, die Seite liest sie weiter.
    assert zeile["symbol"] == "SNDK" and zeile["action"] == "BUY"
