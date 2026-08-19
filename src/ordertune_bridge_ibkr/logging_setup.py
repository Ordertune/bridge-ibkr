"""coloredlogs-basierter Logging-Setup mit Rolling-File."""
from __future__ import annotations

import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

import coloredlogs

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def setup_logging(level: str = "INFO", log_dir: str | Path = "logs") -> Path:
    """Console + rolling-file logging. Files retained 30 days.

    Gibt den **absoluten** Pfad der Protokolldatei zurueck (T1-101 A-4).

    `log_dir` ist relativ zum Arbeitsverzeichnis, und das ist bei einem
    Doppelklick nicht zwingend der Ordner der EXE. Bis 0.6.0 stand der Ort
    nirgends: wer nach dem Protokoll gefragt wurde, musste raten, wo es liegt.
    Deshalb aufgeloest und vom Aufrufer in der ersten Zeile genannt.
    """
    coloredlogs.install(level=level, fmt=LOG_FORMAT)

    log_path = Path(log_dir)
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
