"""T1-88b: der Statusrückweg — was gemeldet wird und was nicht.

## Der Vorfall, aus dem das entstanden ist

Am 2026-08-13 lagen nach zwei Klicks **zwei** Aufträge über dieselbe Position
live bei IBKR, während die Plattform beide für storniert hielt. Auf einem
Echtgeldkonto.

Die Kette:

1. Der Übersetzer schickte Limit- und Market-Aufträge ohne Gültigkeitsdauer
   raus. TWS ergänzt sie aus den Voreinstellungen und quittiert das mit
   Meldung 10349 — ein Hinweis, kein Fehler.
2. `ib_insync` führt eine feste Liste harmloser Codes
   (`warningCodes = {110, 165, 202, 399, 404, 434, 492, 10167}`). 10349 steht
   nicht darin, also läuft alles im Fehlerzweig, und der setzt
   `trade.orderStatus.status = Cancelled` — eine Zuweisung an ein
   Python-Objekt. Es geht kein `cancelOrder` über die Leitung.
3. Die Bridge glaubte das, meldete `cancelled` als Endzustand und hakte den
   Vorgang dauerhaft ab. Eine Sekunde später meldete IBKR `PreSubmitted`,
   dann `Submitted`. Zu spät, niemand hörte mehr zu.
4. Ein als storniert gebuchter Vorgang gilt der Plattform als abgeschlossen —
   und ihr Riegel gegen Doppelaufträge hat genau diesen Status als einzigen
   Eingangswert.

## Was hier geprüft wird

Alles ohne TWS, gegen Attrappen. Die teuerste Zusicherung ist die dritte:
nach einem gemeldeten Storno muss eine **echte Ausführung** noch durchkommen.
Ohne sie entstünde die Position im Depot, käme nie in die Bücher, und der
Modell-Ausstieg würde sie nie anfassen.
"""
from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from ordertune_bridge_ibkr import main as m


@pytest.fixture(autouse=True)
def _reset_module_state():
    """Modulweite Ablagen zwischen den Zusicherungen leeren."""
    m._LAST_REPORTED.clear()
    m._PENDING_CANCEL_CHECKS.clear()
    yield
    m._LAST_REPORTED.clear()
    m._PENDING_CANCEL_CHECKS.clear()


class FakeApi:
    """Nimmt Meldungen entgegen, statt sie zu verschicken."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def result_order(self, dispatch_id: str, **kwargs) -> None:
        self.calls.append({"dispatch_id": dispatch_id, **kwargs})

    @property
    def statuses(self) -> list[str]:
        return [c["status"] for c in self.calls]


def make_trade(status: str, *, error_code=None, filled=0.0, order_id=3,
               order_type="LMT", history=()) -> SimpleNamespace:
    """Ein Auftrag, wie ib_insync ihn durchreicht.

    `history` sind die Zustände, die der Auftrag vorher hatte — ib_insync
    schreibt sie in `trade.log` fort.
    """
    entries = [SimpleNamespace(status=s, errorCode=0) for s in history]
    entries.append(SimpleNamespace(status=status, errorCode=error_code))
    return SimpleNamespace(
        order=SimpleNamespace(orderId=order_id, orderType=order_type),
        orderStatus=SimpleNamespace(status=status, filled=filled, avgFillPrice=0.0),
        log=entries,
        fills=[],
    )


# ── Der Phantom-Storno ───────────────────────────────────────────────────────


def test_a_cancel_without_a_cancel_reason_is_not_reported_yet() -> None:
    """Genau der Fall vom 2026-08-13.

    Fehlercode 10349 ist keine Stornobestaetigung. Die Meldung wird
    zurueckgehalten, statt einen lebenden Auftrag totzuschreiben.
    """
    api = FakeApi()
    on_status = m._make_on_order_status(api, {3: "disp-1"})

    on_status(make_trade("Cancelled", error_code=10349))

    assert api.calls == [], (
        "Der Storno wurde sofort gemeldet. Genau das hat zwei Echtauftraege "
        "erzeugt, die die Plattform beide fuer storniert hielt."
    )
    assert "disp-1" in m._PENDING_CANCEL_CHECKS


def test_the_deferred_check_reports_working_when_the_order_lives() -> None:
    """Eine Sekunde spaeter meldet IBKR den wahren Zustand — der wird gelesen."""
    api = FakeApi()
    trade = make_trade("Cancelled", error_code=10349)
    on_status = m._make_on_order_status(api, {3: "disp-1"})
    on_status(trade)

    # ib_insync schreibt denselben Gegenstand fort.
    trade.orderStatus.status = "Submitted"

    m.handle_deferred_cancels(api, monotonic=lambda: 1e9)

    assert api.statuses == ["working"], (
        "Der Auftrag lebt, es muss `working` gemeldet werden — nicht cancelled."
    )
    assert m._PENDING_CANCEL_CHECKS == {}


def test_a_genuine_cancellation_is_reported_immediately() -> None:
    """Code 202 ist IBKRs Stornobestaetigung. Die wird nicht verzoegert."""
    api = FakeApi()
    on_status = m._make_on_order_status(api, {3: "disp-1"})

    on_status(make_trade("Cancelled", error_code=202, history=["Submitted"]))

    assert api.statuses == ["cancelled"]
    assert m._PENDING_CANCEL_CHECKS == {}


def test_a_still_cancelled_order_is_reported_after_the_wait() -> None:
    api = FakeApi()
    trade = make_trade("Cancelled", error_code=10349)
    m._make_on_order_status(api, {3: "disp-1"})(trade)

    m.handle_deferred_cancels(api, monotonic=lambda: 1e9)

    assert api.statuses == ["cancelled"], (
        "Bleibt der Auftrag storniert, muss die Meldung nachkommen — sonst "
        "haenge die Ausfuehrung fuer immer auf `submitting`."
    )


def test_the_wait_is_not_cut_short() -> None:
    """Vor Ablauf der Frist wird nichts aufgeloest."""
    api = FakeApi()
    m._make_on_order_status(api, {3: "disp-1"})(
        make_trade("Cancelled", error_code=10349)
    )
    m.handle_deferred_cancels(api, monotonic=lambda: 0.0)
    assert api.calls == []
    assert "disp-1" in m._PENDING_CANCEL_CHECKS


def test_a_fill_cancels_the_pending_cancel_check() -> None:
    """Fuellt der Auftrag, ist die Storno-Frage beantwortet."""
    api = FakeApi()
    on_status = m._make_on_order_status(api, {3: "disp-1"})
    on_status(make_trade("Cancelled", error_code=10349))
    on_status(make_trade("Filled", filled=2.0, history=["Submitted"]))

    assert m._PENDING_CANCEL_CHECKS == {}
    assert api.statuses == ["filled"]


# ── Die Sperre, die einen Fill verschluckt hat ───────────────────────────────


def test_a_fill_overrides_a_reported_cancellation() -> None:
    """Die teuerste Zusicherung dieser Datei.

    Vorher war ein Dispatch nach dem ersten Endzustand dauerhaft gesperrt.
    Fuellte der faelschlich stornierte Auftrag spaeter wirklich, wurde das nie
    gemeldet: die Position entstuende im Depot, kaeme nie in die Buecher, und
    der Modell-Ausstieg wuerde sie nie anfassen.
    """
    assert m.should_report("disp-1", "cancelled") is True
    assert m.should_report("disp-1", "filled") is True, (
        "Eine Ausfuehrung ist am Konto passiert und laesst sich nicht "
        "widerrufen. Sie muss eine gemeldete Stornierung ueberschreiben."
    )


def test_nothing_overrides_a_fill() -> None:
    assert m.should_report("disp-1", "filled") is True
    for spaeter in ("cancelled", "rejected", "expired", "working", "partial"):
        assert m.should_report("disp-1", spaeter) is False, spaeter


def test_the_same_state_twice_is_not_a_new_statement() -> None:
    assert m.should_report("disp-1", "working") is True
    assert m.should_report("disp-1", "working") is False


def test_a_live_state_revokes_a_reported_cancellation() -> None:
    """Der Rueckweg aus einem falsch gemeldeten Storno."""
    assert m.should_report("disp-1", "cancelled") is True
    assert m.should_report("disp-1", "working") is True


def test_a_cancellation_does_not_override_another_terminal_state() -> None:
    assert m.should_report("disp-1", "rejected") is True
    assert m.should_report("disp-1", "cancelled") is False


# ── Die Statustabelle ────────────────────────────────────────────────────────


def test_every_ib_insync_state_is_mapped() -> None:
    """Kein Zustand faellt mehr stillschweigend heraus.

    Vorher kannte die Tabelle fuenf von neun Werten — und die fehlenden waren
    ausgerechnet die, die einen LEBENDEN Auftrag beschreiben.
    """
    from ib_insync import OrderStatus

    bekannt = {
        v for k, v in vars(OrderStatus).items()
        if isinstance(v, str) and k[0].isupper() and not k.startswith("_")
    }
    # Nur die Zustandsnamen, nicht die Mengen darunter.
    bekannt = {s for s in bekannt if s and s[0].isupper()}

    fehlend = sorted(s for s in bekannt if s not in m._STATUS_MAP)
    assert not fehlend, f"Nicht abgebildete IBKR-Zustaende: {fehlend}"


def test_live_states_are_not_terminal() -> None:
    """Ein lebender Auftrag darf den Riegel der Plattform nicht oeffnen."""
    for raw in ("PreSubmitted", "Submitted", "PendingSubmit", "PendingCancel"):
        assert m._STATUS_MAP[raw] not in m.TERMINAL_STATES, raw


def test_inactive_is_not_reported_as_rejected() -> None:
    """`Inactive` ist mehrdeutig — im Zweifel Riegel zu.

    Ein faelschlich geoeffneter Riegel kostet einen zweiten Echtauftrag, ein
    faelschlich geschlossener einen Klick.
    """
    assert m._STATUS_MAP["Inactive"] == "working"


def test_an_unknown_state_is_not_reported() -> None:
    api = FakeApi()
    m._make_on_order_status(api, {3: "disp-1"})(make_trade("Voellig Neu"))
    assert api.calls == []


# ── Der erfundene Grund ──────────────────────────────────────────────────────


def test_limit_not_reached_requires_the_order_to_have_been_live() -> None:
    """Am 2026-08-13 stand dieser Grund an einem Auftrag, der sieben Stunden
    vor Boersenoeffnung storniert wurde — an einem Limit, das nie eine Chance
    hatte."""
    nie_am_markt = make_trade("Cancelled", error_code=202)
    assert m._derive_reason_code("cancelled", 0.0, "LMT", nie_am_markt) == (
        "cancelled_by_user"
    )

    war_am_markt = make_trade("Cancelled", error_code=202, history=["Submitted"])
    assert m._derive_reason_code("cancelled", 0.0, "LMT", war_am_markt) == (
        "limit_not_reached"
    )


def test_reason_code_without_a_trade_keeps_the_old_behaviour() -> None:
    assert m._derive_reason_code("cancelled", 0.0, "LMT") == "limit_not_reached"


# ── T1-137 — eine Ablehnung ist keine Stornierung ───────────────────────────


def _rejected_trade(text: str = "Order abgewiesen - Grund: 2335.24 USD") -> SimpleNamespace:
    """Der Auftrag vom 2026-08-31: abgelehnt, von ib_insync als storniert."""
    return SimpleNamespace(
        order=SimpleNamespace(orderId=3, orderType="LMT"),
        orderStatus=SimpleNamespace(status="Cancelled", filled=0.0, avgFillPrice=0.0),
        log=[
            SimpleNamespace(status="PreSubmitted", errorCode=0, message=""),
            SimpleNamespace(status="Cancelled", errorCode=201, message=text),
        ],
        fills=[],
    )


def test_a_rejected_limit_is_not_reported_as_limit_not_reached() -> None:
    """Beide alten Zweige waren falsch, und zwar unterschiedlich falsch.

    Der Auftrag ist eine Limit-Order und war laut Protokoll am Markt
    (`PreSubmitted`) — die alte Heuristik lieferte deshalb
    `limit_not_reached`. Das Limit hatte aber nie eine Chance: IBKR hat den
    Auftrag wegen fehlender Deckung gar nicht erst angenommen.
    """
    assert m._derive_reason_code("cancelled", 0.0, "LMT", _rejected_trade()) == (
        "rejected_by_broker"
    )


def test_a_rejection_outranks_a_phantom_cancel() -> None:
    trade = _rejected_trade()
    assert m.rejection_outranks_cancel(trade, "cancelled") == "rejected"


def test_a_filled_order_is_never_reinterpreted_as_a_rejection() -> None:
    """Eine Ausfuehrung ist am Konto passiert und bleibt es.

    Kein Protokolleintrag darf sie nachtraeglich zu einer Ablehnung machen.
    """
    trade = _rejected_trade()
    trade.orderStatus.filled = 10.0
    assert m.rejection_outranks_cancel(trade, "cancelled") == "cancelled"


def test_a_genuine_cancel_stays_a_cancel() -> None:
    """Der Riegel greift nur bei einer belegten Ablehnung."""
    trade = make_trade("Cancelled", error_code=202, history=["Submitted"])
    assert m.rejection_outranks_cancel(trade, "cancelled") == "cancelled"


def test_the_rejection_reaches_the_platform_with_its_words() -> None:
    """Der ganze Weg: was IBKR gesagt hat, steht in der Meldung.

    Am 2026-08-31 war `error_message` leer, und damit fehlte die einzige
    handlungsrelevante Auskunft — dass der Saldo nicht reichte.
    """
    api = FakeApi()
    m._report_status(api, "disp-1", _rejected_trade(), "cancelled")

    assert api.statuses == ["rejected"]
    meldung = api.calls[0]
    assert meldung["reason_code"] == "rejected_by_broker"
    assert "2335.24" in (meldung["error_message"] or "")
    # Eine Ablehnung ist ein belegtes Ende — nichts ist hinausgegangen.
    assert meldung["broker_confirmed_end"] is True


def test_a_rejection_may_correct_an_already_reported_cancel() -> None:
    """Ohne diesen Rang kaeme die Reparatur nie an.

    `cancelled` und `rejected` standen beide auf Rang 1, und `should_report`
    verwirft alles, was nicht ECHT hoeher steht. Am 2026-08-31 hatte der
    Abgleichslauf `cancelled` bereits gemeldet — eine spaetere, richtige
    Meldung waere an dieser Stelle verworfen worden.
    """
    assert m.should_report("disp-1", "cancelled") is True
    assert m.should_report("disp-1", "rejected") is True


def test_a_cancel_may_not_overwrite_a_reported_rejection() -> None:
    """Die Gegenrichtung bleibt gesperrt — sonst ginge Information verloren."""
    assert m.should_report("disp-1", "rejected") is True
    assert m.should_report("disp-1", "cancelled") is False


def test_a_fill_still_outranks_a_rejection() -> None:
    """Die Rangfolge nach oben bleibt unangetastet."""
    assert m.should_report("disp-1", "rejected") is True
    assert m.should_report("disp-1", "filled") is True


# ── Der Riegel im Abholpfad ──────────────────────────────────────────────────


def test_a_dispatch_with_a_cancel_request_is_not_submitted(tmp_path) -> None:
    """Der zweite von zwei Riegeln — der erste sitzt serverseitig.

    Ohne ihn ginge der Auftrag raus und die Bridge protokollierte im selben
    Durchlauf, dass er storniert werden solle.
    """
    gesendet: list[str] = []

    class FakeIbkr:
        def get_live_equity(self) -> float:
            return 100_000.0

        def place_order(self, contract, order):  # pragma: no cover - darf nie laufen
            gesendet.append("!")
            raise AssertionError("Ein Auftrag mit Storno-Wunsch wurde abgesendet.")

    class Api:
        def get_pending(self):
            return SimpleNamespace(
                server_time="",
                pending=[
                    SimpleNamespace(
                        dispatch_id="disp-1",
                        order_intent={"symbol": "WDAY", "side": "buy", "qty": 2,
                                      "orderType": "day_limit", "lmtPrice": 166.38},
                        expires_at=None,
                        cancel_requested=True,
                    )
                ],
                cancelling=[],
            )

    m._handle_pending(Api(), FakeIbkr(), {}, m.SubmittedStore(tmp_path))
    assert gesendet == []


# ── T1-98 / BUG-98-1: der Rang von `unknown` ────────────────────────────────
#
# Der Abgleich meldet einen verschollenen Auftrag als `unknown`. Ohne Eintrag
# in der Rangfolge fiel dieser Wert aus ihr heraus, und `should_report` liess
# ihn jeden bereits gemeldeten Endzustand ueberschreiben — eine bestaetigte
# Stornierung waere durch ein "wir wissen es nicht" ersetzt worden.


def test_unknown_darf_keinen_belegten_endzustand_ueberschreiben() -> None:
    from ordertune_bridge_ibkr.main import _LAST_REPORTED, should_report

    _LAST_REPORTED.clear()
    assert should_report("d-rank-1", "cancelled") is True
    assert should_report("d-rank-1", "unknown") is False


def test_unknown_darf_eine_fuellung_nicht_ueberschreiben() -> None:
    from ordertune_bridge_ibkr.main import _LAST_REPORTED, should_report

    _LAST_REPORTED.clear()
    assert should_report("d-rank-2", "filled") is True
    assert should_report("d-rank-2", "unknown") is False


def test_eine_fuellung_darf_unknown_sehr_wohl_ueberschreiben() -> None:
    """Sie ist am Konto passiert und laesst sich nicht widerrufen."""
    from ordertune_bridge_ibkr.main import _LAST_REPORTED, should_report

    _LAST_REPORTED.clear()
    assert should_report("d-rank-3", "unknown") is True
    assert should_report("d-rank-3", "filled") is True


def test_unknown_wird_nicht_zweimal_gemeldet() -> None:
    from ordertune_bridge_ibkr.main import _LAST_REPORTED, should_report

    _LAST_REPORTED.clear()
    assert should_report("d-rank-4", "unknown") is True
    assert should_report("d-rank-4", "unknown") is False
