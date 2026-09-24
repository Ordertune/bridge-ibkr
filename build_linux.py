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

import shutil
import subprocess
import sys
from pathlib import Path

NAME = "ordertune-bridge-ibkr"


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

    return verify_bundle(dist / NAME)


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

    print(f"Buendel belegt: {binaer} ist ausfuehrbar, {intern} steht daneben.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
