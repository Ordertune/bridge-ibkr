"""T1-206 — `bridge.env` liegt neben dem Programm.

Der Befund, den das festnagelt: `main` loeste die Datei als
`Path("bridge.env").resolve()` auf, also gegen das **Arbeitsverzeichnis** —
waehrend der Kopf von `paths.py` seit T1-176 B behauptet, sie liege „neben der
EXE". Beides stimmte auf Windows zufaellig ueberein, weil ein Doppelklick das
Arbeitsverzeichnis auf den Ordner der EXE setzt.

Auf einem Linux-Desktop faellt es auseinander, und zwar auf die teure Art: die
Kopplung meldet Erfolg, die Datei landet irgendwo, und der naechste Start sagt
`env_missing`.
"""
from __future__ import annotations

from pathlib import Path

from ordertune_bridge_ibkr import paths


def _gepackt(monkeypatch, programmordner: Path) -> None:
    """Tut so, als liefe die gepackte Anwendung aus `programmordner`."""
    monkeypatch.setattr(paths, "is_frozen", lambda: True)
    monkeypatch.setattr(paths, "exe_dir", lambda: programmordner)


def test_the_file_is_looked_for_next_to_the_program(monkeypatch, tmp_path):
    """Die Zusage, die das Modul immer schon gemacht hat."""
    programm = tmp_path / "programm"
    programm.mkdir()
    (programm / "bridge.env").write_text("ORDERTUNE_BRIDGE_TOKEN=a\n", encoding="utf-8")

    woanders = tmp_path / "woanders"
    woanders.mkdir()
    monkeypatch.chdir(woanders)
    _gepackt(monkeypatch, programm)

    assert paths.env_file() == programm / "bridge.env"


def test_a_file_in_the_working_directory_still_counts(monkeypatch, tmp_path):
    """Ruecksicht auf den Bestand, nicht Zoegern.

    Wer die Bridge ueber eine geplante Aufgabe mit gesetztem „Ausfuehren in"
    startet und die Datei dort abgelegt hat, laeuft weiter. Ohne diesen
    Rueckfall haette dieselbe Aenderung, die einen Fehler behebt, bei ihm einen
    erzeugt.
    """
    programm = tmp_path / "programm"
    programm.mkdir()

    arbeit = tmp_path / "arbeit"
    arbeit.mkdir()
    (arbeit / "bridge.env").write_text("ORDERTUNE_BRIDGE_TOKEN=a\n", encoding="utf-8")

    monkeypatch.chdir(arbeit)
    _gepackt(monkeypatch, programm)

    assert paths.env_file() == (arbeit / "bridge.env").resolve()


def test_next_to_the_program_wins_over_the_working_directory(monkeypatch, tmp_path):
    """Liegen beide da, gilt die Zusage — nicht der Zufall des Aufrufs.

    Zwei Dateien mit verschiedenen Token sind ein Zustand, den es gibt: einmal
    von Hand abgelegt, einmal von einer Kopplung geschrieben. Welche gilt, darf
    nicht davon abhaengen, aus welchem Verzeichnis jemand gestartet hat.
    """
    programm = tmp_path / "programm"
    programm.mkdir()
    (programm / "bridge.env").write_text("ORDERTUNE_BRIDGE_TOKEN=neben\n", encoding="utf-8")

    arbeit = tmp_path / "arbeit"
    arbeit.mkdir()
    (arbeit / "bridge.env").write_text("ORDERTUNE_BRIDGE_TOKEN=arbeit\n", encoding="utf-8")

    monkeypatch.chdir(arbeit)
    _gepackt(monkeypatch, programm)

    assert paths.env_file() == programm / "bridge.env"


def test_with_no_file_anywhere_it_names_the_place_it_should_be(monkeypatch, tmp_path):
    """Gibt es keine, zeigt der Pfad dorthin, wo sie hingehoert.

    Das entscheidet zweierlei: wohin eine Kopplung schreibt, und welchen Ort
    die Fehlermeldung nennt. Beides darf nicht das Arbeitsverzeichnis sein —
    sonst verewigt der Rueckfall genau den Fehler, den er abfedern soll.
    """
    programm = tmp_path / "programm"
    programm.mkdir()
    arbeit = tmp_path / "arbeit"
    arbeit.mkdir()

    monkeypatch.chdir(arbeit)
    _gepackt(monkeypatch, programm)

    assert paths.env_file() == programm / "bridge.env"


def test_out_of_the_source_tree_nothing_changes(monkeypatch, tmp_path):
    """In der Entwicklung bleibt es das Arbeitsverzeichnis.

    `exe_dir()` gibt dort die CWD zurueck, also faellt beides ohnehin
    zusammen — die Zusicherungen und Handlaeufe sollen sich nicht aendern.
    """
    monkeypatch.setattr(paths, "is_frozen", lambda: False)
    monkeypatch.chdir(tmp_path)
    assert paths.env_file() == tmp_path / "bridge.env"


def test_main_no_longer_resolves_against_the_working_directory():
    """Der Riegel gegen den Rueckfall.

    `Path(ENV_FILE).resolve()` ist genau die Form, die den Befund erzeugt hat.
    Sie darf in `main` nicht wieder auftauchen.
    """
    quelle = (
        Path(__file__).resolve().parent.parent
        / "src" / "ordertune_bridge_ibkr" / "main.py"
    ).read_text(encoding="utf-8")

    assert "Path(ENV_FILE).resolve()" not in quelle, (
        "main loest `bridge.env` wieder gegen das Arbeitsverzeichnis auf."
    )
    assert "paths.env_file()" in quelle
