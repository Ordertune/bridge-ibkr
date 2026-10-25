"""Das Tray-Symbol: woran man sieht, dass die fensterlose Bridge noch laeuft.

Ein Test-User schickte einen Screenshot von `tws_api_refused`. Die naheliegende
Lesart: Browserfenster zu, Bridge fuer beendet gehalten, erneut gestartet —
und der zweite Start kollidierte auf der Client-ID.

Geprueft wird hier alles, was ohne Windows pruefbar ist: welcher Punkt und
welcher Text zu welchem Zustand gehoert, wann der Hinweis „laeuft weiter"
kommt, dass die eingebetteten Bilder gueltige Symbole sind und dass der
Server die offenen Fenster zaehlt. Auf einem Windows-Laeufer steht das Symbol
zusaetzlich einmal wirklich.
"""
from __future__ import annotations

import sys
import time
import urllib.request
from pathlib import Path

import pytest

from ordertune_bridge_ibkr import failures
from ordertune_bridge_ibkr.cockpit import CockpitServer, CockpitState, StateStore, tray

WURZEL = Path(__file__).resolve().parent.parent


def _state(**kw) -> CockpitState:
    basis = {"tws_connected": True, "ordertune_ok": True}
    basis.update(kw)
    return CockpitState(**basis)


# ── A — der Punkt sagt dasselbe wie das Fenster ──────────────────────────────


def test_a_healthy_bridge_is_green() -> None:
    assert tray.status_of(_state()) == tray.RUNNING


@pytest.mark.parametrize(
    "kw",
    [
        {"tws_connected": False},
        {"ordertune_ok": False},
        {"failure_code": "access_revoked"},
    ],
)
def test_anything_missing_is_attention(kw) -> None:
    assert tray.status_of(_state(**kw)) == tray.ATTENTION


def test_stopping_wins_over_everything() -> None:
    assert tray.status_of(_state(stopping=True, tws_connected=False)) == tray.STOPPING


def test_the_tooltip_names_the_state_and_the_account() -> None:
    tip = tray.tooltip_of(_state(account_masked="U12***34"))
    assert tip.startswith("Ordertune Bridge: running")
    assert "U12***34" in tip


def test_the_tooltip_says_what_is_missing() -> None:
    assert "no connection to TWS" in tray.tooltip_of(_state(tws_connected=False))
    assert "Ordertune not reachable" in tray.tooltip_of(_state(ordertune_ok=False))


def test_the_tooltip_fits_into_what_windows_shows() -> None:
    tip = tray.tooltip_of(_state(failure_headline="x" * 300, failure_code="y"))
    assert len(tip) <= tray.TIP_MAX


# ── B — der Hinweis kommt einmal, und nur nach einem echten Schliessen ───────


def test_the_notice_comes_after_the_last_window_closed() -> None:
    n = tray.ClosedWindowNotice(grace_s=5)
    assert not n.due(1, False, 0)
    assert not n.due(0, False, 1)
    assert not n.due(0, False, 5.9)
    assert n.due(0, False, 6.0)


def test_a_reload_is_not_a_close() -> None:
    n = tray.ClosedWindowNotice(grace_s=5)
    n.due(1, False, 0)
    n.due(0, False, 1)
    assert not n.due(1, False, 2), "Das Fenster ist wieder da."
    assert not n.due(0, False, 3)
    assert not n.due(0, False, 7.9)
    assert n.due(0, False, 8.0)


def test_it_comes_only_once() -> None:
    n = tray.ClosedWindowNotice(grace_s=0)
    n.due(1, False, 0)
    n.due(0, False, 1)
    assert n.due(0, False, 2)
    n.due(1, False, 3)
    n.due(0, False, 4)
    assert not n.due(0, False, 10)


def test_no_notice_without_a_window_ever_opened() -> None:
    """Ohne Browser ging nie ein Fenster auf — dann wurde auch keins geschlossen."""
    n = tray.ClosedWindowNotice(grace_s=0)
    assert not n.due(0, False, 0)
    assert not n.due(0, False, 100)


def test_no_notice_while_the_bridge_is_stopping() -> None:
    n = tray.ClosedWindowNotice(grace_s=0)
    n.due(1, False, 0)
    assert not n.due(0, True, 1)
    assert not n.due(0, True, 100)


# ── C — die eingebetteten Bilder sind Symbole ────────────────────────────────


@pytest.mark.parametrize("status", [tray.RUNNING, tray.ATTENTION, tray.STOPPING])
def test_every_state_has_a_valid_icon(status) -> None:
    data = tray.icon_bytes(status)
    assert data[:4] == b"\0\0\1\0", "Kein ICO-Kopf."
    frames = tray.ico_frames(data)
    assert [size for size, _ in frames] == [16, 20, 24, 32, 40, 48]
    for size, payload in frames:
        # DIB, nicht PNG: PNG-Rahmen bleiben in RDP-Sitzungen leer.
        assert int.from_bytes(payload[0:4], "little") == 40
        assert int.from_bytes(payload[4:8], "little", signed=True) == size
        assert int.from_bytes(payload[8:12], "little", signed=True) == 2 * size
        assert int.from_bytes(payload[14:16], "little") == 32


def test_the_three_states_look_different() -> None:
    bilder = {tray.icon_bytes(s) for s in (tray.RUNNING, tray.ATTENTION, tray.STOPPING)}
    assert len(bilder) == 3


@pytest.mark.parametrize("wanted,expected", [(16, 16), (18, 20), (32, 32), (64, 48)])
def test_the_frame_matches_the_display_scale(wanted, expected) -> None:
    size, _ = tray.pick_frame(tray.icon_bytes(tray.RUNNING), wanted)
    assert size == expected


# ── D — der Server zaehlt die offenen Fenster ────────────────────────────────


def test_the_server_counts_open_windows() -> None:
    server = CockpitServer(StateStore(_state()))
    url = server.start()
    try:
        assert server.windows.count() == 0
        base, token = url.split("/?t=")
        antwort = urllib.request.urlopen(f"{base}/events?t={token}", timeout=5)
        frist = time.monotonic() + 5
        while server.windows.count() == 0 and time.monotonic() < frist:
            time.sleep(0.05)
        assert server.windows.count() == 1
        antwort.close()
        frist = time.monotonic() + 10
        while server.windows.count() > 0 and time.monotonic() < frist:
            time.sleep(0.05)
        assert server.windows.count() == 0
    finally:
        server.stop()


def test_stopping_the_server_takes_the_tray_with_it() -> None:
    class _Tray:
        stopped = False

        def stop(self) -> None:
            self.stopped = True

    server = CockpitServer(StateStore(_state()))
    server.start()
    t = _Tray()
    server.tray = t
    server.stop()
    assert t.stopped
    assert server.tray is None


# ── E — die Verdrahtung ──────────────────────────────────────────────────────


def test_the_tray_uses_the_same_stop_as_the_button() -> None:
    """Eine Fahne, zwei Ausloeser — kein zweiter Weg zum Beenden (T1-223)."""
    quelle = (WURZEL / "src/ordertune_bridge_ibkr/main.py").read_text("utf-8")
    block = quelle[quelle.index("tray_mod.start_tray(") :][:400]
    assert "on_stop=_halten" in block


def test_there_is_no_tray_outside_windows(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    assert tray.start_tray(
        read_state=lambda: _state(), open_window=lambda: None, on_stop=lambda: None
    ) is None


def test_the_double_start_message_points_at_the_icon(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    text = failures.render(failures.bridge_laeuft_bereits("http://127.0.0.1:1/"))
    assert "notification area" in text
    text.encode("ascii")


def test_without_a_tray_the_message_does_not_promise_one(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    text = failures.render(failures.bridge_laeuft_bereits("http://127.0.0.1:1/"))
    assert "notification area" not in text


# ── F — auf Windows steht es wirklich ────────────────────────────────────────


@pytest.mark.skipif(sys.platform != "win32", reason="Tray-Symbol gibt es nur auf Windows")
def test_the_icons_load_on_windows() -> None:
    api = tray._win32()
    for status in (tray.RUNNING, tray.ATTENTION, tray.STOPPING):
        hicon = tray.make_hicon(api, status)
        assert hicon
        api.user32.DestroyIcon(hicon)


@pytest.mark.skipif(sys.platform != "win32", reason="Tray-Symbol gibt es nur auf Windows")
def test_the_tray_starts_and_stops_on_windows() -> None:
    """Auf dem CI-Laeufer gibt es nicht immer einen Explorer; ob das Symbol
    SICHTBAR wird, ist dort offen. Pruefbar ist: Fenster, Schleife und Abbau
    laufen durch, und nichts haengt."""
    gestoppt = []
    t = tray.TrayIcon(
        read_state=lambda: _state(),
        open_window=lambda: None,
        on_stop=lambda: gestoppt.append(True),
    )
    t.start(timeout=5)
    assert t._thread is not None and t._thread.is_alive()
    t.stop(timeout=5)
    assert not t._thread.is_alive()
    assert not t.visible
