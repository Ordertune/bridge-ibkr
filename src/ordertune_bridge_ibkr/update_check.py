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


def check_for_update(current_version: str = __version__) -> str | None:
    """Return the latest release version string if newer, else None."""
    try:
        with httpx.Client(timeout=5.0) as client:
            r = client.get(GITHUB_LATEST_URL)
            r.raise_for_status()
            latest = str(r.json().get("tag_name", "")).lstrip("v")
        if not latest:
            return None
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
