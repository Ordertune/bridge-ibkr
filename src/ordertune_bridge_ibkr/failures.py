"""T1-101 A-2 — jeder bekannte Startfehler bekommt einen Satz und eine Handlung.

## Warum es diesen Baustein gibt

Bis 0.6.0 endete der Start an drei Stellen mit `return 1`. Was dabei zu lesen
war, war entweder eine Ausnahme im Rohtext (`bridge.env invalid: 2 validation
errors for BridgeConfig ...`) oder eine Zeile, die den Zustand beschreibt statt
den Ausweg (`Handshake failed: Client error '403 Forbidden'`).

Gebaut wird mit `--console`. Bei einem Doppelklick schliesst Windows das Fenster
mit dem Vorgang — die Zeile erscheint fuer einen Sekundenbruchteil und ist dann
fort. Aus Nutzersicht: „ich klicke drauf und es passiert nichts".

Hier steht deshalb die Zuordnung von Ursache zu Klartext und Handlung, und zwar
**genau einmal**: die Konsole liest sie (A-1) und spaeter das Cockpit (B-4).
Zwei Fassungen hiessen der Tag, an dem Konsole und Fenster ueber dieselbe
Stoerung Verschiedenes sagen.

## Zwei Regeln, die hier tragen

**Nur ASCII.** Die Windows-Konsole laeuft je nach Gebietsschema auf einer
Codepage ohne Rahmenzeichen und ohne Pfeile. Ein `UnicodeEncodeError` beim
Ausgeben der Fehlermeldung waere die Fehlermeldung, die es zu vermeiden gilt.

**Kein Wert eines Geheimnisses.** Ein zu kurzer Token ist ein haeufiger Fehler,
und die Versuchung ist gross, den gelesenen Wert zur Erklaerung mit auszugeben.
Er landete damit in der Konsole, im Protokoll und im naechsten Screenshot an
den Support. Die Laenge genuegt zur Diagnose.

Nutzertexte sind englisch, wie alle Nutzertexte des Clients.
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

# Fuer den Fall, dass keine Konfiguration geladen werden konnte und die
# Basis-URL damit unbekannt ist.
DEFAULT_API_BASE = "https://t1.ordertune.com"

RELEASES_URL = "https://github.com/Ordertune/bridge-ibkr/releases/latest"

# Feldnamen, deren Wert nie ausgegeben wird — auch nicht zur Fehlererklaerung.
_SECRET_FIELDS = frozenset({"ordertune_bridge_token"})


def settings_url(api_base: str | None = None) -> str:
    """Der Broker-Reiter in Ordertune — Ziel fast jeder Handlungsempfehlung."""
    base = (api_base or DEFAULT_API_BASE).rstrip("/")
    return f"{base}/settings?tab=broker"


@dataclass(frozen=True)
class Failure:
    """Ein benannter Startfehler.

    `code` ist die stabile Kennung. Sie wandert spaeter unveraendert in den
    Zustandsblock des Cockpits, damit die Flaeche dieselbe Stoerung an
    derselben Kennung erkennt wie die Konsole.
    """

    code: str
    headline: str
    detail: tuple[str, ...] = field(default_factory=tuple)
    action: tuple[str, ...] = field(default_factory=tuple)


# ── Konfiguration ────────────────────────────────────────────────────────────


def _redacted(field_name: str, value: Any) -> str:
    """Der gelesene Wert — bei Geheimnissen nur seine Laenge."""
    if field_name in _SECRET_FIELDS:
        try:
            return f"<{len(str(value))} characters>"
        except Exception:  # pragma: no cover - defensiv
            return "<hidden>"
    text = str(value)
    return text if len(text) <= 60 else text[:57] + "..."


def _pydantic_lines(errors: Iterable[dict[str, Any]]) -> tuple[str, ...]:
    """Je Feld eine Zeile: Name wie in der Datei, Erwartung, gelesener Wert."""
    lines: list[str] = []
    for err in errors:
        loc = err.get("loc") or ("<unknown>",)
        field_name = str(loc[0])
        msg = str(err.get("msg", "invalid"))
        if err.get("type") == "missing":
            # Bei `missing` ist `input` der ganze gelesene Datensatz, nicht der
            # Wert des Feldes. Ihn auszugeben waere irrefuehrend — und bei einem
            # Datensatz mit Token auch noch gefaehrlich.
            lines.append(f"  {field_name.upper()}: missing")
            continue
        got = _redacted(field_name, err.get("input"))
        lines.append(f"  {field_name.upper()}: {msg} (got: {got})")
    return tuple(lines)


def classify_config_error(
    exc: Exception,
    env_path: str,
    env_exists: bool,
) -> Failure:
    """Fehlt die Datei, oder steht etwas Falsches darin?

    Die Unterscheidung ist nicht kosmetisch. Fehlt `bridge.env` ganz, meldet
    Pydantic „Field required" fuer Token und Connection-ID — dieselbe Meldung
    wie bei einer vorhandenen Datei, in der beide Zeilen fehlen. Ohne den Blick
    auf das Dateisystem waeren die beiden Faelle nicht auseinanderzuhalten, und
    der Nutzer bekaeme im haeufigsten Fall ueberhaupt die falsche Auskunft.
    """
    if not env_exists:
        return Failure(
            code="env_missing",
            headline="bridge.env was not found.",
            detail=(f"  Looked for: {env_path}",),
            action=(
                "Download the pre-filled bridge.env from Ordertune and place it",
                "in the same folder as this program:",
                f"  {settings_url()}",
                "",
                "The file must be named exactly bridge.env. Windows hides known",
                "file extensions by default, so a file shown as 'bridge' may",
                "actually be bridge.env.txt.",
            ),
        )

    errors: list[dict[str, Any]] = []
    getter = getattr(exc, "errors", None)
    if callable(getter):
        try:
            errors = list(getter())
        except Exception:  # pragma: no cover - defensiv
            errors = []

    detail = (f"  File: {env_path}",)
    detail += _pydantic_lines(errors) if errors else (f"  {exc}",)

    return Failure(
        code="env_invalid",
        headline="bridge.env was found, but a value is missing or invalid.",
        detail=detail,
        action=(
            "Fix the listed line, or download a fresh pre-filled bridge.env:",
            f"  {settings_url()}",
        ),
    )


# ── IBKR TWS / Gateway ───────────────────────────────────────────────────────


def classify_connect_error(
    host: str,
    port: int,
    exc: Exception,
    answering: tuple[tuple[int, str], ...] = (),
    client_id: int | None = None,
) -> Failure:
    """Kein Socket, falscher Socket, oder Socket ohne API-Freigabe?

    `answering` ist das Ergebnis der Portsuche (A-3): die Standardports, auf
    denen sich ueberhaupt etwas meldet, je mit Beschriftung.

    **Ein offener Socket ist kein Beweis fuer TWS.** Der Text sagt deshalb
    „something answers on 7496" und nicht „TWS runs on 7496" — auf dem Port
    koennte irgendein anderer Dienst liegen, und eine falsche Gewissheit
    schickt den Nutzer in die falsche Richtung.
    """
    others = tuple((p, label) for p, label in answering if p != port)
    configured_answers = any(p == port for p, _ in answering)

    if configured_answers:
        return Failure(
            code="tws_api_refused",
            headline=(
                f"Something answers on {host}:{port}, but the API connection "
                "was refused."
            ),
            detail=(
                f"  {exc}",
                "",
                "  The two usual causes:",
                "  - 'Enable ActiveX and Socket Clients' is off in TWS.",
                "  - Client id "
                + (f"{client_id} is " if client_id is not None else "is ")
                + "already used by another API connection",
                "    to the same TWS or Gateway.",
            ),
            action=(
                "In TWS: File -> Global Configuration -> API -> Settings.",
                "In IB Gateway: Configure -> Settings -> API.",
                "Enable 'ActiveX and Socket Clients', keep 'Read-Only API' off,",
                "and allow 127.0.0.1 as a trusted IP. Restart TWS afterwards.",
                "",
                "If the setting is already on, change IBKR_CLIENT_ID in",
                "bridge.env to a value no other connection uses.",
            ),
        )

    if others:
        listed = ", ".join(f"{p} ({label})" for p, label in others)
        return Failure(
            code="tws_wrong_port",
            headline=f"Nothing answers on port {port}, but something does elsewhere.",
            detail=(
                f"  bridge.env says:  IBKR_GATEWAY_PORT={port}",
                f"  Answering ports:  {listed}",
                "",
                "  An open port is not proof that TWS is behind it, but on this",
                "  machine it is the most likely explanation.",
            ),
            action=(
                "Check the socket port in TWS (File -> Global Configuration ->",
                "API -> Settings) and set IBKR_GATEWAY_PORT in bridge.env to",
                "that number.",
                "",
                "IBKR defaults: TWS 7497 paper / 7496 live,",
                "               IB Gateway 4002 paper / 4001 live.",
                "The port is a setting -- it does not follow from the account.",
            ),
        )

    return Failure(
        code="tws_unreachable",
        headline=f"No connection to TWS or IB Gateway at {host}:{port}.",
        detail=(
            f"  {exc}",
            "",
            "  None of the four IBKR default ports answered on this machine,",
            "  so TWS or IB Gateway is most likely not running.",
        ),
        action=(
            "Start TWS or IB Gateway and log in, then start the Bridge again.",
            "",
            "Note that IBKR logs TWS out daily around 05:00 CET. For unattended",
            "operation use IBC so it logs back in automatically.",
        ),
    )


# ── Ordertune-Plattform ──────────────────────────────────────────────────────

_HANDSHAKE_BY_CODE: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "invalid_token": (
        "token_invalid",
        "Ordertune rejected the access token.",
        (
            "Generate a fresh token in Ordertune and download the new",
            "bridge.env. The plain token is shown only once.",
        ),
    ),
    "missing_token": (
        "token_invalid",
        "The request carried no access token.",
        (
            "ORDERTUNE_BRIDGE_TOKEN is empty or malformed in bridge.env.",
            "Download a fresh pre-filled file.",
        ),
    ),
    "connection_revoked": (
        "connection_revoked",
        "This bridge connection was revoked in Ordertune.",
        (
            "Create a new connection in Ordertune, download the new",
            "bridge.env and replace the old one.",
        ),
    ),
    "ip_mismatch": (
        "ip_mismatch",
        "This bridge is running from a different network than when it registered.",
        (
            "The connection is bound to the source IP of its first handshake.",
            "Run the Bridge on a VPS with a fixed outbound IP, or rotate the",
            "token to register the current network.",
        ),
    ),
    "fingerprint_mismatch": (
        "fingerprint_mismatch",
        "This bridge is running on different hardware than when it registered.",
        (
            "Rotate the token in Ordertune. That clears the stored hardware",
            "fingerprint, and the next handshake registers this machine.",
        ),
    ),
    "fingerprint_already_set": (
        "fingerprint_already_set",
        "This token already belongs to another machine.",
        (
            "Rotate the token in Ordertune and download the new bridge.env.",
            "Do not run two bridges from one token -- give each machine its own.",
        ),
    ),
    "missing_fingerprint": (
        "fingerprint_missing",
        "The request carried no hardware fingerprint.",
        (
            "This build could not identify the machine. Download the current",
            f"release: {RELEASES_URL}",
        ),
    ),
    "rate_limited": (
        "rate_limited",
        "Ordertune is rate limiting this connection.",
        (
            "Wait a minute and start the Bridge again. If it repeats, more",
            "than one bridge is probably using the same connection.",
        ),
    ),
}


def _error_code_from_body(body: str) -> str | None:
    """Die Plattform antwortet mit {error: {code, message}}."""
    try:
        parsed = json.loads(body)
    except Exception:
        return None
    if not isinstance(parsed, dict):
        return None
    err = parsed.get("error")
    if isinstance(err, dict) and isinstance(err.get("code"), str):
        return err["code"]
    return None


def classify_handshake_error(exc: Exception, api_base: str | None = None) -> Failure:
    """Die Antwort der Plattform in einen Satz und eine Handlung uebersetzen."""
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)

    if status is None:
        # Kein HTTP-Status: die Plattform war gar nicht erreichbar.
        return Failure(
            code="platform_unreachable",
            headline="Ordertune could not be reached.",
            detail=(f"  {exc}", f"  Server: {api_base or DEFAULT_API_BASE}"),
            action=(
                "Check that this machine has internet access and that no proxy",
                "or firewall blocks outbound HTTPS. The Bridge only makes",
                "outbound connections -- no inbound port is needed.",
            ),
        )

    body = ""
    try:
        body = response.text or ""
    except Exception:  # pragma: no cover - defensiv
        body = ""

    known = _HANDSHAKE_BY_CODE.get(_error_code_from_body(body) or "")
    if known is not None:
        code, headline, action = known
        return Failure(
            code=code,
            headline=headline,
            detail=(f"  Server answered {status}.",),
            action=action + ("", f"  {settings_url(api_base)}"),
        )

    if status == 422:
        return Failure(
            code="wire_contract_mismatch",
            headline="This Bridge build and the Ordertune server disagree on the message format.",
            detail=(
                f"  Server answered {status}.",
                "  Restarting will not fix it.",
            ),
            action=("Update the Bridge to the current release:", f"  {RELEASES_URL}"),
        )

    return Failure(
        code="handshake_failed",
        headline=f"Ordertune refused the handshake (HTTP {status}).",
        detail=(f"  {body[:200]}" if body else f"  {exc}",),
        action=(
            "Check the Broker tab in Ordertune. If the connection looks healthy",
            "there, rotate the token and download a fresh bridge.env:",
            f"  {settings_url(api_base)}",
        ),
    )


# ── Darstellung ──────────────────────────────────────────────────────────────

_WIDTH = 72
_RULE = "=" * _WIDTH


def render(failure: Failure, log_path: str | None = None) -> str:
    """Der gerahmte Block fuer die Konsole.

    Bewusst ohne Rahmenzeichen jenseits von ASCII — siehe Modul-Docstring.
    """
    lines: list[str] = [
        "",
        _RULE,
        "  BRIDGE COULD NOT START",
        _RULE,
        "",
        "  WHAT HAPPENED",
        f"  {failure.headline}",
    ]
    if failure.detail:
        lines.append("")
        lines.extend(failure.detail)
    if failure.action:
        lines.extend(["", "  WHAT TO DO"])
        lines.extend(f"  {line}" if line else "" for line in failure.action)
    if log_path:
        lines.extend(["", f"  Log file: {log_path}"])
    lines.extend(["", f"  Reference: {failure.code}", _RULE, ""])

    # Der letzte Riegel. Die eigenen Texte sind ASCII, aber in `detail` steckt
    # gelegentlich der Text einer fremden Ausnahme oder ein Dateipfad, und ein
    # `UnicodeEncodeError` beim Ausgeben einer Fehlermeldung waere ausgerechnet
    # der Fehler, den dieser Baustein verhindern soll.
    return "\n".join(lines).encode("ascii", "replace").decode("ascii")
