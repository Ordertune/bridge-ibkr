"""T1-88c: der Stornoweg — anfordern, nicht behaupten.

## Woher das kommt

Bis heute war der Stornoweg an vier Stellen unterbrochen. Der Nutzer konnte
einen abgesendeten Auftrag nirgends stoppen, und die eine Stelle, die es
versucht hätte, meldete Erfolg, ohne etwas erreicht zu haben:
`bridgeRouter.cancel` gab `{ok: true, status: "cancelled"}` zurück, sobald
eine Fahne gesetzt war.

Das ist dieselbe Fehlerklasse wie der Phantom-Storno aus T1-88b, nur mit
umgekehrtem Vorzeichen. Dort hielt die Plattform einen lebenden Auftrag für
tot; hier hielte sie ihn für storniert, während er weiter im Buch liegt — und
wer sich darauf verlässt, merkt es beim nächsten Öffnungskurs.

## Was hier geprüft wird

Zwei Dinge, beide ohne TWS:

1. **Der Storno geht raus und meldet nichts.** Die Bestätigung kommt als
   Zustandsereignis mit Fehlercode 202 und läuft durch dieselbe Prüfung, die
   seit T1-88b den Phantom-Storno abfängt.
2. **Die Zuordnung überlebt einen Neustart.** Ohne den Wiederaufbau über den
   Auftragsvermerk könnte ein Storno den Auftrag nicht finden — und die
   ehrlichste Antwort wäre dann „weiß nicht", was für einen Nutzer mit
   Echtgeld unbrauchbar ist.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from ordertune_bridge_ibkr import main as m


@pytest.fixture(autouse=True)
def _reset():
    m._TRADES_BY_DISPATCH.clear()
    m._CANCEL_SENT.clear()
    m._CANCEL_UNRESOLVED.clear()
    yield
    m._TRADES_BY_DISPATCH.clear()
    m._CANCEL_SENT.clear()
    m._CANCEL_UNRESOLVED.clear()


def make_trade(dispatch_id: str | None, order_id: int = 3) -> SimpleNamespace:
    ref = f"ot-{dispatch_id}" if dispatch_id else ""
    return SimpleNamespace(
        order=SimpleNamespace(orderId=order_id, orderRef=ref, orderType="LMT"),
        orderStatus=SimpleNamespace(status="Submitted", filled=0.0, avgFillPrice=0.0),
        log=[],
        fills=[],
    )


class FakeIbkr:
    def __init__(self, trades=(), fail: bool = False) -> None:
        self._trades = list(trades)
        self._fail = fail
        self.cancelled: list[int] = []

    def open_trades(self):
        return self._trades

    def cancel_order(self, order) -> None:
        if self._fail:
            raise RuntimeError("TWS nicht erreichbar")
        self.cancelled.append(order.orderId)


# ── Der Auftragsvermerk ──────────────────────────────────────────────────────


def test_the_order_ref_carries_the_dispatch_id() -> None:
    assert m.dispatch_id_from_order_ref("ot-6351623c-8cef-46fe-8abf-a7da046fc619") == "6351623c-8cef-46fe-8abf-a7da046fc619"


@pytest.mark.parametrize("ref", [None, "", "abc-123", "ot-", "ot-   ", "xy-abc"])
def test_a_foreign_order_is_not_ours(ref) -> None:
    """Von Hand gestellte Auftraege im selben Konto tragen den Vermerk nicht.

    Sie stillschweigend zu uebergehen ist der Punkt: sie gehoeren uns nicht,
    und wir stornieren sie ganz sicher nicht.
    """
    assert m.dispatch_id_from_order_ref(ref) is None


# ── Der Wiederaufbau nach einem Neustart ─────────────────────────────────────


def test_the_mapping_survives_a_restart() -> None:
    """Die Voraussetzung fuer den Stornoweg.

    IBKR meldet TWS taeglich gegen 05:00 MEZ zwangsweise ab. Ohne diesen
    Wiederaufbau waere danach jeder vorher abgesendete Auftrag unauffindbar —
    weder stornierbar noch meldbar.
    """
    dispatch_id_map: dict[int, str] = {}
    ibkr = FakeIbkr([make_trade("657be283-ed36-426e-8d9f-f0bf708f3881", 3), make_trade("edf40f88-85ec-4106-803d-71d67c07afa1", 4)])

    anzahl = m.rebuild_dispatch_map(ibkr, dispatch_id_map)

    assert anzahl == 2
    assert dispatch_id_map == {3: "657be283-ed36-426e-8d9f-f0bf708f3881", 4: "edf40f88-85ec-4106-803d-71d67c07afa1"}
    assert m.trade_for_dispatch("657be283-ed36-426e-8d9f-f0bf708f3881") is not None
    assert m.trade_for_dispatch("edf40f88-85ec-4106-803d-71d67c07afa1") is not None


def test_foreign_orders_are_skipped_during_rebuild() -> None:
    dispatch_id_map: dict[int, str] = {}
    ibkr = FakeIbkr([make_trade("657be283-ed36-426e-8d9f-f0bf708f3881", 3), make_trade(None, 99)])

    assert m.rebuild_dispatch_map(ibkr, dispatch_id_map) == 1
    assert 99 not in dispatch_id_map


def test_an_unreachable_broker_does_not_kill_the_startup() -> None:
    """Der Wiederaufbau darf den Start nicht verhindern.

    Er ist eine Verbesserung der Lage, kein Vorbehalt: ohne ihn laeuft die
    Bridge wie vorher, nur ohne Storno fuer alte Auftraege.
    """

    class Kaputt(FakeIbkr):
        def open_trades(self):
            raise RuntimeError("keine Verbindung")

    assert m.rebuild_dispatch_map(Kaputt(), {}) == 0


# ── Der Storno selbst ────────────────────────────────────────────────────────


def test_the_cancel_goes_out_and_reports_nothing() -> None:
    """Die tragende Zusicherung.

    Der Storno wird an IBKR geschickt — und es wird NICHTS gemeldet. Die
    Bestaetigung kommt als Zustandsereignis mit Code 202 und laeuft durch
    `cancel_is_genuine`. Haette diese Stelle einen Erfolg gemeldet, staende in
    der Oberflaeche „storniert", waehrend der Auftrag weiter im Buch liegt.
    """
    dispatch_id_map: dict[int, str] = {}
    trade = make_trade("657be283-ed36-426e-8d9f-f0bf708f3881", 3)
    m.register_trade(dispatch_id_map, "657be283-ed36-426e-8d9f-f0bf708f3881", trade)
    ibkr = FakeIbkr()

    m._handle_cancel(ibkr, "657be283-ed36-426e-8d9f-f0bf708f3881")

    assert ibkr.cancelled == [3]


def test_a_cancel_is_sent_only_once() -> None:
    """Die Plattform liefert den Storno bei jedem Abruf erneut aus, bis der
    Broker bestaetigt hat. Ohne diese Merkung ginge alle fuenf Sekunden ein
    weiterer raus."""
    dispatch_id_map: dict[int, str] = {}
    m.register_trade(dispatch_id_map, "657be283-ed36-426e-8d9f-f0bf708f3881", make_trade("657be283-ed36-426e-8d9f-f0bf708f3881", 3))
    ibkr = FakeIbkr()

    for _ in range(5):
        m._handle_cancel(ibkr, "657be283-ed36-426e-8d9f-f0bf708f3881")

    assert ibkr.cancelled == [3]


def test_a_failed_cancel_is_retried() -> None:
    """Gescheitert ist nicht erledigt — sonst bliebe der Auftrag stehen und
    niemand versuchte es noch einmal."""
    dispatch_id_map: dict[int, str] = {}
    m.register_trade(dispatch_id_map, "657be283-ed36-426e-8d9f-f0bf708f3881", make_trade("657be283-ed36-426e-8d9f-f0bf708f3881", 3))

    m._handle_cancel(FakeIbkr(fail=True), "657be283-ed36-426e-8d9f-f0bf708f3881")
    assert "657be283-ed36-426e-8d9f-f0bf708f3881" not in m._CANCEL_SENT

    ibkr = FakeIbkr()
    m._handle_cancel(ibkr, "657be283-ed36-426e-8d9f-f0bf708f3881")
    assert ibkr.cancelled == [3]


def test_an_unknown_dispatch_warns_once_and_reports_nothing() -> None:
    """Kein Auftrag auffindbar heisst nicht „storniert".

    Genau hier waere die Versuchung, etwas zu melden, damit die Oberflaeche
    weiterkommt. Das waere eine Behauptung ueber einen Auftrag, ueber den wir
    nichts wissen.
    """
    ibkr = FakeIbkr()
    for _ in range(3):
        m._handle_cancel(ibkr, "unbekannt")

    assert ibkr.cancelled == []
    assert m._CANCEL_UNRESOLVED == {"unbekannt"}


def test_a_broker_confirmed_cancellation_is_what_gets_reported() -> None:
    """Der Rueckweg, an dem der ganze Entwurf haengt.

    IBKR quittiert eine echte Stornierung mit Code 202. Erst die laeuft durch
    und wird gemeldet — dieselbe Pruefung, die den Phantom-Storno abfaengt.
    """
    storniert = SimpleNamespace(
        log=[SimpleNamespace(status="Cancelled", errorCode=202)]
    )
    assert m.cancel_is_genuine(storniert) is True

    phantom = SimpleNamespace(
        log=[SimpleNamespace(status="Cancelled", errorCode=10349)]
    )
    assert m.cancel_is_genuine(phantom) is False
