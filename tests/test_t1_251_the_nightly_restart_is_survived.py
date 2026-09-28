r"""T1-251 — der naechtliche TWS-Neustart beendet die Bridge nicht.

## Der gemessene Fall, 2026-09-28

Der Owner hat in der TWS eingestellt, dass sie sich taeglich selbst neu
startet. Jedes Mal stand danach auf dem Windows-VPS dieses Fenster:

    Failed to execute script 'launcher' due to unhandled exception:
    Socket disconnect

    File "ordertune_bridge_ibkr\main.py", line 2091, in run_loop
    File "ordertune_bridge_ibkr\ibkr_client.py", line 710, in sleep
    File "ib_insync\util.py", line 386, in sleep
    ConnectionError: Socket disconnect

Die Wiederverbindung ist seit T1-152d gebaut. Sie war fuer genau diesen Fall
**unerreichbar**: `run_loop` kannte zwei Ausgaenge — das Stopp-Signal und
`is_connected() == False`. Bricht die Leitung WAEHREND des Schlafs, nimmt
ib_insync keinen davon, sondern wirft. Die Ausnahme ging an der
Schleifenbedingung vorbei, durch `run_supervised` hindurch, aus `main` heraus.

**Der Riegel existierte, nur auf dem anderen Weg.** Zum achten Mal in diesem
Projekt.

## Drei Folgen, und die dritte sah aus wie ein eigener Fehler

  1. Die Bridge war weg, bis jemand sich auf den VPS verband.
  2. Der Absturzdialog ist modal. Auf einem Server klickt ihn niemand weg.
  3. Weil der Vorgang stehen blieb, liess sich die EXE nicht loeschen — der
     Owner musste vor jedem Fassungswechsel in den Taskmanager. Das war keine
     zweite Ursache, sondern dieselbe.
"""
from __future__ import annotations

import os
import threading
from types import SimpleNamespace
from typing import Any

import pytest

from ordertune_bridge_ibkr import main


class _Ibkr:
    """Eine TWS, die nach `bricht_nach` Schlafvorgaengen die Leitung kappt."""

    def __init__(self, *, bricht_nach: int = 1, fehler: BaseException | None = None):
        self._schlaefe = 0
        self._bricht_nach = bricht_nach
        self._fehler = fehler or ConnectionError("Socket disconnect")
        self.verbunden = True
        self.versuche = 0

    def is_connected(self) -> bool:
        return self.verbunden

    def sleep(self, seconds: float) -> None:
        self._schlaefe += 1
        if self._schlaefe >= self._bricht_nach:
            self.verbunden = False
            raise self._fehler

    def connect(self) -> None:
        self.versuche += 1
        self.verbunden = True


# ── 1) Der Abbruch im Schlaf faellt nicht aus der Schleife ───────────────────


@pytest.mark.parametrize(
    "fehler",
    [
        ConnectionError("Socket disconnect"),
        # Steht im Rueckverfolgungsbericht des Owners ganz oben und erbt seit
        # Python 3.8 NICHT mehr von `Exception`.
        __import__("asyncio").exceptions.CancelledError(),
        OSError("WinError 10054"),
        TimeoutError("read timed out"),
    ],
)
def test_ein_abbruch_im_schlaf_beendet_nur_die_sitzung(fehler: BaseException) -> None:
    """Er wird behandelt wie `is_connected() == False` — als Zustand."""
    stop = threading.Event()
    ibkr = _Ibkr(fehler=fehler)

    # Kehrt zurueck, statt zu werfen. Genau das ist der Unterschied.
    main.run_loop(
        ibkr,
        heartbeat=lambda: None,
        pending=lambda: None,
        stop=stop,
        tick_s=0.0,
    )

    assert not stop.is_set(), "Ein Leitungsabbruch ist keine Anweisung zu stoppen."


# ── 2) Der Aufseher verbindet neu, statt zu sterben ──────────────────────────


def test_der_naechtliche_neustart_fuehrt_zu_einer_wiederverbindung() -> None:
    """Der Fall des Owners, von Anfang bis Ende.

    Die TWS kappt, die Bridge verbindet neu und laeuft weiter. Ohne die
    Korrektur endet dieser Test mit `ConnectionError` statt mit einer
    Zusicherung.
    """
    stop = threading.Event()
    ibkr = _Ibkr()
    wiederverbunden: list[int] = []

    def _reconnect(ziel: Any, halt: threading.Event) -> bool:
        ziel.connect()
        wiederverbunden.append(1)
        # Nach der zweiten Sitzung ist Schluss, sonst liefe der Test ewig.
        if len(wiederverbunden) >= 2:
            halt.set()
        return not halt.is_set()

    main.run_supervised(
        ibkr,
        heartbeat=lambda: None,
        pending=lambda: None,
        stop=stop,
        reconnect=_reconnect,
        loop=lambda z, **k: main.run_loop(z, tick_s=0.0, **k),
    )

    assert len(wiederverbunden) == 2
    assert ibkr.versuche == 2


def test_aus_dem_aufseher_faellt_nichts_heraus() -> None:
    """Der zweite Riegel, unabhaengig vom ersten.

    Selbst wenn die Schleife etwas voellig Unerwartetes wirft, ist das kein
    Grund, den Vorgang zu beenden — auf einem VPS heisst „Vorgang beendet sich
    in einen Dialog" naemlich „Bridge weg, bis jemand kommt".
    """
    stop = threading.Event()
    versuche: list[int] = []

    def _kaputte_schleife(ziel: Any, **_: Any) -> None:
        versuche.append(1)
        raise RuntimeError("etwas, womit niemand gerechnet hat")

    def _reconnect(ziel: Any, halt: threading.Event) -> bool:
        halt.set()
        return False

    main.run_supervised(
        _Ibkr(),
        heartbeat=lambda: None,
        pending=lambda: None,
        stop=stop,
        loop=_kaputte_schleife,
        reconnect=_reconnect,
    )

    assert versuche == [1]


def test_die_flaeche_erfaehrt_vom_verlust_bevor_gewartet_wird() -> None:
    """Die Wartezeiten wachsen bis auf eine Minute je Versuch.

    In dieser Zeit stuende sonst eine Flaeche da, die „TWS connected"
    behauptet, waehrend nichts verbunden ist — und der Nutzer sieht als
    Einziges, dass sein Herzschlag altert. Eine Meldung darf nicht behaupten,
    was sie nicht sieht.
    """
    stop = threading.Event()
    reihenfolge: list[str] = []

    def _reconnect(ziel: Any, halt: threading.Event) -> bool:
        reihenfolge.append("gewartet")
        halt.set()
        return False

    main.run_supervised(
        _Ibkr(),
        heartbeat=lambda: None,
        pending=lambda: None,
        stop=stop,
        loop=lambda z, **k: main.run_loop(z, tick_s=0.0, **k),
        reconnect=_reconnect,
        on_disconnected=lambda: reihenfolge.append("gemeldet"),
    )

    assert reihenfolge == ["gemeldet", "gewartet"]


def test_der_melder_setzt_die_lampen_zurueck() -> None:
    """Nicht nur TWS: Konto und Auftragszugriff sind ebenfalls Vergangenheit.

    Sie stammen alle aus derselben Sitzung. Eine davon stehen zu lassen hiesse,
    einen Teil der alten Sitzung als Gegenwart auszugeben.
    """

    class _Ablage:
        def __init__(self) -> None:
            self.zustand: dict[str, Any] = {}

        def update(self, **werte: Any) -> None:
            self.zustand.update(werte)

    ablage = _Ablage()
    main.report_disconnect(SimpleNamespace(store=ablage))

    assert ablage.zustand == {
        "tws_connected": False,
        "account_known": False,
        "write_access": "unknown",
    }


def test_ein_kaputtes_cockpit_haelt_die_wiederverbindung_nicht_auf() -> None:
    """Das Cockpit ist Beiwerk, die Schleife ist es nicht."""
    stop = threading.Event()

    def _reconnect(ziel: Any, halt: threading.Event) -> bool:
        halt.set()
        return False

    def _kaputt() -> None:
        raise RuntimeError("Anzeige weg")

    main.run_supervised(
        _Ibkr(),
        heartbeat=lambda: None,
        pending=lambda: None,
        stop=stop,
        loop=lambda z, **k: main.run_loop(z, tick_s=0.0, **k),
        reconnect=_reconnect,
        on_disconnected=_kaputt,
    )


def test_strg_c_bleibt_eine_anweisung() -> None:
    """`KeyboardInterrupt` ist das eine, was durchgehen muss.

    Ein Nutzer, der abbricht, will abbrechen — ihn stattdessen neu verbinden zu
    lassen waere ein Fenster, das auf Strg-C nicht reagiert.
    """
    stop = threading.Event()

    def _unterbrochen(ziel: Any, **_: Any) -> None:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        main.run_supervised(
            _Ibkr(),
            heartbeat=lambda: None,
            pending=lambda: None,
            stop=stop,
            loop=_unterbrochen,
            reconnect=lambda *_a, **_k: False,
        )


# ── 3) Der Vorgang endet, statt in einem Dialog stehen zu bleiben ────────────


def test_main_gibt_eine_zahl_zurueck_statt_zu_werfen(monkeypatch: Any) -> None:
    """Die Ursache dafuer, dass sich die alte EXE nicht loeschen liess.

    Der Absturzdialog von PyInstaller ist modal. Auf einem Server sieht ihn
    niemand, also klickt ihn niemand weg, also bleibt der Vorgang stehen — und
    ein stehender Vorgang belegt seine Datei.
    """
    monkeypatch.setattr(
        main, "_main", lambda: (_ for _ in ()).throw(RuntimeError("geplatzt"))
    )
    gezeigt: list[str] = []
    monkeypatch.setattr(
        main.windows_ui, "message_box", lambda text, *a, **k: gezeigt.append(text)
    )

    assert main.main() == 1
    assert gezeigt, "Ohne Fenster erfaehrt der Nutzer am Bildschirm gar nichts."
    assert "geplatzt" in gezeigt[0]
    assert "safe to start it again" in gezeigt[0]


def test_der_absturz_wird_mit_vorgangsnummer_protokolliert(
    monkeypatch: Any, caplog: Any
) -> None:
    """Die Zeile muss WIRKLICH geschrieben werden, nicht nur dastehen.

    `_unerwartetes_ende` faengt Fehler beim Protokollieren ab — richtig so, ein
    Fehler beim Melden eines Fehlers darf den Ausgang nicht verdecken. Nur:
    derselbe stille `catch` hat beim ersten Bauversuch einen `NameError`
    geschluckt (`os` war in `main.py` nicht importiert), und die Zusicherung
    blieb gruen, waehrend die Zeile nie entstand.

    Deshalb wird hier der INHALT gemessen, nicht der Rueckgabewert.
    """
    monkeypatch.setattr(
        main, "_main", lambda: (_ for _ in ()).throw(RuntimeError("geplatzt"))
    )
    monkeypatch.setattr(main.windows_ui, "message_box", lambda *a, **k: True)

    with caplog.at_level("CRITICAL"):
        assert main.main() == 1

    zeilen = [r.getMessage() for r in caplog.records if r.levelname == "CRITICAL"]
    assert zeilen, "Ohne diese Zeile weiss der Support spaeter gar nichts."
    assert str(os.getpid()) in zeilen[0], zeilen[0]


def test_ein_fehler_beim_anzeigen_verdeckt_den_ausgang_nicht(monkeypatch: Any) -> None:
    """Ein Fehler beim Anzeigen eines Fehlers darf nicht der letzte sein."""
    monkeypatch.setattr(
        main, "_main", lambda: (_ for _ in ()).throw(RuntimeError("geplatzt"))
    )

    def _kaputt(*_a: Any, **_k: Any) -> bool:
        raise OSError("kein Fenstersystem")

    monkeypatch.setattr(main.windows_ui, "message_box", _kaputt)

    assert main.main() == 1


def test_strg_c_beendet_main_weiterhin(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        main, "_main", lambda: (_ for _ in ()).throw(KeyboardInterrupt())
    )

    with pytest.raises(KeyboardInterrupt):
        main.main()
