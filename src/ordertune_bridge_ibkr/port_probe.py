"""T1-101 A-3 — den Port suchen statt raten zu lassen.

## Warum

`IBKR_TWS_PORT` ist in der erzeugten `bridge.env` fest auf 7497 vorbelegt. Der
richtige Wert steht in den API-Einstellungen der TWS und **folgt nicht aus dem
Kontotyp** — wer Echtgeld handelt, muss die Zeile aendern und weiss das nicht.
Ein Verbindungsfehler sagt dann nur, dass nichts antwortet, und nicht, dass
daneben sehr wohl etwas antwortet.

Diese Sonde klopft die IBKR-Standardports ab und macht aus der Frage „warum
geht es nicht" eine Aussage mit zwei Zahlen darin.

## T1-214 — zwei Listen, und der Unterschied ist die ganze Spec

Seit T1-207 wird die Bridge **mit der TWS** betrieben: das IB Gateway hat keine
Berichtsfunktion, und ohne sie gibt es keinen Ausfallschutz. Angeboten werden
deshalb nur noch die TWS-Ports (`TWS_PORTS`, und `KNOWN_PORTS` ist genau das).

Die Gateway-Ports verschwinden trotzdem **nicht** aus der Suche. Sie wandern in
`GATEWAY_PORTS` und werden weiter abgeklopft — aber um zu **erklaeren**, nicht
um vorgeschlagen zu werden. Wer heute auf dem Gateway laeuft, soll erfahren,
was ihm fehlt; ihn einfach nichts mehr finden zu lassen waere ein Riegel, der
den Kunden haerter trifft als das Problem.

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

# Die Ports, die wir ANBIETEN. Beschriftet so, wie der Nutzer sie in der TWS
# wiedererkennt.
TWS_PORTS: tuple[tuple[int, str], ...] = (
    (7497, "TWS paper"),
    (7496, "TWS live"),
)

# Die Ports, die wir nur noch ERKENNEN — siehe Kopf. Sie stehen in keiner
# Auswahl und in keinem Vorschlag.
GATEWAY_PORTS: tuple[tuple[int, str], ...] = (
    (4002, "IB Gateway paper"),
    (4001, "IB Gateway live"),
)

# Was der Nutzer angeboten bekommt. Gegenstueck auf der Plattform:
# `tws-setup-shared.ts`. Seit T1-214 fuehrt die Plattform gar keine Portliste
# mehr — die lebende Anleitung steht auf docs.ordertune.com (DOCS-9).
KNOWN_PORTS: tuple[tuple[int, str], ...] = TWS_PORTS

# Was abgeklopft wird. Die Reihenfolge ist die Aussage: was wir anbieten zuerst.
SCANNED_PORTS: tuple[tuple[int, str], ...] = TWS_PORTS + GATEWAY_PORTS

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
        for port, label in SCANNED_PORTS
        if port_answers(host, port, timeout)
    )
    log.debug("port probe on %s: %s", host, found or "nothing answered")
    return found


def nur_gateway(gefunden: tuple[tuple[int, str], ...]) -> bool:
    """T1-214 — antwortet ein Gateway und sonst nichts?

    Genau dieser Zustand verlangt eine eigene Auskunft: der Kunde hat etwas
    Laufendes vor sich, es funktioniert sogar, und trotzdem fehlt ihm der
    Ausfallschutz aus T1-207. Ihm nur „nichts gefunden" zu sagen waere falsch,
    ihm „falscher Port" zu sagen waere die halbe Wahrheit.

    Leer heisst `False` — ohne Antwort gibt es nichts zu erklaeren.
    """
    if not gefunden:
        return False
    gateway = {p for p, _ in GATEWAY_PORTS}
    return all(p in gateway for p, _ in gefunden)
