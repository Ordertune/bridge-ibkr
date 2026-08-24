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


# ── T1-120 — IBKRs Auftragszustand -> der Draht-Zustand ─────────────────────
#
# ## Warum die Abbildung hierher gewandert ist
#
# Sie stand in `main._STATUS_MAP`, und `order_reconcile` fuehrte daneben eine
# Teilmenge davon (`_LIVE_IBKR_STATES`) mit dem Kommentar „wortgleich zur
# Abbildung in main._STATUS_MAP — hier noch einmal, weil diese Datei ohne
# ib_insync auskommen soll". Das war schon die zweite Kopie; der Abgleich
# braucht jetzt die volle Abbildung und waere die dritte gewesen.
#
# Die Begruendung fuer die Trennung war ausserdem nie tragfaehig: ein dict aus
# Zeichenketten haengt an keiner Bibliothek. Was `order_reconcile` von
# ib_insync freihalten muss, sind die Trade-OBJEKTE — nicht die Vokabeln.
IBKR_TO_WIRE_STATUS: dict[str, str] = {
    # Unterwegs, noch nicht am Markt.
    "PendingSubmit": "submitting",
    "ApiPending": "submitting",
    # Am Markt, lebendig.
    "PreSubmitted": "working",
    "Submitted": "working",
    "PendingCancel": "working",
    # T1-88b F4: `Inactive` steht NICHT in `OrderStatus.DoneStates` und ist
    # mehrdeutig — IBKR benutzt es sowohl fuer abgelehnt als auch fuer
    # "angenommen, aber nicht ausfuehrbar". Es als `rejected` zu melden hiesse,
    # im Zweifel den Riegel zu oeffnen, und ein faelschlich geoeffneter Riegel
    # kostet einen zweiten Echtauftrag. Ein faelschlich geschlossener kostet
    # einen Klick. Deshalb nicht-terminal, und laut protokolliert.
    "Inactive": "working",
    # Endzustaende.
    "Filled": "filled",
    "PartiallyFilled": "partial",
    "Cancelled": "cancelled",
    "ApiCancelled": "cancelled",
}

# Draht-Zustaende, die einen lebenden Auftrag beschreiben.
LIVE_WIRE_STATES = frozenset({"submitting", "working"})

# Die IBKR-Zustaende, die einen lebenden Auftrag beschreiben — abgeleitet und
# nicht abgeschrieben. Faellt oben ein Eintrag weg, faellt er hier mit.
LIVE_IBKR_STATES = frozenset(
    ibkr for ibkr, wire in IBKR_TO_WIRE_STATUS.items() if wire in LIVE_WIRE_STATES
)
