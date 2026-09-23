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
from urllib.parse import urlparse

from .. import paths

log = logging.getLogger(__name__)

# T1-222 — der Abruf liegt auf dem Startweg. Eine Sekunde reicht fuer die
# Rueckschleife um ein Vielfaches; laenger zu warten hiesse, jeden Start um die
# Wartezeit zu verzoegern, damit ein seltener Fall genauer wird.
LEBENSPRUEFUNG_TIMEOUT_S = 1.0


def runfile_path(client_id: int, run_dir: str | Path | None = None) -> Path:
    """T1-176 B: ohne Angabe die Ablage aus `paths`, nicht mehr `./run`."""
    basis = paths.run_dir() if run_dir is None else Path(run_dir)
    return basis / f"cockpit-{client_id}.json"


def write(client_id: int, url: str, run_dir: str | Path | None = None) -> Path | None:
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


def remove(client_id: int, run_dir: str | Path | None = None) -> None:
    try:
        runfile_path(client_id, run_dir).unlink(missing_ok=True)
    except OSError as exc:  # pragma: no cover - defensiv
        log.debug("Could not remove the cockpit run file: %s", exc)


def read(client_id: int, run_dir: str | Path | None = None) -> dict[str, object] | None:
    """T1-222 — was in der Ablagedatei steht, oder nichts.

    Bis zum 2026-09-23 wurde diese Datei geschrieben und geloescht, aber nie
    gelesen. Sie traegt die Adresse des laufenden Cockpits und die
    Prozesskennung — also genau die Auskunft, die ein zweiter Start braucht.

    Jeder Fehler beim Lesen endet in `None`. Das Cockpit ist Beiwerk; eine
    unlesbare Datei darf den Handel nicht verhindern (dieselbe Regel wie in
    `write`).
    """
    try:
        roh = runfile_path(client_id, run_dir).read_text(encoding="utf-8")
        daten = json.loads(roh)
    except (OSError, ValueError) as exc:
        log.debug("Could not read the cockpit run file: %s", exc)
        return None
    return daten if isinstance(daten, dict) else None


def ist_lokale_adresse(url: object) -> bool:
    """Zeigt diese Adresse auf die Rueckschleife?

    T1-222 AC-A4: die Datei liegt im Nutzerprofil, aber sie ist kein Grund,
    beim Start irgendwohin zu verbinden. Was nicht auf `127.0.0.1` oder
    `localhost` zeigt, wird verworfen — ohne Abruf.

    Als reine Funktion, damit die Zusicherung sie ohne Netzwerk prueft.
    """
    if not isinstance(url, str) or not url:
        return False
    try:
        zerlegt = urlparse(url)
    except ValueError:
        return False
    if zerlegt.scheme not in ("http", "https"):
        return False
    return zerlegt.hostname in ("127.0.0.1", "::1", "localhost")


def laeuft_dort_eine(url: object, timeout: float = LEBENSPRUEFUNG_TIMEOUT_S) -> bool:
    """Antwortet unter dieser Adresse ein Cockpit?

    ## Warum nicht die Prozesskennung

    Die Datei traegt auch eine `pid`, und sie zu pruefen waere billiger. Nach
    einem Neustart des Rechners kann dieselbe Kennung aber einem voellig
    fremden Vorgang gehoeren — dann verweigerte die Bridge ihren Dienst wegen
    eines Programms, das mit ihr nichts zu tun hat. Ein antwortendes Cockpit
    beweist dagegen genau das, was hier gefragt ist (AC-A3).

    Jeder Fehlschlag heisst „antwortet nicht". Das ist die sichere Richtung:
    im Zweifel startet die Bridge, statt sich selbst auszusperren.
    """
    if not ist_lokale_adresse(url):
        return False
    try:
        import httpx

        with httpx.Client(timeout=timeout) as client:
            antwort = client.get(str(url))
        return antwort.status_code < 500
    except Exception as exc:  # noqa: BLE001 - jeder Fehlschlag heisst „nein"
        log.debug("No cockpit answered at %s: %s", url, exc)
        return False


def laufende_instanz(
    client_id: int,
    run_dir: str | Path | None = None,
    timeout: float = LEBENSPRUEFUNG_TIMEOUT_S,
) -> str | None:
    """Die Adresse einer bereits laufenden Bridge, oder nichts.

    Antwortet die hinterlegte Adresse nicht, gilt die Datei als liegengeblieben
    und wird entfernt (AC-D1) — ein abgewuergter Vorgang kommt nicht mehr zum
    Aufraeumen, und seine Datei darf den naechsten Start nicht aufhalten.
    """
    daten = read(client_id, run_dir)
    if daten is None:
        return None
    url = daten.get("url")
    if laeuft_dort_eine(url, timeout):
        return str(url)
    log.info("A stale cockpit run file was left behind; removing it and starting up.")
    remove(client_id, run_dir)
    return None
