"""T1-252 — der Kurs, mit dem aus einem EUR-Depotwert eine Stueckzahl wird.

## Warum das hier liegt und nicht in `ibkr_client`

Kein Import aus `ib_insync`. Die Regel laesst sich damit ohne laufende TWS
belegen, und das ist bei dieser Rechnung keine Bequemlichkeit: eine falsche
Kursrichtung ist ein stiller Faktor auf **jede** Stueckzahl. An den Zahlen vom
2026-09-28 waeren es 22,6 Prozent gewesen — ohne Absturz, ohne Meldung, ohne
Protokollzeile. Gegen genau diese Fehlerklasse ist T1-85 angetreten.

## Was IBKR liefert, und unter welchen Namen

Gemessen am 2026-09-28 auf `DUT106306` (EUR-Papierkonto):

    $LEDGER-ExchangeRate             BASE   1.00
    $LEDGER-ExchangeRate             EUR    1.00
    $LEDGER-ExchangeRate             USD    0.8797124

    $LEDGER-NetLiquidationByCurrency BASE   997317.877
    $LEDGER-NetLiquidationByCurrency EUR    1000775.19
    $LEDGER-NetLiquidationByCurrency USD    -3930.049

Zwei Fallen stecken schon in diesen sechs Zeilen:

1. **Das Praefix.** Die Zeilen heissen `$LEDGER-ExchangeRate`, nicht
   `ExchangeRate`. Eine Suche nach dem nackten Namen findet nichts und sieht
   aus wie „IBKR liefert keinen Kurs".
2. **Der aehnliche Name.** `NetLiquidation EUR` (Kontoebene, 997.317,88) und
   `$LEDGER-NetLiquidationByCurrency EUR` (Segment, 1.000.775,19) sind
   verschiedene Zahlen. Wer sie mischt, zaehlt das EUR-Segment doppelt.

## Die Richtung wird gerechnet, nicht angenommen

IBKR fuehrt seine Kurse gegen die **Basiswaehrung des Kontos**, nicht gegen
USD. Bei einem EUR-Konto heisst `0,8797124` also *1 USD = 0,8797124 EUR* — die
Gegenrichtung zu der, die die Plattform braucht.

Die Sammelzeile `BASE` ist die einzige Zeile, deren Wert aus den anderen folgt.
Genau deshalb taugt sie als Probe:

    Hypothese A   Kurs rechnet Segment -> Basis:   Summe(Wert x Kurs) == BASE
    Hypothese B   Kurs rechnet Basis -> Segment:   Summe(Wert : Kurs) == BASE

An den echten Zahlen traf A auf 0,000000 Prozent und B lag 0,1013 Prozent
daneben. Das ist der Grund fuer die Regel unten: der Sieger muss praktisch
exakt treffen, der Verlierer **spuerbar** danebenliegen. Eine schlichte
Toleranzgrenze haette hier an der dritten Nachkommastelle gehangen.

## Was die Bridge weitergibt

Den **gedrehten** Kurs: eine Zahl, fuer die `Depotwert x Kurs = Depotwert in
USD` gilt. Die Drehung passiert hier und nicht auf der Plattform, weil nur hier
die Sammelzeile liegt, an der sie sich nachrechnen laesst. Die Plattform saehe
sonst eine Zahl und muesste raten.

Laesst sich der Kurs nicht zweifelsfrei bilden, gibt es **keinen**. Kein Kurs
heisst auf der Plattform: blockieren, so wie heute. Ein geratener Kurs waere
Genauigkeit, die niemand sieht.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

#: Die Waehrung, in der die Plattform rechnet.
PLATTFORM_WAEHRUNG = "USD"

#: IBKR stellt den Ledger-Zeilen dieses Praefix voran.
LEDGER_PRAEFIX = "$LEDGER-"

#: Sammelzeilen benennen keine echte Waehrung.
SAMMELZEILEN = frozenset({"BASE", ""})

#: Der Depotwert JE WAEHRUNG. Nicht `NetLiquidation` — das ist das ganze Konto.
NETLIQ_JE_WAEHRUNG = "NetLiquidationByCurrency"

#: Der Sieger der Richtungsprobe muss praktisch exakt treffen.
TRIFFT = 0.0005
#: Der Verlierer muss spuerbar danebenliegen, sonst ist nichts entschieden.
DANEBEN = 0.0002
#: Der Kurs der Basiswaehrung ist per Definition 1,0. Toleranz fuer Rundung.
BASIS_KURS_TOLERANZ = 0.0001


class Kontowert(Protocol):
    """Die drei Felder, die hier gelesen werden — `ib_insync.AccountValue`."""

    tag: str
    value: Any
    currency: str


@dataclass(frozen=True)
class FxErgebnis:
    """Der gedrehte Kurs, oder warum es keinen gibt."""

    #: `Depotwert x kurs = Depotwert in USD`. `None` heisst: nicht bildbar.
    kurs: float | None
    #: Immer gesetzt. Bei `kurs is None` der Grund, sonst die Herleitung.
    #:
    #: **Englisch**, obwohl die Kommentare hier deutsch sind: dieser Text geht
    #: ueber `_log_fx` in das Protokoll auf dem Rechner des Kunden. Ein
    #: deutscher Halbsatz in einer englischen Zeile ist kein Stilfehler,
    #: sondern ein Nutzertext in der falschen Sprache.
    grund: str


def _zahl(roh: Any) -> float | None:
    """Eine Zahl, oder nichts. Gleiche Haltung wie `_opt` in `ibkr_client`."""
    if roh is None:
        return None
    try:
        f = float(str(roh).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


def normalisiere_tag(tag: str) -> str:
    """`$LEDGER-ExchangeRate` und `ExchangeRate` sind derselbe Gegenstand.

    Nach der Normalisierung wird **exakt** verglichen. Die Suffixe `-P` und
    `-S` gehoeren zu Unterkonten (Paxos-Krypto, CFD) und tragen eigene, meist
    leere Zahlen; ein Praefix-Vergleich wuerde sie einsammeln.
    """
    return tag.removeprefix(LEDGER_PRAEFIX)


def segmente(werte: Sequence[Kontowert], tag: str) -> dict[str, float]:
    """Die Zeilen eines Tags je echter Waehrung — ohne die Sammelzeile."""
    aus: dict[str, float] = {}
    for w in werte:
        if normalisiere_tag(w.tag) != tag:
            continue
        waehrung = (w.currency or "").upper()
        if not waehrung or waehrung in SAMMELZEILEN:
            continue
        zahl = _zahl(w.value)
        if zahl is not None:
            aus[waehrung] = zahl
    return aus


def sammelzeile(werte: Sequence[Kontowert], tag: str) -> float | None:
    """Der Wert der Sammelzeile `BASE` — die Probe fuer die Richtung."""
    for w in werte:
        if normalisiere_tag(w.tag) == tag and (w.currency or "").upper() in SAMMELZEILEN:
            zahl = _zahl(w.value)
            if zahl is not None:
                return zahl
    return None


def richtung_ist_segment_zu_basis(werte: Sequence[Kontowert]) -> bool | None:
    """Rechnet IBKRs Kurs Segment -> Basis?

    `True`  — `Wert x Kurs = Basis` (gemessen der Fall)
    `False` — `Wert : Kurs = Basis`
    `None`  — nicht entscheidbar; dann wird kein Kurs gebildet.
    """
    kurse = segmente(werte, "ExchangeRate")
    betraege = segmente(werte, NETLIQ_JE_WAEHRUNG)
    basis = sammelzeile(werte, NETLIQ_JE_WAEHRUNG)

    if not kurse or not betraege or basis is None or basis == 0.0:
        return None

    gemeinsam = [c for c in sorted(set(kurse) & set(betraege)) if kurse[c] != 0.0]
    if not gemeinsam:
        return None

    mal = sum(betraege[c] * kurse[c] for c in gemeinsam)
    geteilt = sum(betraege[c] / kurse[c] for c in gemeinsam)
    rel_mal = abs(mal - basis) / abs(basis)
    rel_geteilt = abs(geteilt - basis) / abs(basis)

    if rel_mal <= TRIFFT and rel_geteilt >= DANEBEN:
        return True
    if rel_geteilt <= TRIFFT and rel_mal >= DANEBEN:
        return False
    return None


def loese_kurs_auf(
    werte: Sequence[Kontowert], basiswaehrung: str | None
) -> FxErgebnis:
    """Der gedrehte Kurs zur Plattformwaehrung, oder warum es keinen gibt.

    `basiswaehrung` ist das Ergebnis von `resolve_account_currency` — die
    Waehrung, in der das Konto seinen Depotwert meldet. Sie wird hier NICHT
    noch einmal hergeleitet: zwei Herleitungen derselben Sache sind zwei
    Gelegenheiten, verschieden zu antworten.
    """
    if basiswaehrung is None:
        return FxErgebnis(None, "The account currency is not unambiguous.")

    basis = basiswaehrung.upper()
    kurse = segmente(werte, "ExchangeRate")
    if not kurse:
        return FxErgebnis(None, "IBKR did not report any ExchangeRate line.")

    # Die Probe auf die Basiswaehrung. Sie ist per Definition 1,0 — steht dort
    # etwas anderes, passen die Waehrungsangabe und die Kurstabelle nicht
    # zusammen, und dann ist jede Umrechnung geraten. `$LEDGER-Currency BASE`
    # traegt den Wert "BASE" und nennt die Waehrung NICHT; diese Probe ist der
    # Ersatz dafuer.
    eigener = kurse.get(basis)
    if eigener is None:
        return FxErgebnis(
            None, f"No ExchangeRate line for the account currency {basis}."
        )
    if abs(eigener - 1.0) > BASIS_KURS_TOLERANZ:
        return FxErgebnis(
            None,
            f"The rate for the account currency {basis} is {eigener}, not 1.0 — "
            "the currency and the rate table do not match.",
        )

    if basis == PLATTFORM_WAEHRUNG:
        # Nichts zu drehen. Der Kurs reist trotzdem mit, damit auf der
        # Plattform EINE Regel gilt statt einer mit Ausnahme.
        return FxErgebnis(1.0, "The account is already denominated in USD.")

    kurs = kurse.get(PLATTFORM_WAEHRUNG)
    if kurs is None or kurs <= 0.0:
        return FxErgebnis(
            None, f"No usable {PLATTFORM_WAEHRUNG} rate in the response."
        )

    segment_zu_basis = richtung_ist_segment_zu_basis(werte)
    if segment_zu_basis is None:
        return FxErgebnis(
            None,
            "The rate direction cannot be established on this account — a guessed "
            "direction would silently skew every position size.",
        )

    # Segment -> Basis heisst: 1 USD = `kurs` Einheiten der Kontowaehrung.
    # Aus Kontowaehrung nach USD geht es dann GETEILT, der gedrehte Kurs ist
    # der Kehrwert. Andernfalls zeigt der Kurs schon in die richtige Richtung.
    gedreht = (1.0 / kurs) if segment_zu_basis else kurs
    if not math.isfinite(gedreht) or gedreht <= 0.0:
        return FxErgebnis(None, "The inverted rate is not a usable number.")

    richtung = "segment->base" if segment_zu_basis else "base->segment"
    return FxErgebnis(
        gedreht,
        f"1 {PLATTFORM_WAEHRUNG} = {kurs} {basis} ({richtung}); "
        f"inverted: 1 {basis} = {gedreht:.6f} {PLATTFORM_WAEHRUNG}.",
    )
