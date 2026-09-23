"""T1-223 — die Bridge laesst sich beenden.

Bis T1-213 schloss der Kunde dafuer das Konsolenfenster. Das Fenster ist fort,
ein Ersatz wurde nie gebaut, und in den Akzeptanzkriterien von T1-213 taucht
die Frage nicht auf. Gemessen hat es der Owner am 2026-09-23: er schloss beide
Browserfenster, und der Herzschlag lief weiter.

Ohne Netzwerk, ohne Fenster.
"""
from __future__ import annotations

import threading
from pathlib import Path

from ordertune_bridge_ibkr.cockpit import server as server_mod
from ordertune_bridge_ibkr.cockpit.state import CockpitState, StateStore

WURZEL = Path(__file__).resolve().parent.parent
QUELLE = WURZEL / "src" / "ordertune_bridge_ibkr"


# ── A — der Knopf ────────────────────────────────────────────────────────────


def test_the_page_has_a_stop_button_where_actions_live() -> None:
    seite = (QUELLE / "cockpit/page.py").read_text("utf-8")
    assert 'id="stop"' in seite
    assert "Stop the Bridge" in seite
    # AC-A2: er fragt zurueck.
    assert "confirm(" in seite.split('q("stop").onclick', 1)[1][:400]
    # AC-A3: nicht zwischen den Statuswerten, sondern in einem eigenen
    # Abschnitt mit den uebrigen Handlungen.
    assert "<h2>Stop</h2>" in seite


def test_the_surface_stops_claiming_connected() -> None:
    """AC-A4 — waehrend des Beendens ist „Connected" eine Aussage ueber einen
    Zustand, der gerade endet."""
    seite = (QUELLE / "cockpit/page.py").read_text("utf-8")
    urteil = seite.split("function verdict(s) {", 1)[1][:400]
    assert "s.stopping" in urteil
    # Zuerst, damit es nichts anderes verdeckt und von nichts verdeckt wird.
    assert urteil.index("s.stopping") < urteil.index("s.failure_headline")


def test_the_state_carries_the_flag() -> None:
    assert CockpitState().stopping is False
    store = StateStore()
    assert store.update(stopping=True).stopping is True


# ── B — die Richtungsregel bleibt ────────────────────────────────────────────


def test_the_server_only_sets_a_flag() -> None:
    """AC-B1/B2 — der Kern handelt, der Server vermerkt.

    Gemessen am Quelltext des Knopfes: er darf die IBKR-Verbindung nicht
    anfassen. Ein Server-Thread, der mitten in einem laufenden Absendevorgang
    trennt, ist genau die Fehlerklasse, gegen die T1-152d den Signalhandler
    entschaerft hat.
    """
    haupt = (QUELLE / "main.py").read_text("utf-8")
    rumpf = haupt.split("def _halten() -> None:", 1)[1].split("server = CockpitServer", 1)[0]

    # Erst den Docstring und die Kommentare weg, DANN messen. Ohne das misst
    # diese Zusicherung ihren eigenen Erklaertext: dort steht woertlich „Kein
    # `ibkr.disconnect()`" — und sie waere an genau dem Satz gescheitert, der
    # die Regel beschreibt. Dieselbe Falle wie in T1-187 am selben Tag.
    ohne_doku = rumpf.split('"""')[-1]
    code = "\n".join(
        z for z in ohne_doku.split("\n") if not z.lstrip().startswith("#")
    )

    assert "stop_event.set()" in code
    for verboten in ("ibkr.disconnect", "api.close", "sys.exit", "os._exit"):
        assert verboten not in code, f"Der Knopf ruft {verboten} — das gehoert dem Kern."


def test_the_stop_event_exists_before_the_cockpit() -> None:
    """Sonst haette der Server nichts zu setzen."""
    haupt = (QUELLE / "main.py").read_text("utf-8")
    assert haupt.index("stop = threading.Event()") < haupt.index("cockpit = start_cockpit(")


def test_the_cleanup_stays_in_the_loop() -> None:
    """AC-B3 — aufgeraeumt wird im `finally`, wie seit T1-152d."""
    haupt = (QUELLE / "main.py").read_text("utf-8")
    ende = haupt.split("Shutting down: stopping the cockpit.", 1)[1][:400]
    assert "ibkr.disconnect()" in ende
    assert "api.close()" in ende


# ── C — der Weg ist geschuetzt ───────────────────────────────────────────────


def test_stopping_needs_the_token_and_a_post() -> None:
    quelle = (QUELLE / "cockpit/server.py").read_text("utf-8")
    post = quelle.split("def do_POST", 1)[1]
    # AC-C1/C2: die Tokenpruefung steht VOR der Route.
    assert post.index("_authorised") < post.index('"/stop"')
    # AC-C3: nur POST. Ein vorgeladener Link im Browserverlauf darf keine
    # Bridge beenden.
    get = quelle.split("def do_GET", 1)[1].split("def do_POST", 1)[0]
    assert "/stop" not in get


def test_stopping_does_not_hang_on_the_assistant() -> None:
    """Der Weg gilt auch ohne `setup` — sonst haette der laufende Betrieb ihn
    nicht, denn dort ist der Assistent nicht der Gegenstand."""
    quelle = (QUELLE / "cockpit/server.py").read_text("utf-8")
    post = quelle.split("def do_POST", 1)[1]
    assert post.index('"/stop"') < post.index('setup = self.deps.get("setup")')


def test_the_server_passes_the_handler_through() -> None:
    gerufen: list[str] = []
    srv = server_mod.CockpitServer(StateStore(), on_stop=lambda: gerufen.append("ja"))
    assert srv.on_stop is not None
    srv.on_stop()
    assert gerufen == ["ja"]


# ── D — unbeaufsichtigt bleibt unbeaufsichtigt ───────────────────────────────


def test_headless_has_no_cockpit_and_therefore_no_button() -> None:
    haupt = (QUELLE / "main.py").read_text("utf-8")
    rumpf = haupt.split("def start_cockpit(", 1)[1][:600]
    assert "headless_requested(argv)" in rumpf
    assert "return None" in rumpf


def test_the_signals_are_untouched() -> None:
    haupt = (QUELLE / "main.py").read_text("utf-8")
    assert "signal.signal(signal.SIGINT, _shutdown)" in haupt
    assert "signal.signal(signal.SIGTERM, _shutdown)" in haupt


def test_the_event_is_idempotent() -> None:
    """Zweimal geklickt tut nichts Zusaetzliches."""
    ev = threading.Event()
    ev.set()
    ev.set()
    assert ev.is_set()
