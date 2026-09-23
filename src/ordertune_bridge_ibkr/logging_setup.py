"""coloredlogs-basierter Logging-Setup mit Rolling-File.

## T1-213 — der Bildschirm ist optional geworden, die Datei nicht

Seit dem 2026-09-23 wird die EXE fensterlos gebaut. `sys.stdout` steht dann auf
`None`, und `coloredlogs.install()` haengt seinen Handler an einen Kanal, den
es nicht gibt. `logging` verschluckt den Fehler zwar — aber dann hat jede
fehlende Zeile eine andere Ursache als die vermutete, und das ist genau die
Sorte stiller Fehlschlag, gegen die dieses Projekt an einem Dutzend Stellen
gebaut hat.

Die **Datei** wird in jedem Fall geschrieben. Sie ist seit T1-213 der Ort, an
dem der Owner die Ausgabe der Sonde nachliest, wenn er die Bridge ohne
`--console` gestartet hat.
"""
from __future__ import annotations

import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

import coloredlogs

from . import paths, windows_ui

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def setup_logging(level: str = "INFO", log_dir: str | Path | None = None) -> Path:
    """Console + rolling-file logging. Files retained 30 days.

    Gibt den **absoluten** Pfad der Protokolldatei zurueck (T1-101 A-4).

    `log_dir` ist relativ zum Arbeitsverzeichnis, und das ist bei einem
    Doppelklick nicht zwingend der Ordner der EXE. Bis 0.6.0 stand der Ort
    nirgends: wer nach dem Protokoll gefragt wurde, musste raten, wo es liegt.
    Deshalb aufgeloest und vom Aufrufer in der ersten Zeile genannt.
    """
    # T1-213: nur, wenn ueberhaupt ein Kanal da ist. Siehe Kopf.
    if windows_ui.has_console_stream():
        coloredlogs.install(level=level, fmt=LOG_FORMAT)

    log_path = paths.log_dir() if log_dir is None else Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    log_file = (log_path / "bridge.log").resolve()

    file_handler = TimedRotatingFileHandler(
        log_file,
        when="midnight",
        backupCount=30,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
    file_handler.setLevel(getattr(logging, level.upper(), logging.INFO))

    root = logging.getLogger()
    root.addHandler(file_handler)

    return log_file
