"""T1-101 A-3 — den Port suchen statt raten zu lassen.

## Warum

`IBKR_GATEWAY_PORT` ist in der erzeugten `bridge.env` fest auf 7497 vorbelegt.
Der richtige Wert steht in den API-Einstellungen von TWS und **folgt nicht aus
dem Kontotyp** — wer IB Gateway benutzt oder Echtgeld handelt, muss die Zeile
aendern und weiss das nicht. Ein Verbindungsfehler sagt dann nur, dass nichts
antwortet, und nicht, dass daneben sehr wohl etwas antwortet.

Diese Sonde klopft die vier IBKR-Standardports ab und macht aus der Frage „warum
geht es nicht" eine Aussage mit zwei Zahlen darin.

## Was sie tut, und was ausdruecklich nicht

Ein reiner TCP-Verbindungsversuch je Port, danach sofort zu. **Es geht keine
API-Anfrage hinaus, kein Auftrag, nichts wird veraendert.** Ein offener Port
beweist deshalb auch nicht, dass TWS dahinter liegt — nur, dass dort etwas
lauscht. Die Formulierungen in `failures.py` halten diese Grenze ein.

Sie laeuft ausschliesslich im Fehlerfall. Im Normalbetrieb wird kein einziger
zusaetzlicher Socket geoeffnet.
"""
from __future__ import annotations

import logging
import socket

log = logging.getLogger(__name__)

# Die vier Standardports von IBKR, je mit der Beschriftung, die der Nutzer in
# TWS wiedererkennt. Gegenstueck auf der Plattform: `tws-setup-shared.ts`
# (`BRIDGE_SOCKET_PORTS`). Zwei bewusste Kopien ueber eine Repo-Grenze hinweg,
# jede an genau einer Stelle — siehe T1-101 Tech Design E-7.
KNOWN_PORTS: tuple[tuple[int, str], ...] = (
    (7497, "TWS paper"),
    (7496, "TWS live"),
    (4002, "IB Gateway paper"),
    (4001, "IB Gateway live"),
)

# Auf der Rueckschleife antwortet ein offener Port praktisch sofort. Eine halbe
# Sekunde je Port haelt die gesamte Suche unter zwei Sekunden — sie laeuft auf
# einem Weg, an dessen Ende ohnehin ein Abbruch steht, aber ein Nutzer, der auf
# eine Fehlermeldung wartet, soll nicht auch noch warten.
PROBE_TIMEOUT_S = 0.5


def port_answers(host: str, port: int, timeout: float = PROBE_TIMEOUT_S) -> bool:
    """Lauscht auf host:port etwas? Reiner Verbindungsversuch, sofort wieder zu."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def scan(host: str, timeout: float = PROBE_TIMEOUT_S) -> tuple[tuple[int, str], ...]:
    """Die Standardports, auf denen sich etwas meldet — in der Reihenfolge oben.

    Zusaetzlich abgeklopft wird nichts: ein Portscan ueber einen breiteren
    Bereich waere auf einem fremden VPS eine Handlung, die nach etwas anderem
    aussieht, als sie ist.
    """
    found = tuple(
        (port, label)
        for port, label in KNOWN_PORTS
        if port_answers(host, port, timeout)
    )
    log.debug("port probe on %s: %s", host, found or "nothing answered")
    return found
