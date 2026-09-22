"""T1-207 — wie weit diese Bridge das Archiv der TWS gelesen hat.

## Warum eine Datei und kein Zustand im Speicher

Dieselbe Begruendung wie beim `SubmittedStore`: der Neustart ist der Normalfall.
IBKR meldet die TWS taeglich gegen 05:00 zwangsweise ab, jede Aktualisierung der
Bridge ist ein Neustart, und ein Notebook geht abends zu. Eine Marke im
Arbeitsspeicher waere bei jedem Start wieder leer, und dann lasen wir entweder
jedes Mal das ganze Archiv oder gar nichts.

## Was hier NICHT gespeichert wird

**Keine Menge gemeldeter Ausfuehrungskennungen.** Der naheliegende Entwurf —
„merke dir, was du schon gemeldet hast" — hat eine teure Kehrseite: scheitert
die Meldung an die Plattform (Zeitueberschreitung, 502, WLAN weg), waere die
Fuellung als gemeldet vermerkt und nie wieder angefasst. Verloren, endgueltig.

Die Entdopplung ueber mehrere Sitzungen hinweg macht ohnehin die Plattform: der
Abgleich arbeitet nur an Auftraegen, die sie selbst als offen fuehrt. Was
gebucht ist, kommt nicht wieder. Diese Marke hat deshalb genau eine Aufgabe —
zu begrenzen, WIE VIELE Dateien gelesen werden, nicht WAS davon gilt.

## Der Sicherheitsabstand

Gelesen wird ab der Marke **minus zwei Tage**. Der Tag einer Datei wird aus
ihrem Namen geraten und faellt notfalls auf die Änderungszeit zurueck; beides
kann daneben liegen. Zwei Tage Ueberlappung kosten ein paar hundert Kilobyte
erneutes Lesen und retten eine Datei, die spaeter auftaucht, als ihr Name
behauptet.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timedelta
from pathlib import Path

from . import paths

log = logging.getLogger(__name__)

DATEINAME = "trade-reports.json"

#: Wie weit vor der Marke erneut gelesen wird. Siehe Modulkopf.
SICHERHEITSABSTAND_TAGE = 2

#: Wie weit der allererste Lauf zurueckgreift, wenn es noch keine Marke gibt.
#: Ein Kunde kann ein Archiv von zwei Jahren liegen haben; das auf einen Schlag
#: einzulesen waere kein Nachtragen mehr, sondern eine Migration — und eine,
#: die niemand angeordnet hat.
ERSTLAUF_TAGE = 7


def _tag(zeitpunkt: datetime) -> str:
    return zeitpunkt.strftime("%Y%m%d")


def _minus_tage(tag: str, tage: int) -> str:
    try:
        return _tag(datetime.strptime(tag, "%Y%m%d") - timedelta(days=tage))  # noqa: DTZ007
    except ValueError:
        return "00000000"


class TradeReportStore:
    """Die Wasserstandsmarke auf dem Archiv der TWS."""

    def __init__(
        self,
        state_dir: str | Path | None = None,
        *,
        erstlauf_tage: int = ERSTLAUF_TAGE,
    ) -> None:
        basis = paths.run_dir() if state_dir is None else Path(state_dir)
        self._path = basis / DATEINAME
        self._lock = threading.Lock()
        self._letzter_tag: str | None = None
        self._schreibbar = True
        self._erstlauf_tage = max(0, erstlauf_tage)
        self._laden()

    # ── Lesen ────────────────────────────────────────────────────────────────

    def seit_tag(self, *, heute: datetime | None = None) -> str:
        """Ab welchem Tag gelesen wird, einschliesslich.

        Ohne Marke ist es der Erstlauf: dann greift die Altersgrenze, und alles
        Aeltere wird nicht angefasst.
        """
        with self._lock:
            marke = self._letzter_tag
        if marke:
            return _minus_tage(marke, SICHERHEITSABSTAND_TAGE)
        # Ortstag, passend zu den Dateinamen, die die TWS auf derselben
        # Maschine vergibt.
        jetzt = heute or datetime.now()  # noqa: DTZ005
        return _minus_tage(_tag(jetzt), self._erstlauf_tage)

    @property
    def erstlauf(self) -> bool:
        with self._lock:
            return self._letzter_tag is None

    @property
    def schreibbar(self) -> bool:
        """False heisst: die Marke ueberlebt keinen Neustart. Laut sagen."""
        return self._schreibbar

    # ── Schreiben ────────────────────────────────────────────────────────────

    def vermerken(self, tag: str | None) -> None:
        """Die Marke auf den juengsten gelesenen Dateitag ziehen.

        Nur vorwaerts. Eine Datei mit geratenem, zu altem Tag darf die Marke
        nicht zurueckziehen — sonst waechst die Lesemenge bei jedem Lauf.
        """
        if not tag:
            return
        with self._lock:
            if self._letzter_tag is not None and tag <= self._letzter_tag:
                return
            self._letzter_tag = tag
            self._speichern()

    # ── Innereien ────────────────────────────────────────────────────────────

    def _laden(self) -> None:
        try:
            roh = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return
        except OSError as exc:
            log.warning(
                "Could not read %s (%s). The bridge will treat this as a first "
                "run and only look at the last few days of TWS trade reports.",
                self._path,
                exc,
            )
            return
        try:
            daten = json.loads(roh)
            if isinstance(daten, dict):
                wert = daten.get("letzterTag")
                if isinstance(wert, str) and wert.isdigit() and len(wert) == 8:
                    self._letzter_tag = wert
        except (ValueError, TypeError) as exc:
            log.warning("Ignoring a damaged %s: %s", self._path, exc)

    def _speichern(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps({"letzterTag": self._letzter_tag}), encoding="utf-8"
            )
            tmp.replace(self._path)
            try:
                self._path.chmod(0o600)
            except OSError:  # pragma: no cover - Windows kennt den Modus nicht
                pass
            self._schreibbar = True
        except OSError as exc:
            if self._schreibbar:
                log.error(
                    "Could not write %s (%s). The bridge still recovers fills "
                    "from the TWS trade reports, but after a restart it will "
                    "re-read the last few days every time instead of picking up "
                    "where it left off.",
                    self._path,
                    exc,
                )
            self._schreibbar = False
