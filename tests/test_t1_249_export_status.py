"""T1-249 — der Export meldet auch, wenn er nichts zu melden hat.

## Der gemessene Fall, 2026-09-28

Auf dem Windows-VPS des Owners lag `C:\\IBExport\\trades.20260925` — 9 KB,
vollstaendig, mit den 138 manuell verkauften ABNB und dem Kauf ueber 33.
Die Plattform meldete trotzdem **kein** `exportStatus`.

Ursache: `_archiv_fuellungen` kehrte bei fehlendem Exportverzeichnis zurueck,
BEVOR irgendetwas gemessen wurde. Auf der Plattform heisst ein fehlendes Feld
„unbekannt" (alte Bridge) — der Zustand „nicht eingerichtet" war damit gar
nicht erreichbar. Ausgerechnet der Fall, fuer den T1-249 gebaut wurde.

**Ein Nichtwissen zu melden ist nicht dasselbe wie nichts zu melden.**
"""
from __future__ import annotations

import pytest

from ordertune_bridge_ibkr import main


@pytest.fixture(autouse=True)
def _messung_zuruecksetzen():
    main._letzte_export_messung = None
    yield
    main._letzte_export_messung = None


class _Store:
    def seit_tag(self) -> str | None:
        return None

    def vermerken(self, tag: str | None) -> None:  # pragma: no cover
        pass


def test_ohne_exportverzeichnis_wird_trotzdem_gemeldet() -> None:
    """Der Fall vom 2026-09-28. Vorher: gar keine Meldung."""
    main._archiv_fuellungen(None, _Store(), "DUN950877")

    m = main.export_messung()
    assert m is not None, "ohne Meldung ist der Zustand von einer alten Bridge nicht zu unterscheiden"
    assert m["exportDirConfigured"] is False
    assert m["accountKnown"] is True
    assert m["filesRead"] == 0


def test_die_meldung_nennt_den_pfad() -> None:
    """Ein Vorgabewert, den niemand sieht, ist einer, den niemand berichtigt."""
    main._archiv_fuellungen("C:/IBExport", _Store(), None)

    m = main.export_messung()
    assert m is not None
    assert m["exportDir"] == "C:/IBExport"


def test_ohne_konto_wird_ebenfalls_gemeldet() -> None:
    """Ohne scharfes Konto wird nichts gelesen — auch das ist eine Aussage."""
    main._archiv_fuellungen("C:/IBExport", _Store(), None)

    m = main.export_messung()
    assert m is not None
    assert m["exportDirConfigured"] is True
    assert m["accountKnown"] is False


def test_die_meldung_traegt_immer_dieselben_felder() -> None:
    """Zwei Bauorte waeren zwei Gelegenheiten, ein Feld zu vergessen."""
    main._archiv_fuellungen(None, _Store(), None)
    ohne = set(main.export_messung() or {})

    erwartet = {
        "readAt",
        "filesRead",
        "ownFills",
        "foreignRows",
        "otherAccountRows",
        "quarantinedRows",
        "newestFileDay",
        "exportDirConfigured",
        "accountKnown",
        # T1-249 (Nachtrag): WELCHER Pfad. Ohne ihn konnte der Owner nicht
        # sehen, wo die Bridge ueberhaupt sucht.
        "exportDir",
    }
    assert ohne == erwartet


def test_ein_lesefehler_ist_eine_aussage(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ein unlesbares Archiv darf nicht aussehen wie ein fehlendes."""

    def kaputt(*_a: object, **_k: object) -> object:
        raise OSError("Zugriff verweigert")

    monkeypatch.setattr(main.trade_reports, "lies_archiv", kaputt)
    main._archiv_fuellungen("C:/IBExport", _Store(), "DUN950877")

    m = main.export_messung()
    assert m is not None
    assert m["exportDirConfigured"] is True
    assert "Zugriff verweigert" in m["readError"]


def test_der_zeitstempel_traegt_die_z_form() -> None:
    """`+00:00` weist die Plattform mit 422 ab — die Falle aus T1-78."""
    main._archiv_fuellungen(None, _Store(), None)

    m = main.export_messung()
    assert m is not None
    assert m["readAt"].endswith("Z")
    assert "+00:00" not in m["readAt"]
