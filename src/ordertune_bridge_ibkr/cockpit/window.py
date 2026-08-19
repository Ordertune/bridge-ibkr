"""T1-101 B-6 / D6 — das Fenster: Edge im App-Modus, sonst Browser, sonst URL.

## Warum kein GUI-Werkzeugkasten

Der Entwurf sah zuerst `pywebview` ueber die WebView2-Runtime vor. Zwei Gruende
dagegen, beide belegt:

  * **Groesse.** pywebview treibt WebView2 auf Windows ueber die .NET-Bruecke
    an und bringt deren Unterbau mit; ein gemeldeter Fall wuchs von rund 10 MB
    auf 80–90 MB. Die Grenze im Spec ist +15 MB hart.
  * **Verfuegbarkeit.** Die WebView2-Runtime fehlt auf Windows Server 2019/2022
    haeufig, und die Nachinstallation schlaegt dort belegt fehl. Die Huelle
    waere ausgerechnet auf dem Zielsystem die unzuverlaessigste Schicht.

Dazu kommt T1-102 E: die ausgelieferte EXE ist **unsigniert**, SmartScreen
meldet „Unknown publisher". An einer unsignierten Anwendung ist weniger
Beiwerk auch weniger Risiko — ein mitgebuendelter Fensterunterbau erhoeht die
Wahrscheinlichkeit, dass Defender anspringt. Edge im App-Modus fuegt der
Binaerdatei nichts hinzu.

## Die Kette

    Edge im App-Modus  ->  Standardbrowser  ->  URL in der Konsole

Drei Stufen, jede fuer sich ausreichend. **Keine davon darf den Handel
aufhalten**: schlaegt alles fehl, steht die Adresse da und der Kern laeuft
weiter. Das Fenster ist die Huelle, der lokale Server ist das Fundament.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

log = logging.getLogger(__name__)

# Die ueblichen Orte einer Edge-Installation auf Windows. `shutil.which` findet
# sie nicht zuverlaessig, weil Edge nicht im PATH steht.
EDGE_CANDIDATES = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)


def find_edge() -> str | None:
    """Der Pfad zu Edge, oder nichts."""
    for kandidat in EDGE_CANDIDATES:
        if Path(kandidat).exists():
            return kandidat
    return shutil.which("msedge")


def open_window(url: str) -> str:
    """Oeffnet das Cockpit. Gibt zurueck, welche Stufe gegriffen hat.

    `app_mode` | `browser` | `url_only` — der Rueckgabewert ist fuer die
    Zusicherung da: „es hat funktioniert" ist sonst nicht pruefbar, ohne ein
    Fenster aufgehen zu lassen.
    """
    edge = find_edge() if sys.platform == "win32" else None
    if edge:
        try:
            # `--app=` gibt ein rahmenloses Fenster ohne Adresszeile und ohne
            # Reiter: optisch eine Anwendung, technisch der Browser, der
            # ohnehin auf jedem Zielsystem liegt.
            subprocess.Popen(
                [edge, f"--app={url}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return "app_mode"
        except OSError as exc:
            log.debug("Edge app mode failed, falling back to the browser: %s", exc)

    try:
        if webbrowser.open(url):
            return "browser"
    except Exception as exc:  # pragma: no cover - defensiv
        log.debug("Default browser failed: %s", exc)

    # Letzte Stufe, und keine schlechte: auf einem VPS ohne Browser ist die
    # Adresse genau das, was jemand braucht, der sich per RDP verbindet.
    log.info("Open the cockpit in a browser: %s", url)
    return "url_only"
