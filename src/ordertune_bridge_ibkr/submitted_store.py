"""T1-103 H — was diese Bridge schon einmal abgeschickt hat.

## Der Fehler, aus dem das entstanden ist

`_handle_pending` schickt einen Auftrag an IBKR und meldet ihn danach der
Plattform (`ack_order`). Beides sind zwei Schritte, und dazwischen kann alles
passieren. Bis hierher hatte die Bridge kein Gedaechtnis fuer den Zwischenraum:

  1. `place_order` gelingt, der Auftrag lebt bei IBKR.
  2. `ack_order` scheitert — Zeitueberschreitung, 502, WLAN weg.
  3. Der Dispatch bleibt auf der Plattform `pending`.
  4. Fuenf Sekunden spaeter liefert der Abruf ihn erneut aus.
  5. `place_order` laeuft ein zweites Mal. **Zwei Echtauftraege.**

Der Speicher im Arbeitsspeicher (`_TRADES_BY_DISPATCH`) haette Schritt 5
verhindern koennen, wurde vor dem Absenden aber nie gefragt — und er ueberlebt
ohnehin keinen Neustart. `rebuild_dispatch_map` stellt nach einem Neustart nur
die noch OFFENEN Auftraege wieder her; ein bereits ausgefuehrter ist danach
unsichtbar, und genau fuer ihn waere der zweite Auftrag am teuersten.

## Warum eine Datei und kein Zustand im Speicher

Weil der Neustart der Normalfall ist. IBKR meldet TWS taeglich gegen 05:00 MEZ
zwangsweise ab, jede Aktualisierung der Bridge ist ein Neustart, und ein
Notebook geht abends zu. Ein Riegel gegen Doppelauftraege, der bei jedem dieser
Ereignisse vergisst, ist kein Riegel.

## Warum das kein Sackgassen-Riegel ist

Eingetragen wird VOR dem Absenden, ausgetragen nie — die Datei wird nach Alter
beschnitten (`AUFBEWAHRUNG_TAGE`). Ein Dispatch, den die Plattform weiterhin
als offen ausliefert, obwohl wir ihn abgeschickt haben, ist genau der Fall, den
der Rueckweg (`ack`) und der Abgleich (`/orders/unresolved`) aufloesen. Sie
sind dafuer die richtigen Wege; ein zweiter Auftrag ist es nie.

## Was passiert, wenn die Datei nicht geschrieben werden kann

Dann faellt die Bridge auf das Verhalten von vorher zurueck und protokolliert
das laut. Ein schreibgeschuetztes Verzeichnis darf den Handel nicht anhalten —
aber der Nutzer soll wissen, dass ein Riegel fehlt.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)

STATE_DIR = "run"
DATEINAME = "submitted-dispatches.json"

# Wie lange ein Eintrag mitgefuehrt wird. Deutlich mehr als die 24 Stunden, die
# ein Dispatch auf der Plattform gilt, damit der Riegel den Auftrag ueberlebt,
# gegen den er schuetzt — und kurz genug, dass die Datei nicht endlos waechst.
AUFBEWAHRUNG_TAGE = 30


class SubmittedStore:
    """Dispatch-Kennungen, fuer die schon ein Auftrag an IBKR ging.

    Absichtlich klein und ohne Abhaengigkeiten: der Riegel muss auch dann noch
    funktionieren, wenn sonst nichts mehr geht.
    """

    def __init__(self, state_dir: str | Path = STATE_DIR) -> None:
        self._path = Path(state_dir) / DATEINAME
        self._lock = threading.Lock()
        self._eintraege: dict[str, float] = {}
        self._schreibbar = True
        self._laden()

    # ── Lesen ────────────────────────────────────────────────────────────────

    def bereits_abgeschickt(self, dispatch_id: str) -> bool:
        with self._lock:
            return dispatch_id in self._eintraege

    @property
    def schreibbar(self) -> bool:
        """False heisst: der Riegel ueberlebt keinen Neustart. Laut sagen."""
        return self._schreibbar

    # ── Schreiben ────────────────────────────────────────────────────────────

    def vermerken(self, dispatch_id: str, *, jetzt: float | None = None) -> None:
        """Vor dem Absenden aufrufen, nicht danach.

        Die Reihenfolge ist der ganze Punkt: ein Eintrag ohne Auftrag kostet
        eine ausgelassene Order, die der Nutzer erneut freigeben kann. Ein
        Auftrag ohne Eintrag kostet einen zweiten Echtauftrag.
        """
        with self._lock:
            self._eintraege[dispatch_id] = jetzt if jetzt is not None else time.time()
            self._beschneiden()
            self._speichern()

    def vergessen(self, dispatch_id: str) -> None:
        """Nimmt einen Vermerk zurueck — nur wenn das Absenden gescheitert ist.

        Dann liegt bei IBKR nachweislich nichts, und der naechste Abruf darf
        es erneut versuchen.
        """
        with self._lock:
            if self._eintraege.pop(dispatch_id, None) is not None:
                self._speichern()

    # ── Innereien ────────────────────────────────────────────────────────────

    def _beschneiden(self) -> None:
        grenze = time.time() - AUFBEWAHRUNG_TAGE * 24 * 60 * 60
        for kennung, wann in list(self._eintraege.items()):
            if wann < grenze:
                del self._eintraege[kennung]

    def _laden(self) -> None:
        try:
            roh = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return
        except OSError as exc:
            log.warning(
                "Could not read %s (%s). The bridge cannot tell which orders it "
                "already sent in an earlier session. It will not send a second "
                "order for anything your broker still reports as open, but a "
                "dispatch whose acknowledgement never arrived may go out twice.",
                self._path,
                exc,
            )
            return
        try:
            daten = json.loads(roh)
            if isinstance(daten, dict):
                self._eintraege = {
                    str(k): float(v)
                    for k, v in daten.items()
                    if isinstance(v, (int, float))
                }
        except (ValueError, TypeError) as exc:
            # Eine kaputte Datei ist kein Grund, den Handel anzuhalten — aber
            # auch keiner, sie stillschweigend zu ueberschreiben.
            log.warning("Ignoring a damaged %s: %s", self._path, exc)

    def _speichern(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            # Atomar: ein halb geschriebener Riegel ist schlimmer als keiner.
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._eintraege), encoding="utf-8")
            tmp.replace(self._path)
            try:
                self._path.chmod(0o600)
            except OSError:  # pragma: no cover - Windows kennt den Modus nicht
                pass
            self._schreibbar = True
        except OSError as exc:
            if self._schreibbar:
                log.error(
                    "Could not write %s (%s). Orders still go out, but if this "
                    "bridge restarts between sending an order and confirming it "
                    "to Ordertune, that order could be sent a second time. Fix "
                    "the write permissions for this folder.",
                    self._path,
                    exc,
                )
            self._schreibbar = False
