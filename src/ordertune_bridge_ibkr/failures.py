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

    # T1-184 — die Handlung fuer die Flaeche, auf der der Kopplungsknopf steht.
    #
    # `action` beantwortet „was tun" fuer jemanden, der **keinen Knopf** vor
    # sich hat: den gerahmten Konsolen-Abbruch und die Karte im laufenden
    # Cockpit. Dort ist der Verweis auf die Website die einzig moegliche
    # Antwort, und er bleibt unveraendert richtig.
    #
    # Im Assistenten steht derselbe Text ueber einem Knopf, der genau das
    # erledigt — und sagte bis 0.23.3 „download the new bridge.env", drei
    # Zentimeter ueber „Nothing to download, nothing to copy between windows".
    # Die Karte argumentierte gegen den Knopf.
    #
    # Deshalb zwei Angaben statt einer Zeichenkette fuer beide Flaechen: hier
    # steht nur noch der ZUSTAND, das Was-tun traegt der Knopf. Leer heisst
    # „diese Stoerung erreicht den Assistenten nicht" — dann faellt die
    # Darstellung auf `action` zurueck und nichts aendert sich.
    action_paired: tuple[str, ...] = field(default_factory=tuple)


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


# T1-214 — ein Feld, zwei erlaubte Schreibweisen.
#
# Seit `IBKR_TWS_PORT` die neue und `IBKR_GATEWAY_PORT` die weiterhin gueltige
# alte Schreibweise ist, entscheidet **Pydantic**, welche der beiden im
# Fehlerblock landet — und das faellt nicht ueberall gleich aus. Gemessen am
# 2026-09-23 am selben Datensatz: macOS nannte die Schreibweise aus der Datei,
# der Windows-Laeufer die kanonische.
#
# Damit war die Zusage im Kommentar unten — „Name wie in der Datei" — keine
# mehr. Ein Kunde mit `IBKR_GATEWAY_PORT` in seiner Datei haette nach einer
# Zeile gesucht, die dort nicht steht.
#
# Statt zu raten, welche gemeint ist, nennt die Zeile **beide**. Das ist
# plattformunabhaengig richtig und beantwortet die Frage, die der Kunde
# wirklich hat: welche Zeile fasse ich an.
ALIAS_GESCHWISTER: dict[str, str] = {
    "IBKR_TWS_PORT": "IBKR_GATEWAY_PORT",
    "IBKR_GATEWAY_PORT": "IBKR_TWS_PORT",
    "IBKR_TWS_HOST": "IBKR_GATEWAY_HOST",
    "IBKR_GATEWAY_HOST": "IBKR_TWS_HOST",
}


def _feldname(roh: str) -> str:
    """Der Name fuer den Block — bei zwei Schreibweisen beide."""
    name = roh.upper()
    geschwister = ALIAS_GESCHWISTER.get(name)
    return f"{name} (or {geschwister})" if geschwister else name


def _pydantic_lines(errors: Iterable[dict[str, Any]]) -> tuple[str, ...]:
    """Je Feld eine Zeile: Name wie in der Datei, Erwartung, gelesener Wert.

    Traegt ein Feld zwei erlaubte Schreibweisen, stehen beide da — siehe
    `ALIAS_GESCHWISTER`.
    """
    lines: list[str] = []
    for err in errors:
        loc = err.get("loc") or ("<unknown>",)
        field_name = str(loc[0])
        msg = str(err.get("msg", "invalid"))
        if err.get("type") == "missing":
            # Bei `missing` ist `input` der ganze gelesene Datensatz, nicht der
            # Wert des Feldes. Ihn auszugeben waere irrefuehrend — und bei einem
            # Datensatz mit Token auch noch gefaehrlich.
            lines.append(f"  {_feldname(field_name)}: missing")
            continue
        got = _redacted(field_name, err.get("input"))
        lines.append(f"  {_feldname(field_name)}: {msg} (got: {got})")
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
                # T1-213 (Owner-Befund 2026-09-23 am ersten Probelauf der
                # fensterlosen EXE): hier stand „Download the pre-filled
                # bridge.env from Ordertune and place it in the same folder".
                #
                # Der Satz war ueberholt und stand an der auffaelligsten Stelle
                # der ganzen Anwendung. Unmittelbar darunter oeffnet sich der
                # Assistent, dessen erster Schritt genau das ueberfluessig
                # macht: Code holen, in Ordertune eintippen, fertig — die
                # Datei entsteht dabei von selbst (T1-178). Der Kunde wurde
                # also zu einem Umweg aufgefordert, waehrend der kurze Weg
                # unter der Meldung auf ihn wartete.
                "This window is the setup assistant. Step 1 pairs this machine",
                "with Ordertune: fetch a code, type it into the Broker tab, and",
                "the Bridge writes bridge.env for you.",
                "",
                "Nothing to download, nothing to copy between windows.",
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
            # T1-213: auch hier stand ein Download. Bei einer vorhandenen,
            # aber fehlerhaften Datei ist die richtige Auskunft ohnehin „die
            # genannte Zeile richtigstellen" — der zweite Weg ist eine neue
            # Kopplung, nicht ein Dateitransport.
            "Fix the line named above.",
            "",
            "If you would rather start over: delete bridge.env, start the",
            "Bridge again, and pair this machine in the assistant that opens.",
        ),
    )


# T1-222 — es laeuft bereits eine Bridge auf dieser Maschine.
#
# Eigener Text, weil der Zustand ein eigener ist: nichts ist kaputt, der
# Nutzer hat zweimal geklickt. Bis zum 2026-09-23 lief der zweite Start bis
# zum IBKR-Verbindungsversuch, kollidierte dort auf der Client-ID, und
# `classify_connect_error` riet aus einem Socket-Fehler — mit
# „'Enable ActiveX and Socket Clients' is off in TWS" an erster Stelle. Eine
# Einstellung, die in Ordnung war, sonst haette die ERSTE Instanz nicht
# verbunden.


def bridge_laeuft_bereits(url: str) -> Failure:
    """Die Auskunft fuer den Doppelstart. Kein Fehler, kein Verdacht.

    Der Text nennt ausdruecklich keine TWS-Einstellung und keine Client-ID:
    beide waeren hier eine falsche Faehrte, und eine falsche Faehrte schickt
    den Nutzer in seinen Broker, um dort etwas umzustellen, das stimmt.
    """
    return Failure(
        code="bridge_already_running",
        headline="A Bridge is already running on this machine.",
        detail=(
            "  Its window: " + url,
            "",
            "  Nothing is wrong. The Bridge has no taskbar window of its own,",
            "  so a second click looks like a first one.",
        ),
        action=(
            "The running Bridge keeps working -- you do not need to do anything.",
            "",
            # T1-223 — jetzt gibt es den Knopf, und der Text zeigt darauf.
            #
            # Die Geschichte dieser vier Zeilen ist der Grund, warum die
            # Zusicherung dazu BEIDE Seiten misst: zuerst stand hier „close
            # the running one first (its window has the controls)" — ein
            # Versprechen auf Bedienelemente, die es nicht gab. Dann der
            # Task-Manager, wahr, aber unbequem. Erst T1-223 hat das gebaut,
            # was der erste Satz schon behauptet hatte.
            "To stop it: open its window and use Details -> Stop the Bridge.",
            "",
            "Closing the browser window does not stop the Bridge. The window is",
            "a view of it, not the program itself.",
        ),
    )


# ── IBKR TWS ─────────────────────────────────────────────────────────────────


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
                "    to the same TWS.",
            ),
            action=(
                "In TWS: File -> Global Configuration -> API -> Settings.",
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
                f"  bridge.env says:  IBKR_TWS_PORT={port}",
                f"  Answering ports:  {listed}",
                "",
                "  An open port is not proof that TWS is behind it, but on this",
                "  machine it is the most likely explanation.",
            ),
            action=(
                "Check the socket port in TWS (File -> Global Configuration ->",
                "API -> Settings) and set IBKR_TWS_PORT in bridge.env to",
                "that number.",
                "",
                "IBKR defaults: TWS 7497 paper / 7496 live.",
                "The port is a setting -- it does not follow from the account.",
            ),
        )

    return Failure(
        code="tws_unreachable",
        headline=f"No connection to TWS at {host}:{port}.",
        detail=(
            f"  {exc}",
            "",
            "  None of the IBKR default ports answered on this machine,",
            "  so TWS is most likely not running.",
        ),
        action=(
            "Start TWS and log in, then start the Bridge again.",
            "",
            "Note that IBKR logs TWS out daily around 05:00 CET. For unattended",
            "operation use IBC so it logs back in automatically.",
        ),
    )


# T1-214 — der Kunde sitzt auf einem IB Gateway.
#
# Ein eigener Text, weil der Zustand ein eigener ist: es laeuft etwas, es
# funktioniert sogar, und trotzdem fehlt der Ausfallschutz. „Nichts gefunden"
# waere falsch, „falscher Port" waere die halbe Wahrheit.
GATEWAY_HEADLINE = "You are running IB Gateway. Ordertune Bridge needs TWS."

GATEWAY_DETAIL: tuple[str, ...] = (
    "  The Bridge reads the trade reports that TWS writes to disk. That file",
    "  is what lets a fill be recovered when the Bridge was off at the moment",
    "  it happened -- the reason you no longer have to keep the Bridge open",
    "  until the closing bell.",
    "",
    "  IB Gateway has no export function: its configuration tree ends before",
    "  'Export Reports'. Everything else works, this one thing cannot.",
)

GATEWAY_ACTION: tuple[str, ...] = (
    "Install Trader Workstation, log in with the same account, and set",
    "Global Configuration -> Export Reports (leave 'Export filename' empty).",
    "",
    "Until you do, the Bridge keeps trading -- you are missing the recovery,",
    "not the execution.",
)


def gateway_statt_tws(port: int, answering: tuple[tuple[int, str], ...]) -> Failure:
    """Die Auskunft fuer ein erkanntes Gateway. **Kein Abbruch.**

    Ein Riegel waere hier die falsche Antwort: wer heute laeuft, soll
    weiterlaufen. Er bekommt einen Hinweis, keine Sperre — ein Riegel, der den
    Kunden haerter trifft als das Problem, ist keine Verbesserung.
    """
    listed = ", ".join(f"{p} ({label})" for p, label in answering)
    return Failure(
        code="gateway_not_tws",
        headline=GATEWAY_HEADLINE,
        detail=(f"  Answering ports:  {listed}", "", *GATEWAY_DETAIL),
        action=GATEWAY_ACTION,
    )


# ── Ordertune-Plattform ──────────────────────────────────────────────────────

# Vierter Eintrag je Code: der Text fuer den Assistenten (siehe
# `Failure.action_paired`). Leer heisst „erreicht den Assistenten nicht" — das
# gilt fuer jeden Code ausserhalb von `RENEWABLE_AUTH_CODES`, und dort bleibt
# der heutige Wortlaut samt Website unveraendert stehen.
#
# T1-213, Owner-Befund 2026-09-23 am zweiten Probelauf: sechs dieser Texte
# forderten noch zum Herunterladen einer `bridge.env` auf — darunter der
# 401-Fall, den der Owner als Meldungsfenster fotografiert hat. Seit T1-178
# legt die Kopplung die Datei selbst an, und seit T1-181 oeffnet ausgerechnet
# ein wertloses Token den Assistenten: der Satz forderte also einen Umweg,
# waehrend der kurze Weg im selben Augenblick aufging.
#
# `missing_fingerprint` behaelt seinen Download — dort ist die BRIDGE zu alt,
# und die will wirklich heruntergeladen werden.
#
# Die Texte hier nennen bewusst KEINE Handlung. Der Knopf darunter ist die
# Handlung; ein Satz, der dasselbe noch einmal sagt, muss mitgepflegt werden
# und widerspricht ihm beim ersten Mal, wo das jemand vergisst. Genau so ist
# dieser Vorgang entstanden.
_HANDSHAKE_BY_CODE: dict[str, tuple[str, str, tuple[str, ...], tuple[str, ...]]] = {
    "invalid_token": (
        "token_invalid",
        "Ordertune rejected the access token.",
        (
            "Pair this machine again: the assistant opens in a moment and",
            "fetches a fresh token for you.",
        ),
        ("This access token is no longer valid.",),
    ),
    "missing_token": (
        "token_invalid",
        "The request carried no access token.",
        (
            "ORDERTUNE_BRIDGE_TOKEN is empty or malformed in bridge.env.",
            "Pair this machine again to write a working one.",
        ),
        ("This machine has no usable access token.",),
    ),
    "connection_revoked": (
        "connection_revoked",
        "This bridge connection was revoked in Ordertune.",
        (
            "Create a new connection in Ordertune, then pair this machine",
            "with it.",
        ),
        ("This connection was revoked, so its token no longer works.",),
    ),
    "ip_mismatch": (
        "ip_mismatch",
        "This bridge is running from a different network than when it registered.",
        (
            "The connection is bound to the source IP of its first handshake.",
            "Run the Bridge on a VPS with a fixed outbound IP, or rotate the",
            "token to register the current network.",
        ),
        (),
    ),
    "fingerprint_mismatch": (
        "fingerprint_mismatch",
        "This bridge is running on different hardware than when it registered.",
        (
            "Rotate the token in Ordertune. That clears the stored hardware",
            "fingerprint, and the next handshake registers this machine.",
        ),
        (),
    ),
    "fingerprint_already_set": (
        "fingerprint_already_set",
        "This token already belongs to another machine.",
        (
            "Pair this machine again -- that issues it a token of its own.",
            "Do not run two bridges from one token -- give each machine its own.",
        ),
        # Der Zusatz gehoert hierher und nicht zum Knopf: die Kopplung rotiert
        # den Token und loest damit genau diese Lage auf — aber sie macht die
        # ANDERE Maschine still unbrauchbar. Das ist eine Folge, keine
        # Handlung, und sie steht sonst nirgends im Fenster.
        (
            "This token is already bound to another machine.",
            "Pairing here rotates it, and that machine stops working.",
        ),
    ),
    "missing_fingerprint": (
        "fingerprint_missing",
        "The request carried no hardware fingerprint.",
        (
            "This build could not identify the machine. Download the current",
            f"release: {RELEASES_URL}",
        ),
        (),
    ),
    "rate_limited": (
        "rate_limited",
        "Ordertune is rate limiting this connection.",
        (
            "Wait a minute and start the Bridge again. If it repeats, more",
            "than one bridge is probably using the same connection.",
        ),
        (),
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


def _response_body(response: object) -> str:
    """Den Antwortkoerper lesen, ohne dass das Lesen selbst zum Fehler wird.

    Stand zweimal wortgleich da — einmal in der Zuordnung, einmal im
    Widerrufs-Erkenner. Beim zweiten Kopieren gehoert so etwas ins gemeinsame
    Stueck, sonst driften die beiden.
    """
    try:
        return getattr(response, "text", "") or ""
    except Exception:  # noqa: BLE001 - ein unlesbarer Koerper ist kein Absturz
        return ""


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

    body = _response_body(response)

    known = _HANDSHAKE_BY_CODE.get(_error_code_from_body(body) or "")
    if known is not None:
        code, headline, action, action_paired = known
        return Failure(
            code=code,
            headline=headline,
            detail=(f"  Server answered {status}.",),
            action=action + ("", f"  {settings_url(api_base)}"),
            # Ohne die Adresse. Sie ist der Weg fuer jemanden ohne Knopf; im
            # Assistenten waere sie eine zweite, umstaendlichere Anleitung
            # neben der, die als Knopf danebensteht — und der Grund, warum die
            # Karte im Bildschirmfoto zum Herunterladen einer Datei riet.
            action_paired=action_paired,
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
            "there, pair this machine again:",
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


# ── T1-177 D: der Widerruf ist endgueltig, ein Netzfehler nicht ──────────────

# Antwortcodes, nach denen ein Weiterlaufen sinnlos ist. Alle drei sagen
# dasselbe: dieser Token oeffnet nichts mehr, und kein Neustart aendert das.
#
# Bewusst NICHT dabei ist `fingerprint_mismatch`. Er waere ebenso endgueltig,
# aber die Stabilitaet des Fingerabdrucks ist eine eigene, offene Frage
# (T1-176, „Nicht in diesem Spec"), und ein Riegel, der bei einer wandernden
# MAC-Adresse die Bridge anhaelt, waere derselbe Fehler wie der IP-Pin.
TERMINAL_AUTH_CODES = frozenset({
    "connection_revoked",
    "invalid_token",
    "missing_token",
})


def revocation_failure(
    exc: Exception, api_base: str | None = None
) -> Failure | None:
    """Wurde diese Bridge ausgesperrt — oder war nur das Netz weg?

    Der Unterschied ist der ganze Punkt. Bis hierher fing `_handle_heartbeat`
    beides gleich ab, schrieb eine Warnung und lief weiter: nach einem Klick auf
    „Disconnect the bridge" lief das Programm also unveraendert weiter, hielt
    seine TWS-Sitzung und fragte alle paar Sekunden nach Auftraegen, die es nie
    bekommen wuerde. Der Nutzer hatte keine Rueckmeldung, dass da noch etwas
    laeuft — und t1 konnte ihm keine geben, weil der Widerruf genau den Kanal
    kappt, ueber den die Frage zu beantworten waere.

    Gibt `None` zurueck, wenn weitergelaufen werden soll. Das ist die
    Vorgabe — ein Netzausfall darf die Bridge nicht anhalten, dafuer ist
    T1-152d gebaut.
    """
    response = getattr(exc, "response", None)
    if getattr(response, "status_code", None) != 401:
        return None

    if _error_code_from_body(_response_body(response)) not in TERMINAL_AUTH_CODES:
        return None

    return classify_handshake_error(exc, api_base)


# Codes, bei denen eine ERNEUTE KOPPLUNG hilft.
#
# Die Unterscheidung zu `TERMINAL_AUTH_CODES` ist nicht dieselbe Frage. Dort
# geht es um „soll die laufende Schleife aufhoeren"; hier um „kann der Nutzer
# das hier und jetzt selbst in Ordnung bringen".
#
# `fingerprint_already_set` gehoert deshalb dazu, obwohl es kein 401 ist: die
# Kopplung rotiert den Token, und das Rotieren loescht den gebundenen
# Fingerabdruck. Das ist genau der vorgesehene Ausweg bei einem
# Maschinenwechsel — er stand bisher nur als Satz im Fehlerblock und verlangte
# einen Weg ueber die Website.
RENEWABLE_AUTH_CODES = frozenset({
    "connection_revoked",
    "invalid_token",
    "missing_token",
    "fingerprint_already_set",
})


def renewable_failure(
    exc: Exception, api_base: str | None = None
) -> Failure | None:
    """Laesst sich das durch eine neue Kopplung beheben?

    ## Der Fehler, aus dem das entstanden ist

    Owner-Befund 2026-09-14: wer die Verbindung im Broker-Tab trennt und die
    `bridge.env` neben der EXE liegen laesst, bekommt beim naechsten Start
    einen Fehler — und keinen Assistenten.

    Das ist die falsche Antwort auf die Lage. Der Assistent geht auf, wenn
    `load_config()` scheitert; hier laedt die Datei einwandfrei, sie ist nur
    wertlos. Fuer den Nutzer ist das derselbe Zustand: er hat keine gueltigen
    Zugangsdaten. Ihn stattdessen auf die Website zu schicken, um eine Datei zu
    holen, ist genau der Umweg, den T1-178 abgeschafft hat.

    Gibt `None` zurueck, wenn eine neue Kopplung nicht hilft — dann bleibt es
    beim Abbruch mit dem gerahmten Block.
    """
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if status not in (401, 409):
        return None

    if _error_code_from_body(_response_body(response)) not in RENEWABLE_AUTH_CODES:
        return None

    return classify_handshake_error(exc, api_base)
