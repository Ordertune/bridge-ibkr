"""T1-101 C — die Handlungen hinter dem Assistenten und den Einstellungen.

## Die Richtungsregel gilt auch hier

Der Server **wendet nichts an**. Er schreibt `bridge.env` und vermerkt, dass
ein Neustart noetig ist. Die IBKR-Verbindung fasst er nie an — ein
Wiederaufbau mitten in einer laufenden Schleife, aus einem fremden Thread
heraus, ist genau die Fehlerklasse, gegen die T1-88 die Schleife auf einen
einzigen Thread gelegt hat.

Deshalb hier reine Funktionen mit klaren Rueckgabewerten, und die Bewertung
ausserhalb des Netzwerks pruefbar.

## Warum die Verbindungspruefung nur klopft

Schritt 3 des Assistenten stellt **keine** API-Verbindung her. Ein
`ib_insync`-Client aus einem Server-Thread braeuchte dort seine eigene
Ereignisschleife, und ein haengender Verbindungsversuch in einer Anfrage waere
ein Fenster, das nicht mehr antwortet. Geklopft wird auf dem Socket — das
beantwortet die Frage, die an dieser Stelle offen ist („liegt TWS auf dem Port,
den ich eingetragen habe?"), und die vollstaendige Pruefung liefert der Start
der Bridge wenige Sekunden spaeter ins Cockpit.

Schritt 4 dagegen ist echt: der Handshake gegen die Plattform ist ein
gewoehnlicher HTTPS-Aufruf und damit gefahrlos.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx

from .. import env_file, port_probe
from ..fingerprint import compute_fingerprint

log = logging.getLogger(__name__)

HANDSHAKE_TIMEOUT_S = 10.0


def probe_ports(host: str = "127.0.0.1") -> dict[str, Any]:
    """C-1 Schritt 2 — welche der vier Standardports antworten?"""
    gefunden = port_probe.scan(host)
    return {
        "answering": [{"port": p, "label": label} for p, label in gefunden],
        "known": [{"port": p, "label": label} for p, label in port_probe.KNOWN_PORTS],
    }


def check_socket(host: str, port: int) -> dict[str, Any]:
    """C-1 Schritt 3 — liegt auf diesem Port ueberhaupt etwas?"""
    antwortet = port_probe.port_answers(host, port)
    if antwortet:
        return {
            "ok": True,
            "message": (
                f"Something is listening on {host}:{port}. The full API check "
                "runs when the Bridge starts and shows up here within seconds."
            ),
        }
    andere = port_probe.scan(host)
    if andere:
        liste = ", ".join(f"{p} ({label})" for p, label in andere)
        return {
            "ok": False,
            "message": f"Nothing on {port}. Answering ports: {liste}.",
        }
    return {
        "ok": False,
        "message": (
            f"Nothing answers on {host}:{port}, and none of the IBKR default "
            "ports answered either. Start TWS or IB Gateway and log in."
        ),
    }


def check_handshake(base_url: str, token: str, connection_id: str) -> dict[str, Any]:
    """C-1 Schritt 4 — nimmt die Plattform diese Zugangsdaten an?

    Ein gewoehnlicher HTTPS-Aufruf gegen denselben Weg, den die Bridge beim
    Start geht. Er registriert den Fingerabdruck dieser Maschine, wenn er noch
    nicht gesetzt ist — genau das, was beim ersten Start ohnehin passiert.
    """
    from ..failures import classify_handshake_error

    url = f"{base_url.rstrip('/')}/api/bridge/v1/handshake-status"
    try:
        with httpx.Client(timeout=HANDSHAKE_TIMEOUT_S) as client:
            r = client.get(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Bridge-Connection-Id": connection_id,
                    "X-Bridge-Fingerprint": compute_fingerprint(),
                },
            )
            r.raise_for_status()
        return {"ok": True, "message": "Ordertune accepted these credentials."}
    except Exception as exc:
        f = classify_handshake_error(exc, base_url)
        return {
            "ok": False,
            "code": f.code,
            "message": f.headline,
            "action": list(f.action),
        }


def save_settings(
    path: Path, changes: dict[str, str], baseline: str
) -> dict[str, Any]:
    """C-2/C-4/C-5 — schreiben, aber nur, wenn niemand dazwischengekommen ist.

    `baseline` ist der Abdruck der Datei, den die Flaeche beim Laden bekommen
    hat. Weicht er ab, wurde nebenher im Editor gearbeitet — dann wird nicht
    ueberschrieben, sondern gefragt.
    """
    verboten = [k for k in changes if k.upper() not in env_file.EDITABLE]
    if verboten:
        # D9: Token und Connection-ID werden nie getippt. Ein von Hand
        # gekuerzter Token erzeugt `invalid_token` ohne jeden Hinweis auf die
        # Ursache — diese Fehlerklasse entsteht erst durch ein Eingabefeld.
        return {"ok": False, "message": f"Not editable here: {', '.join(verboten)}"}

    if not path.exists():
        return {"ok": False, "message": "bridge.env is missing."}

    jetzt = env_file.fingerprint(path)
    if baseline and jetzt and baseline != jetzt:
        return {
            "ok": False,
            "conflict": True,
            "message": (
                "bridge.env changed on disk since this page loaded. Reload the "
                "page to see the current values, then apply your change again."
            ),
        }

    try:
        text = path.read_text(encoding="utf-8")
        env_file.write_atomic(path, env_file.apply_changes(text, changes))
    except OSError as exc:
        return {"ok": False, "message": f"Could not write bridge.env: {exc}"}

    log.info("bridge.env updated from the cockpit: %s", ", ".join(sorted(changes)))
    return {
        "ok": True,
        "fingerprint": env_file.fingerprint(path),
        "message": "Saved. Restart the Bridge to apply.",
    }


def replace_credentials(path: Path, content: str) -> dict[str, Any]:
    """C-3 — eine frische `bridge.env` ablegen, statt Zugangsdaten zu tippen."""
    werte = env_file.parse(content)
    fehlend = [
        k
        for k in ("ORDERTUNE_BRIDGE_TOKEN", "ORDERTUNE_BRIDGE_CONNECTION_ID")
        if not werte.get(k)
    ]
    if fehlend:
        return {
            "ok": False,
            "message": (
                "That does not look like a bridge.env from Ordertune - "
                f"missing: {', '.join(fehlend)}."
            ),
        }
    try:
        env_file.write_atomic(path, content if content.endswith("\n") else content + "\n")
    except OSError as exc:
        return {"ok": False, "message": f"Could not write bridge.env: {exc}"}

    log.info("bridge.env replaced from the cockpit.")
    return {
        "ok": True,
        "fingerprint": env_file.fingerprint(path),
        "message": "bridge.env written.",
    }


def current_values(path: Path) -> dict[str, Any]:
    """Was die Einstellungen anzeigen — der Token nur als Endung (D9)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {"exists": False, "values": {}, "fingerprint": ""}
    return {
        "exists": True,
        "values": env_file.redacted(env_file.parse(text)),
        "fingerprint": env_file.fingerprint(path),
        "editable": list(env_file.EDITABLE),
        "ports": [{"port": p, "label": label} for p, label in port_probe.KNOWN_PORTS],
    }
