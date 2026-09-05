"""T1-152: keine Abfrage an TWS wartet unbegrenzt.

## Der Vorfall, aus dem das entstanden ist

Am 2026-09-04 um 17:46:11 UTC fragte der Abgleich `reqAllOpenOrders()` an. TWS
schickte auf diese eine Anfrage kein `openOrderEnd`, und der Aufruf hat keine
Frist. Die Bridge stand darin **zwei Stunden und vier Minuten**, bis der Owner
sie von Hand neu startete.

Das Tueckische war, dass nichts danach aussah. `reqAllOpenOrders` wartet ueber
die Ereignisschleife und pumpt sie dabei weiter: `updatePortfolio` lief weiter,
und ein `orderStatus`-Rueckruf meldete zwischendurch sogar noch. Kein Absturz,
keine Fehlermeldung, ein Fenster voller frischer Zeilen — und trotzdem seit zwei
Stunden kein Herzschlag. Ein haengender Client ist von einem abgestuerzten nicht
zu unterscheiden, nur schwerer zu erkennen.

## Was hier geprueft wird

Vier Eigenschaften, und die dritte ist die, die am leisesten kaputtgeht:

1. Der Client setzt ueberhaupt eine Grenze.
2. Laeuft eine Abfrage in die Grenze, kehrt der Aufrufer zurueck, statt den
   Takt mitzureissen — sonst kostet jeder Zeitueberlauf den Heartbeat.
3. Der Pumpvorgang der Ereignisschleife bekommt KEINE Grenze. Er laeuft an
   `_run()` vorbei; wanderte er jemals dorthin, bekaeme `sleep()` still eine
   15-Sekunden-Kappe und die Schleife stotterte, ohne dass es jemand merkt.
4. Die zwei engeren Fristen, die es schon gab, bleiben engmaschig — auch die
   20-Sekunden-Frist der Positionsabfrage, die groesser ist als die neue
   Vorgabe und deshalb nur solange gilt, wie sie an `_run()` vorbeigeht.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from ib_insync import IB, util

from ordertune_bridge_ibkr.ibkr_client import (
    POSITIONS_TIMEOUT_S,
    REQUEST_TIMEOUT_S,
    WRITE_ACCESS_TIMEOUT_S,
    IbkrClient,
)
from ordertune_bridge_ibkr.main import (
    _handle_external_executions,
    _handle_order_reconcile,
)

VERBUNDEN = datetime(2026, 9, 4, 8, 17, 44, tzinfo=timezone.utc)

# Ein ungeklaerter Auftrag, damit der Abgleich ueberhaupt bis zur Abfrage kommt:
# `_handle_order_reconcile` kehrt bei leerer Liste vorher um.
UNRESOLVED_ROW = {
    "dispatchId": "00000000-0000-4000-8000-000000000001",
    "symbol": "TEST",
    "submittedAt": "2026-09-04T15:59:00+00:00",
}


class FakeApi:
    """Nur die drei Wege, die der Abgleich und die Fremdmeldung gehen."""

    def __init__(self) -> None:
        self.results: list[tuple[str, Any]] = []
        self.external: list[Any] = []

    def get_unresolved(self) -> list[dict[str, Any]]:
        return [dict(UNRESOLVED_ROW)]

    def result_order(self, dispatch_id: str, **kw: Any) -> None:
        self.results.append((dispatch_id, kw))

    def report_external_execution(self, body: Any) -> bool:
        self.external.append(body)
        return True


class HaengendeAbfrage:
    """Broker-Attrappe, deren Auftragsabfrage in die Zeitgrenze laeuft.

    `asyncio.TimeoutError` ist genau das, was `util.run` wirft, sobald
    `RequestTimeout` gesetzt ist — auf 3.11 der eingebaute `TimeoutError`, auf
    3.10 der eigene aus `asyncio.exceptions`. Der Alias trifft beide.
    """

    def __init__(self) -> None:
        self.slept = 0.0

    def open_trades(self) -> list[Any]:
        raise asyncio.TimeoutError("openOrderEnd kam nie")

    def executions(self) -> list[Any]:
        raise asyncio.TimeoutError("execDetailsEnd kam nie")

    def completed_trades(self, api_only: bool = False) -> list[Any]:
        raise AssertionError(
            "Nach einer gescheiterten Auftragsabfrage darf nicht "
            "weitergefragt werden."
        )

    def fills(self) -> list[Any]:
        return []

    def trading_account(self) -> str:
        return "DU0000000"

    def sleep(self, seconds: float) -> None:
        self.slept += seconds


def test_the_client_puts_a_time_limit_on_every_request() -> None:
    """Die Grenze haengt an der Instanz, nicht an einer Aufrufstelle.

    Bewusst gegen `> 0` und nicht gegen die Zahl geprueft: die Zahl darf sich
    aendern, das Vorhandensein nicht. `RequestTimeout` steht bei ib_insync von
    Haus aus auf 0, und 0 heisst „warte ewig" — genau der Zustand vom 04.09.
    """
    c = IbkrClient(host="127.0.0.1", port=7497, client_id=17)

    assert c._ib.RequestTimeout > 0
    assert c._ib.RequestTimeout == REQUEST_TIMEOUT_S
    assert IB.RequestTimeout == 0, (
        "Die Vorgabe der Bibliothek soll unberuehrt bleiben — die Grenze "
        "gehoert an unsere Instanz, nicht an fremde Klassen."
    )


def test_a_timing_out_open_order_query_does_not_take_the_beat_with_it() -> None:
    """Der Fall vom 04.09., nachgestellt.

    Vor T1-152 kehrte `open_trades()` nie zurueck und `_beat()` damit auch
    nicht — kein Heartbeat mehr, zwei Stunden lang. Mit der Grenze wirft der
    Aufruf, der vorhandene `except`-Zweig greift, und der Takt laeuft weiter.
    """
    api = FakeApi()
    ibkr = HaengendeAbfrage()

    _handle_order_reconcile(api, ibkr, VERBUNDEN)  # type: ignore[arg-type]

    assert api.results == [], (
        "Eine gescheiterte Abfrage ist keine Auskunft. Aus ihr darf kein "
        "Auftragsergebnis an die Plattform gehen."
    )


def test_a_timing_out_execution_query_does_not_take_the_beat_with_it() -> None:
    """Dieselbe Zusicherung fuer den zweiten Weg im selben Takt.

    `_handle_external_executions` laeuft unmittelbar nach dem Heartbeat und vor
    dem Abgleich. Haengt sie, ist der Ausfall derselbe.
    """
    api = FakeApi()
    ibkr = HaengendeAbfrage()

    _handle_external_executions(api, ibkr)  # type: ignore[arg-type]

    assert api.external == []


def test_the_event_loop_pump_keeps_no_time_limit() -> None:
    """`sleep()` und `run()` gehen an `_run()` vorbei — und muessen es.

    `IB.sleep` ist der Pumpvorgang der Ereignisschleife. Bekaeme er die
    Anfrage-Grenze, wuerde jeder Schleifendurchgang nach 15 Sekunden werfen.
    `IB.run` traegt die zwei engeren Fristen unten. Beides haengt daran, dass
    ib_insync sie als `staticmethod(util.…)` fuehrt; diese Zusicherung faellt,
    falls eine kuenftige Fassung das aendert.
    """
    assert IB.sleep is util.sleep
    assert IB.run is util.run


def test_the_narrower_limits_survive_the_default() -> None:
    """Die 20-Sekunden-Frist der Positionsabfrage bleibt bei 20 Sekunden.

    Sie ist groesser als die neue Vorgabe und ueberlebt nur, weil
    `self._ib.run(...)` an `_run()` vorbeigeht. Genau das wird hier gemessen —
    nicht behauptet.
    """
    aufgezeichnet: list[float | None] = []

    class MessenderIb:
        RequestTimeout = REQUEST_TIMEOUT_S

        def run(self, _coro: Any, timeout: float | None = None) -> None:
            aufgezeichnet.append(timeout)

        def reqPositionsAsync(self) -> object:
            return object()

        def positions(self) -> list[Any]:
            return []

    c = IbkrClient(host="127.0.0.1", port=7497, client_id=17)
    c._ib = MessenderIb()  # type: ignore[assignment]

    c._confirm_positions_subscription()

    assert aufgezeichnet == [POSITIONS_TIMEOUT_S]
    assert POSITIONS_TIMEOUT_S > REQUEST_TIMEOUT_S, (
        "Wenn die Positionsfrist unter die Vorgabe faellt, ist diese "
        "Zusicherung wertlos geworden und der Fall neu zu denken."
    )
    assert WRITE_ACCESS_TIMEOUT_S < REQUEST_TIMEOUT_S
