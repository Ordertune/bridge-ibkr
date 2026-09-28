"""T1-249 — eine Berichtsdatei ohne Endung ist ein Bericht.

## Der gemessene Fall, 2026-09-28

Auf dem Windows-VPS des Owners lag `C:\\IBExport\\trades.20260925`: 9 KB,
vollstaendig, mit den 138 manuell verkauften ABNB und dem Kauf ueber 33.
**Ohne Dateiendung.**

Der Leser nahm nur `*.csv`. Er verwarf die Datei ungesehen, die
Bereitschaftspruefung meldete „noch kein Bericht", und die Plattform sah nie
eine Zeile davon — waehrend der Owner drei Tage lang einen vollstaendigen
Export auf der Platte hatte.

Das Bittere: die Datei heisst so, **weil unsere eigene Anleitung es verlangt.**
`config.py` sagt woertlich „leave 'Export filename' EMPTY there so TWS writes
one dated file per trading day" — und dann vergibt die TWS keinen Suffix.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ordertune_bridge_ibkr import trade_reports as tr

KOPF = (
    "Drill Down;Security Type;Last Trading Day;Strike;Put/Call;Currency;"
    "Fin Instrument;Action;Action Sub-Type;Quantity;Comb.;Symbol;Price;Time;"
    "Date;Exch.;Vwap Time;Comment;Account;Order Ref.;ID;"
)
ZEILE = (
    ";STK;;;;USD;ABNB;SLD;;100;;ABNB;151.97;13:30:25;20260925;BEX;;;"
    "DUN950877;;0000e0d5.6ab62134.01.01;"
)


def test_die_datei_des_owners_gilt_als_bericht(tmp_path: Path) -> None:
    """`trades.20260925` — genau der Name vom Windows-VPS."""
    datei = tmp_path / "trades.20260925"
    datei.write_text(f"{KOPF}\n{ZEILE}\n", encoding="utf-8")

    assert tr.ist_berichtsdatei(datei) is True


def test_mit_endung_gilt_sie_weiterhin(tmp_path: Path) -> None:
    """Wer einen Dateinamen gesetzt hat, bekommt `.csv` — auch das bleibt."""
    datei = tmp_path / "trades.20260925.csv"
    datei.write_text(f"{KOPF}\n{ZEILE}\n", encoding="utf-8")

    assert tr.ist_berichtsdatei(datei) is True


def test_eine_csv_ohne_tag_bleibt_zulaessig(tmp_path: Path) -> None:
    """Mit gesetztem Dateinamen steht der Tag nur in der Spalte `Date`."""
    datei = tmp_path / "meine-trades.csv"
    datei.write_text(f"{KOPF}\n{ZEILE}\n", encoding="utf-8")

    assert tr.ist_berichtsdatei(datei) is True


@pytest.mark.parametrize("name", ["notizen.txt", "bridge.log", "readme"])
def test_was_weder_tag_noch_endung_traegt_bleibt_draussen(
    tmp_path: Path, name: str
) -> None:
    datei = tmp_path / name
    datei.write_text("irgendwas\n", encoding="utf-8")

    assert tr.ist_berichtsdatei(datei) is False


def test_ein_verzeichnis_ist_keine_datei(tmp_path: Path) -> None:
    (tmp_path / "trades.20260925").mkdir()

    assert tr.ist_berichtsdatei(tmp_path / "trades.20260925") is False


def test_die_bereitschaft_sieht_die_datei_jetzt(tmp_path: Path) -> None:
    """Vorher: „noch kein Bericht", obwohl 9 KB danebenlagen."""
    (tmp_path / "trades.20260925").write_text(
        f"{KOPF}\n{ZEILE}\n", encoding="utf-8"
    )

    bereit = tr.pruefe(tmp_path, heute="20260928")

    assert bereit.zustand != "no_files", bereit.text


def test_das_archiv_wird_gelesen(tmp_path: Path) -> None:
    """Der eigentliche Zweck: die Zeile kommt an."""
    (tmp_path / "trades.20260925").write_text(
        f"{KOPF}\n{ZEILE}\n", encoding="utf-8"
    )

    lesung = tr.lies_archiv(str(tmp_path), "DUN950877", seit_tag=None)

    assert lesung.gelesene_dateien == 1
    # Ohne `ot-`-Vermerk: eine fremde Zeile. Gezaehlt, nicht gebucht.
    assert lesung.fremde == 1


def test_eine_datei_mit_tag_aber_ohne_bericht_kostet_nichts(tmp_path: Path) -> None:
    """Sie wird angefasst und faellt in die Quarantaene — kein Absturz."""
    (tmp_path / "logfile.20260925").write_text("kein Bericht\n", encoding="utf-8")

    lesung = tr.lies_archiv(str(tmp_path), "DUN950877", seit_tag=None)

    assert lesung.fuellungen == []
