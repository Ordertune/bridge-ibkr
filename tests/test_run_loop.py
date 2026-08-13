"""T1-88: die Schleife, die IBKR anfassen darf — und der Thread, in dem sie laeuft.

## Der Fehler, aus dem das entstanden ist

Am 2026-08-13 wurde zum ersten Mal in der Geschichte des Produkts ein Auftrag
abgesendet. Er scheiterte:

    [ERROR] submit failed for dispatch 11b415a3-...:
    There is no current event loop in thread 'ThreadPoolExecutor-0_0'.

Bis 0.3.0 liefen Heartbeat und Auftragsabruf in einem `BackgroundScheduler`,
also in Arbeiter-Threads. `ib_insync` haengt an einer asyncio-Schleife, die dem
Hauptthread gehoert; ein Absendevorgang aus einem fremden Thread findet sie
nicht.

Warum es monatelang gruen aussah: der Heartbeat liest mit `accountValues()` und
`portfolio()` nur zwischengespeicherten Zustand und braucht die Schleife gar
nicht. Das Abholen offener Auftraege ist reines HTTP. **Nur das Absenden** fasst
IBKR wirklich an — der eine Weg, den nie jemand gegangen war.

## Was hier geprueft wird

Vor allem eine Eigenschaft, und sie ist die eigentliche Reparatur: **beide
Aufgaben laufen im selben Thread wie die Schleife.** Ein Test auf „der Auftrag
kommt an" wuerde TWS brauchen und den Fehler trotzdem nicht dauerhaft
fernhalten — er entstuende beim naechsten Aufruf wieder, den jemand in einen
Thread auslagert.
"""
from __future__ import annotations

import threading

import pytest

from ordertune_bridge_ibkr.main import (
    HEARTBEAT_INTERVAL_S,
    LOOP_TICK_S,
    PENDING_INTERVAL_MARKET_S,
    PENDING_INTERVAL_OFF_S,
    run_loop,
)


class FakeIbkr:
    """Attrappe fuer den Broker-Client.

    `sleep` zaehlt die Durchgaenge und beendet die Schleife nach `ticks` —
    im echten Betrieb laeuft sie bis zum Signal.
    """

    def __init__(self, ticks: int) -> None:
        self.remaining = ticks
        self.sleep_threads: list[int] = []

    def is_connected(self) -> bool:
        return self.remaining > 0

    def sleep(self, seconds: float) -> None:
        self.sleep_threads.append(threading.get_ident())
        self.remaining -= 1


class TickingIbkr(FakeIbkr):
    """Wie oben, laesst die Uhr aber mit jedem Tick weiterlaufen.

    Damit misst der Test ein simuliertes Zeitfenster statt echter Sekunden —
    60 Sekunden Schleife in wenigen Millisekunden.
    """

    def __init__(self, clock: "Clock", ticks: int) -> None:
        super().__init__(ticks)
        self._clock = clock

    def sleep(self, seconds: float) -> None:
        super().sleep(seconds)
        self._clock.advance(seconds)


class Clock:
    """Steuerbare Uhr. Ohne sie muesste der Test echte Sekunden warten."""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def test_both_jobs_run_on_the_loop_thread() -> None:
    """Die Zusicherung, die 0.3.0 gefehlt hat.

    Laeuft eine der beiden Aufgaben in einem anderen Thread, ist die
    asyncio-Schleife von ib_insync fuer sie nicht erreichbar, und jedes
    Absenden scheitert mit „There is no current event loop".
    """
    ibkr = FakeIbkr(ticks=5)
    seen: dict[str, list[int]] = {"heartbeat": [], "pending": []}

    run_loop(
        ibkr,
        heartbeat=lambda: seen["heartbeat"].append(threading.get_ident()),
        pending=lambda: seen["pending"].append(threading.get_ident()),
        stop=threading.Event(),
        market_hours=lambda: True,
        monotonic=Clock(),
    )

    here = threading.get_ident()
    assert seen["heartbeat"], "Heartbeat lief kein einziges Mal"
    assert seen["pending"], "Auftragsabruf lief kein einziges Mal"
    assert set(seen["heartbeat"]) == {here}
    assert set(seen["pending"]) == {here}
    assert set(ibkr.sleep_threads) == {here}


def test_a_slow_job_does_not_refire_immediately() -> None:
    """Die naechste Faelligkeit wird NACH dem Aufruf gestellt.

    Wuerde sie vorher gesetzt, liesse ein HTTP-Aufruf, der laenger dauert als
    das Intervall, die Aufgabe sofort erneut feuern — ein haengender Server
    zoege die Schleife dann in eine Dauerschleife, statt sie nur zu verzoegern.
    """
    clock = Clock()
    ibkr = FakeIbkr(ticks=3)
    calls: list[float] = []

    def slow_heartbeat() -> None:
        calls.append(clock.t)
        clock.advance(HEARTBEAT_INTERVAL_S * 2)  # dauert laenger als sein Intervall

    run_loop(
        ibkr,
        heartbeat=slow_heartbeat,
        pending=lambda: None,
        stop=threading.Event(),
        market_hours=lambda: True,
        monotonic=clock,
    )

    assert len(calls) == 1, (
        "Der Heartbeat ist erneut gefeuert, obwohl sein Intervall erst nach "
        "dem Aufruf beginnt — genau so entsteht die Dauerschleife."
    )


@pytest.mark.parametrize(
    "market_open, interval",
    [(True, PENDING_INTERVAL_MARKET_S), (False, PENDING_INTERVAL_OFF_S)],
)
def test_pending_follows_the_market_hours_interval(
    market_open: bool, interval: float
) -> None:
    """Waehrend der Handelszeit wird haeufiger abgefragt, sonst seltener.

    Gemessen wird ueber ein simuliertes Zeitfenster: die Uhr laeuft mit jedem
    Tick der Schleife weiter. Eine Zusicherung auf „mindestens einmal gefeuert"
    waere praktisch immer wahr und pruefte nichts.
    """
    window_s = 60.0
    clock = Clock()
    ibkr = TickingIbkr(clock, ticks=int(window_s / LOOP_TICK_S))
    at: list[float] = []

    run_loop(
        ibkr,
        heartbeat=lambda: None,
        pending=lambda: at.append(clock.t),
        stop=threading.Event(),
        market_hours=lambda: market_open,
        monotonic=clock,
    )

    # Erster Durchgang feuert sofort, danach je Intervall einmal.
    expected = 1 + int(window_s / interval)
    assert abs(len(at) - expected) <= 1, (
        f"{len(at)} Abrufe in {window_s:.0f}s, erwartet rund {expected} "
        f"bei einem Intervall von {interval:.0f}s"
    )


def test_stop_flag_ends_the_loop_without_another_tick() -> None:
    """SIGINT setzt nur eine Fahne; das Aufraeumen gehoert hinter die Schleife.

    Frueher rief der Handler `sys.exit(0)` und schloss Verbindungen selbst —
    mitten in einem Signal, also potenziell mitten in einem Absendevorgang.
    """
    stop = threading.Event()
    stop.set()
    ibkr = FakeIbkr(ticks=99)
    ran: list[str] = []

    run_loop(
        ibkr,
        heartbeat=lambda: ran.append("heartbeat"),
        pending=lambda: ran.append("pending"),
        stop=stop,
        monotonic=Clock(),
    )

    assert ran == []
    assert ibkr.remaining == 99, "Die Schleife hat trotz gesetzter Fahne getickt"


def test_disconnect_ends_the_loop() -> None:
    ibkr = FakeIbkr(ticks=0)
    ran: list[str] = []
    run_loop(
        ibkr,
        heartbeat=lambda: ran.append("heartbeat"),
        pending=lambda: ran.append("pending"),
        stop=threading.Event(),
        monotonic=Clock(),
    )
    assert ran == []


def test_no_scheduler_is_imported_any_more() -> None:
    """Kein Zeitgeber mehr — geprueft am Baum, nicht am Text.

    Ohne diese Zusicherung kaeme der Fehler zurueck, sobald jemand die naechste
    wiederkehrende Aufgabe „wie frueher" anlegt. Geprueft wird der geparste
    Syntaxbaum: der Modulkopf erzaehlt die Geschichte des Fehlers und nennt
    `BackgroundScheduler` dabei beim Namen — eine Textsuche wuerde daran
    haengenbleiben und hier faelschlich Alarm schlagen.
    """
    import ast

    import ordertune_bridge_ibkr.main as m

    tree = ast.parse(open(m.__file__, encoding="utf-8").read())
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)

    assert not [name for name in imported if "apscheduler" in name.lower()], (
        f"Ein Zeitgeber ist zurueck im Modul: {imported}"
    )
    assert not hasattr(m, "BackgroundScheduler")
