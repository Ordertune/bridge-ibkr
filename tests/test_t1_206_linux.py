"""T1-206 — Linux wird ein unterstuetzter Weg.

Sechs Zusicherungen, und jede haengt an einem Befund aus der Spec, nicht an
einer Meinung:

  * der Fingerprint lieferte auf x86-Linux konstant `"0"`,
  * `TWS_EXPORT_DIR` hatte ausserhalb von Windows keinen Vorschlag, womit die
    Bereitschaftspruefung dort `not_configured` als Voreinstellung gemeldet
    haette,
  * die Kopplung lief ausschliesslich ueber das Cockpit — auf einem Server ohne
    Desktop konnte sich ein Erstnutzer gar nicht koppeln,
  * eine nicht schreibbare Ablage fiel erst beim ersten Auftrag auf,
  * das Release trug kein Linux-Artefakt,
  * und die `.sh` darf kein selbstentpackendes Archiv sein.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ordertune_bridge_ibkr import fingerprint, pair_console, paths, trade_reports

WURZEL = Path(__file__).resolve().parent.parent


# ── D — der Fingerprint bekommt einen echten Maschinenwert ───────────────────


def test_machine_id_wins_over_cpuinfo(monkeypatch, tmp_path) -> None:
    """Die Maschinenkennung schlaegt `/proc/cpuinfo`.

    Der Befund: `/proc/cpuinfo` beginnt auf x86 mit `processor : 0`, und die
    alte Fassung nahm die erste Zeile, die mit `Serial` ODER `processor`
    beginnt. Die mittlere Zutat des Hashs war damit auf JEDER x86-Maschine
    dieselbe.
    """
    kennung = tmp_path / "machine-id"
    kennung.write_text("4f9a2c1b8e7d4a6f9c3b1e5d7a8f2c4b\n", encoding="utf-8")
    monkeypatch.setattr(fingerprint, "_MACHINE_ID_PFADE", (str(kennung),))

    assert fingerprint._read_cpu_id_unix() == "4f9a2c1b8e7d4a6f9c3b1e5d7a8f2c4b"


def test_two_machines_differ_in_the_middle_ingredient(monkeypatch, tmp_path) -> None:
    """Zwei Maschinen, gleicher Hostname und gleiche MAC — und doch verschieden.

    Genau diese Haelfte fiel vorher durch: zwei frisch bestellte Server
    desselben Anbieters unterschieden sich nur ueber Hostname und MAC, und die
    aehneln sich dort manchmal bis zur Ununterscheidbarkeit.
    """
    eins = tmp_path / "eins"
    zwei = tmp_path / "zwei"
    eins.write_text("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", encoding="utf-8")
    zwei.write_text("bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", encoding="utf-8")

    monkeypatch.setattr(fingerprint, "_MACHINE_ID_PFADE", (str(eins),))
    a = fingerprint._read_cpu_id_unix()
    monkeypatch.setattr(fingerprint, "_MACHINE_ID_PFADE", (str(zwei),))
    b = fingerprint._read_cpu_id_unix()

    assert a != b


def test_without_a_machine_id_the_old_way_still_answers(monkeypatch, tmp_path) -> None:
    """Fehlt die Datei, bleibt es beim heutigen Verhalten.

    Auf einem ARM-Board mit `Serial`-Zeile ist der alte Weg die richtige
    Antwort. Ein Abbruch waere hier schlechter: der Hash wuerde dadurch nicht
    falsch, nur schwaecher.
    """
    monkeypatch.setattr(
        fingerprint, "_MACHINE_ID_PFADE", (str(tmp_path / "gibt-es-nicht"),)
    )
    # Faellt durch auf `/proc/cpuinfo`, das es hier geben kann oder nicht.
    # Beide Ausgaenge sind zulaessig — was NICHT passieren darf, ist ein Wurf.
    assert isinstance(fingerprint._read_cpu_id_unix(), str)


def test_the_hash_keeps_its_shape(monkeypatch, tmp_path) -> None:
    """Die Form bleibt, nur der Wert aendert sich.

    Das ist der Grund, warum auf der Plattform nichts angefasst werden muss:
    keine Spalte, kein Vertrag, keine Migration.
    """
    kennung = tmp_path / "machine-id"
    kennung.write_text("cccccccccccccccccccccccccccccccc", encoding="utf-8")
    monkeypatch.setattr(fingerprint, "_MACHINE_ID_PFADE", (str(kennung),))

    wert = fingerprint.compute_fingerprint()
    assert len(wert) == 64
    assert all(c in "0123456789abcdef" for c in wert)


# ── G — das Berichtsverzeichnis bekommt auf Linux einen Vorschlag ────────────


def test_non_windows_gets_a_suggestion(monkeypatch, tmp_path) -> None:
    """Ausserhalb von Windows steht jetzt ein Pfad da, keine leere Zeichenkette.

    Ohne ihn haette die Bereitschaftspruefung auf JEDER frischen
    Linux-Installation `not_configured` gemeldet — also die Warnung, die sagt,
    dass eine Fuellung waehrend einer Auszeit der Bridge nicht nachtragbar ist.
    Der teuerste Zustand des Systems waere die Voreinstellung gewesen.
    """
    monkeypatch.setattr(trade_reports.sys, "platform", "linux")
    monkeypatch.setattr(trade_reports.Path, "home", staticmethod(lambda: tmp_path))

    assert trade_reports.standard_verzeichnis() == str(tmp_path / "IBExport")


def test_windows_is_word_for_word_unchanged(monkeypatch) -> None:
    """Der Windows-Weg bleibt, wie er war. Regressionsnachweis."""
    monkeypatch.setattr(trade_reports.sys, "platform", "win32")
    assert trade_reports.standard_verzeichnis() == r"C:\IBExport"


def test_without_a_home_it_stays_silent(monkeypatch) -> None:
    """Kein aufloesbares Heimverzeichnis — dann lieber schweigen.

    Ein Vorschlag, der nirgendwohin zeigt, ist schlechter als keiner: genau
    das war die Begruendung fuer die leere Zeichenkette, und fuer diesen Fall
    bleibt sie richtig.
    """
    monkeypatch.setattr(trade_reports.sys, "platform", "linux")

    def wirft() -> Path:
        raise RuntimeError("no home")

    monkeypatch.setattr(trade_reports.Path, "home", staticmethod(wirft))
    assert trade_reports.standard_verzeichnis() == ""


# ── B — die Kopplung ohne Fenster ───────────────────────────────────────────


def test_pair_flag_is_read_as_a_pure_function() -> None:
    assert pair_console.pair_requested(["--pair"])
    assert pair_console.pair_requested(["--headless", "--pair"])
    assert not pair_console.pair_requested(["--headless"])
    assert not pair_console.pair_requested([])


def test_pairing_writes_through_the_same_path(monkeypatch, tmp_path) -> None:
    """`--pair` benutzt `write_credentials` — es entsteht kein zweiter Schreibweg.

    Das ist die Zusage aus Entscheidung 2. Zwei Wege, die `bridge.env`
    schreiben, waeren zwei Wege, die auseinanderlaufen koennen.
    """
    env_path = tmp_path / "bridge.env"
    gesehen: dict = {}

    monkeypatch.setattr(pair_console.time, "sleep", lambda _s: None)
    monkeypatch.setattr(
        pair_console.pairing,
        "start",
        lambda _b: {
            "ok": True,
            "code": "ABCD-1234",
            "expires_in": 600,
            "verifier": "geheim",
            "fingerprint_prefix": "abcdef0123456789",
            "hostname": "vps-1",
        },
    )
    monkeypatch.setattr(
        pair_console.pairing,
        "claim",
        lambda _b, _c, _v: {
            "ok": True,
            "status": "ready",
            "token": "ot_bridge_deadbeef",
            "connection_id": "11111111-2222-3333-4444-555555555555",
        },
    )

    def merken(pfad, **kwargs):
        gesehen.update(kwargs)
        gesehen["pfad"] = pfad
        return {"ok": True, "message": "Paired."}

    monkeypatch.setattr(pair_console.pairing, "write_credentials", merken)

    assert pair_console.run_pairing(env_path) == 0
    assert gesehen["pfad"] == env_path
    assert gesehen["token"] == "ot_bridge_deadbeef"
    assert gesehen["connection_id"] == "11111111-2222-3333-4444-555555555555"


def test_an_expired_code_writes_nothing(monkeypatch, tmp_path) -> None:
    """Laeuft die Frist ab, bleibt keine halbe `bridge.env` zurueck.

    Die Uhr wird gestellt, nicht die Frist auf null gesetzt: `expires_in` geht
    durch `... or 600`, und eine 0 ist falsch im Sinne von Python — sie faellt
    auf die Vorgabe zurueck. Das ist als Schutz gegen eine fehlende Angabe
    richtig und taugt deshalb nicht als Hebel fuer diese Zusicherung.
    """
    env_path = tmp_path / "bridge.env"

    # 0.0 setzt die Frist (Schluss = 600), 10.0 laesst einen Durchgang zu,
    # 700.0 ist darueber hinaus.
    zeiten = iter([0.0, 10.0, 700.0])
    monkeypatch.setattr(pair_console.time, "monotonic", lambda: next(zeiten))
    monkeypatch.setattr(pair_console.time, "sleep", lambda _s: None)
    monkeypatch.setattr(
        pair_console.pairing,
        "start",
        lambda _b: {
            "ok": True,
            "code": "ABCD-1234",
            "expires_in": 600,
            "verifier": "geheim",
            "fingerprint_prefix": "abcdef0123456789",
            "hostname": "vps-1",
        },
    )
    # Der Nutzer bestaetigt nie.
    monkeypatch.setattr(
        pair_console.pairing,
        "claim",
        lambda _b, _c, _v: {"ok": True, "status": "pending"},
    )

    def darf_nicht(*_a, **_k):  # pragma: no cover - der Sinn ist, nicht zu laufen
        raise AssertionError("write_credentials was called after the code expired")

    monkeypatch.setattr(pair_console.pairing, "write_credentials", darf_nicht)

    assert pair_console.run_pairing(env_path) == 1
    assert not env_path.exists()


def test_existing_credentials_are_not_replaced_without_a_human(
    monkeypatch, tmp_path
) -> None:
    """Ohne Eingabekanal heisst es nein.

    Ein stilles Ueberschreiben kappte eine laufende Verbindung: der alte Token
    wird bei der neuen Kopplung ungueltig, und die Bridge, die noch damit
    laeuft, faellt ohne erkennbaren Anlass aus.
    """
    env_path = tmp_path / "bridge.env"
    env_path.write_text(
        "ORDERTUNE_BRIDGE_TOKEN=ot_bridge_alt\n"
        "ORDERTUNE_BRIDGE_CONNECTION_ID=alt\n",
        encoding="utf-8",
    )

    def darf_nicht(*_a, **_k):  # pragma: no cover
        raise AssertionError("pairing.start was called without a confirmation")

    monkeypatch.setattr(pair_console.pairing, "start", darf_nicht)
    monkeypatch.setattr(pair_console, "_bestaetigt_ersetzen", lambda: False)

    assert pair_console.run_pairing(env_path) == 1
    # Unveraendert.
    assert "ot_bridge_alt" in env_path.read_text(encoding="utf-8")


# ── C — die nicht schreibbare Ablage wird nach vorn geholt ───────────────────


def test_the_probe_passes_on_a_writable_folder(tmp_path) -> None:
    rang, grund = paths.probe_writable(ziel=tmp_path)
    assert rang == paths.ABLAGE_SCHREIBBAR
    assert grund is None
    # Die Marke raeumt sich selbst weg.
    assert list(tmp_path.iterdir()) == []


@pytest.mark.skipif(
    __import__("os").name == "nt",
    reason="Der Schreibschutz wirkt unter Windows-ACLs anders; der Fall wird "
    "dort ueber die Rechteverwaltung geprueft, nicht ueber den Modus.",
)
def test_the_probe_names_the_guard_that_is_missing(tmp_path) -> None:
    """Die Warnung nennt den Riegel — nicht nur den Ordner.

    „Could not write to the data folder" waere richtig und nutzlos: es sagt
    nicht, was dadurch ausfaellt, und genau das entscheidet, ob jemand hinsieht.
    """
    import os

    gesperrt = tmp_path / "gesperrt"
    gesperrt.mkdir()
    os.chmod(gesperrt, 0o500)
    try:
        rang, grund = paths.probe_writable(ziel=gesperrt)
        if rang == paths.ABLAGE_SCHREIBBAR:
            pytest.skip("Laeuft als root — der Schreibschutz greift nicht.")
        assert rang == paths.ABLAGE_NICHT_SCHREIBBAR

        text = "\n".join(paths.writability_warning(grund, ziel=gesperrt))
        assert "same order twice" in text
        assert str(gesperrt) in text
        assert "Trading continues" in text
    finally:
        os.chmod(gesperrt, 0o700)


# ── G — die Uebergabe des Berichtsverzeichnisses ─────────────────────────────


def test_check_flag_is_read_as_a_pure_function() -> None:
    assert trade_reports.check_requested(["--check-reports"])
    assert trade_reports.check_requested(["--headless", "--check-reports"])
    assert not trade_reports.check_requested(["--headless"])


def test_the_check_names_the_three_settings_when_something_is_off(tmp_path) -> None:
    """Der Befund allein genuegt nicht — der Block sagt, was einzutragen ist.

    Zwei der drei Einstellungen sind Fallen, die sich nicht von selbst zeigen:
    ein gefuelltes Namensfeld laesst die TWS dieselbe Datei ueberschreiben, und
    ein Komma zerbricht Zeilen, weil IBKR nicht quotet.
    """
    text = "\n".join(trade_reports.check_bericht(tmp_path / "gibt-es-nicht"))

    assert "no_dir" in text
    assert "Global Configuration - Export Reports" in text
    assert "leave EMPTY" in text
    assert "semicolon" in text
    # Der Rechte-Fall ist auf Linux der wahrscheinlichste und aus der Meldung
    # allein nicht zu erraten.
    assert "same user" in text


def test_the_check_shows_what_it_found_when_it_is_fine(tmp_path) -> None:
    """Im guten Fall zaehlt der Block die Dateien auf, statt nur `ok` zu sagen.

    „Alles in Ordnung" ohne Beleg ist die Sorte Auskunft, die beim zweiten Mal
    niemand mehr liest.
    """
    (tmp_path / "trades.20260924.csv").write_text(
        "Account;Order Ref.;ID;Quantity;Price;Date;Time\n", encoding="utf-8"
    )
    text = "\n".join(
        trade_reports.check_bericht(tmp_path, )
    )
    assert "trades.20260924.csv" in text
    assert "report file(s) found" in text


def test_the_installer_hands_the_path_over_at_the_right_moment() -> None:
    """Der Installer nennt Pfad und Pruefbefehl — dort, wo der Kunde wechselt.

    Der eine Handgriff, den kein Skript abnehmen kann, ist die Uebergabe des
    Verzeichnisses an die TWS. Ein Tippfehler faellt dabei nicht auf: die TWS
    legt den Ordner an, den sie bekommt, und alles sieht richtig aus.
    """
    skript = (
        WURZEL / "packaging/linux/ordertune-bridge-ibkr-linux-installer.sh"
    ).read_text(encoding="utf-8")

    assert "EXPORT_DIR=" in skript
    assert "--check-reports" in skript
    assert "Export Reports" in skript
    assert "leave EMPTY" in skript


def test_the_report_folder_survives_an_update() -> None:
    """Das Archiv liegt NICHT im Programmordner, den der Installer ersetzt.

    Der Installer macht `rm -rf` auf `/opt/ordertune-bridge`. Laege das Archiv
    dort, waere es nach jeder Aktualisierung weg — und es ist genau die Quelle,
    mit der eine Fuellung nach einer Auszeit der Bridge noch nachtragbar ist.
    """
    skript = (
        WURZEL / "packaging/linux/ordertune-bridge-ibkr-linux-installer.sh"
    ).read_text(encoding="utf-8")

    zeile = next(
        z for z in skript.splitlines()
        if z.strip().startswith("EXPORT_DIR=")
    )
    assert "/opt/ordertune-bridge" not in zeile, (
        "Das Berichtsarchiv liegt im Ordner, den eine Aktualisierung loescht."
    )
    assert "${HEIM}" in zeile


def test_the_folder_name_matches_windows(monkeypatch, tmp_path) -> None:
    """Gleicher Ordnername auf beiden Plattformen, anderer Elternordner.

    Damit steht in der Anleitung EIN Name mit zwei Praefixen statt zweier
    Anleitungen — genau die Trennung, die DOCS-9 verlangt.
    """
    monkeypatch.setattr(trade_reports.sys, "platform", "win32")
    windows = trade_reports.standard_verzeichnis()

    monkeypatch.setattr(trade_reports.sys, "platform", "linux")
    monkeypatch.setattr(trade_reports.Path, "home", staticmethod(lambda: tmp_path))
    linux = trade_reports.standard_verzeichnis()

    assert windows.endswith(trade_reports.EXPORT_ORDNERNAME)
    assert linux.endswith(trade_reports.EXPORT_ORDNERNAME)
    assert windows != linux


# ── A / Entscheidung 8 — das Release und die `.sh` ───────────────────────────


def test_the_release_builds_linux_too() -> None:
    """Der Workflow traegt den Linux-Strang, und zwar nachgelagert.

    Nebeneinander wollten beide Jobs dasselbe Release anlegen, und wer zuerst
    kommt, entschiede der Zufall.
    """
    yml = (WURZEL / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert "build-linux:" in yml
    assert "needs: build" in yml
    # Gebaut wird auf der aelteren Basis — das ist es, was die glibc-Zusage
    # nach unten absichert.
    assert "ubuntu-22.04" in yml


def test_the_linked_names_carry_no_version() -> None:
    """Stabile Namen, weil die Karte ueber `releases/latest/download/<name>` geht.

    Genau hier bricht ein versionierter Dateiname, und zwar still.
    """
    yml = (WURZEL / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert "ordertune-bridge-ibkr-linux-x86_64.tar.gz" in yml
    assert "ordertune-bridge-ibkr-linux-installer.sh" in yml


def test_the_installer_is_a_script_and_not_an_archive() -> None:
    """Entscheidung 8, festgenagelt.

    Ein selbstentpackendes Archiv holte die `/tmp`-noexec-Fehlerklasse zurueck,
    die One-Folder gerade beseitigt hat. Diese Zusicherung ist der Riegel
    dagegen, dass jemand spaeter „eine Datei waere doch schoener" denkt.
    """
    skript = WURZEL / "packaging/linux/ordertune-bridge-ibkr-linux-installer.sh"
    roh = skript.read_bytes()

    # Lesbarer Text von vorn bis hinten. Ein makeself-Archiv haengt eine
    # Binaernutzlast an das Skript an — die faellt hier durch.
    roh.decode("utf-8")
    assert roh.startswith(b"#!/usr/bin/env bash")

    text = roh.decode("utf-8")
    assert "sha256" in text.lower()

    # Der Zwischenspeicher liegt unter /opt, nicht unter /tmp.
    #
    # Geprueft werden nur die AUSGEFUEHRTEN Zeilen. Die Kommentare nennen
    # `/tmp` mehrfach — sie erklaeren ja gerade, warum es hier nicht vorkommt —
    # und eine Suche ueber die ganze Datei wuerde an der eigenen Begruendung
    # scheitern.
    befehle = [
        z for z in text.splitlines()
        if z.strip() and not z.strip().startswith("#")
    ]
    assert not [z for z in befehle if "/tmp" in z], (
        "Der Installer fasst /tmp an. Genau das soll Entscheidung 8 vermeiden."
    )


def test_the_installer_and_the_unit_agree_on_where_things_live() -> None:
    """Skript und Einheit nennen denselben Ort.

    Zwei Dateien, die einen Pfad je fuer sich fuehren, laufen beim naechsten
    Umbenennen auseinander — und das faellt erst auf dem Kundenserver auf.
    """
    skript = (
        WURZEL / "packaging/linux/ordertune-bridge-ibkr-linux-installer.sh"
    ).read_text(encoding="utf-8")
    einheit = (WURZEL / "packaging/linux/ordertune-bridge.service").read_text(
        encoding="utf-8"
    )

    assert "/opt/ordertune-bridge" in skript
    assert "WorkingDirectory=/opt/ordertune-bridge" in einheit
    assert "ExecStart=/opt/ordertune-bridge/ordertune-bridge-ibkr --headless" in einheit
    assert "User=ordertune-bridge" in einheit
    # Das Heimverzeichnis ist der Grund, warum der Dienstnutzer eines braucht.
    assert "Environment=HOME=/home/ordertune-bridge" in einheit
    assert "--create-home" in skript


def test_the_unit_does_not_lock_the_data_folder() -> None:
    """`ProtectHome` haette ausgerechnet die Ablage schreibgeschuetzt.

    Eine Haertung, die den teuersten Zustand des Systems wahrscheinlicher
    macht, ist keine.
    """
    einheit = (WURZEL / "packaging/linux/ordertune-bridge.service").read_text(
        encoding="utf-8"
    )
    zeilen = [z.strip() for z in einheit.splitlines() if not z.strip().startswith("#")]
    assert not any(z.startswith("ProtectHome=") for z in zeilen)


def test_pairing_runs_as_the_service_user_from_the_program_folder() -> None:
    """Die zwei Handgriffe, die unsichtbar sind, wenn sie fehlen.

    `bridge.env` loest gegen das ARBEITSVERZEICHNIS auf, und `runuser -u`
    wechselt die Kennung, nicht die Umgebung. Ohne `cd` landet die Datei am
    falschen Ort; ohne `HOME` zeigen Ablage und Berichtsverzeichnis auf das
    Heimverzeichnis von root.
    """
    skript = (
        WURZEL / "packaging/linux/ordertune-bridge-ibkr-linux-installer.sh"
    ).read_text(encoding="utf-8")

    assert "runuser -u" in skript
    assert "HOME=" in skript
    assert 'cd "${ZIEL}"' in skript
