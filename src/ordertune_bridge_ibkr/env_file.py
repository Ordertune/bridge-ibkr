"""T1-101 C-4 / D8 — `bridge.env` bleibt die Wahrheit auf der Platte.

Kein zweites Konfigurationsformat, keine Registry. Das Cockpit **schreibt diese
Datei**, in diesem Format, an dieser Stelle. Damit bleiben der Wizard-Download,
`docs/`, der Konsolenweg und jede Supportantwort gueltig.

## Was hier sorgfaeltig sein muss

**Der Kommentarkopf bleibt.** Die erzeugte Datei traegt die Porttabelle und
Hinweise, die der Nutzer spaeter noch braucht. Eine Datei neu zu schreiben und
dabei die Erklaerungen wegzuwerfen, waere ein stiller Verlust — deshalb wird
Zeile fuer Zeile ersetzt und nur Fehlendes angehaengt.

**Der Token wird nie angefasst.** Er steht in einer Zeile, die niemand
bearbeitet; sie wird durchgereicht wie jede andere unbekannte Zeile.

**Geschrieben wird atomar, mit Sicherung.** Ein abgebrochener Schreibvorgang an
der Datei, die den Zugang zu einem Depot traegt, waere die teuerste Art, hier zu
sparen: die Bridge startet danach nicht mehr, und der Token ist nur einmal
sichtbar gewesen.

**Fremde Aenderungen werden erkannt.** Wer die Datei nebenher im Editor
bearbeitet, soll sie nicht stillschweigend ueberschrieben bekommen.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

BACKUP_SUFFIX = ".bak"

# Felder, die ueber die Einstellungen bearbeitet werden duerfen. Alles andere
# — Token, Connection-ID, Basis-URL — wird angezeigt und durchgereicht, nie
# getippt (D9). `IBKR_TRADING_MODE` fehlt hier mit Absicht: es ist laut eigener
# Beschreibung ein Label, das nichts bewirkt (D10).
EDITABLE = ("IBKR_GATEWAY_PORT", "IBKR_CLIENT_ID", "LOG_LEVEL", "UPDATE_CHECK_ENABLED")

# Felder, deren Wert nie an die Flaeche geht.
SECRET = ("ORDERTUNE_BRIDGE_TOKEN",)


def parse(text: str) -> dict[str, str]:
    """Die Schluessel-Wert-Paare. Kommentare und Leerzeilen fallen weg."""
    werte: dict[str, str] = {}
    for zeile in text.splitlines():
        blank = zeile.strip()
        if not blank or blank.startswith("#") or "=" not in blank:
            continue
        schluessel, _, wert = blank.partition("=")
        werte[schluessel.strip().upper()] = wert.strip()
    return werte


def apply_changes(text: str, changes: dict[str, str]) -> str:
    """Ersetzt vorhandene Zeilen, haengt fehlende an — alles andere bleibt.

    Zeile fuer Zeile, damit Kommentarkopf, Reihenfolge und Leerzeilen erhalten
    bleiben. Ein Neuschreiben aus einem Datensatz waere kuerzer und wuerfe die
    Erklaerungen weg, die der Nutzer spaeter braucht.
    """
    offen = {k.upper(): v for k, v in changes.items()}
    zeilen = text.splitlines()
    ergebnis: list[str] = []

    for zeile in zeilen:
        blank = zeile.strip()
        if blank and not blank.startswith("#") and "=" in blank:
            schluessel = blank.partition("=")[0].strip().upper()
            if schluessel in offen:
                ergebnis.append(f"{schluessel}={offen.pop(schluessel)}")
                continue
        ergebnis.append(zeile)

    if offen:
        if ergebnis and ergebnis[-1].strip():
            ergebnis.append("")
        for schluessel, wert in offen.items():
            ergebnis.append(f"{schluessel}={wert}")

    return "\n".join(ergebnis) + "\n"


def fingerprint(path: Path) -> str:
    """Ein billiger Abdruck der Datei, um fremde Aenderungen zu erkennen."""
    try:
        s = path.stat()
    except OSError:
        return ""
    return f"{s.st_mtime_ns}:{s.st_size}"


def _restrict(path: Path) -> None:
    """Nur der Eigentuemer. Auf Windows ohne Wirkung, dort greifen die ACLs."""
    try:
        path.chmod(0o600)
    except OSError:  # pragma: no cover - defensiv
        pass


def write_atomic(path: Path, text: str) -> None:
    """Sicherung anlegen, daneben schreiben, dann ersetzen.

    `os.replace` ist auf einem Dateisystem atomar: entweder steht die alte
    Datei da oder die neue, nie eine halbe.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        try:
            sicherung = path.with_suffix(path.suffix + BACKUP_SUFFIX)
            sicherung.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
            # Die Sicherung traegt DENSELBEN Token wie das Original. Sie mit den
            # Vorgaben der Umgebung anzulegen hiess: die neue Datei wird durch
            # `mkstemp` auf 0600 verengt, und daneben liegt eine fuer alle
            # lesbare Kopie desselben Geheimnisses.
            _restrict(sicherung)
        except OSError:
            # Keine Sicherung moeglich — dann wird auch nicht geschrieben. Die
            # Datei traegt den Zugang zu einem Depot.
            raise

    fd, temp = tempfile.mkstemp(dir=str(path.parent), prefix=".bridge-env-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


def redacted(values: dict[str, str]) -> dict[str, str]:
    """Was die Flaeche sehen darf: alles ausser dem Wert des Tokens.

    Vom Token die letzten vier Zeichen — genug, um zwei Dateien voneinander zu
    unterscheiden, zu wenig, um damit etwas anzufangen.
    """
    sicht: dict[str, str] = {}
    for schluessel, wert in values.items():
        if schluessel in SECRET:
            sicht[schluessel] = f"...{wert[-4:]}" if len(wert) > 4 else "(set)"
        else:
            sicht[schluessel] = wert
    return sicht
