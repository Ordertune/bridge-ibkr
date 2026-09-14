"""T1-178 — die Kopplung: ein Code statt einer Datei.

## Woher das kommt

Owner-Befund 2026-09-14: die zwei Dateien sind fuer weniger technikaffine
Nutzer die groesste Huerde am Produkt. Das Abfragefenster beim ersten Start gab
es bereits (`run_setup_cockpit`), aber sein erster Schritt verlangte genau das,
was wegfallen sollte — „Download it from Ordertune and paste the whole block".

Weggefallen ist deshalb nicht die Datei, sondern die **Uebergabe**: dass ein
Mensch sie erzeugt, herunterlaedt und transportiert. Die Bridge schreibt sie
jetzt selbst.

## Die Richtung, und warum sie so herum ist

    1. Die Bridge erzeugt ein Geheimnis und BEHAELT es. Sie schickt nur dessen
       SHA-256 an `/pairing/start` und bekommt einen Code zurueck.
    2. Sie zeigt den Code an. Der Nutzer tippt ihn bei t1 ein, wo er
       ANGEMELDET ist, und bestaetigt dort.
    3. Sie fragt `/pairing/claim` — mit dem Code UND dem Geheimnis — und
       bekommt Token und Verbindungskennung.

Damit muss der Code nicht geheim sein. Er sagt nur, WELCHE wartende Bridge
gemeint ist; autorisiert wird durch die angemeldete Sitzung, abgeholt wird nur
von dem, der das Geheimnis hat. Wer den Code mitliest, hat beides nicht.

Die naheliegende Gegenrichtung — t1 zeigt einen Code, die Bridge loest ihn ein
— macht ihn zum Inhaber-Geheimnis: wer ihn mitliest, koppelt seine eigene
Maschine.

## Was diese Datei NICHT tut

Sie fasst die IBKR-Verbindung nicht an und wendet nichts an. Sie schreibt
`bridge.env` und sagt, dass ein Neustart faellig ist — dieselbe Richtungsregel
wie im ganzen Assistenten.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
from pathlib import Path
from typing import Any

import httpx

from . import __version__, env_file
from .fingerprint import compute_fingerprint

log = logging.getLogger(__name__)

TIMEOUT_S = 15.0

# Was der Nutzer sieht, waehrend er abtippt. Muss mit `FINGERPRINT_DISPLAY_LENGTH`
# auf der Plattform uebereinstimmen — die beiden Seiten zeigen denselben
# Ausschnitt, sonst kann niemand vergleichen, und der Vergleich ist der ganze
# Riegel gegen Kopplungs-Phishing.
FINGERPRINT_DISPLAY_LENGTH = 16


def generate_verifier() -> str:
    """256 Bit, base64url. Verlaesst diese Maschine nie."""
    roh = os.urandom(32)
    return base64.urlsafe_b64encode(roh).decode("ascii").rstrip("=")


def sha256_hex(wert: str) -> str:
    return hashlib.sha256(wert.encode("utf-8")).hexdigest()


def hostname() -> str:
    import platform

    return platform.node() or "unknown-host"


def start(base_url: str) -> dict[str, Any]:
    """Eine Kopplung anfordern. Gibt Code und Geheimnis zurueck.

    Das Geheimnis geht an den Aufrufer und nicht auf die Leitung — der Server
    bekommt nur seinen Hash.
    """
    verifier = generate_verifier()
    fp = compute_fingerprint()
    url = f"{base_url.rstrip('/')}/api/bridge/v1/pairing/start"

    try:
        with httpx.Client(timeout=TIMEOUT_S) as client:
            r = client.post(
                url,
                json={
                    "bridgeVersion": __version__,
                    "hostname": hostname(),
                    "fingerprint": fp,
                    "verifierHash": sha256_hex(verifier),
                },
            )
            r.raise_for_status()
            daten = r.json()
    except Exception as exc:  # noqa: BLE001 - jeder Fehlschlag ist hier dasselbe:
        # die Plattform hat nicht geantwortet. `classify_handshake_error` macht
        # daraus einen Satz, den der Nutzer lesen kann — Netzfehler, falsche
        # Adresse und abgewiesener Aufruf laufen alle dort zusammen.
        from .failures import classify_handshake_error

        f = classify_handshake_error(exc, base_url)
        return {"ok": False, "message": f.headline, "action": list(f.action)}

    return {
        "ok": True,
        "code": daten.get("code", ""),
        "expires_in": daten.get("expiresInSeconds", 600),
        "verifier": verifier,
        "fingerprint_prefix": fp[:FINGERPRINT_DISPLAY_LENGTH],
        "hostname": hostname(),
    }


def claim(base_url: str, code: str, verifier: str) -> dict[str, Any]:
    """Nachfragen, ob der Nutzer bestaetigt hat.

    Drei Ausgaenge, und `pending` ist der haeufigste — er heisst „warte weiter"
    und ist kein Fehler.
    """
    url = f"{base_url.rstrip('/')}/api/bridge/v1/pairing/claim"
    try:
        with httpx.Client(timeout=TIMEOUT_S) as client:
            r = client.post(url, json={"code": code, "verifier": verifier})
            r.raise_for_status()
            daten = r.json()
    except Exception as exc:  # noqa: BLE001 - siehe `start`: ein Abruf, der nicht
        # durchkommt, ist fuer den Nutzer ein einziger Fall.
        from .failures import classify_handshake_error

        f = classify_handshake_error(exc, base_url)
        return {"ok": False, "status": "error", "message": f.headline}

    status = daten.get("status")
    if status == "ready":
        return {
            "ok": True,
            "status": "ready",
            "token": daten.get("token", ""),
            "connection_id": daten.get("connectionId", ""),
        }
    if status == "pending":
        return {"ok": True, "status": "pending"}
    return {"ok": True, "status": "unknown"}


# ── Die Datei schreiben ──────────────────────────────────────────────────────

_VORLAGE = """\
# ============================================================================
# Ordertune Bridge configuration
# ----------------------------------------------------------------------------
# Written by the Bridge itself when you paired this machine. Keep it in the
# SAME folder as the program.
#
# The identity block below was issued by Ordertune. Do not edit it by hand --
# if you need new credentials, pair this machine again from
# Settings -> Broker.
# ============================================================================

# ----------------------------------------------------------------------------
# Ordertune identity  (ISSUED BY PAIRING -- do not edit)
# ----------------------------------------------------------------------------
ORDERTUNE_API_BASE={api_base}
ORDERTUNE_BRIDGE_TOKEN={token}
ORDERTUNE_BRIDGE_CONNECTION_ID={connection_id}

# ----------------------------------------------------------------------------
# IBKR local socket  (USER EDITABLE)
# ----------------------------------------------------------------------------
# The Bridge talks to Trader Workstation (TWS) or IB Gateway over a local
# socket. It never sends your IBKR credentials anywhere -- TWS/Gateway must be
# started and logged in separately.
#
#   TWS      paper 7497 / live 7496
#   Gateway  paper 4002 / live 4001
IBKR_GATEWAY_HOST=127.0.0.1
IBKR_GATEWAY_PORT={port}
IBKR_TRADING_MODE=paper

# Each program connected to one TWS/Gateway needs a unique id.
IBKR_CLIENT_ID={client_id}

# ----------------------------------------------------------------------------
# Optional behavior tweaks  (USER EDITABLE)
# ----------------------------------------------------------------------------
ORDER_SUBMIT_DELAY_MS=100
LOG_LEVEL={log_level}
UPDATE_CHECK_ENABLED={update_check}
"""


def write_credentials(
    path: Path,
    *,
    api_base: str,
    token: str,
    connection_id: str,
) -> dict[str, Any]:
    """Die Zugangsdaten in `bridge.env` schreiben.

    ## Zwei Faelle, und der zweite ist der wichtigere

    **Datei existiert schon** — dann werden NUR die drei Identitaetszeilen
    ersetzt, ueber `env_file.apply_changes`. Alles andere bleibt, wie es ist:
    Port, Client-ID, Protokollstufe, und jeder Kommentar, den der Nutzer
    hineingeschrieben hat. Wer seinen Gateway-Port auf 4001 gestellt hat, soll
    ihn nach einer erneuten Kopplung nicht wieder suchen muessen.

    **Datei existiert nicht** — dann eine frische Vorlage mit den Vorgaben.

    Die Vorlage ist bewusst kuerzer als die, die der Server beim Dateiweg
    erzeugt. Sie hat einen anderen Zweck: dort ist sie eine ANLEITUNG fuer
    jemanden, der die Datei gleich von Hand an ihren Platz legt, hier ist sie
    das Ergebnis eines Vorgangs, der bereits gefuehrt hat. Die ausfuehrliche
    Fassung steht weiterhin hinter dem Download.
    """
    aenderungen = {
        "ORDERTUNE_API_BASE": api_base,
        "ORDERTUNE_BRIDGE_TOKEN": token,
        "ORDERTUNE_BRIDGE_CONNECTION_ID": connection_id,
    }

    try:
        if path.exists():
            alt = path.read_text(encoding="utf-8")
            neu = env_file.apply_changes(alt, aenderungen)
        else:
            neu = _VORLAGE.format(
                api_base=api_base,
                token=token,
                connection_id=connection_id,
                port="7497",
                client_id="17",
                log_level="INFO",
                update_check="true",
            )
        env_file.write_atomic(path, neu)
    except OSError as exc:
        return {"ok": False, "message": f"Could not write bridge.env: {exc}"}

    log.info("bridge.env written from a pairing.")
    return {"ok": True, "message": "Paired. bridge.env written."}
