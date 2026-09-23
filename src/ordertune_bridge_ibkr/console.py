"""T1-101 A-1 — ein Startfehler haelt das Fenster.

## T1-213, 2026-09-23 — die Konsole ist fort, die Aufgabe geblieben

Die EXE wird seit dem 2026-09-23 mit `--windowed` gebaut: ein Doppelklick
oeffnet genau ein Fenster, und das ist das Cockpit. Damit entfaellt das
Warten auf eine Eingabe — es gibt kein Konsolenfenster mehr, das man
offenhalten koennte, und eine Aufforderung an ein Fenster, das es nicht gibt,
waere eine Anweisung, die nicht stimmt. Genau dagegen ist dieser Vorgang
gebaut.

An die Stelle des Wartens tritt `windows_ui.message_box`. `hold()` bleibt als
Funktion stehen und tut ausserhalb einer echten Konsole nichts; sie greift
noch, wenn der Owner die Bridge mit `--console` startet.

## Warum es das Warten ueberhaupt gab

Die EXE wurde mit `--console` gebaut. Windows schliesst das Konsolenfenster
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

    Zwei Bedingungen, seit T1-213:

      * nicht `--headless`,
      * gepackte EXE (oder ausdruecklich `--setup` fuer die Entwicklung).

    ## Warum die dritte weggefallen ist

    Hier stand zusaetzlich `is_interactive()` — **und eine interaktive
    Konsole**. Der Grund war teuer erkauft: zweimal hing ein Lauf, weil der
    Assistent auf eine Eingabe wartete, die niemand tippte. Zuerst der
    Paket-Testlauf, dann der Smoke-Test des Release-Workflows, der die fertige
    EXE in einem leeren Verzeichnis startet.

    Beide Faelle betrafen einen Assistenten, der in der **Konsole** lief. Seit
    T1-101 C laeuft er im Cockpit: `run_setup_cockpit` startet einen lokalen
    Server und oeffnet ein Fenster, getippt wird im Browser. Die Bedingung
    schuetzt damit einen Vorgang, den es nicht mehr gibt.

    Sie stehenzulassen waere nicht nur ueberfluessig, sondern schaedlich: eine
    fensterlos gebaute Anwendung hat **nie** eine interaktive Konsole. Der
    Assistent ginge dann bei keinem Kunden mehr auf, und der erste Start
    endete mit einem Meldungsfenster statt mit einer Einrichtung.

    ## Was an ihre Stelle tritt

    Die Gefahr, gegen die sie gebaut war, bleibt echt: ein Vorgang, der auf
    eine Eingabe wartet, die nie kommt, meldet keinen Herzschlag und ist fuer
    die Plattform von einem Absturz nicht zu unterscheiden. Der Schutz dagegen
    ist jetzt `--headless` — die ausdrueckliche Zusage an den Dauerbetrieb —,
    und der Smoke-Test des Release-Workflows setzt ihn (T1-213 AC-E1).
    """
    if headless_requested(argv):
        return False
    if SETUP_FLAG in argv:
        return True
    return is_frozen()


def dialog_wanted(argv: list[str]) -> bool:
    """T1-213 — soll bei einem Startfehler ueberhaupt ein Fenster aufgehen?

    ## Warum das nicht „nicht headless" heisst

    Die erste Fassung fragte genau das, und sie war falsch. Ein Meldungsfenster
    ist der Ersatz fuer eine Konsole, die es nicht gibt — es gehoert zum
    Doppelklick auf die gepackte EXE und **nur** dorthin.

    Laeuft derselbe Vorgang aus dem Quelltext, sitzt eine Konsole davor: beim
    Entwickeln, in der Zusicherungssuite, in der CI. Dort ist der gerahmte
    Block die richtige Auskunft, und ein modaler Dialog ist keine
    zusaetzliche Hilfe, sondern ein Anhalten. `MessageBoxW` kehrt erst zurueck,
    wenn jemand klickt.

    ## Gemessen, nicht ueberlegt

    Am 2026-09-23 ist der Release-Lauf zweimal im Schritt „Run tests" stehen
    geblieben, jeweils bis zum Abbruch von Hand. Ursache beim zweiten Mal:
    `test_launcher_starts_and_reaches_configuration` startet `launcher.py`
    ohne `bridge.env` als Unterprozess — ohne Zeitgrenze. Auf einem
    Windows-Laeufer oeffnete der Abbruchweg dort einen echten Dialog.

    Es ist dieselbe Bedingung wie in `should_hold`, und das ist kein Zufall:
    beide beantworten „steht hier ein Mensch vor einem Fenster, das gleich
    verschwindet".
    """
    return is_frozen() and not headless_requested(argv)


def hold(argv: list[str] | None = None) -> None:
    """Wartet auf eine Eingabe — sofern das ueberhaupt sinnvoll ist.

    T1-213: in der ausgelieferten, fensterlosen Fassung ist das nie der Fall —
    `is_interactive()` ist dort falsch, und die Funktion kehrt still zurueck.
    Sie greift noch, wenn der Owner mit `--console` startet. Die Auskunft fuer
    den Kunden uebernimmt `windows_ui.message_box`, aufgerufen in `_abort`.

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
