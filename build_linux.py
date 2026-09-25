"""T1-206 A — PyInstaller-Build fuer Linux.

Baut ein **One-Folder**-Buendel:

    dist/ordertune-bridge-ibkr/ordertune-bridge-ibkr   die ausfuehrbare Datei
    dist/ordertune-bridge-ibkr/_internal/...           alles, was sie braucht

## Warum One-Folder und nicht One-File wie auf Windows

Ein One-File-Buendel entpackt sich bei **jedem Start** in ein temporaeres
Verzeichnis. Auf einem gehaerteten VPS ist `/tmp` mit `noexec` eingehaengt, und
dann startet das Programm nicht — mit einer Meldung, die kein Kunde deuten
kann. `--runtime-tmpdir` verschiebt das Problem nur: der Pfad wird beim Bauen
festgeschrieben, und ob er beim Kunden existiert und ihm gehoert, entscheidet
sich erst dort.

One-Folder laesst die Fehlerklasse **verschwinden**, statt sie zu entschaerfen:
es wird nichts entpackt, also braucht es kein beschreibbares
Temporaerverzeichnis. Zweitens startet es schneller, und das zaehlt hier mehr
als ueblich — systemd startet den Dienst nach einem Absturz neu, und jeder
Neustart wuerde sonst erneut entpacken.

Der Einwand „aber Windows liefert eine Datei" trifft nicht: der Kunde packt auf
Linux ohnehin ein Archiv aus und sieht dort nie eine einzelne Datei, gleich
welche Bauweise gewaehlt wird.

## Warum kein Symbol geprueft wird

`build.py` bricht ab, wenn `assets/icon.ico` fehlt, und liest die gebaute Datei
anschliessend daraufhin nach. Das ist eine **Windows-Ressourcenoperation**. Auf
Linux gibt es keine eingebettete Symbolressource und keinen Explorer, der sie
zeigte — ein Dienst hat kein Symbol. Die Pruefung hier wegzulassen ist deshalb
kein uebersprungener Schritt, sondern die Abwesenheit eines Schrittes.
"""
from __future__ import annotations

import base64
import shutil
import subprocess
import sys
from pathlib import Path

NAME = "ordertune-bridge-ibkr"

#: Das Symbol fuer den Menue-Eintrag. Liegt IM Programmordner und nicht daneben,
#: weil der Desktop-Weg nur diesen Ordner auspackt
#: (`tar --strip-components=1 ordertune-bridge-ibkr`). Was daneben liegt —
#: README, Dienst-Einheit — bekommt er nie zu sehen.
ICON_NAME = "ordertune-bridge.png"


def main() -> int:
    if sys.platform == "win32":
        print(
            "FEHLER: build_linux.py baut das Linux-Buendel und gehoert auf\n"
            "        einen Linux-Laeufer. Fuer Windows ist build.py zustaendig.",
            file=sys.stderr,
        )
        return 2

    root = Path(__file__).parent
    dist = root / "dist"
    build = root / "build"

    if dist.exists():
        shutil.rmtree(dist)
    if build.exists():
        shutil.rmtree(build)

    # `launcher.py`, NICHT `src/ordertune_bridge_ibkr/main.py` — siehe die
    # ausfuehrliche Begruendung in `build.py` und im Kopf von `launcher.py`.
    # Ein Modul aus dem Paket als Startskript zu nehmen macht es zu `__main__`,
    # und der erste relative Import stirbt.
    cmd = [
        "pyinstaller",
        "--onedir",
        "--name",
        NAME,
        # Bewusst `--console` und nicht `--windowed`.
        #
        # Auf Windows loest `--windowed` das Zwei-Fenster-Problem beim
        # Doppelklick (T1-213). Auf Linux gibt es diesen Doppelklick nicht: die
        # Bridge laeuft als Dienst unter systemd oder in einer SSH-Sitzung. Ein
        # fensterloser Bau nimmt dort `sys.stdout` weg — und damit genau den
        # Kanal, ueber den `--pair` seinen Kopplungscode zeigt und ueber den
        # systemd das Journal fuellt.
        "--console",
        "--clean",
        "--noconfirm",
        "--paths",
        str(root / "src"),
        str(root / "launcher.py"),
    ]

    proc = subprocess.run(cmd, check=False)
    if proc.returncode != 0:
        return proc.returncode

    write_icon(dist / NAME)
    return verify_bundle(dist / NAME)


def write_icon(ordner: Path) -> None:
    """Das Marken-Glyph als PNG neben das Programm legen.

    ## Warum erzeugt und nicht committet

    `assets/icon.ico` liegt als Datei im Repo, damit der Windows-Build kein
    Pillow braucht. Fuer Linux gibt es diesen Grund nicht: ein `.desktop`
    verlangt ein PNG, und das steckt bereits fertig in
    `cockpit/assets.py:ICON_PNG` — base64, 512x512, aus dem Design-System
    erzeugt und dort als einziges erlaubtes Marken-Glyph benannt.

    Eine zweite Bilddatei im Repo waere genau das, wovor `tools/make_icon.py`
    im eigenen Kopf warnt: die zweite Stelle, an der die Marke falsch werden
    kann. Hier wird deshalb dekodiert, nicht kopiert.

    ## Wozu es ueberhaupt gebraucht wird

    Auf einem Linux-Desktop fuehrt der Dateimanager eine nackte ausfuehrbare
    Datei per Doppelklick meist NICHT aus — GNOME tut es bewusst nicht. Das
    Gegenstueck zum Windows-Doppelklick ist ein Eintrag im Anwendungsmenue,
    und der will ein Bild. Ohne dieses haette er ein Platzhaltersymbol.
    """
    ziel = ordner / ICON_NAME
    ziel.write_bytes(base64.b64decode(_glyph_base64()))
    print(f"Symbol geschrieben: {ziel} ({ziel.stat().st_size} Bytes)")


def _glyph_base64() -> str:
    """Das Glyph aus dem Paket holen, ohne es zu importieren zu muessen.

    `sys.path` wird hier angefasst und nicht global: dieses Skript laeuft VOR
    dem Build und soll das Paket nicht dauerhaft in seinen Suchpfad ziehen.
    """
    root = Path(__file__).parent
    sys.path.insert(0, str(root / "src"))
    try:
        from ordertune_bridge_ibkr.cockpit import assets

        return assets.ICON_PNG
    finally:
        sys.path.pop(0)


def verify_bundle(ordner: Path) -> int:
    """Belegt, dass das Buendel die Form hat, die der Installer erwartet.

    Das ist dieselbe Haltung wie bei der Symbolpruefung in `build.py`: dass
    PyInstaller ein Argument angenommen hat, ist kein Beleg fuer das Ergebnis.
    Der Installer legt die **Inhalte** dieses Ordners nach `/opt/ordertune-
    bridge/`, und `paths.exe_dir()` loest dann auf das Elternverzeichnis der
    ausfuehrbaren Datei auf — genau dorthin, wo `bridge.env` liegen soll. Geht
    die Form kaputt, bricht das erst beim Kunden auf.
    """
    binaer = ordner / NAME
    intern = ordner / "_internal"
    symbol = ordner / ICON_NAME

    if not binaer.exists():
        print(f"FEHLER: {binaer} wurde nicht gebaut.", file=sys.stderr)
        return 2
    if not binaer.stat().st_mode & 0o111:
        print(f"FEHLER: {binaer} ist nicht ausfuehrbar.", file=sys.stderr)
        return 2
    if not intern.is_dir():
        print(
            f"FEHLER: {intern} fehlt.\n"
            "        PyInstaller hat kein One-Folder-Buendel gebaut, oder die\n"
            "        Form hat sich geaendert. Der Installer und die\n"
            "        Dienst-Einheit nennen beide diesen Aufbau.",
            file=sys.stderr,
        )
        return 2

    # Das Symbol wird MITGEPRUEFT und nicht nur geschrieben: es reist im
    # Programmordner mit, und der Menue-Eintrag aus der Anleitung nennt es mit
    # festem Namen. Faellt es weg, bekommt der Kunde einen Eintrag mit
    # Platzhaltersymbol — und niemand merkt es im Bau.
    if not symbol.exists() or symbol.stat().st_size == 0:
        print(f"FEHLER: {symbol} fehlt oder ist leer.", file=sys.stderr)
        return 2
    if symbol.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
        print(f"FEHLER: {symbol} ist kein PNG.", file=sys.stderr)
        return 2

    print(f"Buendel belegt: {binaer} ist ausfuehrbar, {intern} und {symbol.name} stehen daneben.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
