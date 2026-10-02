"""T1-277 — die Kennung DIESES Prozesses.

## Warum es sie gibt

Der Fingerprint aus `fingerprint.py` sagt, auf welcher MASCHINE die Bridge
laeuft. Er hasht Hostname, Maschinenkennung und erste MAC — alle drei sind
maschinenweit und nicht nutzerbezogen. Mehrere Bridges unter verschiedenen
OS-Nutzern desselben VPS, alle mit derselben `bridge.env`, tragen deshalb
denselben Fingerprint und sind fuer die Plattform N-mal derselbe berechtigte
Rechner. Die Bindung verhindert den **Umzug**, nicht die **Vervielfachung**.

Diese Kennung schliesst genau diese Luecke in der Beobachtung: sie sagt, welcher
PROZESS gesprochen hat.

## Warum sie gewuerfelt wird und nichts ableitet

Eine Kennung, die aus Hostname, Benutzernamen, Prozessnummer oder Pfad
abgeleitet waere, haette genau den Fehler, den sie aufdecken soll — sie waere
wieder eine Eigenschaft der Umgebung. Die Prozessnummer scheidet zusaetzlich
aus, weil das Betriebssystem sie wiederverwendet.

Sie lebt nur, solange der Prozess lebt, und wird ausdruecklich **nicht**
gespeichert. Eine Kennung auf der Platte waere wieder maschinengebunden, und ein
Neustart soll eine neue tragen: die Plattform unterscheidet Neustart und zweiten
Prozess an der Lage der Zeiten, nicht an der Gleichheit der Kennung.

## Was sie nicht ist

Kein Geheimnis. Sie wird in jeder Anfrage im Klartext gesendet und taugt zu
nichts — sie autorisiert nichts und laesst sich nicht gegen ihren Trager
verwenden. Wer sie faelscht, faelscht eine Beobachtung, und genau deshalb ist
sie auf der Plattform keine Durchsetzungsgrundlage.
"""
from __future__ import annotations

import secrets

#: Form und Spanne muessen zu `INSTANZ_KENNUNG_RE` auf der Plattform passen
#: (`^[A-Za-z0-9_-]{8,64}$`). `token_urlsafe(16)` liefert 22 Zeichen aus genau
#: diesem Vorrat. Weicht das eine ab, gilt die Kennung dort als „nicht
#: angegeben" — kein Fehler, aber eine stille Luecke in der Zaehlung.
_LAENGE_BYTES = 16

_kennung: str | None = None


def instanzkennung() -> str:
    """Die Kennung dieses Prozesses. Einmal gewuerfelt, danach unveraendert."""
    global _kennung
    if _kennung is None:
        _kennung = secrets.token_urlsafe(_LAENGE_BYTES)
    return _kennung
