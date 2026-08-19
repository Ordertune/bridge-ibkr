"""T1-101 B-1 — die Ablagedatei: wo das Cockpit dieser Bridge erreichbar ist.

Nach Client-ID benannt, damit zwei Bridges auf einer Maschine — zwei Konten,
zwei API-Verbindungen — einander nicht ueberschreiben. Beim Beenden geloescht,
damit eine liegengebliebene URL aus einer alten Sitzung niemanden in die Irre
fuehrt; das Token darin waere ohnehin wertlos, weil bei jedem Start ein neues
erzeugt wird.

Die Datei ist der Grund, aus dem der Fernzugriff Nicht-Ziel bleiben kann: wer
sie lesen kann, ist auf der Maschine bereits angemeldet und kommt damit ohnehin
an `bridge.env` und das Protokoll.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

RUN_DIR = "run"


def runfile_path(client_id: int, run_dir: str | Path = RUN_DIR) -> Path:
    return Path(run_dir) / f"cockpit-{client_id}.json"


def write(client_id: int, url: str, run_dir: str | Path = RUN_DIR) -> Path | None:
    """Legt die Adresse ab. Ein Fehler hier haelt die Bridge nicht auf."""
    path = runfile_path(client_id, run_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"url": url, "pid": os.getpid()}, indent=2),
            encoding="utf-8",
        )
        # Die Datei traegt das Zugangstoken des Cockpits. Mit den Vorgaben der
        # Umgebung waere sie fuer jeden lesbar, der auf der Maschine ein Konto
        # hat — und wer sie liest, darf danach auch `bridge.env` schreiben.
        try:
            path.chmod(0o600)
        except OSError:  # pragma: no cover - Windows kennt den Modus nicht
            pass
        return path
    except OSError as exc:
        # Das Cockpit ist Beiwerk. Ein schreibgeschuetztes Verzeichnis darf den
        # Handel nicht verhindern — die URL steht ohnehin in der Konsole.
        log.warning("Could not write the cockpit run file: %s", exc)
        return None


def remove(client_id: int, run_dir: str | Path = RUN_DIR) -> None:
    try:
        runfile_path(client_id, run_dir).unlink(missing_ok=True)
    except OSError as exc:  # pragma: no cover - defensiv
        log.debug("Could not remove the cockpit run file: %s", exc)
