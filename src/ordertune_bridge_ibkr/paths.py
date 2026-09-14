"""T1-176 B — wo die Bridge ihre Zustandsdateien ablegt.

## Der Fehler, aus dem das entstanden ist

Drei Ablagen loesten relativ zum **Arbeitsverzeichnis** auf: `SubmittedStore`
(`"run"`), `cockpit/runfile` (`"run"`) und `setup_logging` (`"logs"`). Fuer
`bridge.env` war genau das bedacht worden, mit der Begruendung in `main.main`:

    bei einem Doppelklick ist das Arbeitsverzeichnis nicht zwingend der Ordner
    der EXE

Die Zustandsdateien haben dieselbe Behandlung nicht bekommen. Ein Start aus
einem anderen Arbeitsverzeichnis — geplante Aufgabe, Verknuepfung mit
gesetztem „Ausfuehren in", Konsole an anderer Stelle — findet deshalb ein
leeres `run/`.

Das ist teuer, weil dort `submitted-dispatches.json` liegt: der Riegel gegen
den Doppelauftrag aus T1-103 H, dessen ganzer Zweck es ist, den Neustart zu
ueberleben. Ist er leer, gilt wieder der Ablauf, gegen den er gebaut wurde —
`place_order` gelingt, `ack_order` scheitert, der naechste Abruf liefert
denselben Auftrag erneut aus, **zwei Echtauftraege**.

Derselbe Ordner ist ausserdem das, was jemand beim Aufraeumen mitnimmt: ein
Verzeichnis namens `run` mit einer JSON-Datei sieht nach Abfall aus.

## Was jetzt gilt

  * **Gepackte EXE** → `%LOCALAPPDATA%\\Ordertune\\Bridge` unter Windows,
    sonst `~/.local/share/ordertune-bridge`. Dort raeumt niemand auf, und der
    Ort haengt nicht daran, von wo gestartet wurde.
  * **Aus dem Quellbaum** → das Arbeitsverzeichnis wie bisher. Die
    Entwicklung soll nicht ins Nutzerprofil schreiben, und die Zusicherungen
    geben ihre Pfade ohnehin selbst mit.

`bridge.env` bleibt, wo sie ist: neben der EXE. Sie ist die Datei, die der
Nutzer anfassen soll — die anderen sind es nicht.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from .console import is_frozen

README_NAME = "README.txt"
README_TEXT = """Ordertune Bridge — working files

Please do not delete anything in this folder.

The Bridge remembers here which orders it has already sent to your broker.
Without that memory an order can be placed twice: once before a network
error, and again after the restart.

  run/submitted-dispatches.json   orders already sent (kept 30 days)
  run/cockpit-*.json              address of the Bridge window, per session
  logs/bridge.log                 the log, rotated daily, kept 30 days

Your settings are NOT here. They live in bridge.env next to the program.
"""


def data_root() -> Path:
    """Die Wurzel, gegen die alle Zustandsdateien aufloesen."""
    if not is_frozen():
        return Path.cwd()
    if sys.platform == "win32":
        basis = os.environ.get("LOCALAPPDATA")
        if basis:
            return Path(basis) / "Ordertune" / "Bridge"
        # Ohne LOCALAPPDATA bleibt das Profil. Ein Windows ohne diese Variable
        # ist ungewoehnlich genug, dass Raten schlechter waere als Ausweichen.
        return Path.home() / "AppData" / "Local" / "Ordertune" / "Bridge"
    return Path.home() / ".local" / "share" / "ordertune-bridge"


def run_dir() -> Path:
    return data_root() / "run"


def log_dir() -> Path:
    return data_root() / "logs"


def exe_dir() -> Path:
    """Der Ordner der EXE — der Ort, an dem `bridge.env` liegt."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def _hat_inhalt(pfad: Path) -> bool:
    return pfad.is_dir() and any(pfad.iterdir())


def migrate_legacy(*, ziel: Path | None = None) -> list[tuple[str, str]]:
    """Die alten Ablagen einmalig an den neuen Ort holen.

    Ohne diesen Schritt verloere die erste Aktualisierung genau den Riegel, um
    den es hier geht — die Datei laege noch neben der EXE, gelesen wuerde ab
    sofort woanders.

    Gibt `(Stufe, Text)` zurueck, statt zu protokollieren: der Umzug laeuft
    **vor** `setup_logging`, weil der Protokollordner selbst dazugehoert. Der
    Aufrufer schreibt sie, sobald es ein Protokoll gibt.

    Die Regel ist bewusst zaghaft. Liegt am Zielort schon etwas, wird **nicht**
    zusammengefuehrt und **nichts** ueberschrieben — dann steht eine Warnung
    da, und ein Mensch entscheidet. Ein Riegel gegen Doppelauftraege ist nichts,
    was ein Aufraeumvorgang stillschweigend zusammenwerfen darf.
    """
    if not is_frozen():
        return []

    wurzel = ziel if ziel is not None else data_root()
    meldungen: list[tuple[str, str]] = []

    # Die alte Ablage lag relativ zum Arbeitsverzeichnis. Bei einem Doppelklick
    # war das meist der Ordner der EXE, sicher ist das aber nie — deshalb
    # beide Orte ansehen, und den EXE-Ordner zuerst.
    quellen = []
    for basis in (exe_dir(), Path.cwd()):
        if basis.resolve() != wurzel.resolve() and basis not in quellen:
            quellen.append(basis)

    for name in ("run", "logs"):
        neu = wurzel / name
        for basis in quellen:
            alt = basis / name
            if not _hat_inhalt(alt):
                continue
            if _hat_inhalt(neu):
                meldungen.append((
                    "warning",
                    f"Both {alt} and {neu} hold files. Nothing was moved - "
                    f"the Bridge reads {neu}. Please merge them by hand.",
                ))
                break
            try:
                neu.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(alt), str(neu))
                meldungen.append(("info", f"Moved {alt} to {neu}."))
            except OSError as exc:
                meldungen.append((
                    "warning", f"Could not move {alt} to {neu}: {exc}"
                ))
            break

    return meldungen


def ensure_readme(*, ziel: Path | None = None) -> None:
    """Einen Satz danebenlegen, damit niemand den Ordner fuer Abfall haelt."""
    wurzel = ziel if ziel is not None else data_root()
    try:
        wurzel.mkdir(parents=True, exist_ok=True)
        datei = wurzel / README_NAME
        if not datei.exists():
            datei.write_text(README_TEXT, encoding="utf-8")
    except OSError:
        # Beiwerk. Ein schreibgeschuetztes Verzeichnis darf den Handel nicht
        # anhalten — dieselbe Haltung wie im SubmittedStore.
        pass
