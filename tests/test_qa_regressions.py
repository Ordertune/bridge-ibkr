"""T1-101 — die Befunde der QA vom 2026-08-19, festgenagelt.

Jede Zusicherung hier steht fuer einen Fehler, der im fertigen Code lag und
beim Durchgehen gefunden wurde. Sie sind billig und verhindern genau die
Rueckfaelle, die niemand bemerkt haette.
"""
from __future__ import annotations

import json
import stat
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from ordertune_bridge_ibkr import env_file
from ordertune_bridge_ibkr.cockpit import CockpitServer, StateStore
from ordertune_bridge_ibkr.cockpit import runfile
from ordertune_bridge_ibkr.cockpit.page import PAGE_HTML

ROOT = Path(__file__).resolve().parents[1]


# ── BUG-101-1 (kritisch): die Sicherung traegt denselben Token ───────────────


@pytest.mark.parametrize("name", ["bridge.env", "bridge.env.bak", ".bridge-env-tmp123"])
def test_nothing_carrying_the_token_can_be_committed(name: str) -> None:
    """`bridge.env` war ignoriert, das Danebenliegende nicht.

    Das Cockpit legt beim Speichern `bridge.env.bak` an — mit **demselben**
    Token wie das Original — und das atomare Schreiben eine temporaere Datei.
    Beide fielen durch die Regel. Auf einer Entwicklermaschine, auf der eine
    echte `bridge.env` im Repo-Wurzelverzeichnis liegt, haette ein `git add .`
    einen lebenden Token in ein **oeffentliches** Repo gestellt.
    """
    ergebnis = subprocess.run(
        ["git", "check-ignore", "-q", name], cwd=ROOT, capture_output=True
    )
    assert ergebnis.returncode == 0, (
        f"{name} wird von .gitignore nicht erfasst und landet in `git status`."
    )


# `chmod` setzt auf Windows nur das Schreibschutz-Bit; die Zugriffsgrenze
# liegt dort in den ACLs des Benutzerprofils, nicht in den Modus-Bits. Der
# Riegel ist deshalb POSIX-only — und weil Windows die Zielplattform ist,
# steht das hier ausdruecklich da statt in einer Fussnote.
posix_only = pytest.mark.skipif(
    sys.platform == "win32",
    reason="chmod ist auf Windows wirkungslos; dort schuetzen die ACLs des Profils",
)


@posix_only
def test_the_backup_is_no_more_readable_than_the_original(tmp_path) -> None:
    p = tmp_path / "bridge.env"
    p.write_text("ORDERTUNE_BRIDGE_TOKEN=ot_bridge_geheim\n", encoding="utf-8")
    p.chmod(0o644)

    env_file.write_atomic(p, "ORDERTUNE_BRIDGE_TOKEN=ot_bridge_geheim\nLOG_LEVEL=DEBUG\n")

    sicherung = tmp_path / "bridge.env.bak"
    assert "ot_bridge_geheim" in sicherung.read_text("utf-8")
    assert stat.S_IMODE(sicherung.stat().st_mode) == 0o600, (
        "Die neue Datei wird durch mkstemp auf 0600 verengt — daneben lag eine "
        "fuer alle lesbare Kopie desselben Geheimnisses."
    )


# ── BUG-101-3 (mittel): die Ablagedatei traegt ein Zugangstoken ─────────────


@posix_only
def test_the_run_file_is_owner_only(tmp_path) -> None:
    p = runfile.write(17, "http://127.0.0.1:1/?t=geheim", run_dir=tmp_path)
    assert p is not None
    assert "geheim" in json.loads(p.read_text("utf-8"))["url"]
    assert stat.S_IMODE(p.stat().st_mode) == 0o600, (
        "Wer diese Datei liest, darf danach ueber das Cockpit auch bridge.env "
        "schreiben."
    )


# ── BUG-101-4 (mittel): Nicht-ASCII im Token zerlegte den Bearbeiter ────────


def test_a_non_ascii_token_is_refused_not_a_crash() -> None:
    """`hmac.compare_digest` wirft bei Zeichenketten mit Nicht-ASCII.

    Vorher: `?t=%C3%BC` beendete die Verbindung ohne Antwort und schrieb einen
    Stapelauszug nach `stderr` — vorbei an der Stummschaltung des Servers, in
    genau die Konsole, die Abschnitt A lesbar gemacht hat. Ein lokales Skript
    haette sie damit zumuellen koennen.
    """
    srv = CockpitServer(StateStore())
    srv.start()
    try:
        for pfad in ("/state?t=%C3%BC", "/?t=%E2%82%AC", "/log?t=%C3%A4%C3%B6"):
            try:
                urllib.request.urlopen(  # noqa: S310
                    f"http://127.0.0.1:{srv.port}{pfad}", timeout=5
                )
                pytest.fail(f"{pfad} wurde durchgelassen")
            except urllib.error.HTTPError as exc:
                assert exc.code == 403, f"{pfad} -> {exc.code} statt 403"
    finally:
        srv.stop()


# ── BUG-101-2 (hoch) und BUG-101-5 (gering): die Flaeche ────────────────────


def test_the_panes_are_not_reset_on_every_tick() -> None:
    """`hidden = setup || undefined` ergab ausserhalb des Assistenten `false`.

    Damit standen alle drei Reiter gleichzeitig offen, und jeder Reiterwechsel
    wurde vom naechsten Takt — eine Sekunde spaeter — wieder aufgehoben.
    """
    # Gesucht ist die ZUWEISUNG, nicht die Erwaehnung: der Kommentar im
    # Quelltext nennt den alten Ausdruck absichtlich, damit niemand ihn
    # versehentlich wieder einsetzt.
    assert ".hidden = setup ||" not in PAGE_HTML, (
        "Der Ausdruck ist zurueck. `undefined` als hidden-Wert heisst sichtbar."
    )
    assert 'q("pane-" + n).hidden = true;' in PAGE_HTML, (
        "Im Assistenten muessen die Reiter ausdruecklich zu sein."
    )


def test_a_missing_first_heartbeat_is_not_overdue() -> None:
    """Unmittelbar nach dem Verbinden ist der erste Herzschlag noch unterwegs.

    Ein falsches Rot in den ersten Augenblicken jedes Starts waere genau die
    Sorte Aussage, gegen die dieser Vorgang gebaut wurde.
    """
    assert "if (!s.last_heartbeat_at) return false;" in PAGE_HTML
    assert "waiting for the first one" in PAGE_HTML


# ── Vom ersten Lauf auf dem VPS (2026-08-19, v0.8.0) ────────────────────────


def test_a_dropped_connection_does_not_print_a_traceback(capfd) -> None:
    """Ein geschlossenes Fenster ist kein Fehler.

    Beim ersten Lauf auf dem VPS stand nach dem Schliessen des Cockpits ein
    `ConnectionAbortedError`-Stapelauszug in der Konsole — geschrieben von
    `socketserver` direkt nach `stderr`, an jedem Protokoll vorbei. Genau in
    der Konsole, die Abschnitt A lesbar gemacht hat, und ausgeloest durch eine
    voellig normale Handlung.

    Nachgestellt wird der Fall an seiner Wurzel: `handle_error` ist der Weg,
    ueber den `socketserver` schreibt.
    """
    srv = CockpitServer(StateStore())
    srv.start()
    try:
        capfd.readouterr()
        try:
            raise ConnectionAbortedError(10053, "aborted by the host machine")
        except ConnectionAbortedError:
            srv._httpd.handle_error(None, ("127.0.0.1", 59624))

        ausgabe = capfd.readouterr()
        assert "Traceback" not in ausgabe.err + ausgabe.out, (
            "Der Stapelauszug steht wieder in der Konsole."
        )
        assert "ConnectionAbortedError" not in ausgabe.err + ausgabe.out
    finally:
        srv.stop()
