"""T1-207 B — das Skript der Cockpit-Flaeche muss ueberhaupt laufen.

## Der Fehler, aus dem das entstanden ist

In v0.25.0 ausgeliefert, vom Owner am 2026-09-22 auf dem Server gefunden: die
Bridge stand dauerhaft auf „Connecting", kein Feld wurde gefuellt, und die
Reiter reagierten auf keinen Klick. Die Bridge selbst war die ganze Zeit
gesund — im Protokoll liefen `updatePortfolio`-Zeilen durch, die Verbindung zur
TWS stand.

Kaputt war eine einzige Maskierung. `PAGE_HTML` ist ein nicht-roher
Python-String, der JavaScript traegt; ein `\\n` darin muss im Quelltext
`\\\\n` geschrieben werden. Stand dort nur `\\n`, wurde daraus beim Laden des
Moduls ein **echter Zeilenumbruch mitten in einem JS-String** — ein
Syntaxfehler, der nicht eine Zeile lahmlegt, sondern das komplette Skript und
damit jede Anzeige und jeden Knopf.

Keine der 586 Zusicherungen hat das gesehen. Sie pruefen den Zustandsblock,
den Server und die Fenstergroesse — niemand hat je gefragt, ob das Skript
ueberhaupt parst.

## Warum zwei Pruefungen

`node --check` ist die richtige Antwort: es ist derselbe Parser, den der
Browser mitbringt. Node liegt auf beiden CI-Laeufern, aber nicht zwingend auf
jedem Entwicklerrechner — und eine Zusicherung, die still uebersprungen wird,
ist beim naechsten Mal wieder nicht da. Die zweite Pruefung braucht nichts und
faengt genau die Fehlerklasse von oben.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from ordertune_bridge_ibkr.cockpit.page import PAGE_HTML

QUELLE = (
    Path(__file__).parent.parent
    / "src"
    / "ordertune_bridge_ibkr"
    / "cockpit"
    / "page.py"
)


def _skript() -> str:
    return PAGE_HTML.split("<script>", 1)[1].rsplit("</script>", 1)[0]


def test_ein_einzelnes_backslash_n_im_quelltext_ist_immer_ein_fehler() -> None:
    """Die Regel, an der v0.25.0 gescheitert ist — ohne Werkzeug pruefbar.

    In diesem Modul gibt es keinen berechtigten Grund fuer ein einzelnes
    `\\n`: ein gewollter Umbruch im HTML steht als echter Umbruch da, und
    jedes `\\n`, das im Browser ankommen soll, muss `\\\\n` geschrieben sein.
    """
    quelltext = QUELLE.read_text(encoding="utf-8")
    treffer = [
        quelltext[: m.start()].count("\n") + 1
        for m in re.finditer(r"(?<!\\)\\n", quelltext)
    ]
    assert not treffer, (
        "In page.py steht ein einzelnes \\n statt \\\\n, in Zeile(n) "
        f"{treffer}. Daraus wird ein echter Zeilenumbruch im JavaScript — "
        "das Skript parst dann nicht mehr, und die Flaeche bleibt auf "
        "'Connecting' stehen."
    )


def test_kein_string_bricht_ueber_die_zeile() -> None:
    """Dieselbe Fehlerklasse, am erzeugten Skript statt am Quelltext.

    Kommentare fliegen vorher raus: sie duerfen Anfuehrungszeichen enthalten,
    und deutsche Kommentare tun das reichlich.
    """
    verdaechtig = []
    for nummer, zeile in enumerate(_skript().split("\n"), 1):
        ohne_kommentar = zeile.split("//", 1)[0] if "://" not in zeile else zeile
        sauber = (
            ohne_kommentar.replace('\\"', "")
            .replace("\\'", "")
            .replace("\\\\", "")
        )
        # Ein Zeichenklassen-Literal wie /[&<>"]/ traegt ein einzelnes
        # Anfuehrungszeichen voellig zu Recht.
        if "/[" in sauber or "':\"" in sauber:
            continue
        if sauber.count('"') % 2:
            verdaechtig.append((nummer, zeile.strip()[:90]))

    assert not verdaechtig, (
        "Zeile(n) mit ungerader Zahl an Anfuehrungszeichen — vermutlich ein "
        f"String, der ueber das Zeilenende bricht: {verdaechtig}"
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="node liegt nicht vor")
def test_das_skript_parst(tmp_path: Path) -> None:
    """Der eigentliche Beleg: derselbe Parser, den der Browser mitbringt."""
    datei = tmp_path / "cockpit.js"
    datei.write_text(_skript(), encoding="utf-8")

    ergebnis = subprocess.run(
        ["node", "--check", str(datei)], capture_output=True, text=True
    )
    assert ergebnis.returncode == 0, (
        "Das Cockpit-Skript hat einen Syntaxfehler. Die Flaeche zeigt dann "
        "nichts an und reagiert auf keinen Klick:\n" + ergebnis.stderr
    )


# ── T1-206: ein leerer Berichtsordner ist kein Befund ────────────────────────


def _verdict(zustand: dict, tmp_path: Path) -> list:
    """`verdict()` wirklich ausfuehren, nicht den Quelltext danach absuchen.

    Das Skript haengt am DOM — `render()`, `q()` und alles darunter laufen
    ausserhalb eines Browsers nicht. `verdict()` dagegen ist eine reine
    Funktion von einem Zustandsobjekt auf ein Paar [Text, Stufe], und genau
    deshalb laesst sie sich messen.

    Herausgeschnitten wird sie samt ihrer beiden Helfer. Eine Textsuche im
    Quelltext waere die schlechtere Pruefung: sie belegt, dass ein Satz
    dasteht, nicht dass er bei diesem Zustand herauskommt.
    """
    import json

    skript = _skript()
    teile = []
    for name in ("HEARTBEAT_STALE_S", "heartbeatStale", "exportBroken",
                 "gatewayInstead", "verdict"):
        if name == "HEARTBEAT_STALE_S":
            treffer = re.search(r"const HEARTBEAT_STALE_S = \d+;", skript)
            assert treffer, "HEARTBEAT_STALE_S nicht gefunden"
            teile.append(treffer.group(0))
            continue
        treffer = re.search(
            r"^function " + name + r"\(.*?^\}", skript, re.S | re.M
        )
        assert treffer, f"{name}() nicht gefunden"
        teile.append(treffer.group(0))

    datei = tmp_path / "verdict.js"
    datei.write_text(
        "\n".join(teile)
        + "\nconsole.log(JSON.stringify(verdict("
        + json.dumps(zustand)
        + ")));\n",
        encoding="utf-8",
    )
    ergebnis = subprocess.run(
        ["node", str(datei)], capture_output=True, text=True
    )
    assert ergebnis.returncode == 0, ergebnis.stderr
    return json.loads(ergebnis.stdout)


GESUND = {
    "stopping": False,
    "failure_headline": None,
    "tws_connected": True,
    "last_heartbeat_age_s": 1,
    "write_access": "writable",
    "ordertune_ok": True,
    "gateway_instead_of_tws": False,
}


@pytest.mark.skipif(shutil.which("node") is None, reason="node fehlt")
def test_ein_leerer_berichtsordner_ist_keine_stoerung(tmp_path: Path) -> None:
    """Owner-Befund 2026-09-25, an der laufenden Bridge.

    Die Seite sagte oben „TWS trade reports are not being read - fills may be
    lost" und unten in derselben Karte „Nothing to do if you have just set this
    up." Zwei Aussagen, ein Bildschirm, gegensaetzlich — und die obere war die
    falsche.

    Ein leerer Ordner heisst „noch nichts zu lesen", nicht „wird nicht
    gelesen". Die TWS exportiert Handelsberichte; ohne Handel gibt es nichts
    zu exportieren.
    """
    text, stufe = _verdict({**GESUND, "trade_export": "no_file"}, tmp_path)

    assert "not being read" not in text
    assert "may be lost" not in text
    # Ohne Warnfarbe: eine gelbe Zeile fuer den Normalfall erzieht dazu, die
    # gelbe Zeile im Ernstfall zu uebersehen.
    assert stufe == "", f"no_file faerbt die Zeile als {stufe!r}"
    assert "no trade report yet" in text.lower()


@pytest.mark.skipif(shutil.which("node") is None, reason="node fehlt")
def test_die_echten_befunde_warnen_weiterhin(tmp_path: Path) -> None:
    """Der Regressionsteil — und der wichtigere.

    `fixed_name` und `stale` sind die teuren: beide sehen aus wie ein
    funktionierendes Archiv und sind keins. Sie duerfen durch diese Aenderung
    nicht mit stillgelegt werden.
    """
    for zustand in ("not_configured", "no_dir", "unreadable", "fixed_name", "stale"):
        text, stufe = _verdict({**GESUND, "trade_export": zustand}, tmp_path)
        assert stufe == "warn", f"{zustand} warnt nicht mehr"
        assert "not being read" in text, f"{zustand}: {text}"


@pytest.mark.skipif(shutil.which("node") is None, reason="node fehlt")
def test_ok_und_unknown_sagen_weiterhin_nichts(tmp_path: Path) -> None:
    for zustand in ("ok", "unknown"):
        text, stufe = _verdict({**GESUND, "trade_export": zustand}, tmp_path)
        assert stufe == ""
        assert text == "Connected - waiting for releases"
