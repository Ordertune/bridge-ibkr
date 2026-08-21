"""T1-109 — der Auftragsvermerk, den ein Mensch lesen kann.

## Wofuer es das gibt

In TWS steht in der Spalte `Order-Referenz` bislang `ot-68b51461-05e6-4c...`.
Fuer die Bridge ist dieser Vermerk die wichtigste Angabe ueberhaupt: er ist das
einzige, was einen Neustart ueberlebt, weil `orderId` sitzungsgebunden ist und
die Ablagen im Speicher fluechtig sind. Fuer den Nutzer ist er vollkommen stumm.

Owner am 2026-08-21, beim Gegenlesen seiner OCA-Beine in TWS: „Kann man hinter
`ot-` auch Signal-ID, Strategie und Symbol und dann die Zahlenreihe setzen, die
da schon ist?"

Ergebnis:

    ot-ALAB-7808-Peak_Reload-68b51461-05e6-4c8a-...
       ^^^^^^^^^^^^^^^^^^^^^ Etikett von der Plattform
                             ^^^^^^^^^^^^^^^^^^^^^^^ dispatch_id, wie bisher

Der lesbare Teil steht VORNE, weil TWS die Spalte rechts abschneidet. Hinter
einer 36-stelligen UUID waere er in der Anzeige genauso stumm wie vorher.

## Warum das Lesen von HINTEN geschieht

`dispatch_id_from_order_ref` nahm bisher „alles nach dem Praefix". Mit einem
Etikett dazwischen traegt diese Regel nicht mehr. Die dispatch_id ist eine
UUID und damit an ihrer Form erkennbar — sie wird am ENDE gesucht.

Das ist zugleich die Abwaertskompatibilitaet: bei `ot-<uuid>` steht die UUID
ebenfalls am Ende. Ein Auftrag, den eine aeltere Fassung gestellt hat, wird von
der neuen Regel unveraendert gefunden.

**Der umgekehrte Weg gilt nicht.** Eine aeltere Bridge findet in einem neuen
Vermerk ihre dispatch_id nicht und verliert den Auftrag nach einem Neustart aus
den Augen. Falsch gebucht wird nichts — `is_ours()` prueft nur das Praefix und
sagt weiterhin „gehoert uns" —, aber das Ergebnis kaeme nicht zurueck. Ein
Rueckschritt der Bridge-Fassung ist deshalb nach diesem Spec nicht folgenlos.
"""

from __future__ import annotations

import re

#: Praefix, mit dem jeder Auftrag von uns bei IBKR hinterlegt ist.
ORDER_REF_PREFIX = "ot-"

#: Obergrenze fuer den GESAMTEN Vermerk.
#:
#: 64 ist keine von IBKR dokumentierte Grenze, sondern eine bewusst
#: konservative Wahl: die tatsaechliche Laenge von `Order.orderRef` ist nicht
#: belastbar dokumentiert, und ein Auftrag, den der Broker wegen eines zu
#: langen Vermerks ablehnt, kostet einen Ausstieg im Echtgeld.
#:
#: Reicht der Platz nicht, faellt das ETIKETT weg — nie die dispatch_id.
#: Lieber ein stummer Vermerk als ein unauffindbarer Auftrag.
ORDER_REF_MAX_LEN = 64

#: Die Form einer UUID, verankert am Ende der Zeichenkette.
_UUID_AM_ENDE = re.compile(
    r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$"
)

#: Was in einem Etikett stehen darf. `-` ist das Trennzeichen und deshalb
#: ausgeschlossen; Punkt und Unterstrich bleiben, damit `BRK.B` und
#: `Peak_Reload` ihre vertraute Schreibweise behalten.
_ETIKETT_ERLAUBT = re.compile(r"[^A-Za-z0-9_.\-]")


def build_order_ref(dispatch_id: str, label: str | None) -> str:
    """Setzt den Auftragsvermerk zusammen.

    Ohne Etikett — oder wenn es nicht hineinpasst — entsteht exakt das Format
    von vor T1-109. Der Rueckfall ist damit kein Sonderfall, sondern der
    bisherige Normalfall.
    """
    basis = f"{ORDER_REF_PREFIX}{dispatch_id}"
    if not label:
        return basis

    sauber = _ETIKETT_ERLAUBT.sub("", str(label).strip())
    if not sauber:
        return basis

    zusammen = f"{ORDER_REF_PREFIX}{sauber}-{dispatch_id}"
    if len(zusammen) > ORDER_REF_MAX_LEN:
        # Das Etikett wird NICHT beschnitten, um es doch noch unterzubringen.
        # Die Plattform hat es bereits auf ihre Grenze gekuerzt; passt es hier
        # trotzdem nicht, stimmt eine Annahme nicht, und dann ist Schweigen die
        # sichere Antwort.
        return basis
    return zusammen


def dispatch_id_from_order_ref(order_ref: str | None) -> str | None:
    """Liest die dispatch_id aus dem Auftragsvermerk, oder `None`.

    Fremde Auftraege im selben Konto — von Hand gestellt oder von einem anderen
    Werkzeug — tragen den Vermerk nicht und werden stillschweigend uebergangen.
    Sie gehoeren uns nicht.

    Gelesen wird die UUID am ENDE. Damit deckt dieselbe Regel beide Formate ab:
    `ot-<uuid>` und `ot-<etikett>-<uuid>`.
    """
    if not order_ref:
        return None

    # Erst saeubern, dann pruefen. Die Fassung in `order_reconcile` tat das,
    # die in `main` nicht — beim Zusammenlegen gewinnt die tolerantere: ein
    # Vermerk mit Leerraum drumherum ist derselbe Vermerk.
    text = str(order_ref).strip()
    if not text.startswith(ORDER_REF_PREFIX):
        return None

    treffer = _UUID_AM_ENDE.search(text)
    if treffer:
        return treffer.group(1)

    # Rueckfall fuer alles, was wie das alte Format aussieht, ohne eine UUID zu
    # sein — etwa in Tests oder aus einer Zeit vor der UUID-Vergabe. Die alte
    # Regel Wort fuer Wort.
    rest = text[len(ORDER_REF_PREFIX) :].strip()
    return rest or None


def is_ours(order_ref: object) -> bool:
    """Traegt dieser Vermerk unsere Handschrift?

    Bewusst NUR das Praefix. Diese Frage entscheidet, ob eine Fuellung als
    eigener Auftrag oder als fremde Ausfuehrung gebucht wird — sie muss auch
    dann noch stimmen, wenn sich das Format dahinter aendert.
    """
    return bool(order_ref) and str(order_ref).startswith(ORDER_REF_PREFIX)
