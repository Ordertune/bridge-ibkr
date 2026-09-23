"""GitHub-Latest-Release-Check beim Startup.

Silent-fail-Design: wenn GitHub-API nicht erreichbar ist, wird der Bridge-
Client nicht blockiert. Nur ein WARNING-Log, wenn eine neuere Version
verfügbar ist.
"""
from __future__ import annotations

import logging

import httpx

from . import __version__

GITHUB_LATEST_URL = (
    "https://api.github.com/repos/ordertune/bridge-ibkr/releases/latest"
)
RELEASE_PAGE = "https://github.com/ordertune/bridge-ibkr/releases/latest"

log = logging.getLogger(__name__)


def _als_zahlen(fassung: str) -> tuple[int, ...]:
    """`"0.26.0"` → `(0, 26, 0)`. Was sich nicht lesen laesst, wird zu `()`.

    Eine leere Folge ist kleiner als jede andere und faellt damit in den
    Rueckfall unten — raten waere hier schlimmer als schweigen.
    """
    teile: list[int] = []
    for stueck in fassung.split("."):
        ziffern = "".join(c for c in stueck if c.isdigit())
        if not ziffern:
            return ()
        teile.append(int(ziffern))
    return tuple(teile)


def check_for_update(current_version: str = __version__) -> str | None:
    """Die neueste veroeffentlichte Fassung — aber nur, wenn sie NEUER ist.

    ## Der Befund (Owner, 2026-09-23)

    Hier stand `if latest != current_version`. Damit meldete die Bridge jede
    Abweichung als Aktualisierung, auch eine aeltere:

        A newer Bridge version is available: v0.25.2 (you have v0.26.0)

    Gesehen beim ersten Probelauf der fensterlosen EXE, und der Fall ist kein
    Kunstprodukt: er tritt bei jedem Vorabbau auf, also genau dann, wenn jemand
    eine Fassung prueft, die noch nicht veroeffentlicht ist. Die Meldung
    empfiehlt dann, auf einen aelteren Stand zurueckzugehen.

    Die Zusage stand die ganze Zeit im eigenen Kopf dieser Funktion — „if
    newer". Der Code hat sie nur nie eingehalten.
    """
    try:
        with httpx.Client(timeout=5.0) as client:
            r = client.get(GITHUB_LATEST_URL)
            r.raise_for_status()
            latest = str(r.json().get("tag_name", "")).lstrip("v")
        if not latest:
            return None
        hier, dort = _als_zahlen(current_version), _als_zahlen(latest)
        if hier and dort:
            if dort > hier:
                return latest
            return None
        # Laesst sich eine der beiden nicht lesen, bleibt der alte Vergleich —
        # er meldet dann zu viel statt zu wenig, und das ist die richtige
        # Richtung fuer einen Hinweis, der niemanden aufhaelt.
        if latest != current_version:
            return latest
    except Exception as exc:
        log.debug("update-check silent-fail: %s", exc)
    return None


def emit_update_warning_if_any(current_version: str = __version__) -> None:
    latest = check_for_update(current_version)
    if latest:
        log.warning(
            "A newer Bridge version is available: v%s (you have v%s)",
            latest,
            current_version,
        )
        log.warning("Download: %s", RELEASE_PAGE)
        log.warning("Update recommended before next trading day.")
