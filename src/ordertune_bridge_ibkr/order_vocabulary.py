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


# ── T1-137 — die Ablehnungserkennung, jetzt fuer BEIDE Meldewege ─────────────
#
# ## Warum sie hierher gewandert ist
#
# Sie stand vollstaendig in `main.py` und wurde dort von genau einem Weg
# gefragt: der Nachbeobachtung einer verdaechtigen Stornierung. Der zweite Weg
# — der Abgleichslauf in `order_reconcile.py` — hatte den Grund stattdessen
# fest verdrahtet:
#
#     if status in ("Cancelled", "ApiCancelled"):
#         reason_code="cancelled_by_user"   # unabhaengig vom Protokoll
#
# Am 2026-08-31 hat IBKR vier Auftraege wegen fehlender Deckung abgewiesen
# (Error 201). Auf t1 standen sie als `cancelled_by_user` — eine Behauptung
# ueber eine Handlung des Nutzers, die es nie gab, und die einzige
# handlungsrelevante Auskunft (2.335 USD reichen nicht fuer 2.554 USD) fehlte.
#
# Der Grund-Code sagte damit nicht, WAS passiert ist, sondern welcher Codepfad
# zuerst hingesehen hat. Das ist die Wurzel, und sie verschwindet nur, wenn
# beide Wege dieselbe Frage an dieselbe Stelle richten.
#
# Sie steht hier und nicht in `main.py`, weil `order_reconcile` bewusst ohne
# ib_insync auskommt: die Trade-OBJEKTE sind das Problem, nicht die Vokabeln.
# Alles unten liest ausschliesslich ueber `getattr` — dieselbe Grenze, die
# T1-120 fuer `IBKR_TO_WIRE_STATUS` gezogen hat, als daraus sonst die dritte
# Kopie geworden waere.

#   201  Order rejected — IBKR weist den Auftrag ab, mit Begruendung im Text
#
# Bewusst eine ENGE, belegte Liste und keine Heuristik ueber Zahlenbereiche:
# was hier falsch geraten wird, kostet entweder einen Echtauftrag oder ein
# verlorenes Signal. Neue Codes kommen dazu, wenn sie beobachtet wurden.
REJECTION_CODES = frozenset({201})

# Die echten Stornobestaetigungen. Code 0 gehoert dazu: ein Protokolleintrag
# ohne Fehlercode ist ein blosser Zustandswechsel und keine Ablehnung.
GENUINE_CANCEL_CODES = frozenset({0, 202, 10148})

# IBKR dokumentiert den Block 2100–2199 als „Warning Message"; Warnungen
# beenden keinen Auftrag. Aus dieser Klasse stammt der Vorfall vom 2026-08-13.
WARNING_CODE_MIN = 2100
WARNING_CODE_MAX = 2200

# Warnungen ausserhalb des 2100er-Blocks, die uns nachweislich begegnet sind.
# 10349 ist der Ausloeser von T1-88b: „Gueltigkeitsdauer auf DAY gesetzt" —
# eine Anpassung, keine Ablehnung, und ib_insync macht daraus trotzdem ein
# erfundenes `Cancelled`. Waechst nur mit gemessenen Faellen.
KNOWN_WARNING_CODES = frozenset({10349})


def is_warning_code(code: int) -> bool:
    """Ist das eine Warnung von IBKR und damit kein Ende des Auftrags?"""
    if code in KNOWN_WARNING_CODES:
        return True
    return WARNING_CODE_MIN <= code < WARNING_CODE_MAX


def rejection_reason_of(trade: object) -> str | None:
    """Der Wortlaut, mit dem IBKR diesen Auftrag abgelehnt hat, oder nichts.

    Zwei Wege zur selben Antwort:

    1. Ein Code aus `REJECTION_CODES` irgendwo im Protokoll. Das ist der
       belegte Fall und bleibt unveraendert.
    2. Der allgemeine Fall (T1-103 G): der LETZTE Protokolleintrag traegt einen
       Fehlercode, der weder eine Stornobestaetigung noch eine Warnung ist.
       Der letzte Eintrag ist der, der den aktuellen Zustand ausgeloest hat —
       dieselbe Stelle, an der `cancel_is_genuine` seit T1-88b nachsieht.

    Der zweite Weg wird nur beschritten, wenn nichts gefuellt wurde. Eine
    Ausfuehrung ist am Konto passiert; was danach im Protokoll steht, kann sie
    nicht mehr zu einer Ablehnung machen.

    `None` heisst „keine Ablehnung gefunden" — und dann bleibt es bei der
    Vorsicht aus T1-88b.

    ## Die Grenze, die dem Abgleichslauf gilt

    Ein Auftrag aus `reqCompletedOrders` traegt KEIN Protokoll — ib_insync baut
    es nur fuer Auftraege, die diese Sitzung selbst platziert hat. Dann liefern
    beide Wege hier `None`, und das ist die richtige Antwort: ohne Protokoll
    gibt es keinen Beleg fuer eine Ablehnung. Der Aufrufer darf daraus keine
    Nutzerhandlung machen — genau das war der Fehler vom 2026-08-31.
    """
    entries = list(getattr(trade, "log", None) or [])

    for entry in reversed(entries):
        if getattr(entry, "errorCode", 0) in REJECTION_CODES:
            message = (getattr(entry, "message", "") or "").strip()
            return message or "Rejected by IBKR."

    if not entries:
        return None

    # Der allgemeine Weg deutet einen als storniert gemeldeten Auftrag um. Er
    # gilt deshalb NUR dort, wo genau das vorliegt: der Auftrag steht jetzt auf
    # `Cancelled`. Lebt er noch — und das ist der Verlauf des Vorfalls vom
    # 2026-08-13, wo eine Sekunde spaeter `Submitted` kam —, ist hier nichts zu
    # entscheiden. Ohne Zustandsangabe wird ebenfalls nichts behauptet.
    status = getattr(getattr(trade, "orderStatus", None), "status", "")
    if IBKR_TO_WIRE_STATUS.get(str(status)) != "cancelled":
        return None

    filled = float(getattr(getattr(trade, "orderStatus", None), "filled", 0) or 0)
    if filled != 0:
        return None

    letzter = entries[-1]
    code = getattr(letzter, "errorCode", None)
    if code is None:
        return None
    # Code 0 steckt bereits in `GENUINE_CANCEL_CODES` — ein Eintrag ohne
    # Fehlercode ist ein Zustandswechsel und sagt nichts ueber eine Ablehnung.
    if code in GENUINE_CANCEL_CODES:
        return None
    if is_warning_code(code):
        return None

    message = (getattr(letzter, "message", "") or "").strip()
    return message or "Rejected by IBKR."
