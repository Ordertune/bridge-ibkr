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
