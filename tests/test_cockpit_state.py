"""T1-101 B-1 — der Zustandsblock und die vier Beruehrpunkte im Kern.

Der wichtigste Satz hier ist ein negativer: **das Cockpit ist Beiwerk, die
Schleife ist es nicht.** Ein Fehler in der Anzeige darf nie einen Heartbeat
kosten — und der Heartbeat ist das Einzige, woran die Plattform erkennt, dass
diese Bridge lebt.
"""
from __future__ import annotations

from types import SimpleNamespace

from ordertune_bridge_ibkr import main as m
from ordertune_bridge_ibkr.cockpit import CockpitState, StateStore
from ordertune_bridge_ibkr.write_access import WriteAccess


def _snap(positions=None, cash=100.0, equity=200.0, currency="USD"):
    return SimpleNamespace(
        cash=cash, equity=equity, currency=currency, positions=positions
    )


# ── Der Block ────────────────────────────────────────────────────────────────


def test_an_update_produces_a_new_snapshot_and_counts_up() -> None:
    store = StateStore(CockpitState(bridge_version="0.1.0"))
    vorher, v0 = store.get()

    store.update(bridge_version="0.2.0")
    nachher, v1 = store.get()

    assert vorher.bridge_version == "0.1.0", (
        "Die alte Aufnahme wurde veraendert. Sie muss unveraenderlich sein, "
        "sonst sieht ein Leser einen halb gepflegten Zustand."
    )
    assert nachher.bridge_version == "0.2.0"
    assert v1 == v0 + 1


def test_the_wire_form_keeps_none_apart_from_empty() -> None:
    """T1-99 woertlich, auch auf der Flaeche."""
    assert StateStore().get()[0].to_wire()["positions"] is None
    leer = CockpitState(positions=[]).to_wire()
    assert leer["positions"] == []


# ── Die Beruehrpunkte ────────────────────────────────────────────────────────


def test_nothing_happens_without_a_cockpit() -> None:
    """Unter `--headless` gibt es keins — und dann darf nichts davon werfen."""
    m.report_heartbeat(None, True, _snap())
    m.report_poll(None)
    m.stop_cockpit(None, 17)


def test_headless_starts_no_cockpit() -> None:
    assert (
        m.start_cockpit(
            ["--headless"],
            config=SimpleNamespace(
                ibkr_client_id=17,
                ibkr_gateway_host="127.0.0.1",
                ibkr_gateway_port=7497,
                ordertune_api_base="https://t1.ordertune.com",
            ),
            version="0.8.0",
            fingerprint="a" * 64,
            log_file=None,
            session_connected_at=__import__("datetime").datetime.now(),
            write_access=WriteAccess(),
        )
        is None
    )


def test_a_heartbeat_lands_in_the_state() -> None:
    store = StateStore()
    cockpit = SimpleNamespace(store=store)

    m.report_heartbeat(cockpit, True, _snap(positions=[{"symbol": "MU"}]))

    state, _ = store.get()
    assert state.tws_connected is True
    assert state.ordertune_ok is True
    assert state.account_known is True
    assert state.cash == 100.0
    assert state.positions == [{"symbol": "MU"}]
    assert state.last_heartbeat_at is not None


def test_an_unknown_portfolio_is_not_an_empty_one() -> None:
    """Der Fall, der am 2026-08-18 zwei echte Positionen gekostet hat."""
    store = StateStore()
    cockpit = SimpleNamespace(store=store)

    m.report_heartbeat(cockpit, True, _snap(positions=None))

    state, _ = store.get()
    assert state.positions is None
    assert state.account_known is False, (
        "Ohne Depotauskunft darf die Flaeche keine leere Tabelle zeigen — das "
        "ist dieselbe Verwechslung wie in T1-99, nur eine Ebene weiter oben."
    )


def test_a_failed_heartbeat_marks_the_platform_as_silent() -> None:
    store = StateStore(CockpitState(ordertune_ok=True))
    cockpit = SimpleNamespace(store=store)

    m.report_heartbeat(cockpit, True, None)

    assert store.get()[0].ordertune_ok is False


def test_a_broken_cockpit_never_reaches_the_loop() -> None:
    """Der tragende negative Satz: die Anzeige darf den Handel nicht kosten."""

    class Kaputt:
        @property
        def store(self):
            raise RuntimeError("das Cockpit ist hin")

    m.report_heartbeat(Kaputt(), True, _snap())  # darf nicht werfen
    m.report_poll(Kaputt())
    m.stop_cockpit(Kaputt(), 17)


def test_a_poll_only_touches_its_own_timestamp() -> None:
    store = StateStore(CockpitState(last_heartbeat_at="2026-08-19T07:00:00+00:00"))
    cockpit = SimpleNamespace(store=store)

    m.report_poll(cockpit)

    state, _ = store.get()
    assert state.last_pending_poll_at is not None
    assert state.last_heartbeat_at == "2026-08-19T07:00:00+00:00"
