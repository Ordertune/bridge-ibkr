"""coloredlogs-basierter Logging-Setup mit Rolling-File."""
from __future__ import annotations

import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

import coloredlogs

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def setup_logging(level: str = "INFO", log_dir: str | Path = "logs") -> None:
    """Console + rolling-file logging. Files retained 30 days."""
    coloredlogs.install(level=level, fmt=LOG_FORMAT)

    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    file_handler = TimedRotatingFileHandler(
        log_path / "bridge.log",
        when="midnight",
        backupCount=30,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
    file_handler.setLevel(getattr(logging, level.upper(), logging.INFO))

    root = logging.getLogger()
    root.addHandler(file_handler)
