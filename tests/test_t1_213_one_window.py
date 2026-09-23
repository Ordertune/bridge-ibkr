"""T1-213 — ein Fenster.

Der Kunde sieht nach dem Doppelklick genau ein Fenster: das Cockpit. Die
Konsole ist fort, ihre beiden Aufgaben haben Ersatz, und der Owner holt sie
sich mit `--console` zurueck.

Geprueft wird ohne Windows und ohne Fenster — jede Entscheidung dieses Vorgangs
ist eine reine Funktion ueber `argv` und den Zustand, wie `headless_requested`
es seit T1-101 vormacht.
"""
from __future__ import annotations

import sys
from pathlib import Path

from ordertune_bridge_ibkr import console, logging_setup, windows_ui
from ordertune_bridge_ibkr import main as m
from ordertune_bridge_ibkr.failures import Failure

WURZEL = Path(__file__).resolve().parent.parent


# ── A — die EXE wird fensterlos gebaut ───────────────────────────────────────


def test_the_build_is_windowed() -> None:
    """`--console` im Bauaufruf waere genau das Fenster, das hier wegfaellt."""
    quelle = (WURZEL / "build.py").read_text("utf-8")
    argumente = quelle.split("cmd = [", 1)[1].split("]", 1)[0]
    assert '"--windowed"' in argumente
    assert '"--console"' not in argumente, (
        "Ein `--console`-Build blitzt beim Doppelklick sichtbar auf. Das ist "
        "kein Fortschritt gegenueber einem Fenster."
    )


def test_the_icon_check_is_untouched() -> None:
    """T1-182 haengt am selben Bauaufruf und muss ihn ueberleben."""
    quelle = (WURZEL / "build.py").read_text("utf-8")
    assert '"--icon"' in quelle and "def verify_icon(" in quelle


# ── B — der Schalter des Owners ──────────────────────────────────────────────


def test_the_console_flag_is_a_pure_decision() -> None:
    assert windows_ui.console_requested(["--console"]) is True
    assert windows_ui.console_requested([]) is False
    assert windows_ui.console_requested(["--headless"]) is False


def test_main_opens_the_console_before_anything_else(monkeypatch) -> None:
    """Die Reihenfolge ist die Zusage.

    `setup_logging` fragt den Ausgabekanal ab. Stuende der Aufruf danach,
    bekaeme der Owner ein schwarzes Fenster ohne eine einzige Zeile darin.
    """
    quelle = (WURZEL / "src/ordertune_bridge_ibkr/main.py").read_text("utf-8")
    rumpf = quelle.split("def main() -> int:", 1)[1]
    vor_konsole = rumpf.index("windows_ui.console_requested")
    assert vor_konsole < rumpf.index("setup_logging("), (
        "Die Konsole muss stehen, bevor irgendetwas hineingeschrieben wird."
    )


# ── C — der Startfehler bleibt lesbar ────────────────────────────────────────


def test_the_message_text_names_the_trouble_and_the_log() -> None:
    text = m._meldungstext(
        Failure(
            code="env_missing",
            headline="bridge.env is missing.",
            detail=("It was expected next to the executable.",),
            action=("Download a fresh one from the Broker tab.",),
        ),
        Path("C:/Users/x/AppData/Local/Ordertune/Bridge/logs/bridge.log"),
    )
    assert "bridge.env is missing." in text
    assert "It was expected next to the executable." in text
    assert "Download a fresh one" in text
    assert "bridge.log" in text


def test_the_message_text_survives_a_missing_log() -> None:
    text = m._meldungstext(Failure(code="x", headline="Kaputt."), None)
    assert text == "Kaputt."


def _dialoge(monkeypatch) -> list[str]:
    """Faengt die Dialoge ab, statt sie zu oeffnen.

    `m.windows_ui` und `windows_ui` sind dasselbe Modulobjekt — ein `setattr`
    genuegt. Es steht hier gebuendelt, damit kein Test aus Versehen das echte
    Fenster ruft; auf einem Windows-Laeufer haelt das den Lauf an.
    """
    gezeigt: list[str] = []
    monkeypatch.setattr(
        windows_ui, "message_box", lambda text, *a, **k: gezeigt.append(text) or True
    )
    monkeypatch.setattr(console, "hold", lambda argv=None: None)
    return gezeigt


def test_the_abort_shows_a_message_box(monkeypatch) -> None:
    """Der Doppelklick-Fall: gepackt, kein `--headless`, also ein Fenster."""
    gezeigt = _dialoge(monkeypatch)
    monkeypatch.setattr(console, "is_frozen", lambda: True)

    code = m._abort(Failure(code="c", headline="Keine Verbindung."), None, [])
    assert code == 1
    assert gezeigt and "Keine Verbindung." in gezeigt[0]


def test_headless_never_gets_a_dialog(monkeypatch) -> None:
    """Ein Dialog, den niemand wegklicken kann, ist ein haengender Vorgang."""
    gezeigt = _dialoge(monkeypatch)
    monkeypatch.setattr(console, "is_frozen", lambda: True)

    m._abort(Failure(code="c", headline="Keine Verbindung."), None, ["--headless"])
    assert gezeigt == []


def test_running_from_source_never_gets_a_dialog(monkeypatch) -> None:
    """Und der Fall, der zwei Release-Laeufe gekostet hat.

    Aus dem Quelltext gestartet — beim Entwickeln, in der Zusicherungssuite, in
    der CI — sitzt eine Konsole davor. Dort ist der gerahmte Block die richtige
    Auskunft; ein modaler Dialog ist keine zusaetzliche Hilfe, sondern ein
    Anhalten.

    Am 2026-09-23 stand der Lauf zweimal im Schritt „Run tests", weil
    `test_launcher_starts_and_reaches_configuration` den Launcher ohne
    `bridge.env` als Unterprozess startet und der Abbruchweg dort auf Windows
    ein Fenster oeffnete.
    """
    gezeigt = _dialoge(monkeypatch)
    monkeypatch.setattr(console, "is_frozen", lambda: False)

    m._abort(Failure(code="c", headline="Keine Verbindung."), None, [])
    assert gezeigt == []
    assert console.dialog_wanted([]) is False
    assert console.dialog_wanted(["--headless"]) is False


def test_the_dialog_falls_back_quietly_without_windows(monkeypatch, capsys) -> None:
    """Der Rueckfallweg — und dieser Test ruft NIE das echte `MessageBoxW`.

    ## Warum das hier ausdruecklich steht

    Die erste Fassung rief `message_box()` ungeschuetzt auf und prueste das
    Ergebnis nur ausserhalb von Windows. Lokal auf macOS lief sie durch. Auf
    dem Windows-Laeufer des Release-Workflows oeffnete sie einen echten
    modalen Dialog — und `MessageBoxW` kehrt erst zurueck, wenn jemand klickt.

    Gemessen am 2026-09-23: der Lauf stand **zehn Minuten** im Schritt „Run
    tests", bis er von Hand abgebrochen wurde. Ein Vorgang, der auf eine
    Eingabe wartet, die nie kommt — also genau die Fehlerklasse, gegen die
    T1-213 gebaut ist, eingeschleppt durch dessen eigene Zusicherung.

    Deshalb wird die Plattformfrage hier **gestellt und beantwortet**, statt
    sie der Wirklichkeit zu ueberlassen: so laeuft derselbe Zweig auf jedem
    System, und keiner oeffnet ein Fenster.
    """
    monkeypatch.setattr(windows_ui, "is_windows", lambda: False)
    assert windows_ui.message_box("etwas", title="T") is False
    assert "etwas" in capsys.readouterr().err


def test_no_assertion_ever_opens_a_real_window() -> None:
    """Die Regel, die den Fall von oben kuenftig faengt.

    Wer in dieser Datei `message_box` oder `allocate_console` wirklich aufruft,
    muss im selben Test vorher festgelegt haben, auf welcher Plattform er sich
    befindet. Sonst oeffnet der Aufruf auf einem Windows-Laeufer ein Fenster,
    und der Lauf steht.

    Eine Zusicherung ueber Zusicherungen — und sie ist billiger als ein zweiter
    Lauf, der zehn Minuten haengt.
    """
    quelle = Path(__file__).read_text("utf-8")
    # Je Testfunktion ein Rumpf. `split` auf die Definitionszeile reicht: die
    # Datei enthaelt keine verschachtelten Testfunktionen.
    for rumpf in quelle.split("\ndef test_")[1:]:
        name = rumpf.split("(", 1)[0]
        ruft = any(
            aufruf in rumpf
            for aufruf in ("windows_ui.message_box(", "windows_ui.allocate_console(")
        )
        if not ruft:
            continue
        assert '"is_windows"' in rumpf, (
            f"`{name}` ruft das echte Fenster, ohne die Plattformfrage zu "
            "klaeren. Auf einem Windows-Laeufer haelt das den Lauf an — genau "
            "so ist der Release-Lauf am 2026-09-23 stehengeblieben."
        )


# ── D — das Protokoll ist die einzige Quelle, die bleibt ─────────────────────


def test_logging_skips_the_screen_when_there_is_none(monkeypatch, tmp_path) -> None:
    gerufen: list[str] = []
    monkeypatch.setattr(
        logging_setup.coloredlogs,
        "install",
        lambda **kw: gerufen.append("ja"),
    )

    monkeypatch.setattr(logging_setup.windows_ui, "has_console_stream", lambda: False)
    logging_setup.setup_logging(log_dir=tmp_path / "a")
    assert gerufen == [], (
        "Ein Handler auf `None` ist kein Handler, sondern eine Fehlerquelle."
    )

    monkeypatch.setattr(logging_setup.windows_ui, "has_console_stream", lambda: True)
    logging_setup.setup_logging(log_dir=tmp_path / "b")
    assert gerufen == ["ja"]


def test_the_log_file_is_written_either_way(tmp_path) -> None:
    pfad = logging_setup.setup_logging(log_dir=tmp_path)
    assert pfad.name == "bridge.log"
    assert pfad.parent == tmp_path.resolve()


def test_a_startup_failure_leaves_a_trace(monkeypatch, tmp_path) -> None:
    """Der Fall, der bis T1-213 gar nichts hinterliess.

    Scheitert die Konfiguration, bricht `main()` ab, BEVOR `setup_logging`
    laeuft. Mit Konsole stand der Block auf dem Bildschirm; ohne Konsole gab es
    weder Zeile noch Datei — bei der haeufigsten Stoerung ueberhaupt.
    """
    monkeypatch.setattr(m.paths, "migrate_legacy", list)
    monkeypatch.setattr(m, "setup_logging", lambda: tmp_path / "bridge.log")

    pfad = m._protokoll_fuer_startfehler(
        Failure(code="env_missing", headline="Weg.", detail=("Zeile eins.",))
    )
    assert pfad == tmp_path / "bridge.log"


def test_a_failing_log_setup_does_not_hide_the_failure(monkeypatch) -> None:
    def explodiert() -> None:
        raise OSError("Platte voll")

    monkeypatch.setattr(m.paths, "migrate_legacy", list)
    monkeypatch.setattr(m, "setup_logging", explodiert)
    assert m._protokoll_fuer_startfehler(Failure(code="x", headline="y")) is None


# ── E — der Nachweis im Release-Workflow ─────────────────────────────────────


def test_the_smoke_test_no_longer_reads_a_stream_that_is_gone() -> None:
    """Die gefaehrlichste Stelle dieses Vorgangs, als Zusicherung.

    Der Schritt prueft seit 0.1.0 die Standardausgabe der gestarteten EXE. Eine
    fensterlos gebaute Anwendung hat keine. Ohne Umbau bestuende der Schritt
    still jeden Lauf — und er ist derjenige, der jeden Startfehler gefunden hat.
    """
    workflow = (WURZEL / ".github/workflows/release.yml").read_text("utf-8")
    schritt = workflow.split("Smoke-test the built EXE", 1)[1].split("- name:", 1)[0]

    assert "--headless" in schritt, (
        "Ohne diese Fahne geht hier ein Cockpit auf, auf das niemand wartet."
    )
    assert "bridge.log" in schritt, "Die Protokolldatei ist die neue Quelle."
    assert "left no log file" in schritt, (
        "Ein Lauf, der nichts hinterlaesst, ist kein bestandener Lauf."
    )
    assert "env_missing" in schritt, "Die stabile Kennung aus T1-101 A-2 bleibt."
    assert "$code -ne 1" in schritt, "Der Ausgangscode bleibt Teil des Urteils."


# ── F — was sich ausdruecklich NICHT aendert ─────────────────────────────────


def test_headless_behaves_exactly_as_before(monkeypatch) -> None:
    monkeypatch.setattr(console, "is_frozen", lambda: True)
    assert console.setup_wanted(["--headless"]) is False
    assert console.should_hold(["--headless"]) is False
    assert (
        m.run_setup_cockpit(
            Failure(code="env_missing", headline="x"),
            Path("bridge.env"),
            ["--headless"],
        )
        is False
    )
