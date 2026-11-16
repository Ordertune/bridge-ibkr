"""Maskierung von Kontokennungen (T1-103 O), geteilt seit T1-414."""

from __future__ import annotations


def mask_account(account: str | None) -> str | None:
    """T1-103 O — die Kontokennung, so weit gekuerzt, dass sie noch unterscheidet.

    Der Zweck ist, ein Live- von einem Papierkonto zu unterscheiden, nicht die
    Nummer auszuweisen. IBKR-Papierkonten beginnen mit `D`, Livekonten mit `U`
    — der erste Buchstabe und die letzten beiden Stellen reichen dafuer, und
    mehr gehoert nicht in eine Anzeige, die ueber HTTP ausgeliefert wird.

    Die Zusage aus T1-97 lautet, dass die vollstaendige Nummer den Prozess nur
    maskiert verlaesst. Das Cockpit ist ein Prozessausgang.
    """
    if not account:
        return None
    kennung = str(account).strip()
    if len(kennung) <= 3:
        return kennung
    return f"{kennung[0]}***{kennung[-2:]}"
