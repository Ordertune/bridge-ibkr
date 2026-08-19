"""T1-101 A-1 — ein Startfehler haelt das Fenster.

## Warum

Die EXE wird mit `--console` gebaut. Windows schliesst das Konsolenfenster
zusammen mit dem Vorgang, sobald er endet. Bei einem Doppelklick heisst das:
jede Startmeldung, auch die sorgfaeltigste, ist nach einem Sekundenbruchteil
fort. Genau das erzeugt „ich klicke drauf und es passiert nichts".

## Wann gehalten wird — und wann ausdruecklich nicht

Gehalten wird nur, wenn beides zutrifft:

  * der Vorgang laeuft als gepackte EXE (`sys.frozen`), also nicht aus einer
    Entwicklungsumgebung und nicht aus einem Dienst, der sie gestartet hat, und
  * `--headless` steht nicht auf der Befehlszeile.

`--headless` ist die Zusage an den Dauerbetrieb: unter IBC, in einer geplanten
Aufgabe oder in CI darf nichts auf eine Eingabe warten, die nie kommt. Ein
haengender Vorgang meldet keinen Herzschlag und ist fuer die Plattform nicht
von einem Absturz zu unterscheiden — das waere schlimmer als das Problem, das
hier geloest wird.

Aus demselben Grund ist ein fehlender oder geschlossener Eingabekanal kein
Fehler, sondern ein Grund, nicht zu warten.
"""
from __future__ import annotations

import sys

HEADLESS_FLAG = "--headless"

# T1-101 C-1: zwingt den Erst-Start-Assistenten auch ausserhalb einer gepackten
# EXE herbei. Fuer die Entwicklung — im Alltag entscheidet `should_hold`.
SETUP_FLAG = "--setup"

HOLD_PROMPT = "  Press Enter to close this window."


def headless_requested(argv: list[str]) -> bool:
    """Steht `--headless` auf der Befehlszeile?

    Als reine Funktion, damit die Zusicherung sie ohne Vorgang pruefen kann —
    wie `probe_requested` in `probe.py`.
    """
    return HEADLESS_FLAG in argv


def is_frozen() -> bool:
    """Laeuft der Vorgang als gepackte EXE?"""
    return bool(getattr(sys, "frozen", False))


def should_hold(argv: list[str]) -> bool:
    """Soll das Fenster nach einem Fehler offen bleiben?"""
    return is_frozen() and not headless_requested(argv)


def setup_wanted(argv: list[str]) -> bool:
    """Soll bei fehlender `bridge.env` der Assistent aufgehen?

    Dieselbe Bedingung wie beim Halt — und aus demselben Grund. Der Assistent
    wartet, bis jemand etwas eintraegt. Ist niemand da, waere das kein
    Assistent, sondern ein haengender Vorgang, der keinen Herzschlag meldet:
    fuer die Plattform nicht von einem Absturz zu unterscheiden.

    Genau das ist beim Bauen passiert — der Testlauf des Pakets startet den
    Launcher ohne `bridge.env`, und der wartete danach endlos. `--setup`
    holt den Assistenten fuer die Entwicklung ausdruecklich zurueck.
    """
    if headless_requested(argv):
        return False
    return SETUP_FLAG in argv or is_frozen()


def hold(argv: list[str] | None = None) -> None:
    """Wartet auf eine Eingabe — sofern das ueberhaupt sinnvoll ist.

    Kein Eingabekanal, geschlossener Eingabekanal oder ein Abbruch durch den
    Nutzer beenden das Warten still. Ein Fehler beim Anzeigen eines Fehlers
    darf den Ausgang nicht noch einmal verdecken.
    """
    if not should_hold(sys.argv[1:] if argv is None else argv):
        return
    try:
        print(HOLD_PROMPT, flush=True)
        input()
    except (EOFError, KeyboardInterrupt, OSError):
        return
