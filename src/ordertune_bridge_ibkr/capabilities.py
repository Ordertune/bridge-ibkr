"""T1-176 — was dieser Client dem Broker gegenueber kann.

Stand bis hierher in `main.py`. Herausgeloest, weil ausser der Schleife jetzt
auch der Assistent sie braucht (`cockpit/setup.py::check_handshake`), und
`cockpit` darf `main` nicht importieren — dort haengt die gesamte
IBKR-Maschinerie dran, und der Assistent laeuft gerade dann, wenn die noch
nicht steht.

Eine Angabe, ein Ort. Die Alternative waere eine zweite Kopie im Assistenten
gewesen, und was daraus wird, steht in der Notiz zu gemeinsamen Bausteinen:
sie driften, und man merkt es an der Stelle, an der die falsche gelesen wird.
"""
from __future__ import annotations

from typing import Any

# IBKR kennt keine Bruchstuecke im hier unterstuetzten Kontenkreis, nimmt aber
# einen ganzen Korb auf einmal entgegen.
#
# Die Richtung der Vorgabe ist der Punkt: „unbekannt" muss auf der Plattform
# ganzzahlig heissen, nicht bruchstueckfaehig. Eine geratene Menge wie 3,4
# weist IBKR rundheraus ab, und der Nutzer saehe einen Auftrag, den es nie
# gegeben hat, ohne jede Erklaerung.
IBKR_CAPABILITIES: dict[str, Any] = {
    "supportsFractionalShares": False,
    "fractionalQtyPrecision": 0,
    "minNotionalUsd": None,
    "supportsBulkSend": True,
}
