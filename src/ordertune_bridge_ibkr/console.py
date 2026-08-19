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


def is_interactive() -> bool:
    """Sitzt ueberhaupt jemand davor?

    Bei einem Doppelklick bekommt der Vorgang eine echte Konsole, und die
    Eingabe haengt an einem Konsolen-Handle. Unter einer geplanten Aufgabe,
    einem Dienst oder in einer Bauumgebung ist es eine Pipe — dort tippt
    niemand etwas ein.
    """
    try:
        return bool(sys.stdin) and sys.stdin.isatty()
    except (ValueError, AttributeError, OSError):  # pragma: no cover - defensiv
        return False


def setup_wanted(argv: list[str]) -> bool:
    """Soll bei fehlender `bridge.env` der Assistent aufgehen?

    Drei Bedingungen, und die dritte ist teuer erkauft:

      * nicht `--headless`,
      * gepackte EXE (oder ausdruecklich `--setup` fuer die Entwicklung),
      * **und eine interaktive Konsole.**

    ## Warum die dritte dazukam

    Der Assistent wartet, bis jemand etwas eintraegt — in einer Schleife, ohne
    Ende. Ist niemand da, ist das kein Assistent, sondern ein haengender
    Vorgang: er meldet keinen Herzschlag und ist fuer die Plattform von einem
    Absturz nicht zu unterscheiden.

    Das ist beim Bauen zweimal passiert, und beim zweiten Mal an der
    gefaehrlichen Stelle. Zuerst hing der Testlauf des Pakets, weil er den
    Launcher ohne `bridge.env` startet — dagegen kam `is_frozen()`. Dann hing
    der Smoke-Test des **Release-Workflows**, der die fertige EXE in einem
    leeren Verzeichnis startet: dort ist `is_frozen()` wahr, und der Assistent
    lief endlos. Der Schritt heisst „Smoke-test the built EXE" und existiert
    genau fuer diese Sorte Fehler.

    Dahinter steht der Fall, der nicht nur die Bauumgebung trifft: eine
    geplante Aufgabe oder ein Dienst-Wrapper startet die EXE ohne Konsole. Ohne
    diese Bedingung wartete sie dort bis zum Neustart der Maschine.
    """
    if headless_requested(argv):
        return False
    if SETUP_FLAG in argv:
        return True
    return is_frozen() and is_interactive()


def hold(argv: list[str] | None = None) -> None:
    """Wartet auf eine Eingabe — sofern das ueberhaupt sinnvoll ist.

    Kein Eingabekanal, geschlossener Eingabekanal oder ein Abbruch durch den
    Nutzer beenden das Warten still. Ein Fehler beim Anzeigen eines Fehlers
    darf den Ausgang nicht noch einmal verdecken.
    """
    if not should_hold(sys.argv[1:] if argv is None else argv):
        return
    if not is_interactive():
        # Im Protokoll des Release-Builds stand „Press Enter to close this
        # window." — an einer Stelle, an der niemand etwas druecken konnte.
        # Eine Anweisung, die nicht stimmt, ist genau die Sorte Aussage,
        # gegen die dieser Vorgang gebaut ist. Der Halt selbst war schon
        # richtig aufgehoben (`input()` wirft dort), nur die Zeile davor
        # wurde trotzdem ausgegeben.
        return
    try:
        print(HOLD_PROMPT, flush=True)
        input()
    except (EOFError, KeyboardInterrupt, OSError):
        return
