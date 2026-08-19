"""T1-101 B-2 — laeuft TWS im Schreibschutz? Gemessen, nicht geraten.

## Woher die Regel kommt

Am 2026-08-19 hat der Owner den Schalter „Schreibgeschuetzte API" ein- und
wieder ausgeschaltet und beide Protokolle geliefert. Mit Schreibschutz:

    07:04:53  position: WDAY / MU / CSCO
    07:04:53  Error 321, reqId -1: ... -'cp' : cause -
              Die API befindet sich im schreibgeschuetzten Modus.
    07:04:57  open orders request timed out
    07:04:57  completed orders request timed out

Ohne: kein 321, kein Zeitueberlauf, und `Synchronization complete` nach 1,1 s
statt nach 4,6 s.

**TWS sagt es also von selbst**, rund eine Zehntelsekunde nachdem die
Positionen da sind — vier Sekunden vor dem Zeitueberlauf und mit einer
Begruendung im Klartext. Der Entwurf hatte den Zeitueberlauf als Signal
angenommen; das hier ist besser.

## Zwei Regeln, die hier tragen

**Erkannt wird am Code, nie am Text.** Der Wortlaut ist lokalisiert — auf der
Maschine des Owners deutsch, auf einer englischen TWS anders. Eine Pruefung auf
„schreibgeschuetzt" funktionierte nur bei ihm. Der Text wird **angezeigt**,
nicht ausgewertet.

**Zwei Sicherheitsgrade, weil 321 fuer sich genommen allgemein ist.** 321
heisst „Fehler bei der Validierung der Anfrage" und kann auch anderes bedeuten.
Deshalb zaehlt es nur zusammen mit dem zweiten, sprachunabhaengigen Signal.
Ein falsches Positiv kostet hier einen Warnhinweis, keinen Auftrag — die
Richtung stimmt.

## Warum das ueberhaupt gebraucht wird

Im gemessenen Durchgang war **alles gruen**: Handshake 200, Heartbeat 200, drei
Positionen gemeldet, `Bridge is active`. Auf der Plattform stand die Verbindung
als lebend und gesund da — und der erste Auftrag des Tages waere abgeprallt.
Woertlich die Zeile, die in T1-82 als die gefaehrliche markiert ist. Die
Plattform kann das strukturell nicht sehen; die Bridge hat den Beleg auf der
Platte liegen.
"""
from __future__ import annotations

from dataclasses import dataclass

# IBKR: „Error validating request". Allgemein — traegt den eigentlichen Grund
# im angehaengten Text, und der ist lokalisiert.
VALIDATION_ERROR_CODE = 321

CONFIRMED = "read_only_confirmed"
SUSPECTED = "read_only_suspected"
WRITABLE = "writable"
UNKNOWN = "unknown"


@dataclass(frozen=True)
class WriteAccess:
    """Was ueber den Schreibzugriff dieser Verbindung bekannt ist."""

    state: str = UNKNOWN
    # Der Wortlaut von IBKR, in der Sprache der TWS-Installation. Nur zur
    # Anzeige — nie zur Entscheidung.
    detail: str | None = None

    @property
    def blocks_orders(self) -> bool:
        return self.state in (CONFIRMED, SUSPECTED)


def classify(
    *,
    validation_errors: list[str],
    open_orders_answered: bool,
) -> WriteAccess:
    """Die Regel aus der Messung, als reine Funktion.

    `validation_errors` sind die Texte der 321er, die im Verbindungsfenster
    eingetroffen sind. `open_orders_answered` sagt, ob die Auftragsanfrage
    beantwortet wurde — das sprachunabhaengige Signal.
    """
    if open_orders_answered:
        # Antwortet der Auftragskanal, ist geschrieben werden erlaubt. Ein
        # einzelnes 321 aus anderem Anlass darf dann keinen Alarm ausloesen.
        return WriteAccess(WRITABLE)

    if validation_errors:
        return WriteAccess(CONFIRMED, validation_errors[-1])

    return WriteAccess(SUSPECTED)
