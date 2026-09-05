"""T1-152d: ein Verbindungsverlust ist nicht das Ende.

## Woher das kommt

Am 2026-09-04 um 23:45:01 UTC schloss TWS die Verbindung — der naechtliche
Zwangsneustart, den `rebuild_dispatch_map` seit T1-88c beim Namen nennt.
`run_loop` laeuft `while ibkr.is_connected()`, endete also, und `main()` raeumte
auf. Die Bridge war 15 Stunden weg, bis sie jemand von Hand startete.

`run_loop` kennt zwei Gruende aufzuhoeren: das Stopp-Signal, und die Verbindung
ist weg. Der erste ist eine Anweisung, der zweite ein Zustand. Bis 0.21.0 wurde
dieser Unterschied nirgends gemacht.

## Was hier geprueft wird

Die Wiederverbindung selbst ist der leichte Teil. Die drei Zusicherungen, die
wirklich zaehlen, decken das ab, was eine zweite Sitzung im selben Vorgang
kaputtmachen kann:

* `connect()` haengt seinen Fehler-Rueckruf nicht zweimal an, und die
  321er-Befunde der VORIGEN Sitzung faerben nicht auf die neue ab. Ohne das
  haelt die Bridge sich nach einer Nacht grundlos fuer schreibgeschuetzt — und
  zwar stumm.
* Der Auftragsstatus-Rueckruf wird NICHT erneut angehaengt. Er haengt am
  `IB`-Objekt und ueberlebt die Verbindung; ein zweites `+=` schickte jede
  Auftragsmeldung doppelt.
* Nach jeder Wiederverbindung laufen Sitzungszeitpunkt und Auftragszuordnung
  neu. Beides haengt an einer Sitzung, nicht an einem Vorgang.
"""
from __future__ import annotations

from typing import Any

from ordertune_bridge_ibkr.ibkr_client import IbkrClient
from ordertune_bridge_ibkr.main import (
    RECONNECT_BACKOFF_S,
    reconnect_forever,
    run_supervised,
)


class FakeStop:
    """Stopp-Signal, das die Wartezeiten aufschreibt statt zu warten.

    Ohne das wuerde eine einzige Zusicherung ueber die Wartestaffel gut vier
    Minuten echte Zeit kosten.
    """

    def __init__(self, set_after_waits: int | None = None) -> None:
        self.waits: list[float] = []
        self._set = False
        self._set_after = set_after_waits

    def is_set(self) -> bool:
        return self._set

    def wait(self, seconds: float) -> bool:
        self.waits.append(seconds)
        if self._set_after is not None and len(self.waits) >= self._set_after:
            self._set = True
        return self._set

    def set(self) -> None:
        self._set = True


class FlakyIbkr:
    """Broker-Attrappe, die die ersten `fail_times` Versuche abweist."""

    def __init__(self, fail_times: int = 0) -> None:
        self.fail_times = fail_times
        self.attempts = 0

    def connect(self) -> None:
        self.attempts += 1
        if self.attempts <= self.fail_times:
            raise ConnectionRefusedError("TWS ist noch nicht wieder da")

    def subscribe_order_status_callback(self, cb: Any) -> None:
        raise AssertionError(
            "Der Auftragsstatus-Rueckruf haengt am IB-Objekt und ueberlebt die "
            "Verbindung. Ein zweites Anhaengen meldet jede Ausfuehrung doppelt."
        )


def test_the_connection_comes_back_on_its_own() -> None:
    """Der Fall vom 04.09.: TWS ist kurz weg und dann wieder da."""
    stop = FakeStop()
    ibkr = FlakyIbkr(fail_times=2)

    assert reconnect_forever(ibkr, stop) is True
    assert ibkr.attempts == 3
    assert stop.waits == [5.0, 10.0, 20.0]


def test_the_wait_grows_and_then_stays() -> None:
    """Gemessen, nicht behauptet — inklusive der Deckelung.

    Ohne Deckelung waere die Wartezeit nach einem Wochenende bei mehreren
    Stunden, und die Bridge kaeme Montag frueh nicht rechtzeitig zurueck.
    """
    stop = FakeStop()
    ibkr = FlakyIbkr(fail_times=8)

    assert reconnect_forever(ibkr, stop) is True
    assert stop.waits == [5.0, 10.0, 20.0, 30.0, 60.0, 60.0, 60.0, 60.0, 60.0]
    assert stop.waits[-1] == RECONNECT_BACKOFF_S[-1]


def test_a_stop_signal_during_the_wait_ends_it_at_once() -> None:
    """Strg-C darf nicht bis zu einer Minute liegen bleiben.

    Deshalb `stop.wait(...)` und nicht `time.sleep(...)`. Und es darf danach
    kein Verbindungsversuch mehr kommen — der Nutzer hat Schluss gesagt.
    """
    stop = FakeStop(set_after_waits=1)
    ibkr = FlakyIbkr(fail_times=99)

    assert reconnect_forever(ibkr, stop) is False
    assert ibkr.attempts == 0


def test_the_supervisor_re_enters_the_loop_after_a_reconnect() -> None:
    """Der eigentliche Zweck: nach der Trennung laeuft die Schleife weiter."""
    stop = FakeStop()
    ibkr = FlakyIbkr()
    laeufe: list[int] = []
    neu_verbunden: list[int] = []

    def fake_loop(_ibkr: Any, **_kw: Any) -> None:
        laeufe.append(1)
        if len(laeufe) >= 2:
            stop.set()

    run_supervised(
        ibkr,
        heartbeat=lambda: None,
        pending=lambda: None,
        stop=stop,  # type: ignore[arg-type]
        on_reconnected=lambda: neu_verbunden.append(1),
        loop=fake_loop,
        reconnect=lambda *_a, **_k: True,
    )

    assert laeufe == [1, 1], "Die Schleife muss ein zweites Mal betreten werden."
    assert neu_verbunden == [1], (
        "Sitzungszeitpunkt und Auftragszuordnung haengen an einer Sitzung. "
        "Genau einmal je Wiederverbindung, nicht je Durchgang."
    )


def test_a_stop_signal_ends_the_supervisor_without_reconnecting() -> None:
    """Ein gewolltes Ende ist kein Verbindungsverlust."""
    stop = FakeStop()
    versuche: list[int] = []

    def fake_loop(_ibkr: Any, **_kw: Any) -> None:
        stop.set()

    run_supervised(
        FlakyIbkr(),
        heartbeat=lambda: None,
        pending=lambda: None,
        stop=stop,  # type: ignore[arg-type]
        loop=fake_loop,
        reconnect=lambda *_a, **_k: versuche.append(1) or True,
    )

    assert versuche == []


def test_a_hopeless_reconnect_ends_the_supervisor() -> None:
    """Gibt die Wiederverbindung auf, laeuft der Abbau — keine Endlosschleife."""
    stop = FakeStop()
    laeufe: list[int] = []
    neu_verbunden: list[int] = []

    def fake_loop(_ibkr: Any, **_kw: Any) -> None:
        laeufe.append(1)

    run_supervised(
        FlakyIbkr(),
        heartbeat=lambda: None,
        pending=lambda: None,
        stop=stop,  # type: ignore[arg-type]
        on_reconnected=lambda: neu_verbunden.append(1),
        loop=fake_loop,
        reconnect=lambda *_a, **_k: False,
    )

    assert laeufe == [1]
    assert neu_verbunden == []


# ── Was eine ZWEITE Sitzung im selben Vorgang kaputtmachen kann ──────────────


class FakeEvent:
    """eventkit-Ereignis, soweit `connect()` es anfasst."""

    def __init__(self) -> None:
        self.handlers: list[Any] = []

    def __iadd__(self, cb: Any) -> FakeEvent:  # noqa: PYI034 - Attrappe, kein Protokoll
        self.handlers.append(cb)
        return self


class FakeIb:
    """Gerade so viel `IB`, wie `connect()` braucht."""

    RequestTimeout = 0.0

    def __init__(self) -> None:
        self.errorEvent = FakeEvent()
        self.connects = 0

    def connect(self, *_a: Any, **_kw: Any) -> None:
        self.connects += 1

    def run(self, _coro: Any, timeout: float | None = None) -> None:
        return None

    def reqPositionsAsync(self) -> object:
        return object()

    def reqOpenOrdersAsync(self) -> object:
        return object()

    def positions(self) -> list[Any]:
        return []


def test_connecting_twice_attaches_the_error_hook_once() -> None:
    """Sonst stuende jede 321er-Meldung nach einer Nacht doppelt in der Liste."""
    c = IbkrClient(host="127.0.0.1", port=7497, client_id=17)
    c._ib = FakeIb()  # type: ignore[assignment]

    c.connect()
    c.connect()

    assert c._ib.connects == 2
    assert len(c._ib.errorEvent.handlers) == 1  # type: ignore[union-attr]


def test_a_new_session_does_not_inherit_the_old_findings() -> None:
    """Der gefaehrlichste der beiden Fehler, und der leiseste.

    Eine 321er-Meldung von gestern wuerde die Schreibrechte der heutigen
    Sitzung als eingeschraenkt einstufen. Die Bridge haelt sich dann grundlos
    fuer schreibgeschuetzt, meldet weiter Herzschlaege und laesst jeden Auftrag
    abprallen — ohne dass irgendwo etwas rot wird.
    """
    c = IbkrClient(host="127.0.0.1", port=7497, client_id=17)
    c._ib = FakeIb()  # type: ignore[assignment]
    c._validation_errors = ["Order abgelehnt, Konto ist schreibgeschuetzt"]
    c._positions_known = True

    c.connect()

    assert c._validation_errors == []
