"""T1-252 — liefert IBKR einen Wechselkurs, und in welche Richtung rechnet er?

## Die Frage, die dieses Skript beantwortet

Ein Konto in Euro kann bei Ordertune heute keine Stueckzahl tragen. Die
Mengenformel lautet `Positionsgroesse% x Depotwert : Einstiegspreis`, der
Einstiegspreis steht in USD, und ein EUR-Betrag darin ergibt eine Zahl, die
aussieht wie eine Stueckzahl und um den Wechselkurs danebenliegt. T1-85 hat
deshalb einen Riegel gesetzt und die Umrechnung vertagt.

T1-252 will den Riegel oeffnen. Der Entwurf steht und haengt an EINER Annahme:

    IBKR fuehrt zu `NetLiquidation` je Waehrungssegment eine `ExchangeRate`-Zeile
    in derselben Antwort.

Trifft sie zu, reist der Kurs im selben Schnappschuss wie der Depotwert, und
drei der vier Festlegungen aus T1-85 (Quelle, Aktualitaet, Ausfall) fallen weg.
Trifft sie nicht zu, braucht der Vorgang eine eigene Kursquelle und wird ein
anderer. **Die Annahme ist ungeprueft.** Dieses Skript prueft sie.

## Es gibt ZWEI Quellen, und die erste Fassung fragte nur eine

Gemessen am 2026-09-28 auf `DUT106306` (EUR-Papierkonto): `accountValues()`
lieferte **keine einzige** `ExchangeRate`-Zeile und nicht einmal eine
Sammelzeile `BASE`. Das sah nach einer widerlegten Annahme aus und war ein
Fehler der Sonde.

`accountValues()` wird von `reqAccountUpdates` gespeist und meldet das Konto in
**seiner** Basiswaehrung — ein Kurs hat dort gar nichts zu suchen. Die Kurse
liegen im **Ledger**, und an den kommt man ueber `reqAccountSummary` mit der
Kennung `$LEDGER:ALL`. In ib_insync ist das `accountSummary()`; die Kennung
steht fest in `reqAccountSummaryAsync` (ib.py, Zeile 1894).

Eine Abwesenheit an der Stelle, an der die Sache nie lag, belegt nichts.
Deshalb liest die Sonde jetzt **beide** Quellen und sagt zu jeder Zeile, woher
sie stammt.

## Die zweite Frage: in welche Richtung?

Das ist die gefaehrlichere Haelfte. IBKR fuehrt seine Kurse gegen die
**Basiswaehrung des Kontos**, nicht gegen USD. Bei einem EUR-Konto heisst das:
das EUR-Segment traegt 1,0, und das USD-Segment traegt ~0,92 — ein Kurs, der
USD in EUR umrechnet, also genau die Gegenrichtung zu der, die wir brauchen.

Eine falsche Richtung ist kein Fehler, den jemand sieht. Sie ist ein stiller
Faktor auf jede Stueckzahl, bei 0,92 rund 17 Prozent daneben (der Unterschied
zwischen x0,92 und :0,92). Deshalb wird die Richtung hier nicht angenommen,
sondern **gerechnet**: die Sammelzeile `BASE` ist die Probe. Passt die Summe
der Segmente mal Kurs zu ihr, rechnet der Kurs Segment→Basis. Passt die Summe
geteilt durch Kurs, rechnet er Basis→Segment.

## Die dritte Frage: welche Zahl ist „sein Kapital"?

T1-85 hat offengelassen, ob die Bezugsgroesse der umgerechnete Depotwert (A)
oder IBKRs USD-Kaufkraft inklusive Margin (B) sein soll. Das Skript liest
beide, damit die Entscheidung an Zahlen faellt und nicht an einer Vorstellung.

## Es aendert nichts

Nur Lesezugriffe: `managedAccounts()` und `accountValues()`. Kein Auftrag, kein
Storno, keine Subskription, die etwas hinterlaesst. Es laeuft deshalb auch
gegen ein Echtgeldkonto gefahrlos — es liest, was die TWS ohnehin anzeigt.

## Aufruf auf dem Rechner, auf dem die TWS laeuft

    python3 tools/currency_rate_probe.py
    python3 tools/currency_rate_probe.py --port 4002      # Papier-Gateway
    python3 tools/currency_rate_probe.py --all-tags       # alles, was ankommt
    python3 tools/currency_rate_probe.py --selftest       # ohne TWS, prueft die Rechnung

Es braucht nichts ausser `ib_insync` — dieselbe Bibliothek, die die Bridge
benutzt. Damit misst die Sonde, was der Ernstfall saehe.
"""
from __future__ import annotations

import argparse
import asyncio
import math
import sys
from dataclasses import dataclass

# ── Muss VOR dem Import von ib_insync stehen ────────────────────────────────
#
# Dieselbe Falle wie in `bracket_oca_probe.py`: `eventkit` ruft beim Import
# `asyncio.get_event_loop()`, und ab Python 3.14 wirft der Aufruf, statt still
# eine Schleife anzulegen. `ib_insync` wird seit 2023 nicht gepflegt und kennt
# das nicht.
if sys.version_info >= (3, 12):
# Gefragt wird nach dem LAUFENDEN Loop, nicht nach `get_event_loop()`. Der
# Unterschied ist nicht Geschmack: `get_event_loop()` wirft erst ab 3.14, warnt
# aber schon ab 3.12 — auf dem Debian-VPS des Owners (Python 3.13) stand
# deshalb vor jedem Lauf eine DeprecationWarning. Der Riegel fing die Ausnahme
# und liess die Warnung durch. `get_running_loop()` wirft in einem Skript immer
# (es laeuft ja noch nichts), sagt dabei aber nichts.
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

# Eine Kennung, die sonst niemand benutzt: die Bridge faehrt 17 bzw. 101, die
# Klammer-Sonde 992/993, das Owner-Testskript 994. Zwei Clients mit derselben
# Kennung werfen sich gegenseitig aus der TWS (Fehler 326).
CLIENT_ID = 991

PLATTFORM_WAEHRUNG = "USD"
# IBKR benennt die Sammelzeile so; sie traegt keine echte Waehrung.
SAMMELZEILEN = {"BASE", ""}
# Die Kaufkraft-Familie. Welche davon IBKR fuehrt, ist je Kontoform verschieden
# — deshalb wird gelesen, was da ist, statt eine zu verlangen.
KAUFKRAFT_TAGS = (
    "BuyingPower",
    "AvailableFunds",
    "FullAvailableFunds",
    "ExcessLiquidity",
    "FullExcessLiquidity",
)


# ── Die reine Rechnung ───────────────────────────────────────────────────────
#
# Getrennt von allem, was eine TWS braucht: nur so laesst sich die Richtungs-
# probe ohne laufende Verbindung belegen (`--selftest`). Eine Sonde, deren Kern
# man erst am Messobjekt pruefen kann, ist kein Messgeraet.


@dataclass(frozen=True)
class Kontowert:
    tag: str
    waehrung: str
    wert: float


@dataclass(frozen=True)
class Richtungsurteil:
    """Wie IBKRs Kurs rechnet — oder dass es sich nicht entscheiden laesst."""

    richtung: str  # "segment_zu_basis" | "basis_zu_segment" | "unentscheidbar"
    summe_mal: float | None
    summe_geteilt: float | None
    basis_summe: float | None
    begruendung: str


def _zahl(roh: object) -> float | None:
    try:
        f = float(str(roh).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f  # NaN faellt raus


# IBKR nennt die Ledger-Zeilen mit Praefix: `$LEDGER-ExchangeRate`, nicht
# `ExchangeRate`. Gemessen am 2026-09-28 — die erste Fassung dieser Sonde suchte
# den nackten Namen und meldete „kein Kurs", waehrend er zwei Zeilen tiefer
# stand.
LEDGER_PRAEFIX = "$LEDGER-"
# Die Suffixe `-P` und `-S` gehoeren zu Unterkonten (Paxos-Krypto, CFD) und
# tragen eigene, meist leere Zahlen. Sie duerfen nie in eine Summe geraten,
# deshalb wird nach der Normalisierung EXAKT verglichen, nicht per Praefix.


def normalisiere_tag(tag: str) -> str:
    """`$LEDGER-ExchangeRate` und `ExchangeRate` sind derselbe Gegenstand."""
    return tag.removeprefix(LEDGER_PRAEFIX)


def segmente(werte: list[Kontowert], tag: str) -> dict[str, float]:
    """Die Zeilen eines Tags je echter Waehrung — ohne die Sammelzeile."""
    return {
        w.waehrung.upper(): w.wert
        for w in werte
        if normalisiere_tag(w.tag) == tag
        and w.waehrung
        and w.waehrung.upper() not in SAMMELZEILEN
    }


def sammelzeile(werte: list[Kontowert], tag: str) -> float | None:
    """Der Wert der Sammelzeile `BASE` — die Probe fuer die Richtung."""
    for w in werte:
        if normalisiere_tag(w.tag) == tag and w.waehrung.upper() in SAMMELZEILEN:
            return w.wert
    return None


def netliq_tag(werte: list[Kontowert]) -> str:
    """Welcher Tag traegt den Depotwert JE WAEHRUNG?

    Zwei Zeilen heissen aehnlich und meinen Verschiedenes:

        NetLiquidation                    EUR  997.317,88   ← das GANZE Konto,
                                                              in Basiswaehrung
        $LEDGER-NetLiquidationByCurrency  EUR  1.000.775,19  ← nur das
                                                              EUR-Segment

    Die Richtungsprobe braucht die zweite. Die erste dazuzumischen ergaebe eine
    Summe, die es nicht gibt — das EUR-Segment wuerde doppelt gezaehlt. Nur wenn
    das Ledger fehlt, ist die Kontozeile die beste verfuegbare Auskunft.
    """
    for w in werte:
        if normalisiere_tag(w.tag) == "NetLiquidationByCurrency":
            return "NetLiquidationByCurrency"
    return "NetLiquidation"


def vereinige(
    primaer: list[Kontowert], sekundaer: list[Kontowert]
) -> list[Kontowert]:
    """Beide Quellen zu einer Sicht — bei Gleichstand gewinnt die primaere.

    `accountSummary()` (Ledger) und `accountValues()` (reqAccountUpdates)
    ueberschneiden sich in einigen Tags. Zwei Zeilen fuer dasselbe Paar aus Tag
    und Waehrung waeren in der Richtungsprobe eine doppelte Summe — und die
    Probe rechnet dann an einer Zahl, die es nicht gibt.
    """
    sicht: dict[tuple[str, str], Kontowert] = {}
    for w in sekundaer:
        sicht[(w.tag, w.waehrung.upper())] = w
    for w in primaer:
        sicht[(w.tag, w.waehrung.upper())] = w
    return list(sicht.values())


def pruefe_richtung(
    werte: list[Kontowert], *, toleranz: float = 0.0005
) -> Richtungsurteil:
    """In welche Richtung rechnet `ExchangeRate`?

    Die Sammelzeile `BASE` von `NetLiquidation` ist die einzige Zeile, deren
    Wert aus den anderen folgt. Genau deshalb taugt sie als Probe:

        Hypothese A  Kurs rechnet Segment -> Basis:   Summe(Wert x Kurs) == BASE
        Hypothese B  Kurs rechnet Basis -> Segment:   Summe(Wert : Kurs) == BASE

    Passt genau eine, ist die Richtung belegt. Passen beide, ist nichts
    entschieden, und das ist die ehrliche Antwort. Raten waere hier der
    teuerste Fehler des ganzen Vorgangs.

    **Die Toleranz ist eng (0,1 %), und das mit Absicht.** IBKR bildet BASE aus
    genau diesen Zahlen, die richtige Hypothese trifft also bis auf Rundung.
    Eine weite Toleranz wuerde beide Hypothesen einschliessen, sobald das
    Fremdsegment klein gegen das Hauptsegment ist — die Probe saehe dann aus
    wie eine Antwort und waere keine. Mit 1 % passierte genau das: bei
    50.000 USD neben 996.914 EUR liegen beide Rechnungen 0,8 % auseinander.
    """
    kurse = segmente(werte, "ExchangeRate")
    tag = netliq_tag(werte)
    betraege = segmente(werte, tag)
    basis = sammelzeile(werte, tag)

    if not kurse:
        return Richtungsurteil(
            "unentscheidbar", None, None, basis,
            "IBKR liefert keine ExchangeRate-Zeile — die Annahme von T1-252 trifft nicht zu.",
        )
    if basis is None:
        return Richtungsurteil(
            "unentscheidbar", None, None, None,
            f"Keine Sammelzeile BASE zu {tag} — ohne sie gibt es keine Probe.",
        )

    gemeinsam = sorted(set(kurse) & set(betraege))
    if not gemeinsam:
        return Richtungsurteil(
            "unentscheidbar", None, None, basis,
            "Kein Waehrungssegment traegt Betrag UND Kurs — nichts zu rechnen.",
        )

    summe_mal = sum(betraege[c] * kurse[c] for c in gemeinsam)
    summe_geteilt = sum(
        betraege[c] / kurse[c] for c in gemeinsam if kurse[c] != 0.0
    )

    # Nicht „liegt innerhalb einer Grenze", sondern „trifft, waehrend die andere
    # danebenliegt". Der Unterschied ist an den echten Zahlen vom 2026-09-28
    # entscheidend: dort war A exakt und B um 0,1013 % daneben — bei einer
    # Grenze von 0,1 % haette die Entscheidung an der dritten Nachkommastelle
    # gehangen. Eine Probe, die so knapp ausgeht, ist keine.
    #
    # IBKR bildet BASE aus genau diesen Zahlen. Die richtige Hypothese trifft
    # also bis auf Rundung, und die falsche muss SPUERBAR danebenliegen.
    rel_mal = abs(summe_mal - basis) / abs(basis) if basis else float("inf")
    rel_geteilt = abs(summe_geteilt - basis) / abs(basis) if basis else float("inf")
    TRIFFT = toleranz  # der Sieger muss praktisch exakt sein
    DANEBEN = 0.0002  # der Verlierer muss mindestens 0,02 % danebenliegen

    passt_mal = rel_mal <= TRIFFT and rel_geteilt >= DANEBEN
    passt_geteilt = rel_geteilt <= TRIFFT and rel_mal >= DANEBEN

    if passt_mal and not passt_geteilt:
        return Richtungsurteil(
            "segment_zu_basis", summe_mal, summe_geteilt, basis,
            "Summe(Wert x Kurs) trifft die Sammelzeile, Summe(Wert : Kurs) nicht.",
        )
    if passt_geteilt and not passt_mal:
        return Richtungsurteil(
            "basis_zu_segment", summe_mal, summe_geteilt, basis,
            "Summe(Wert : Kurs) trifft die Sammelzeile, Summe(Wert x Kurs) nicht.",
        )
    if min(rel_mal, rel_geteilt) > TRIFFT:
        return Richtungsurteil(
            "unentscheidbar", summe_mal, summe_geteilt, basis,
            "Keine der beiden Rechnungen trifft die Sammelzeile. IBKR bildet BASE anders, "
            "als dieser Entwurf annimmt — das gehoert in den Spec, bevor gebaut wird.",
        )
    return Richtungsurteil(
        "unentscheidbar", summe_mal, summe_geteilt, basis,
        "Die beiden Rechnungen liegen zu nah beieinander. Das heisst nicht, dass beide "
        "stimmen, sondern dass dieses Konto sie nicht auseinanderhaelt — ein einziges "
        "Segment, lauter Kurse von 1,0, oder ein Fremdsegment, das zu klein gegen das "
        "Hauptsegment ist. Die Richtung braucht ein Konto mit einem spuerbaren zweiten "
        "Segment.",
    )


def in_plattformwaehrung(
    werte: list[Kontowert], urteil: Richtungsurteil
) -> tuple[float | None, str]:
    """Der Depotwert in USD — oder warum er sich nicht bilden laesst."""
    betraege = segmente(werte, "NetLiquidation")
    kurse = segmente(werte, "ExchangeRate")

    if PLATTFORM_WAEHRUNG in betraege and len(betraege) == 1:
        return betraege[PLATTFORM_WAEHRUNG], "Das Konto ist bereits USD — keine Umrechnung noetig."
    if urteil.richtung == "unentscheidbar":
        return None, "Die Kursrichtung ist nicht belegt; eine Umrechnung waere geraten."

    kurs_usd = kurse.get(PLATTFORM_WAEHRUNG)
    if kurs_usd is None or kurs_usd == 0.0:
        return None, "Kein brauchbarer Kurs fuer USD in der Antwort."
    if urteil.basis_summe is None:
        return None, "Keine Sammelzeile BASE."

    # BASE steht in der Basiswaehrung des Kontos. Der USD-Kurs sagt, wie diese
    # beiden zueinander stehen — in der Richtung, die oben belegt wurde.
    if urteil.richtung == "segment_zu_basis":
        # Kurs rechnet USD -> Basis, also Basis : Kurs = USD.
        return urteil.basis_summe / kurs_usd, "BASE geteilt durch den USD-Kurs."
    return urteil.basis_summe * kurs_usd, "BASE mal den USD-Kurs."


# ── Der Selbsttest ───────────────────────────────────────────────────────────


def selftest() -> int:
    bestanden = 0
    fehlgeschlagen = 0

    def check(name: str, bedingung: bool, detail: str = "") -> None:
        nonlocal bestanden, fehlgeschlagen
        if bedingung:
            bestanden += 1
            print(f"  ok    {name}")
        else:
            fehlgeschlagen += 1
            print(f"  FEHL  {name}   {detail}")

    # Ein EUR-Konto mit einem USD-Segment. Kurse rechnen Segment -> Basis:
    # 996.914,07 EUR x 1,0 + 50.000 USD x 0,92 = 1.042.914,07 EUR
    a = [
        Kontowert("NetLiquidation", "BASE", 1_042_914.07),
        Kontowert("NetLiquidation", "EUR", 996_914.07),
        Kontowert("NetLiquidation", "USD", 50_000.00),
        Kontowert("ExchangeRate", "EUR", 1.0),
        Kontowert("ExchangeRate", "USD", 0.92),
    ]
    ua = pruefe_richtung(a)
    check("A  Segment->Basis wird erkannt", ua.richtung == "segment_zu_basis", ua.richtung)
    usd_a, _ = in_plattformwaehrung(a, ua)
    check(
        "A  Depotwert in USD = BASE : 0,92",
        usd_a is not None and abs(usd_a - 1_042_914.07 / 0.92) < 0.01,
        str(usd_a),
    )

    # GEGENTEST. Dieselben Betraege, Kurse in der Gegenrichtung:
    # 996.914,07 : 1,0 + 50.000 : 1,0870 = 1.042.914,07
    b = [
        Kontowert("NetLiquidation", "BASE", 1_042_914.07),
        Kontowert("NetLiquidation", "EUR", 996_914.07),
        Kontowert("NetLiquidation", "USD", 50_000.00),
        Kontowert("ExchangeRate", "EUR", 1.0),
        Kontowert("ExchangeRate", "USD", 50_000.0 / 46_000.0),
    ]
    ub = pruefe_richtung(b)
    check("B  Basis->Segment wird erkannt (Gegentest)", ub.richtung == "basis_zu_segment", ub.richtung)
    check("B  ist NICHT dasselbe Urteil wie A", ua.richtung != ub.richtung)

    # Fehlt die Kurszeile, ist die Annahme von T1-252 widerlegt — und das muss
    # das Skript sagen, nicht ueberspielen.
    c = [
        Kontowert("NetLiquidation", "BASE", 996_914.07),
        Kontowert("NetLiquidation", "EUR", 996_914.07),
    ]
    uc = pruefe_richtung(c)
    check("C  Ohne ExchangeRate: unentscheidbar", uc.richtung == "unentscheidbar", uc.richtung)
    check("C  und die Begruendung nennt T1-252", "T1-252" in uc.begruendung)
    usd_c, _ = in_plattformwaehrung(c, uc)
    check("C  kein geratener Depotwert", usd_c is None, str(usd_c))

    # Ein Konto mit nur einem Segment kann die Richtung nicht belegen. Das ist
    # der Fall des Owner-Kontos (USD) — und der Grund, warum die Messung an
    # DUT106306 laufen muss.
    d = [
        Kontowert("NetLiquidation", "BASE", 309_018.00),
        Kontowert("NetLiquidation", "USD", 309_018.00),
        Kontowert("ExchangeRate", "USD", 1.0),
    ]
    ud = pruefe_richtung(d)
    check("D  Ein-Segment-Konto: unentscheidbar", ud.richtung == "unentscheidbar", ud.richtung)
    usd_d, _ = in_plattformwaehrung(d, ud)
    check("D  reines USD-Konto meldet trotzdem seinen Wert", usd_d == 309_018.00, str(usd_d))

    # Passt keine der beiden Rechnungen, wird das gesagt statt gewaehlt.
    e = [
        Kontowert("NetLiquidation", "BASE", 5_000_000.00),
        Kontowert("NetLiquidation", "EUR", 996_914.07),
        Kontowert("NetLiquidation", "USD", 50_000.00),
        Kontowert("ExchangeRate", "EUR", 1.0),
        Kontowert("ExchangeRate", "USD", 0.92),
    ]
    ue = pruefe_richtung(e)
    check("E  Passt nichts: unentscheidbar", ue.richtung == "unentscheidbar", ue.richtung)
    check("E  und es wird nicht gerundet weggeredet", "anders" in ue.begruendung)

    # Die Sammelzeile darf nie als Segment durchgehen.
    check("F  BASE zaehlt nicht als Waehrungssegment", "BASE" not in segmente(a, "NetLiquidation"))
    check("F  leere Waehrung zaehlt auch nicht",
          segmente([Kontowert("NetLiquidation", "", 1.0)], "NetLiquidation") == {})

    # G — die Toleranz muss Rundung ueberleben. Waere sie zu eng, meldete die
    # Sonde an echten Zahlen "passt nichts" und waere unbrauchbar.
    g = [
        Kontowert("NetLiquidation", "BASE", 1_042_914.11),  # vier Cent daneben
        Kontowert("NetLiquidation", "EUR", 996_914.07),
        Kontowert("NetLiquidation", "USD", 50_000.00),
        Kontowert("ExchangeRate", "EUR", 1.0),
        Kontowert("ExchangeRate", "USD", 0.92),
    ]
    ug = pruefe_richtung(g)
    check("G  Rundung bricht die Probe nicht", ug.richtung == "segment_zu_basis", ug.richtung)

    # H — GEGENTEST zur engen Toleranz. Ist das Fremdsegment winzig, liegen
    # BEIDE Rechnungen nah an der Sammelzeile. Dann ist "unentscheidbar" die
    # richtige Antwort, nicht die naechstbeste Hypothese. Genau diesen Fall hat
    # eine Toleranz von 1 % verschluckt und als Antwort ausgegeben.
    h = [
        Kontowert("NetLiquidation", "BASE", 996_998.07),
        Kontowert("NetLiquidation", "EUR", 996_914.07),
        Kontowert("NetLiquidation", "USD", 100.00),
        Kontowert("ExchangeRate", "EUR", 1.0),
        Kontowert("ExchangeRate", "USD", 0.84),
    ]
    uh = pruefe_richtung(h)
    check("H  Winziges Fremdsegment: unentscheidbar", uh.richtung == "unentscheidbar", uh.richtung)
    check("H  und die Begruendung nennt den Grund", "zu klein" in uh.begruendung, uh.begruendung)
    # Und der Beleg, dass die Manipulation ueberhaupt gegriffen hat: mit einem
    # spuerbaren Segment entscheidet dieselbe Regel sehr wohl.
    check("H  Gegenprobe: dieselbe Regel entscheidet bei grossem Segment",
          pruefe_richtung(a).richtung == "segment_zu_basis")

    # I — die Vereinigung beider Quellen. Ohne sie zaehlt die Richtungsprobe
    # ein Segment doppelt, sobald beide Quellen denselben Tag melden.
    ledger = [
        Kontowert("NetLiquidation", "EUR", 996_914.07),
        Kontowert("ExchangeRate", "EUR", 1.0),
    ]
    updates = [
        Kontowert("NetLiquidation", "EUR", 111_111.11),  # dieselbe Zelle, anderer Wert
        Kontowert("TotalCashValue", "EUR", 685_151.94),  # nur hier
    ]
    v = vereinige(ledger, updates)
    check("I  Ledger gewinnt bei Gleichstand",
          segmente(v, "NetLiquidation") == {"EUR": 996_914.07},
          str(segmente(v, "NetLiquidation")))
    check("I  Zeilen nur aus der zweiten Quelle bleiben",
          segmente(v, "TotalCashValue") == {"EUR": 685_151.94})
    check("I  keine Dublette", len(v) == 3, str(len(v)))
    # GEGENTEST: ohne Vereinigung waere die Summe eine andere. Der Beleg, dass
    # die Manipulation ueberhaupt greift.
    check("I  Gegentest: unvereinigt zaehlt doppelt",
          len(ledger + updates) == 4 and len(v) == 3)

    # J — DIE ECHTEN ZAHLEN. Gemessen am 2026-09-28 auf DUT106306, mit den
    # Tag-Namen, wie IBKR sie wirklich schickt. Das ist der Rueckfall-Riegel
    # gegen genau den Fehler, den diese Sonde zweimal gemacht hat: sie suchte
    # `ExchangeRate` und `NetLiquidation`, IBKR schickt `$LEDGER-ExchangeRate`
    # und `$LEDGER-NetLiquidationByCurrency`.
    echt = [
        Kontowert("$LEDGER-NetLiquidationByCurrency", "BASE", 997_317.877),
        Kontowert("$LEDGER-NetLiquidationByCurrency", "EUR", 1_000_775.19),
        Kontowert("$LEDGER-NetLiquidationByCurrency", "USD", -3_930.049),
        Kontowert("$LEDGER-ExchangeRate", "BASE", 1.00),
        Kontowert("$LEDGER-ExchangeRate", "EUR", 1.00),
        Kontowert("$LEDGER-ExchangeRate", "USD", 0.8797124),
        # Die Kontozeile traegt denselben Namen ohne Praefix und einen ANDEREN
        # Wert — sie darf die Summe nicht verfaelschen.
        Kontowert("NetLiquidation", "EUR", 997_317.88),
        # Unterkonto-Zeilen. Duerfen nie in eine Summe geraten.
        Kontowert("NetLiquidation-P", "EUR", 0.00),
        Kontowert("NetLiquidation-S", "EUR", 0.00),
    ]
    check("J  Der Kurs wird im Ledger gefunden",
          segmente(echt, "ExchangeRate") == {"EUR": 1.00, "USD": 0.8797124},
          str(segmente(echt, "ExchangeRate")))
    check("J  Der Depotwert je Waehrung kommt aus dem Ledger",
          netliq_tag(echt) == "NetLiquidationByCurrency", netliq_tag(echt))
    check("J  Die Kontozeile faelscht die Summe nicht",
          segmente(echt, "NetLiquidationByCurrency") == {"EUR": 1_000_775.19, "USD": -3_930.049},
          str(segmente(echt, "NetLiquidationByCurrency")))
    uj = pruefe_richtung(echt)
    check("J  Richtung: Segment -> Basis", uj.richtung == "segment_zu_basis", uj.begruendung)
    usd_j, _ = in_plattformwaehrung(echt, uj)
    check("J  Depotwert 1.133.686,27 USD",
          usd_j is not None and abs(usd_j - 1_133_686.27) < 1.0, f"{usd_j}")
    # GEGENTEST auf die Entscheidungsregel: an diesen Zahlen lag die falsche
    # Hypothese nur 0,1013 % daneben. Mit einer schlichten 0,1-%-Grenze haette
    # die Probe an der dritten Nachkommastelle gehangen — hier wird belegt,
    # dass sie das nicht mehr tut.
    rel_falsch = abs(sum(
        v / {"EUR": 1.00, "USD": 0.8797124}[c]
        for c, v in {"EUR": 1_000_775.19, "USD": -3_930.049}.items()
    ) - 997_317.877) / 997_317.877
    check("J  Gegentest: die falsche Hypothese liegt nur 0,1 % daneben",
          0.0009 < rel_falsch < 0.0011, f"{rel_falsch:.6f}")
    check("J  und wird trotzdem sicher verworfen", uj.richtung == "segment_zu_basis")

    print(f"\n  {bestanden} bestanden, {fehlgeschlagen} fehlgeschlagen")
    return 0 if fehlgeschlagen == 0 else 1


# ── Die Messung an der TWS ───────────────────────────────────────────────────


def zeile(label: str, wert: object) -> None:
    print(f"  {label:<34} {wert}")


def messe(host: str, port: int, client_id: int, alle_tags: bool) -> int:
    # Erst hier, nicht oben: der Import muss NACH dem Event-Loop-Kniff laufen.
    from ib_insync import IB

    ib = IB()
    print(f"Verbinde mit {host}:{port} (Client {client_id}) …")
    try:
        ib.connect(host, port, clientId=client_id, timeout=15)
    except Exception as exc:  # noqa: BLE001 — jede Gestalt soll denselben Hinweis geben
        print(f"\nKeine Verbindung: {exc}")
        print("  Laeuft die TWS? Ist die API freigegeben? Stimmt der Port?")
        print("  Der Port ist eine EINSTELLUNG in der TWS und folgt nicht aus der Kontoform.")
        return 2

    try:
        # `reqAccountUpdates` laeuft beim Verbinden an; die Zeilen trudeln ein.
        ib.sleep(3.0)

        konten = [k for k in ib.managedAccounts() if k]

        def als_werte(roh: list) -> list[Kontowert]:
            return [
                Kontowert(v.tag, v.currency or "", z)
                for v in roh
                if (z := _zahl(v.value)) is not None
            ]

        # Quelle 1: reqAccountUpdates. Meldet das Konto in SEINER Basiswaehrung.
        roh_updates = ib.accountValues()
        # Quelle 2: reqAccountSummary mit $LEDGER:ALL. Hier liegen die Kurse.
        # Blockiert beim ersten Aufruf (rund 250 ms), danach nicht mehr.
        try:
            roh_summary = ib.accountSummary()
        except Exception as exc:  # noqa: BLE001 — eine fehlende Quelle ist ein Befund, kein Absturz
            print(f"\n  accountSummary() nicht lesbar: {exc}")
            roh_summary = []

        w_updates = als_werte(roh_updates)
        w_summary = als_werte(roh_summary)
        # Das Ledger gewinnt: es ist die Quelle, die nach Waehrung aufschluesselt.
        werte = vereinige(w_summary, w_updates)

        print("\n════ Das Konto ════")
        zeile("Verwaltete Konten", ", ".join(konten) or "(keine)")
        zeile("Zeilen aus accountValues()", len(w_updates))
        zeile("Zeilen aus accountSummary()", f"{len(w_summary)}  ($LEDGER:ALL)")
        if len(konten) > 1:
            print("  ACHTUNG: mehrere Konten. Die Bridge verweigert hier die Deutung")
            print("           (Advisory-Fall, eigener Vorgang). Die Zahlen unten")
            print("           koennen ueber Konten hinweg summiert sein.")

        netliq = segmente(werte, "NetLiquidation")
        basis = sammelzeile(werte, "NetLiquidation")
        zeile("NetLiquidation BASE", f"{basis:,.2f}" if basis is not None else "(keine Sammelzeile)")
        for w, v in sorted(netliq.items()):
            zeile(f"NetLiquidation {w}", f"{v:,.2f}")

        print("\n════ Frage 1 — liefert IBKR einen Kurs? ════")
        kurse_u = segmente(w_updates, "ExchangeRate")
        kurse_s = segmente(w_summary, "ExchangeRate")
        zeile("aus accountValues()", ", ".join(f"{k}={v}" for k, v in sorted(kurse_u.items())) or "keine")
        zeile("aus accountSummary()", ", ".join(f"{k}={v}" for k, v in sorted(kurse_s.items())) or "keine")
        kurse = segmente(werte, "ExchangeRate")
        if kurse:
            quelle = "accountSummary() / $LEDGER:ALL" if kurse_s else "accountValues()"
            print(f"  JA — der Kurs kommt aus {quelle}.")
        else:
            print("  NEIN — in KEINER der beiden Quellen eine ExchangeRate-Zeile.")
            print("  Erst damit ist die Annahme von T1-252 widerlegt. Der Vorgang")
            print("  braucht dann eine eigene Kursquelle, und die drei Festlegungen")
            print("  aus T1-85 (Quelle, Aktualitaet, Ausfall) kommen zurueck.")

        print("\n════ Frage 2 — in welche Richtung rechnet er? ════")
        urteil = pruefe_richtung(werte)
        zeile("Urteil", urteil.richtung)
        zeile("Begruendung", urteil.begruendung)
        if urteil.summe_mal is not None:
            zeile("Summe(Wert x Kurs)", f"{urteil.summe_mal:,.2f}")
            zeile("Summe(Wert : Kurs)", f"{urteil.summe_geteilt:,.2f}")
            zeile("Sammelzeile BASE", f"{urteil.basis_summe:,.2f}")

        print("\n════ Frage 3 — welche Zahl ist sein Kapital? ════")
        umgerechnet, grund = in_plattformwaehrung(werte, urteil)
        if umgerechnet is not None:
            zeile("A  Depotwert in USD", f"{umgerechnet:,.2f}   ({grund})")
        else:
            zeile("A  Depotwert in USD", f"nicht bildbar — {grund}")

        gefunden = False
        for tag in KAUFKRAFT_TAGS:
            for w, v in sorted(segmente(werte, tag).items()):
                zeile(f"B  {tag} {w}", f"{v:,.2f}")
                gefunden = True
            s = sammelzeile(werte, tag)
            if s is not None:
                zeile(f"B  {tag} BASE", f"{s:,.2f}")
                gefunden = True
        if not gefunden:
            print("  Keine Kaufkraft-Zeile in der Antwort — Variante B entfaellt damit.")

        if alle_tags:
            for name, quelle in (("accountValues()", roh_updates),
                                 ("accountSummary() / $LEDGER:ALL", roh_summary)):
                print(f"\n════ Alle Zeilen aus {name} ════")
                for v in sorted(quelle, key=lambda x: (x.tag, x.currency or "")):
                    print(f"  {v.tag:<32} {(v.currency or '-'):<6} {v.value}")

        print("\n── Fuer den Spec: das gehoert nach AC-1 und AC-2 ──")
        return 0
    finally:
        ib.disconnect()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=7497,
                   help="7497 Papier-TWS, 7496 Echt-TWS, 4002 Papier-Gateway, 4001 Echt-Gateway")
    p.add_argument("--client-id", type=int, default=CLIENT_ID)
    p.add_argument("--all-tags", action="store_true", help="jede Zeile ausgeben, die ankommt")
    p.add_argument("--selftest", action="store_true", help="die Rechnung pruefen, ohne TWS")
    a = p.parse_args()

    if a.selftest:
        print("Selbsttest der Richtungsprobe (ohne TWS):\n")
        return selftest()
    return messe(a.host, a.port, a.client_id, a.all_tags)


if __name__ == "__main__":
    raise SystemExit(main())
