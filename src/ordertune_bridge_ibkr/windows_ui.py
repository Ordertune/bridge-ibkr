"""T1-213 — die zwei Windows-Handgriffe, die ein Fenster ersetzen.

## Warum es dieses Modul gibt

Bis zum 2026-09-23 wurde die EXE mit `--console` gebaut. Ein Doppelklick
oeffnete deshalb zwei Fenster: das Konsolenfenster mit dem laufenden Protokoll
und das Cockpit. Das Protokollfenster ist fuer den Owner gemacht; fuer den
Kunden war es die erste Aussage, die die Anwendung ueber sich selbst trifft.

Die Konsole hatte dabei zwei echte Aufgaben. Eine ist entfallen — der
Erst-Start-Assistent liegt seit T1-101 C im Cockpit und wird im Browser
bedient. Die andere bleibt: **einen Startfehler festhalten**, bevor das Cockpit
ueberhaupt steht. Dafuer steht hier `message_box`.

## Warum `ctypes` und kein Werkzeugkasten

Dieselbe Begruendung wie in `cockpit/window.py`, wo `pywebview` verworfen
wurde: die Spec aus T1-101 setzt +15 MB als harte Grenze, und an einer
unsignierten Anwendung ist weniger Beiwerk auch weniger Risiko, dass Defender
anspringt. `MessageBoxW` und `AllocConsole` stehen in jeder Windows-
Installation und kosten der Binaerdatei **0 MB**.

## Warum hier nichts wirft

Ein Fehler beim Anzeigen eines Fehlers darf den Ausgang nicht noch einmal
verdecken — dieselbe Regel, unter der `console.hold()` schon einmal
stillgeschwiegen hat. Jede Funktion hier meldet ihr Ergebnis als Wahrheitswert
und laesst nichts nach oben durch.
"""
from __future__ import annotations

import logging
import sys

log = logging.getLogger(__name__)

# T1-213 D-1 — der Schalter, mit dem sich der Owner die Konsole zurueckholt.
CONSOLE_FLAG = "--console"

# MB_OK | MB_ICONERROR | MB_SETFOREGROUND. Ohne das letzte kann der Dialog
# hinter dem Fenster liegen, das ihn ausgeloest hat, und dann ist er fuer den
# Kunden dasselbe wie gar keiner.
_MB_OK = 0x0
_MB_ICONERROR = 0x10
_MB_ICONINFORMATION = 0x40
_MB_SETFOREGROUND = 0x10000


def console_requested(argv: list[str]) -> bool:
    """Steht `--console` auf der Befehlszeile?

    Als reine Funktion, damit die Zusicherung sie ohne Vorgang pruefen kann —
    wie `headless_requested` und `probe_requested`.
    """
    return CONSOLE_FLAG in argv


def is_windows() -> bool:
    return sys.platform == "win32"


def message_box(text: str, title: str = "Ordertune Bridge", *, error: bool = True) -> bool:
    """Ein natives Meldungsfenster. Gibt zurueck, ob es wirklich erschienen ist.

    Der Rueckgabewert ist nicht Zierde: „es wurde angezeigt" ist sonst nicht
    pruefbar, ohne ein Fenster aufgehen zu lassen — dieselbe Ueberlegung, aus
    der `open_window()` seine Stufe zurueckgibt.

    Ausserhalb von Windows faellt der Weg auf die Standardfehlerausgabe zurueck
    und meldet `False`. Das ist kein Fehlschlag, sondern die Entwicklungs-
    umgebung: dort sitzt ohnehin eine Konsole davor.
    """
    if not is_windows():
        print(f"{title}: {text}", file=sys.stderr, flush=True)
        return False
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(  # type: ignore[attr-defined]
            None,
            text,
            title,
            _MB_OK
            | (_MB_ICONERROR if error else _MB_ICONINFORMATION)
            | _MB_SETFOREGROUND,
        )
        return True
    except Exception as exc:  # noqa: BLE001 - ein Fehler beim Melden bleibt stumm
        log.debug("MessageBoxW failed: %s", exc)
        return False


def allocate_console() -> bool:
    """Oeffnet eine Konsole und haengt die Standardkanaele daran.

    Nur fuer den Owner-Schalter. Gibt zurueck, ob es geklappt hat.

    ## Warum die Kanaele ausdruecklich neu gebunden werden

    `AllocConsole` gibt dem Vorgang ein Fenster, aber `sys.stdout` zeigt in
    einer fensterlos gebauten Anwendung auf `None` und bleibt dort. Ohne das
    Neubinden gaebe es ein leeres schwarzes Fenster — sichtbar, und trotzdem
    ohne eine Zeile darin. Das waere schlimmer als keine Konsole.
    """
    if not is_windows():
        # Ausserhalb von Windows gibt es immer eine Konsole; der Schalter ist
        # dort folgenlos und NICHT gescheitert.
        return True
    try:
        import ctypes

        if not ctypes.windll.kernel32.AllocConsole():  # type: ignore[attr-defined]
            # Schon eine da — etwa beim Start aus einer Eingabeaufforderung.
            # Kein Fehler.
            log.debug("AllocConsole: a console is already attached.")
        # Absichtlich ohne `with`: diese Kanaele sollen fuer die gesamte
        # Laufzeit offen bleiben — sie ZU schliessen waere der Fehler.
        for kanal, geraet, modus in (
            ("stdout", "CONOUT$", "w"),
            ("stderr", "CONOUT$", "w"),
            ("stdin", "CONIN$", "r"),
        ):
            try:
                setattr(sys, kanal, open(geraet, modus))  # noqa: SIM115
            except OSError as exc:  # pragma: no cover - je Kanal defensiv
                log.debug("Could not rebind %s: %s", kanal, exc)
        return True
    except Exception as exc:  # noqa: BLE001
        log.debug("AllocConsole failed: %s", exc)
        return False


def has_console_stream() -> bool:
    """Gibt es ueberhaupt einen Ausgabekanal?

    In einer fensterlos gebauten Anwendung steht `sys.stdout` auf `None`. Ein
    Protokoll-Handler auf `None` ist kein Handler, sondern eine Fehlerquelle —
    `logging` verschluckt ihn zwar, aber dann ist die Ursache jeder fehlenden
    Zeile eine andere als die vermutete.
    """
    return getattr(sys, "stdout", None) is not None
