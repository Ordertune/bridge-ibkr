"""PyInstaller build-script.

Baut single-file EXE für Windows:
  dist/ordertune-bridge-ibkr.exe

Nach dem Build wird die EXE signiert — siehe `.github/workflows/release.yml`,
Schritt „Sign EXE". Das passiert ueber einen Cloud-HSM-Dienst; ein
`.pfx`-Datei-Zertifikat, wie es hier bis T1-182 stand, gibt es seit dem
CA/Browser-Forum-Beschluss vom 01.06.2023 nicht mehr zu kaufen.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).parent
    dist = root / "dist"
    build = root / "build"

    if dist.exists():
        shutil.rmtree(dist)
    if build.exists():
        shutil.rmtree(build)

    # Build `launcher.py`, NOT `src/ordertune_bridge_ibkr/main.py`.
    #
    # Pointing PyInstaller at a module inside the package makes that module the
    # `__main__` script, and a `__main__` script has no parent package. The
    # first relative import then fails with
    #
    #     ImportError: attempted relative import with no known parent package
    #
    # which is exactly how every build since 0.1.0 died on startup. `--paths`
    # puts `src` on the analysis path so the launcher can import the package
    # by name and PyInstaller bundles it as a package.
    cmd = [
        "pyinstaller",
        "--onefile",
        "--name",
        "ordertune-bridge-ibkr",
        # T1-213 — ein Fenster fuer den Kunden.
        #
        # Bis zum 2026-09-23 stand hier `--console`, und ein Doppelklick
        # oeffnete zwei Fenster: das Protokoll und das Cockpit. Das Protokoll
        # ist fuer den Owner; er holt es sich mit `--console` auf der
        # Befehlszeile zurueck (`windows_ui.allocate_console`).
        #
        # Verworfen wurde die kleinere Aenderung — weiter mit `--console`
        # bauen und das Fenster beim Start verbergen. Windows behandelt die
        # Datei dann weiterhin als Konsolenanwendung, und beim Doppelklick
        # blitzt das schwarze Fenster sichtbar auf. Ein Aufblitzen ist kein
        # Fortschritt gegenueber einem Fenster, sondern dasselbe Bekenntnis in
        # kuerzer.
        "--windowed",
        "--clean",
        "--noconfirm",
        "--paths",
        str(root / "src"),
        str(root / "launcher.py"),
    ]
    # Das Symbol ist Pflicht, nicht Kuer.
    #
    # Hier stand `if icon.exists()`. Die Datei existierte nie — `assets/` war
    # ein leeres Verzeichnis —, also fiel der Build stillschweigend auf
    # PyInstallers Voreinstellung zurueck, und die ist das **Python-Symbol**.
    # Jede Fassung bis 0.23.2 hat so ausgeliefert: der Kunde stellt eine
    # Anwendung neben sein Depot, und sie sieht aus wie eine fremde
    # Programmiersprache. Gemerkt hat es niemand, weil ein uebersprungener
    # Schritt nichts sagt.
    #
    # Ein fehlendes Symbol ist ab jetzt ein Baufehler. Wer `assets/icon.ico`
    # loescht, bekommt keinen stillen Rueckfall, sondern einen Abbruch mit dem
    # Befehl, der die Datei wiederherstellt.
    icon = root / "assets" / "icon.ico"
    if not icon.exists():
        print(
            f"FEHLER: {icon.relative_to(root)} fehlt.\n"
            "        Ohne diese Datei baut PyInstaller die EXE mit dem\n"
            "        Python-Symbol — das ist kein brauchbares Ergebnis.\n"
            "        Wiederherstellen mit:  python tools/make_icon.py",
            file=sys.stderr,
        )
        return 2
    cmd.extend(["--icon", str(icon)])

    proc = subprocess.run(cmd, check=False)
    if proc.returncode != 0:
        return proc.returncode

    return verify_icon(dist / "ordertune-bridge-ibkr.exe", icon)


def ico_frames(ico: Path) -> list[bytes]:
    """Die Rahmen-Nutzlasten einer ICO-Datei, unveraendert.

    Genau diese Bytes legt PyInstaller als `RT_ICON`-Ressourcen in die EXE.
    Sie dort wiederzufinden ist der Beleg, dass das Symbol angekommen ist.
    """
    raw = ico.read_bytes()
    count = int.from_bytes(raw[4:6], "little")
    frames = []
    for i in range(count):
        entry = 6 + i * 16
        length = int.from_bytes(raw[entry + 8:entry + 12], "little")
        offset = int.from_bytes(raw[entry + 12:entry + 16], "little")
        frames.append(raw[offset:offset + length])
    return frames


def verify_icon(exe: Path, icon: Path) -> int:
    """Belegt, dass das Symbol wirklich in der EXE steht.

    `--icon` mitzugeben ist kein Beweis — PyInstaller nimmt das Argument auch
    dann an, wenn es die Ressource anschliessend nicht schreibt, und genau die
    Sorte stiller Rueckfall hat das Python-Symbol ueberhaupt erst bis zum
    Kunden getragen. Hier wird deshalb die gebaute Datei gelesen, nicht der
    Aufruf geglaubt.
    """
    if sys.platform != "win32":
        # Das Einbetten ist eine Windows-Ressourcenoperation. Ausserhalb von
        # Windows baut PyInstaller ohne sie, und ein Fehlschlag waere hier
        # kein Befund, sondern ein falscher Alarm.
        print("Hinweis: Symbolpruefung nur auf Windows — hier uebersprungen.")
        return 0

    if not exe.exists():
        print(f"FEHLER: {exe} wurde nicht gebaut.", file=sys.stderr)
        return 2

    blob = exe.read_bytes()
    frames = ico_frames(icon)
    gefunden = sum(1 for f in frames if f in blob)

    if gefunden == 0:
        print(
            "FEHLER: Keiner der Symbolrahmen steht in der gebauten EXE.\n"
            "        PyInstaller hat `--icon` angenommen und die Ressource\n"
            "        nicht geschrieben. Die EXE traegt damit weiterhin das\n"
            "        Python-Symbol — genau der Zustand, den T1-182 beendet.",
            file=sys.stderr,
        )
        return 2

    print(f"Symbol belegt: {gefunden} von {len(frames)} Rahmen in der EXE gefunden.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
