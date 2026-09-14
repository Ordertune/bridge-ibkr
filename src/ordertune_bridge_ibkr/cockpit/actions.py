"""T1-101 C-5 — die Aenderungsablage zwischen Flaeche und Kern.

Die Flaeche schickt einen Wunsch, dieser Baustein schreibt `bridge.env` und
vermerkt, dass ein Neustart noetig ist. **Angewandt wird nichts**: die
IBKR-Verbindung gehoert dem Hauptthread, und ein Wiederaufbau aus einem
Server-Thread heraus ist die Fehlerklasse, gegen die T1-88 die Schleife
ueberhaupt auf einen einzigen Thread gelegt hat.

## Warum „Restart to apply" und nicht „Apply and reconnect"

Der Spec sah einen Knopf „Apply and reconnect" vor. Beim Bauen ist daraus ein
Speichern mit Neustart-Hinweis geworden, und das ist die ehrlichere Bauform:
ein Wiederaufbau mitten im Betrieb muesste die Schleife anhalten, die
Rueckrufe abhaengen, neu verbinden und die Auftragszuordnung neu aufbauen —
vier Schritte, von denen jeder einzelne einen laufenden Auftrag verlieren
kann. Ein Neustart macht dasselbe, nur belegt und auf einem Weg, der taeglich
gegangen wird: IBKR meldet TWS gegen 05:00 MEZ ohnehin ab.

## Der Riegel

Gespeichert wird nicht, solange ein Auftrag unquittiert unterwegs ist. Eine
geaenderte Client-ID oder ein geaenderter Port waehrend eines lebenden
Auftrags heisst beim naechsten Start: die Verbindung findet ihn nicht mehr.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from . import setup as setup_mod

log = logging.getLogger(__name__)


class SetupActions:
    """Was die Flaeche ausloesen darf. Mehr gibt es nicht."""

    def __init__(
        self,
        env_path: Path,
        *,
        store: Any = None,
        orders_in_flight: Callable[[], bool] | None = None,
        api_base: str = "",
    ) -> None:
        self._env_path = env_path
        self._store = store
        self._in_flight = orders_in_flight or (lambda: False)
        self._api_base = api_base
        # T1-178: das Geheimnis der laufenden Kopplung. Es lebt ausschliesslich
        # hier im Arbeitsspeicher — auf die Leitung geht nur sein SHA-256, und
        # auf die Platte gar nichts. Ein Neustart des Assistenten verwirft es,
        # und das ist richtig: der zugehoerige Code ist dann ohnehin wertlos.
        self._pairing: dict[str, str] | None = None

    # ── Lesen ────────────────────────────────────────────────────────────

    def config(self) -> dict[str, Any]:
        return setup_mod.current_values(self._env_path)

    # ── Pruefen (aendert nichts) ─────────────────────────────────────────

    def probe(self, body: dict[str, Any]) -> dict[str, Any]:
        host = str(body.get("host") or "127.0.0.1")
        if body.get("port"):
            return setup_mod.check_socket(host, int(body["port"]))
        return setup_mod.probe_ports(host)

    def verify(self, _body: dict[str, Any]) -> dict[str, Any]:
        werte = setup_mod.env_file.parse(
            self._env_path.read_text(encoding="utf-8")
            if self._env_path.exists()
            else ""
        )
        token = werte.get("ORDERTUNE_BRIDGE_TOKEN", "")
        connection = werte.get("ORDERTUNE_BRIDGE_CONNECTION_ID", "")
        if not token or not connection:
            return {"ok": False, "message": "bridge.env carries no credentials yet."}
        base = werte.get("ORDERTUNE_API_BASE") or self._api_base or "https://t1.ordertune.com"
        return setup_mod.check_handshake(base, token, connection)

    # ── T1-178: die Kopplung ─────────────────────────────────────────────

    def pair_start(self, _body: dict[str, Any]) -> dict[str, Any]:
        """Einen Kopplungscode anfordern und ihn anzeigen lassen."""
        from .. import pairing

        basis = self._basis()
        ergebnis = pairing.start(basis)
        if not ergebnis.get("ok"):
            return ergebnis

        self._pairing = {
            "code": ergebnis["code"],
            "verifier": ergebnis["verifier"],
            "base": basis,
        }
        # Das Geheimnis verlaesst diesen Vorgang nicht — die Flaeche braucht es
        # nicht und soll es nicht haben.
        return {
            "ok": True,
            "code": ergebnis["code"],
            "expires_in": ergebnis["expires_in"],
            "hostname": ergebnis["hostname"],
            "fingerprint_prefix": ergebnis["fingerprint_prefix"],
        }

    def pair_poll(self, _body: dict[str, Any]) -> dict[str, Any]:
        """Hat der Nutzer bestaetigt? Wenn ja, `bridge.env` schreiben."""
        from .. import pairing

        if self._pairing is None:
            return {"ok": False, "status": "error", "message": "No pairing is running."}

        ergebnis = pairing.claim(
            self._pairing["base"], self._pairing["code"], self._pairing["verifier"]
        )
        if not ergebnis.get("ok"):
            return ergebnis
        if ergebnis["status"] != "ready":
            return ergebnis

        geschrieben = pairing.write_credentials(
            self._env_path,
            api_base=self._pairing["base"],
            token=ergebnis["token"],
            connection_id=ergebnis["connection_id"],
        )
        # Das Geheimnis ist verbraucht. Es stehen zu lassen hiesse, einen
        # zweiten Abruf zu ermoeglichen, den es nicht geben kann — die Zeile ist
        # auf der Plattform bereits geloescht.
        self._pairing = None

        if not geschrieben.get("ok"):
            return {"ok": False, "status": "error", "message": geschrieben["message"]}

        self._mark_restart_pending()

        return {"ok": True, "status": "ready", "message": geschrieben["message"]}

    def _basis(self) -> str:
        """Gegen welche Adresse gekoppelt wird."""
        from .. import env_file

        try:
            werte = env_file.parse(self._env_path.read_text(encoding="utf-8"))
        except OSError:
            werte = {}
        return (
            werte.get("ORDERTUNE_API_BASE")
            or self._api_base
            or "https://t1.ordertune.com"
        )

    # ── Schreiben ────────────────────────────────────────────────────────

    def save(self, body: dict[str, Any]) -> dict[str, Any]:
        if self._in_flight():
            return {
                "ok": False,
                "message": (
                    "An order is still in flight. Changing the port or the "
                    "client id now would leave it unreachable after the next "
                    "start. Wait until it is settled."
                ),
            }
        changes = {str(k): str(v) for k, v in (body.get("changes") or {}).items()}
        if not changes:
            return {"ok": False, "message": "Nothing to change."}
        ergebnis = setup_mod.save_settings(
            self._env_path, changes, str(body.get("baseline") or "")
        )
        if ergebnis.get("ok"):
            self._mark_restart_pending()
        return ergebnis

    def replace(self, body: dict[str, Any]) -> dict[str, Any]:
        ergebnis = setup_mod.replace_credentials(
            self._env_path, str(body.get("content") or "")
        )
        if ergebnis.get("ok"):
            self._mark_restart_pending()
        return ergebnis

    def _mark_restart_pending(self) -> None:
        if self._store is None:
            return
        try:
            self._store.update(pending_restart=True)
        except Exception as exc:  # pragma: no cover - defensiv
            log.debug("Could not mark the restart as pending: %s", exc)
