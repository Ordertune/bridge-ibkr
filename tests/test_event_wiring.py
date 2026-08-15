"""Woran der Rueckruf fuer Auftragszustaende haengt — und woran nicht.

## Der Befund

Bis 0.4.1 wurde derselbe einargumentige Rueckruf an zwei Ereignisse gehaengt:

    self._ib.execDetailsEvent += cb   # emittiert (trade, fill)
    self._ib.orderStatusEvent += cb   # emittiert (trade)

Der erste Weg hat nie funktioniert. eventkit ruft den Rueckruf mit zwei
Argumenten auf, faengt den TypeError ab und schreibt ihn samt Traceback ins
Protokoll — bei jeder Ausfuehrung. Folgenlos blieb es nur, weil
`orderStatusEvent` Menge und Preis ohnehin traegt; gemeldet wurde also immer
ueber den zweiten Weg.

## Warum der naheliegende Fix falsch waere

`*args` am Rueckruf haette den Traceback beseitigt und dafuer die Gebuehr
gekostet: `execDetails` trifft ein, bevor die Gebuehrenabrechnung vorliegt.
Der Rueckruf haette `filled` ohne Gebuehr gemeldet, und die spaetere
`orderStatus`-Meldung mit derselben Aussage faellt in `should_report` heraus.
Die Kostenbasis aus T1-78 haette dauerhaft gefehlt.

Diese Datei nagelt beide Haelften fest: die Registrierung haengt nur noch an
`orderStatusEvent`, und die Meldereihenfolge liefert die Gebuehr.
"""
from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import pytest
from eventkit import Event

from ordertune_bridge_ibkr import main as m
from ordertune_bridge_ibkr.ibkr_client import IbkrClient


@pytest.fixture(autouse=True)
def _reset():
    m._LAST_REPORTED.clear()
    yield
    m._LAST_REPORTED.clear()


class FakeApi:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def result_order(self, dispatch_id: str, **kwargs: Any) -> None:
        self.calls.append({"dispatchId": dispatch_id, **kwargs})


def _client_with_fake_ib() -> tuple[IbkrClient, SimpleNamespace]:
    """Ein Client, dessen IB-Verbindung durch echte Ereignisse ersetzt ist.

    `IbkrClient.__init__` baut nur ein `IB`-Objekt und verbindet nichts —
    deshalb laesst sich die Verdrahtung ohne TWS pruefen.
    """
    client = IbkrClient(host="127.0.0.1", port=7497, client_id=17)
    fake = SimpleNamespace(
        execDetailsEvent=Event("execDetailsEvent"),
        orderStatusEvent=Event("orderStatusEvent"),
    )
    client._ib = fake  # type: ignore[assignment]
    return client, fake


def test_the_callback_hangs_on_order_status_only() -> None:
    """Der zweite Weg ist weg — er war seit jeher tot."""
    client, fake = _client_with_fake_ib()
    client.subscribe_order_status_callback(lambda trade: None)

    assert len(fake.orderStatusEvent) == 1
    assert len(fake.execDetailsEvent) == 0, (
        "An `execDetailsEvent` darf dieser Rueckruf nicht haengen: das Ereignis "
        "emittiert zwei Argumente, und ein `*args`-Fix wuerde die Gebuehr kosten."
    )


def test_a_fill_no_longer_writes_a_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Die Ausfuehrung meldet sich, ohne dass eventkit einen Fehler protokolliert.

    Vor der Berichtigung stand hier bei jeder Ausfuehrung
    `TypeError: on_status() takes 1 positional argument but 2 were given`.
    """
    client, fake = _client_with_fake_ib()
    api = FakeApi()
    client.subscribe_order_status_callback(
        m._make_on_order_status(api, {42: "d-1"})
    )

    trade = SimpleNamespace(
        order=SimpleNamespace(orderId=42, orderType="LMT", tif="DAY"),
        orderStatus=SimpleNamespace(status="Filled", filled=2.0, avgFillPrice=112.46),
        log=[SimpleNamespace(status="Filled", message="", errorCode=0)],
        fills=[
            SimpleNamespace(
                commissionReport=SimpleNamespace(commission=1.9),
            )
        ],
    )

    with caplog.at_level(logging.ERROR):
        # So, wie ib_insync es tut: zwei Argumente auf dem einen Weg, eines auf
        # dem anderen. Nur der zweite traegt noch einen Empfaenger.
        fake.execDetailsEvent.emit(trade, object())
        fake.orderStatusEvent.emit(trade)

    assert not any(
        "TypeError" in r.getMessage() or "caused exception" in r.getMessage()
        for r in caplog.records
    ), "eventkit protokolliert wieder einen Fehler bei jeder Ausfuehrung"

    assert len(api.calls) == 1
    assert api.calls[0]["fill_qty"] == 2.0


def test_the_commission_survives_the_report() -> None:
    """Der Grund, warum `execDetails` nicht mitmelden darf.

    Ueber `orderStatus` liegt die Gebuehrenabrechnung bereits am Auftrag. Haette
    `execDetails` vorher gemeldet, waere diese Meldung in `should_report`
    herausgefallen und die Gebuehr nie angekommen.
    """
    api = FakeApi()
    trade = SimpleNamespace(
        order=SimpleNamespace(orderId=42, orderType="LMT", tif="DAY"),
        orderStatus=SimpleNamespace(status="Filled", filled=2.0, avgFillPrice=112.46),
        log=[SimpleNamespace(status="Filled", message="", errorCode=0)],
        fills=[SimpleNamespace(commissionReport=SimpleNamespace(commission=1.9))],
    )

    m._report_status(api, "d-2", trade, "filled")
    assert api.calls[0]["commission_usd"] == 1.9

    # Die Gegenprobe: eine zweite Meldung derselben Aussage kommt nicht durch.
    # Genau daran waere die Gebuehr gescheitert, haette `execDetails` zuerst
    # gemeldet.
    m._report_status(api, "d-2", trade, "filled")
    assert len(api.calls) == 1
