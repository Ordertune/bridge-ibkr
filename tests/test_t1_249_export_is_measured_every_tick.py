r"""T1-249 (Nachtrag) — die Messung haengt an keiner fremden Bedingung.

## Der gemessene Fall, 2026-09-28

Auf dem VPS des Owners lief Bridge 0.29.2. Das Cockpit zeigte `C:\IBExport` und
„reading it", der Herzschlag ging im Minutentakt raus, das Konto war verbunden.
Und auf der Plattform stand in **zwoelf aufeinanderfolgenden** Herzschlaegen
`exportStatus: FEHLT`.

Die Ursache stand eine Ebene hoeher als der Export. Der Aufruf, der die Messung
setzt, lag mitten in `_handle_order_reconcile` — hinter dessen erster
Abbruchbedingung:

    rows = api.get_unresolved()
    if not rows:
        return          # <- hier war Schluss

Damit hing die Export-Messung an einer Frage, die mit ihr nichts zu tun hat:
„gibt es gerade einen ungeklaerten Auftrag?". Auf einem ruhigen Konto lautet die
Antwort immer nein — und ein ruhiges Konto ist der Normalfall, nicht die
Ausnahme.

Das Cockpit sah dabei richtig aus, weil es einen ANDEREN Weg liest
(`trade_reports.pruefe`). Zwei Wege zu derselben Frage, und nur einer lief.

## Was hier zugesichert wird

Nicht der Inhalt der Messung — den pruefen `test_t1_249_export_status.py` und
`test_t1_249_report_file_without_suffix.py`. Hier steht die **Unabhaengigkeit**:
gemessen wird je Takt, ohne Auftrag, ohne Fuellung, ohne alles.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ordertune_bridge_ibkr import main


KOPF = (
    "Drill Down;Security Type;Last Trading Day;Strike;Put/Call;Currency;"
    "Fin Instrument;Action;Action Sub-Type;Quantity;Comb.;Symbol;Price;Time;"
    "Date;Exch.;Vwap Time;Comment;Account;Order Ref.;ID;"
)
ZEILE = (
    ";STK;;;;USD;ABNB;SLD;;100;;ABNB;151.97;13:30:25;20260925;BEX;;;"
    "DUN950877;;0000e0d5.6ab62134.01.01;"
)


class _Ablage:
    """Der Marken-Speicher, so schlicht wie er im Betrieb wirkt."""

    def __init__(self, seit: str = "20260901") -> None:
        self.tag: str | None = None
        self._seit = seit

    def seit_tag(self, *, heute: Any = None) -> str:
        return self.tag or self._seit

    def erstlauf(self) -> bool:
        return self.tag is None

    def vermerken(self, tag: str | None) -> None:
        if tag:
            self.tag = tag


class _Ibkr:
    def __init__(self, konto: str | None = "DUN950877") -> None:
        self._konto = konto

    def trading_account(self) -> str | None:
        return self._konto


@pytest.fixture(autouse=True)
def _messung_zuruecksetzen() -> Any:
    main._letzte_export_messung = None
    yield
    main._letzte_export_messung = None


@pytest.fixture()
def archiv(tmp_path: Path) -> Path:
    (tmp_path / "trades.20260925").write_text(f"{KOPF}\n{ZEILE}\n", encoding="utf-8")
    return tmp_path


# ── Der Kern ─────────────────────────────────────────────────────────────────


def test_die_messung_braucht_keinen_ungeklaerten_auftrag(archiv: Path) -> None:
    """Der Befund, woertlich.

    `miss_den_export` fragt die Plattform ueberhaupt nicht — es gibt hier kein
    `api`. Genau das ist die Eigenschaft: die Messung kann nicht daran
    scheitern, dass gerade nichts zu klaeren ist.
    """
    main.miss_den_export(
        _Ibkr(), export_dir=str(archiv), report_store=_Ablage()
    )

    messung = main.export_messung()
    assert messung is not None, (
        "Ohne Messung laesst der Herzschlag das Feld weg. Auf der Plattform "
        "heisst ein fehlendes Feld: diese Bridge sagt nichts dazu. Das ist "
        "etwas anderes als: da liegt nichts."
    )
    assert messung["filesRead"] == 1
    assert messung["exportDir"] == str(archiv)


def test_die_messung_meldet_auch_ein_leeres_verzeichnis(tmp_path: Path) -> None:
    """Ein ruhiger Tag ist eine Aussage, kein Schweigen."""
    main.miss_den_export(
        _Ibkr(), export_dir=str(tmp_path), report_store=_Ablage()
    )

    messung = main.export_messung()
    assert messung is not None
    assert messung["filesRead"] == 0
    assert messung["exportDirConfigured"] is True


def test_ohne_verzeichnis_wird_das_nichtwissen_gemeldet() -> None:
    main.miss_den_export(_Ibkr(), export_dir=None, report_store=_Ablage())

    messung = main.export_messung()
    assert messung is not None
    assert messung["exportDirConfigured"] is False


def test_ohne_scharfes_konto_wird_das_ebenfalls_gemeldet(archiv: Path) -> None:
    """Mehrere verwaltete Konten: bewusst nicht gelesen — aber gemeldet."""
    main.miss_den_export(
        _Ibkr(konto=None), export_dir=str(archiv), report_store=_Ablage()
    )

    messung = main.export_messung()
    assert messung is not None
    assert messung["accountKnown"] is False


def test_ein_kaputter_kontoabruf_verhindert_die_messung_nicht(archiv: Path) -> None:
    """Faengt alles ab — die Messung ist Beiwerk, das Lebenszeichen nicht."""

    class _Kaputt:
        def trading_account(self) -> str:
            raise RuntimeError("TWS antwortet nicht")

    main.miss_den_export(
        _Kaputt(), export_dir=str(archiv), report_store=_Ablage()
    )

    messung = main.export_messung()
    assert messung is not None
    assert messung["accountKnown"] is False


# ── Der Rueckgabewert bleibt, was der Abgleich braucht ───────────────────────


def test_die_fuellungen_kommen_weiterhin_zurueck(tmp_path: Path) -> None:
    """Eine EIGENE Fuellung — mit unserem Vermerk — gehoert dem Abgleich."""
    # Der Vermerk traegt die UUID am Ende — `dispatch_id_from_order_ref`
    # verlangt sie, und ohne sie gilt die Zeile als fremder Handel.
    eigene = ZEILE.replace(
        "DUN950877;;0000e0d5",
        "DUN950877;ot-ABNB-33-Tech_Compounder-"
        "bc0bb7e5-a974-4638-ad56-09e443e17427;0000e0d5",
    )
    (tmp_path / "trades.20260925").write_text(
        f"{KOPF}\n{eigene}\n", encoding="utf-8"
    )

    fuellungen = main.miss_den_export(
        _Ibkr(), export_dir=str(tmp_path), report_store=_Ablage()
    )

    assert len(fuellungen) == 1
    assert main.export_messung()["ownFills"] == 1


def test_der_abgleich_liest_nicht_noch_einmal(archiv: Path) -> None:
    """Gereichte Fuellungen werden benutzt, nicht ersetzt.

    Ein zweites Lesen im selben Takt faende wegen der fortgeschriebenen Marke
    weniger Zeilen als das erste — und der Abgleich arbeitete dann auf einer
    aermeren Sicht als die Messung, die gerade rausgegangen ist.
    """
    gelesen: list[str] = []

    def _falle(export_dir: Any, report_store: Any, konto: Any) -> list[Any]:
        gelesen.append(str(export_dir))
        return []

    class _Api:
        def get_unresolved(self) -> list[dict[str, Any]]:
            return [{"dispatchId": "disp-1", "symbol": "ABNB"}]

    echt = main._archiv_fuellungen
    main._archiv_fuellungen = _falle  # type: ignore[assignment]
    try:
        main._handle_order_reconcile(
            _Api(),  # type: ignore[arg-type]
            SimpleNamespace(  # type: ignore[arg-type]
                trading_account=lambda: "DUN950877",
                fills=lambda: [],
                open_trades=lambda: [],
                completed_trades=lambda: [],
            ),
            main.datetime.now(main.timezone.utc),
            export_dir=str(archiv),
            report_store=_Ablage(),
            aus_archiv=[],
        )
    except Exception:
        # Der Abgleich darf an anderer Stelle scheitern — geprueft wird allein,
        # dass er das Archiv nicht ein zweites Mal angefasst hat.
        pass
    finally:
        main._archiv_fuellungen = echt  # type: ignore[assignment]

    assert gelesen == [], (
        "Der Abgleich hat trotz gereichter Fuellungen selbst gelesen — damit "
        "gibt es wieder zwei Messungen desselben Takts."
    )
