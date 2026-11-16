"""T1-416 — eine ruhige Woche ist kein abgeschalteter Export.

Owner-Befund 2026-11-16: Trading einige Tage ausgesetzt, Export in TWS an,
letzte Datei korrekt am 10.11. abgelegt. Die Bridge meldete trotzdem
„TWS is not writing trade reports“, weil `pruefe` nur das Alter der neuesten
Datei ansah. TWS schreibt aber nur dann eine Datei, wenn etwas gefuellt wurde.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from ordertune_bridge_ibkr import trade_reports


def _schreibe(ordner: Path, name: str) -> None:
    (ordner / name).write_text("Account;Order Ref.;ID;Quantity;Price;Date;Time\n", encoding="utf-8")


def test_ohne_fuellung_seit_der_letzten_datei_keine_warnung(tmp_path: Path) -> None:
    _schreibe(tmp_path, "trades.20261110.csv")
    bereit = trade_reports.pruefe(tmp_path, heute="20261116", fuellungstage=[])
    assert bereit.ok, bereit.text
    assert "20261110" in bereit.text


def test_fuellung_vor_der_letzten_datei_warnt_nicht(tmp_path: Path) -> None:
    _schreibe(tmp_path, "trades.20261110.csv")
    bereit = trade_reports.pruefe(
        tmp_path, heute="20261116", fuellungstage=["20261110", "20261109"]
    )
    assert bereit.ok


def test_fuellung_nach_der_letzten_datei_warnt(tmp_path: Path) -> None:
    _schreibe(tmp_path, "trades.20261110.csv")
    bereit = trade_reports.pruefe(tmp_path, heute="20261116", fuellungstage=["20261116"])
    assert bereit.zustand == "stale"
    assert "20261116" in bereit.text


def test_ohne_kenntnis_der_fuellungen_bleibt_es_bei_der_alten_regel(
    tmp_path: Path,
) -> None:
    """`--check-reports` laeuft ohne TWS: dort bleibt die Altersregel."""
    _schreibe(tmp_path, "trades.20261110.csv")
    assert trade_reports.pruefe(tmp_path, heute="20261116").zustand == "stale"


def test_fuellungstage_aus_ib_fills() -> None:
    from ordertune_bridge_ibkr.main import fuellungstage_aus

    fills = [
        SimpleNamespace(time=datetime(2026, 11, 16, 15, 0, tzinfo=timezone.utc)),
        SimpleNamespace(time=None),
        SimpleNamespace(),
    ]
    jetzt = datetime(2026, 11, 16, 16, 0, tzinfo=timezone.utc)
    tage = fuellungstage_aus(fills, jetzt=jetzt)
    assert len(tage) == 1
    assert tage[0].startswith("202611")


def test_frische_fuellung_zaehlt_noch_nicht() -> None:
    """Die TWS schreibt im Minutentakt; eine Fuellung von eben ist kein Befund."""
    from ordertune_bridge_ibkr.main import fuellungstage_aus

    jetzt = datetime(2026, 11, 16, 16, 0, tzinfo=timezone.utc)
    frisch = [SimpleNamespace(time=datetime(2026, 11, 16, 15, 55, tzinfo=timezone.utc))]
    assert fuellungstage_aus(frisch, jetzt=jetzt) == []
