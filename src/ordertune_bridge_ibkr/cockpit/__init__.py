"""T1-101 Abschnitt B — das lokale Cockpit.

Ein Fenster, das ein Urteil spricht, statt eines Protokolls, das gelesen werden
will. Der Kern bleibt kopflos und autoritativ; dieses Paket liest nur.

  state.py    der Zustandsblock — der Kern schreibt, das Cockpit liest
  server.py   HTTP + Ereignisstrom, ausschliesslich 127.0.0.1, mit Token
  page.py     die Seite (B-1: roh; Gestaltung folgt)
  runfile.py  wo dieses Cockpit erreichbar ist
  journal.py  die letzten Protokollzeilen, gedeckelt
  window.py   Edge im App-Modus, sonst Browser, sonst URL
  setup.py    die Handlungen hinter Assistent und Einstellungen
  actions.py  die Aenderungsablage — schreibt bridge.env, wendet nichts an

Ohne `--headless` startet es mit dem Kern. Ein Fehler hier haelt den Handel
nie auf: das Cockpit ist Beiwerk, die Schleife ist es nicht.
"""
from __future__ import annotations

from .actions import SetupActions
from .server import CockpitServer
from .state import CockpitState, StateStore

__all__ = ["CockpitServer", "CockpitState", "SetupActions", "StateStore"]
