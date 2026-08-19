"""T1-101 B-5 — die letzten Protokollzeilen, gedeckelt.

## Warum das Protokoll erreichbar bleibt

Eine reduzierte Oberflaeche darf den Weg „schick mir dein Log" nicht kappen.
Support lebt davon, und wer sich auskennt, will die Rohzeilen sehen. Deshalb
haengt hier ein zweiter Handler an der Wurzel, der mitschreibt, was ohnehin
schon ins Protokoll geht.

## Warum eine feste Obergrenze

`LOG_LEVEL=DEBUG` ueber Tage erzeugt sehr viele Zeilen, und die Bridge laeuft
im Dauerbetrieb auf einem VPS. Ein unbegrenzter Puffer waere ein Speicherleck
mit Ansage. `deque` mit `maxlen` wirft die aeltesten von selbst weg — der
vollstaendige Verlauf liegt ohnehin auf der Platte, mit Tageswechsel und 30
Tagen Aufbewahrung.
"""
from __future__ import annotations

import logging
from collections import deque

# Genug, um einen Startvorgang und mehrere Takte vollstaendig zu sehen, und
# klein genug, dass der Speicherbedarf feststeht.
MAX_LINES = 2000


class Journal(logging.Handler):
    """Haelt die letzten Protokollzeilen im Arbeitsspeicher."""

    def __init__(self, maxlen: int = MAX_LINES) -> None:
        super().__init__()
        self._lines: deque[str] = deque(maxlen=maxlen)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._lines.append(self.format(record))
        except Exception:  # pragma: no cover - defensiv
            # Ein Fehler beim Mitschreiben darf niemals nach oben schlagen:
            # dieser Handler haengt an der Wurzel und saehe damit jeden Aufruf
            # von `log.*` im ganzen Programm.
            pass

    def lines(self, limit: int | None = None) -> list[str]:
        werte = list(self._lines)
        return werte if limit is None else werte[-limit:]


def attach(fmt: str) -> Journal:
    """Haengt das Journal an die Wurzel und gibt es zurueck."""
    journal = Journal()
    journal.setFormatter(logging.Formatter(fmt))
    logging.getLogger().addHandler(journal)
    return journal
