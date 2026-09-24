"""T1-206 B — die Kopplung fuer einen Server ohne Fenster.

## Der Befund, aus dem das entstanden ist

Die Kopplung lief bis hierher **ausschliesslich** ueber das Cockpit:
`cockpit/actions.py` ruft `pairing.start` und `pairing.claim`, getippt wird im
Browser. `--headless` schaltet das Cockpit vollstaendig ab, und sein Port ist
absichtlich fluechtig — Port 0, das Betriebssystem waehlt, damit nichts
Vorhersagbares auf der Rueckschleife steht.

Fuer einen Kunden auf einem Linux-Server ohne Desktop ergibt das eine
Sackgasse, und zwar beim **ersten** Schritt: das Cockpit geht auf, gibt eine
Adresse aus, die auf diesem Server niemand oeffnen kann, und ein SSH-Tunnel
haette den Port vorher wissen muessen. Er koennte sich also gar nicht koppeln.

Deshalb steht `--pair` in T1-206 und nicht in einem spaeteren Vorgang.

## Keine zweite Betriebsart, eine zweite Anzeige

`--pair` schreibt `bridge.env` ueber **denselben** Weg wie das Cockpit
(`pairing.write_credentials`). Es entsteht kein zweiter Schreibweg, nur eine
zweite Art, den Code zu zeigen — dieselbe Trennung, die `pairing` ohnehin
vorsieht: das Modul kennt die Richtung, die Oberflaeche kennt nur die Anzeige.

Gewartet wird an genau der Weiche, an der heute der Assistent wartet: ohne
Zugangsdaten kann die Bridge nichts tun, sie kommt nicht einmal bis zur
IBKR-Verbindung. Nach dem Erfolg laeuft der Start normal weiter.

## Was hier bewusst nicht passiert

Geschrieben wird **erst**, wenn die Gegenseite den Code als eingeloest meldet.
Bricht die SSH-Sitzung ab oder laeuft die Frist aus, bleibt keine halbe
`bridge.env` zurueck und ein zweiter Versuch faengt sauber von vorn an.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from . import env_file, pairing

PAIR_FLAG = "--pair"

#: Wie oft nachgefragt wird, ob der Nutzer bestaetigt hat. Drei Sekunden sind
#: schnell genug, dass es sich unmittelbar anfuehlt, und langsam genug, dass
#: eine Zehn-Minuten-Frist rund 200 Abrufe kostet statt Tausender.
POLL_INTERVAL_S = 3.0

#: Die Seite, auf der der Code einzutippen ist. Dieselbe, auf die das Cockpit
#: verweist (`cockpit/page.py`) — eine Adresse, nicht zwei.
PAIR_PATH = "/settings?tab=broker"

_LINIE = "─" * 68


def pair_requested(argv: list[str]) -> bool:
    """Steht `--pair` auf der Befehlszeile?

    Als reine Funktion, damit die Zusicherung sie ohne Vorgang pruefen kann —
    wie `probe_requested`, `headless_requested` und `console_requested`.
    """
    return PAIR_FLAG in argv


def _sagen(text: str = "") -> None:
    """Auf die Standardausgabe, sofort.

    Ueber SSH ist die Ausgabe gepuffert, sobald sie nicht an ein Endgeraet
    geht. Ein Kopplungscode, der erst nach dem Programmende erscheint, ist
    keiner — deshalb hier ausnahmslos `flush`.
    """
    print(text, flush=True)


def _vorhandene_zugangsdaten(env_path: Path) -> bool:
    """Steht in `bridge.env` schon ein Token?"""
    try:
        werte = env_file.parse(env_path.read_text(encoding="utf-8"))
    except OSError:
        return False
    return bool(werte.get("ORDERTUNE_BRIDGE_TOKEN"))


def _basis(env_path: Path) -> str:
    """Gegen welche Adresse gekoppelt wird.

    Dieselbe Rangfolge wie im Cockpit (`actions._basis`): was in der Datei
    steht, schlaegt die Vorgabe. Ein Kunde auf einer abweichenden Adresse soll
    sie nicht bei jeder Kopplung erneut eintragen muessen.
    """
    try:
        werte = env_file.parse(env_path.read_text(encoding="utf-8"))
    except OSError:
        werte = {}
    return werte.get("ORDERTUNE_API_BASE") or "https://t1.ordertune.com"


def _bestaetigt_ersetzen() -> bool:
    """Darf eine bestehende Kopplung ersetzt werden?

    Ein stilles Ueberschreiben wuerde eine laufende Verbindung kappen — der
    alte Token wird bei der neuen Kopplung ungueltig, und die Bridge, die noch
    damit laeuft, faellt ohne erkennbaren Anlass aus. Das ist eine Frage, die
    ein Mensch beantworten muss.

    Kein Eingabekanal heisst **nein**. Wer `--pair` in eine geplante Aufgabe
    haengt, soll damit keine laufende Verbindung verlieren.
    """
    try:
        if not sys.stdin or not sys.stdin.isatty():
            return False
        antwort = input("  Replace them? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt, OSError, ValueError):
        return False
    return antwort in ("y", "yes")


def _zeige_code(ergebnis: dict, basis: str) -> None:
    """Der Block, den der Kunde im Terminal vor sich hat."""
    ziel = f"{basis.rstrip('/')}{PAIR_PATH}"
    frist = int(ergebnis.get("expires_in") or 600)

    _sagen()
    _sagen(_LINIE)
    _sagen("  Pair this Bridge with your Ordertune account")
    _sagen(_LINIE)
    _sagen()
    _sagen(f"  1. Open   {ziel}")
    _sagen("  2. Go to  Settings -> Broker -> Pair a Bridge")
    _sagen("  3. Enter this code:")
    _sagen()
    _sagen(f"        {ergebnis.get('code', '')}")
    _sagen()
    _sagen(f"     It expires in {frist // 60} minutes.")
    _sagen()
    # Der Abgleich ist kein Schmuck: er ist der Riegel gegen eine
    # untergeschobene Kopplung. Wer den Code mitliest, kann ihn einloesen —
    # aber er kann diese beiden Werte nicht faelschen, und t1 zeigt dieselben.
    _sagen("  Check that t1 shows the same machine before you confirm:")
    _sagen(f"     host        {ergebnis.get('hostname', '-')}")
    _sagen(f"     fingerprint {ergebnis.get('fingerprint_prefix', '-')}")
    _sagen()
    _sagen("  Waiting. Press Ctrl+C to stop.")
    _sagen()


def run_pairing(env_path: Path) -> int:
    """Koppeln und `bridge.env` schreiben. Gibt einen Ausgangscode zurueck.

    `0` heisst: es steht jetzt ein Token in der Datei und der Start darf
    weitergehen. Alles andere heisst: nicht gekoppelt, und der Aufrufer
    beendet sich.
    """
    if _vorhandene_zugangsdaten(env_path):
        _sagen()
        _sagen(f"  {env_path} already carries credentials.")
        _sagen("  Pairing again issues a new token and invalidates the old one.")
        _sagen("  A Bridge still running with it will stop working.")
        if not _bestaetigt_ersetzen():
            _sagen()
            _sagen("  Left untouched. Nothing was changed.")
            return 1

    basis = _basis(env_path)
    ergebnis = pairing.start(basis)
    if not ergebnis.get("ok"):
        _sagen()
        _sagen(f"  Could not reach Ordertune: {ergebnis.get('message', '')}")
        for zeile in ergebnis.get("action", ()):
            _sagen(f"    - {zeile}")
        return 1

    _zeige_code(ergebnis, basis)

    frist = float(ergebnis.get("expires_in") or 600)
    schluss = time.monotonic() + frist
    code = ergebnis["code"]
    verifier = ergebnis["verifier"]

    while time.monotonic() < schluss:
        try:
            time.sleep(POLL_INTERVAL_S)
        except KeyboardInterrupt:
            _sagen()
            _sagen("  Stopped. Nothing was written.")
            return 1

        antwort = pairing.claim(basis, code, verifier)
        if not antwort.get("ok"):
            # Ein einzelner Fehlschlag ist hier kein Abbruchgrund: ueber eine
            # Mobilfunkleitung oder hinter einem neu startenden Netzdienst
            # faellt ein Abruf aus und der naechste geht wieder durch. Die
            # Frist begrenzt das Ganze ohnehin.
            continue

        if antwort.get("status") == "pending":
            continue

        if antwort.get("status") != "ready":
            continue

        geschrieben = pairing.write_credentials(
            env_path,
            api_base=basis,
            token=antwort.get("token", ""),
            connection_id=antwort.get("connection_id", ""),
        )
        if not geschrieben.get("ok"):
            _sagen()
            _sagen(f"  {geschrieben.get('message', 'Could not write bridge.env.')}")
            # Der Token ist auf der Gegenseite ausgestellt, liegt hier aber
            # nirgends. Das laut zu sagen ist wichtiger, als es zu verbergen:
            # der naechste Versuch braucht eine neue Kopplung, nicht dieselbe.
            _sagen("  The token was issued but could not be stored.")
            _sagen("  Fix the permissions on the folder and pair again.")
            return 1

        _sagen()
        _sagen(f"  Paired. Credentials written to {env_path}.")
        _sagen()
        return 0

    _sagen()
    _sagen("  The code expired before it was confirmed. Nothing was written.")
    _sagen("  Run the Bridge with --pair again to get a new one.")
    return 1
