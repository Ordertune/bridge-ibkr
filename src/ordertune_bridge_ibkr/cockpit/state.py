"""T1-101 B-1 — der Zustandsblock: was der Kern gerade ueber sich weiss.

## Die Richtungsregel

Der Kern **schreibt**, das Cockpit **liest**. Nie umgekehrt, und der Server
fasst die IBKR-Verbindung nie an. Damit gilt „ein offenes Fenster kann den
Handel weder verlangsamen noch stoeren" durch die Bauform und nicht durch
Disziplin beim Programmieren.

Deshalb steht hier eine unveraenderliche Momentaufnahme hinter einem Schloss,
das nur fuer die Dauer eines Zeigertauschs gehalten wird — nicht eine Ablage,
in der zwei Threads herumschreiben. Der Kern baut eine neue Aufnahme und haengt
sie ein; ein Leser bekommt immer eine vollstaendige, in sich stimmige.

## Warum fluechtig

Alles hier ist beim naechsten Start aus IBKR und t1 wieder herstellbar, oder es
beantwortet die Frage „wie geht es gerade" — die nach einem Neustart keine
Bedeutung mehr hat. Eine Datei erzeugte nur eine zweite Wahrheit, die veralten
kann.

## Zeitpunkte bleiben Zeitpunkte

Nach aussen gehen ISO-Zeitstempel, keine fertigen Saetze wie „vor 42 s". Das
Alter rechnet die Flaeche selbst. Eine stehende Zeitangabe, die aussieht wie
eine laufende, ist eine dauerhaft falsche Aussage.
"""
from __future__ import annotations

import threading
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class CockpitState:
    """Eine vollstaendige Momentaufnahme. Unveraenderlich."""

    # ── Ueber sich selbst ────────────────────────────────────────────────
    bridge_version: str = ""
    client_id: int = 0
    gateway_host: str = ""
    gateway_port: int = 0
    fingerprint_prefix: str = ""
    log_path: str = ""
    api_base: str = ""

    # ── Lage ─────────────────────────────────────────────────────────────
    tws_connected: bool = False
    ordertune_ok: bool = False
    # T1-99 woertlich: „noch keine Auskunft" ist ein eigener Zustand und nicht
    # dasselbe wie „das Konto haelt nichts".
    account_known: bool = False

    # ── Zeitpunkte (ISO, UTC) ────────────────────────────────────────────
    started_at: str = field(default_factory=_now_iso)
    session_connected_at: str | None = None
    last_heartbeat_at: str | None = None
    last_pending_poll_at: str | None = None

    # ── Konto ────────────────────────────────────────────────────────────
    currency: str | None = None
    cash: float | None = None
    equity: float | None = None
    # T1-103 O: welches IBKR-Konto am Draht haengt. Beim Wechsel zwischen
    # Live- und Papierkonto war das nirgends abzulesen, und man musste es aus
    # dem Depotwert erraten. Maskiert — die vollstaendige Nummer gehoert nicht
    # in eine Anzeige, die ueber HTTP ausgeliefert wird.
    account_masked: str | None = None
    # None heisst „keine Aussage", [] heisst „das Konto haelt nichts".
    positions: list[dict[str, Any]] | None = None

    # ── Auftraege (T1-101 B-3) ───────────────────────────────────────────
    # Wieder dieselbe Unterscheidung: `None` heisst „diese Verbindung konnte
    # IBKR nicht nach Auftraegen fragen", `[]` heisst „es gibt keine".
    orders: list[dict[str, Any]] | None = None

    # ── Schreibzugriff (T1-101 B-2) ──────────────────────────────────────
    write_access: str = "unknown"
    # IBKRs eigener Wortlaut, in der Sprache der TWS-Installation. Nur zur
    # Anzeige — die Entscheidung faellt am Fehlercode.
    write_access_detail: str | None = None

    # ── Einrichtung (T1-101 C) ───────────────────────────────────────────
    # Der Assistent laeuft, wenn `bridge.env` fehlt oder nicht laedt. Dann ist
    # ausser diesem Feld praktisch nichts belegt — es gibt ja noch nichts.
    setup_mode: bool = False
    # Eine Aenderung wurde geschrieben und wirkt beim naechsten Start (C-5).
    pending_restart: bool = False

    # ── Stoerung ─────────────────────────────────────────────────────────
    # Die Kennung aus `failures.py`, damit Konsole und Flaeche dieselbe
    # Stoerung an derselben Kennung erkennen.
    failure_code: str | None = None
    failure_headline: str | None = None
    failure_detail: list[str] = field(default_factory=list)
    failure_action: list[str] = field(default_factory=list)

    def to_wire(self) -> dict[str, Any]:
        return asdict(self)


class StateStore:
    """Haelt die jeweils aktuelle Aufnahme und zaehlt jede Aenderung mit.

    Der Zaehler ist das, woran der Ereignisstrom erkennt, dass es etwas Neues
    gibt — ohne die Aufnahmen vergleichen zu muessen und ohne einen Takt, der
    unabhaengig vom Kern laeuft.
    """

    def __init__(self, initial: CockpitState | None = None) -> None:
        self._lock = threading.Lock()
        self._state = initial or CockpitState()
        self._version = 0

    def get(self) -> tuple[CockpitState, int]:
        with self._lock:
            return self._state, self._version

    def update(self, **changes: Any) -> CockpitState:
        """Baut die naechste Aufnahme aus der aktuellen plus den Aenderungen.

        Bewusst kein „setze Feld X": ein Leser soll nie eine halb gepflegte
        Aufnahme sehen. Der Tausch des Zeigers ist die einzige Schreiboperation.
        """
        with self._lock:
            self._state = replace(self._state, **changes)
            self._version += 1
            return self._state
