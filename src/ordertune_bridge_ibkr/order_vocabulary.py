"""T1-101 B-3 / D14 — dieselben Worte wie im Order Management.

## Warum das eine eigene Datei ist

T1-100 hat auf der Plattform das Vokabular festgelegt und `Working` gestrichen:
es war IBKR-Jargon und stand in derselben Farbe direkt unter `Submitting`. Die
Quelle dort ist `order-execution-status-pill.tsx`.

Ein Cockpit, das denselben Auftrag „working" nennt, den t1 „At broker" nennt,
stellt genau den Zustand wieder her, den T1-100 beseitigt hat: zwei Flaechen,
die ueber dieselbe Sache verschieden reden — und der Nutzer sitzt zwischen
beiden und weiss nicht, ob er zwei Auftraege hat oder einen.

Die Liste ist damit eine **bewusste zweite Kopie** ueber eine Repo-Grenze
hinweg, wie die Portliste in `port_probe.py`. An genau einer Stelle, mit
Verweis auf das Gegenstueck. Eine Kopplung zur Bauzeit zwischen einer
Next-Anwendung und einer Python-EXE ist elf Woerter nicht wert.

Gegenstueck: `t1.ordertune.com/src/components/order-management/
order-execution-status-pill.tsx`
"""
from __future__ import annotations

# Innerer Zustand der Bridge -> das Wort, das der Nutzer auf t1 sieht.
LABELS: dict[str, str] = {
    "submitting": "Sending",
    "working": "At broker",
    "filled": "Filled",
    "partial": "Partly filled",
    "cancelled": "Cancelled",
    "rejected": "Rejected",
    "failed": "Failed",
    "replaced": "Replaced",
    "expired": "Expired",
    "queued": "Queued",
    "unknown": "Unknown",
}

FALLBACK = "Unknown"


def label(status: str | None) -> str:
    """Das Wort zum Zustand. Unbekanntes wird `Unknown`, nie roher Jargon.

    Ein durchgereichter unbekannter Wert waere die schlechteste Antwort: er
    saehe aus wie eine Aussage und waere keine.
    """
    if not status:
        return FALLBACK
    return LABELS.get(str(status).strip().lower(), FALLBACK)
