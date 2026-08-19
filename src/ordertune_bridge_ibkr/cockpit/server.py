"""T1-101 B-1 — der lokale Server: ausschliesslich Rueckschleife, mit Token.

## Warum aus der Standardbibliothek und ohne Web-Framework

Das Cockpit liefert eine Seite, einen Ereignisstrom und spaeter zwei kleine
Schreibwege. Ein Framework braechte Megabyte ins Binaerpaket und eine
Abhaengigkeitskette in ein Programm, das Orders absendet. Der HTTP-Server aus
Pythons eigener Bibliothek reicht.

## Die Zugriffsgrenze

Sie verlaeuft hier nicht zwischen Nutzern, sondern **an der Maschine**:

  * Gebunden wird ausschliesslich auf 127.0.0.1. Eine Bindung auf 0.0.0.0
    loeste den Windows-Firewall-Dialog aus — noch ein Fenster, das niemand
    erwartet — und stellte ein depotnahes Interface ins Netz.
  * Der Port ist ephemer (Port 0, das Betriebssystem waehlt). Zwei Bridges auf
    einer Maschine kollidieren damit nicht.
  * Jede Anfrage braucht das Token aus der Ablagedatei. Wer die lesen kann, ist
    auf dem VPS bereits angemeldet und kommt ohnehin an `bridge.env` und das
    Protokoll — **das Cockpit oeffnet keine neue Tuer, es macht die vorhandene
    lesbar.** Neu erzeugt bei jedem Start, damit eine liegengebliebene URL aus
    einer alten Sitzung nichts wert ist.

## Warum ein Ereignisstrom und keine Abfrage im Takt

Eine Richtung, vom Server zur Seite, ohne Bibliothek, und er ueberlebt ein
geschlossenes und wieder geoeffnetes Fenster. Geschoben wird hoechstens einmal
je Sekunde und nur, wenn der Kern etwas geaendert hat.
"""
from __future__ import annotations

import hmac
import json
import logging
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .page import PAGE_HTML
from .state import StateStore

log = logging.getLogger(__name__)

BIND_HOST = "127.0.0.1"

# Wie oft der Ereignisstrom nach einer Aenderung sieht. Der Kern taktet mit
# 60 s (Heartbeat) und 5 s (Auftragsabruf); haeufiger hinzusehen bringt nichts.
STREAM_POLL_S = 1.0

# Kommentarzeile fuer den Ereignisstrom, damit ein stiller Kanal nicht von
# einem Zwischenglied geschlossen wird.
STREAM_KEEPALIVE_S = 15.0

# Wie viele Protokollzeilen der Details-Reiter und die Diagnose mitgeben.
LOG_TAIL = 200


class _Handler(BaseHTTPRequestHandler):
    # Wird von `serve()` gesetzt.
    store: StateStore
    token: str
    stopping: threading.Event
    # In einem Behaelter, NICHT als blosses Klassenattribut: eine Funktion, die
    # direkt an der Klasse haengt, wird von Python zur Methode gebunden und
    # bekaeme `self` als erstes Argument. Der Behaelter umgeht den Deskriptor.
    deps: dict

    protocol_version = "HTTP/1.1"

    # ── Protokoll ────────────────────────────────────────────────────────

    def log_message(self, fmt: str, *args: object) -> None:
        """Der Server schreibt nicht nach stderr.

        Sonst stuende zwischen den Zeilen des Kerns eine Zugriffszeile je
        Sekunde, und die Konsole — nach Abschnitt A der Ort, an dem Fehler
        stehenbleiben — waere unlesbar.
        """
        log.debug("cockpit %s", fmt % args)

    # ── Zugang ───────────────────────────────────────────────────────────

    def _authorised(self, query: dict[str, list[str]]) -> bool:
        given = (query.get("t") or [""])[0]
        # Zeitkonstant, damit das Token nicht Zeichen fuer Zeichen erraten
        # werden kann. Auf der Rueckschleife eher theoretisch — aber es kostet
        # nichts, und ein Vergleich mit `==` an einem Geheimnis ist der Sorte
        # Detail, die spaeter niemand mehr nachtraegt.
        #
        # Verglichen wird ueber Bytes, NICHT ueber Zeichenketten: `compare_digest`
        # wirft bei Zeichenketten mit Nicht-ASCII einen `TypeError`. In der QA
        # hat `?t=%C3%BC` damit den Bearbeiter-Thread zerlegt — kein Umgehen der
        # Pruefung, aber ein Abbruch ohne Antwort und ein Stapelauszug auf
        # `stderr`, vorbei an der Stummschaltung unten. Genau die Konsole, die
        # Abschnitt A lesbar gemacht hat.
        try:
            return hmac.compare_digest(given.encode("utf-8"), self.token.encode("utf-8"))
        except (TypeError, ValueError, AttributeError):  # pragma: no cover - defensiv
            return False

    def _deny(self) -> None:
        body = b"Not authorised. Open the cockpit from the URL in the console."
        self.send_response(403)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ── Wege ─────────────────────────────────────────────────────────────

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)

        if not self._authorised(query):
            self._deny()
            return

        if parsed.path == "/":
            self._send_page()
        elif parsed.path == "/state":
            self._send_state()
        elif parsed.path == "/events":
            self._stream_events()
        elif parsed.path == "/log":
            self._send_log()
        elif parsed.path == "/diagnostics":
            self._send_diagnostics()
        elif parsed.path == "/config":
            self._send_config()
        else:
            self.send_error(404)

    # ── T1-101 C: die Schreibwege ────────────────────────────────────────
    #
    # Sie schreiben `bridge.env` und sonst nichts. Die IBKR-Verbindung fasst
    # der Server nie an — ein Wiederaufbau aus einem fremden Thread ist genau
    # die Fehlerklasse, gegen die T1-88 die Schleife auf einen einzigen Thread
    # gelegt hat. Uebernommen wird beim naechsten Start.

    def do_POST(self) -> None:  # noqa: N802 - von BaseHTTPRequestHandler vorgegeben
        parsed = urlparse(self.path)
        if not self._authorised(parse_qs(parsed.query)):
            self._deny()
            return

        setup = self.deps.get("setup")
        if setup is None:
            self.send_error(404)
            return

        try:
            laenge = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(laenge) or b"{}")
        except (ValueError, OSError):
            self._send_json({"ok": False, "message": "Malformed request."})
            return

        wege = {
            "/probe": setup.probe,
            "/verify": setup.verify,
            "/settings": setup.save,
            "/credentials": setup.replace,
        }
        handler = wege.get(parsed.path)
        if handler is None:
            self.send_error(404)
            return
        try:
            self._send_json(handler(body))
        except Exception as exc:  # pragma: no cover - defensiv
            log.warning("Cockpit setup action failed: %s", exc)
            self._send_json({"ok": False, "message": f"Failed: {exc}"})

    def _send_config(self) -> None:
        setup = self.deps.get("setup")
        self._send_json(setup.config() if setup else {"exists": False, "values": {}})

    def _send_log(self) -> None:
        journal = self.deps.get("journal")
        self._send_json({"lines": journal.lines(LOG_TAIL) if journal else []})

    def _send_diagnostics(self) -> None:
        """T1-101 B-5 — alles, was der Support braucht, in einem Stueck.

        Der Token ist hier **nicht** dabei. „Copy diagnostics" landet als
        Naechstes in einem Chat oder einer E-Mail; ein Geheimnis, das den Weg
        nimmt, ist keins mehr.
        """
        diagnostics = self.deps.get("diagnostics")
        journal = self.deps.get("journal")
        payload = dict(diagnostics()) if diagnostics else {}
        payload["log"] = journal.lines(LOG_TAIL) if journal else []
        self._send_json(payload)

    def _send_page(self) -> None:
        body = PAGE_HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # Nichts aus dem Netz, und nichts, was der Browser zwischenspeichert:
        # die Seite aendert sich mit jeder Version des Programms.
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_state(self) -> None:
        state, version = self.store.get()
        self._send_json({"version": version, "state": state.to_wire()})

    def _stream_events(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        letzte_version = -1
        letztes_lebenszeichen = time.monotonic()
        try:
            while not self.stopping.is_set():
                state, version = self.store.get()
                if version != letzte_version:
                    letzte_version = version
                    payload = json.dumps({"version": version, "state": state.to_wire()})
                    self.wfile.write(f"data: {payload}\n\n".encode())
                    self.wfile.flush()
                    letztes_lebenszeichen = time.monotonic()
                elif time.monotonic() - letztes_lebenszeichen > STREAM_KEEPALIVE_S:
                    self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
                    letztes_lebenszeichen = time.monotonic()
                time.sleep(STREAM_POLL_S)
        except (BrokenPipeError, ConnectionResetError, OSError):
            # Das Fenster wurde geschlossen. Kein Fehler — und vor allem kein
            # Grund, im Protokoll des Kerns aufzutauchen.
            return


class CockpitServer:
    """Der Server als Nebenlaeufer, mit einem sauberen Weg zum Anhalten."""

    def __init__(
        self,
        store: StateStore,
        journal: object | None = None,
        diagnostics: object | None = None,
        setup: object | None = None,
    ) -> None:
        self.store = store
        self.journal = journal
        self.diagnostics = diagnostics
        self.setup = setup
        self.token = secrets.token_urlsafe(32)
        self._stopping = threading.Event()
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return self._httpd.server_address[1] if self._httpd else 0

    @property
    def url(self) -> str:
        return f"http://{BIND_HOST}:{self.port}/?t={self.token}"

    def start(self) -> str:
        handler = type(
            "_BoundHandler",
            (_Handler,),
            {
                "store": self.store,
                "token": self.token,
                "stopping": self._stopping,
                "deps": {
                    "journal": self.journal,
                    "diagnostics": self.diagnostics,
                    "setup": self.setup,
                },
            },
        )
        # Port 0: das Betriebssystem waehlt einen freien. Damit kollidieren
        # zwei Bridges auf einer Maschine nicht, und es gibt keinen festen
        # Port, den etwas anderes belegt haben koennte.
        self._httpd = ThreadingHTTPServer((BIND_HOST, 0), handler)
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            name="cockpit-server",
            daemon=True,
        )
        self._thread.start()
        log.info("Cockpit is listening on %s", self.url)
        return self.url

    def stop(self) -> None:
        self._stopping.set()
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
