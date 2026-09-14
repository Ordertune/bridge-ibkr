"""T1-176 B — die Zustandsdateien haengen nicht mehr am Arbeitsverzeichnis.

Der Fall, den das festnagelt: `SubmittedStore` schrieb nach `Path("run")`, also
relativ zum Arbeitsverzeichnis. Ein Start von anderswo — geplante Aufgabe,
Verknuepfung mit gesetztem „Ausfuehren in", Konsole an anderer Stelle — fand
deshalb einen leeren Riegel gegen den Doppelauftrag. Ohne dass jemand etwas
geloescht hat.
"""
from __future__ import annotations

import pytest

from ordertune_bridge_ibkr import paths
from ordertune_bridge_ibkr.submitted_store import SubmittedStore


@pytest.fixture()
def gepackt(monkeypatch, tmp_path):
    """Tut so, als liefe die gepackte EXE, mit Profil unter `tmp_path`."""
    monkeypatch.setattr(paths, "is_frozen", lambda: True)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))
    monkeypatch.setattr(paths.Path, "home", staticmethod(lambda: tmp_path / "home"))
    return tmp_path


# ── Wo abgelegt wird ─────────────────────────────────────────────────────────


def test_out_of_the_source_tree_nothing_changes(monkeypatch, tmp_path) -> None:
    """Die Entwicklung schreibt weiter ins Arbeitsverzeichnis.

    Sonst legten Zusicherungen und Handlaeufe Dateien im Nutzerprofil ab —
    ein Nebeneffekt, den niemand bestellt hat.
    """
    monkeypatch.setattr(paths, "is_frozen", lambda: False)
    monkeypatch.chdir(tmp_path)
    assert paths.data_root() == tmp_path
    assert paths.run_dir() == tmp_path / "run"


def test_the_packed_exe_writes_to_the_profile(gepackt, monkeypatch) -> None:
    monkeypatch.setattr(paths.sys, "platform", "win32")
    assert "Ordertune" in str(paths.data_root())
    assert paths.run_dir().name == "run"
    assert paths.log_dir().name == "logs"


def test_the_place_does_not_move_with_the_working_directory(
    gepackt, monkeypatch, tmp_path
) -> None:
    """**Der Kern dieses Specs.**

    Zweimal gestartet, zweimal aus einem anderen Verzeichnis, zweimal derselbe
    Ort. Waere das nicht so, waere der Riegel gegen den Doppelauftrag beim
    zweiten Start leer — und genau dann am teuersten.
    """
    monkeypatch.setattr(paths.sys, "platform", "win32")

    erster = tmp_path / "irgendwo"
    zweiter = tmp_path / "ganz" / "woanders"
    erster.mkdir(parents=True)
    zweiter.mkdir(parents=True)

    monkeypatch.chdir(erster)
    a = paths.run_dir()
    monkeypatch.chdir(zweiter)
    b = paths.run_dir()

    assert a == b


def test_the_guard_file_follows_the_new_place(gepackt, monkeypatch) -> None:
    monkeypatch.setattr(paths.sys, "platform", "win32")
    store = SubmittedStore()
    store.vermerken("dispatch-1")

    assert SubmittedStore().bereits_abgeschickt("dispatch-1")
    assert (paths.run_dir() / "submitted-dispatches.json").exists()


def test_an_explicit_place_still_wins(tmp_path) -> None:
    """Die Zusicherungen geben ihren Pfad selbst mit — das muss so bleiben."""
    store = SubmittedStore(tmp_path)
    store.vermerken("a")
    assert (tmp_path / "submitted-dispatches.json").exists()


# ── Der Umzug ────────────────────────────────────────────────────────────────


def test_the_old_place_is_carried_over_once(gepackt, monkeypatch, tmp_path) -> None:
    """Ohne diesen Schritt verloere die erste Aktualisierung den Riegel."""
    monkeypatch.setattr(paths.sys, "platform", "win32")
    alt = tmp_path / "alt"
    alt.mkdir()
    monkeypatch.chdir(alt)
    monkeypatch.setattr(paths, "exe_dir", lambda: alt)

    (alt / "run").mkdir()
    (alt / "run" / "submitted-dispatches.json").write_text("{}", encoding="utf-8")

    meldungen = paths.migrate_legacy()

    assert any(stufe == "info" for stufe, _ in meldungen)
    assert (paths.run_dir() / "submitted-dispatches.json").exists()
    assert not (alt / "run").exists()


def test_two_populated_places_are_never_merged(
    gepackt, monkeypatch, tmp_path
) -> None:
    """Zaghaft mit Absicht.

    Ein Riegel gegen Doppelauftraege ist nichts, was ein Aufraeumvorgang
    stillschweigend zusammenwerfen darf. Es bleibt beides liegen, und es steht
    eine Warnung da.
    """
    monkeypatch.setattr(paths.sys, "platform", "win32")
    alt = tmp_path / "alt"
    alt.mkdir()
    monkeypatch.chdir(alt)
    monkeypatch.setattr(paths, "exe_dir", lambda: alt)

    (alt / "run").mkdir()
    (alt / "run" / "submitted-dispatches.json").write_text("alt", encoding="utf-8")
    paths.run_dir().mkdir(parents=True)
    (paths.run_dir() / "submitted-dispatches.json").write_text("neu", encoding="utf-8")

    meldungen = paths.migrate_legacy()

    assert any(stufe == "warning" for stufe, _ in meldungen)
    assert (alt / "run" / "submitted-dispatches.json").read_text(encoding="utf-8") == "alt"
    assert (
        paths.run_dir() / "submitted-dispatches.json"
    ).read_text(encoding="utf-8") == "neu"


def test_nothing_moves_out_of_the_source_tree(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(paths, "is_frozen", lambda: False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "run").mkdir()
    (tmp_path / "run" / "submitted-dispatches.json").write_text("{}", encoding="utf-8")

    assert paths.migrate_legacy() == []
    assert (tmp_path / "run" / "submitted-dispatches.json").exists()


# ── Der Satz daneben ─────────────────────────────────────────────────────────


def test_a_readme_explains_what_must_not_be_deleted(tmp_path) -> None:
    paths.ensure_readme(ziel=tmp_path)
    text = (tmp_path / paths.README_NAME).read_text(encoding="utf-8")
    assert "do not delete" in text.lower()
    assert "bridge.env" in text


def test_the_readme_is_not_rewritten(tmp_path) -> None:
    datei = tmp_path / paths.README_NAME
    datei.write_text("vom Nutzer angefasst", encoding="utf-8")
    paths.ensure_readme(ziel=tmp_path)
    assert datei.read_text(encoding="utf-8") == "vom Nutzer angefasst"
