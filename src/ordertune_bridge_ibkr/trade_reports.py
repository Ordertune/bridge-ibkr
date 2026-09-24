"""T1-207 — die TWS schreibt ihre Ausfuehrungen selbst auf die Platte.

## Der Fehler, aus dem das entstanden ist

Ist die Bridge zum Handelsende aus, ist die Fuellung fuer sie verloren. Belegt
am Konto …2572: zwei Kaeufe von je 21 MU am 15.09. in der Schlussauktion, die
Bridge 25 Minuten vorher aus. Der Abgleich am 18.09. schrumpfte ein fremdes Lot
und klebte das falsche Etikett darauf; am 21.09. ist der falsche Verkauf
gelaufen.

Nachfragen geht nicht. `reqCompletedOrders` und `ib.fills()` halten den
laufenden Tag, und `reqExecutions` mit Zeitfilter ebenfalls — am 2026-09-22 mit
einer eigenen Sonde gemessen: fuenf Fuellungen vom 18.09. lagen im
Sieben-Tage-Fenster, die Sonde bekam null zurueck. Das ist keine Fehlfunktion,
sondern eine Grenze von IBKR, und sie hat T1-203 erledigt.

## Was stattdessen da ist

Die TWS hat unter `Global Configuration → Export Reports` eine
Berichtsfunktion, die je Handelstag eine Datei mit allen Ausfuehrungen
schreibt und sie **nie loescht**. Die Grenze oben gilt fuer die
Schnittstelle — die TWS schreibt die Datei unabhaengig davon, ob ein
API-Client verbunden ist. Genau deshalb kann diese Quelle, was T1-203 nicht
konnte.

Das IB Gateway hat die Funktion nicht; sein Konfigurationsbaum endet bei
`Orders → Smart Routing`. Deshalb verlangt das Setup ab diesem Vorgang die
TWS.

## Was dieses Modul NICHT tut

Es entscheidet nichts. Es liefert Fuellungen in genau der Form, die
`order_reconcile.fills_by_dispatch` ohnehin liest — vierter Zeuge neben den
drei tagesgebundenen. Die Entscheidung, ob ein Auftrag ausgefuehrt ist, faellt
weiterhin an genau einer Stelle.

## Drei Entscheidungen, die aus der echten Datei stammen

**Spalten nach Namen, nie nach Position.** Die Spaltenauswahl ist eine
Einstellung beim Kunden. Wer nach Position liest, baut eine Bombe mit
Zeitzuender: sie geht beim ersten Kunden hoch, der eine Spalte abwaehlt.

**Feldzahl pruefen statt der Einstellung vertrauen.** Die Datei kennt kein
Quoting — in 45 Spalten der Beispieldatei steht kein einziges
Anfuehrungszeichen. Ein Trennzeichen in einem frei getippten Kommentar
verschiebt still alle folgenden Spalten, und die verschobene Zeile saehe aus
wie eine gueltige. Deshalb wird sie nicht gelesen, sondern benannt. Aus
demselben Grund liest `csv.reader` hier mit `QUOTE_NONE`: ein einzelnes
Anfuehrungszeichen in einem Kommentar duerfte nicht anfangen, Felder
zusammenzuziehen.

**Das Etikett im Vermerk wird nicht ausgewertet.** In drei Zeilen derselben
Strategie stand es als `Momentum_Power`, `Momentum_Powerho` und
`Momentum_Powerh` — die Plattform kuerzt es je nach Laenge von Symbol und
Nummer verschieden, damit der Vermerk in 64 Zeichen passt. Nur die UUID am
Ende zaehlt, und die liest `dispatch_id_from_order_ref`.
"""
from __future__ import annotations

import csv
import logging
import math
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .order_reference import dispatch_id_from_order_ref

log = logging.getLogger(__name__)

#: Der Name des Ordners, den beide Plattformen vorschlagen. Er steht hier
#: einmal, damit Anleitung und Vorschlag nicht auseinanderlaufen koennen.
EXPORT_ORDNERNAME = "IBExport"


def standard_verzeichnis() -> str:
    r"""Wohin die TWS ueblicherweise exportiert. Nur ein Vorschlag.

    Der Kunde waehlt das Verzeichnis im Dialog der TWS selbst, und `bridge.env`
    hat in jedem Fall das letzte Wort. Dieser Wert entscheidet nur, ob er
    ueberhaupt etwas eintragen **muss**.

    ## Warum hier bis T1-206 eine leere Zeichenkette stand

    Die Begruendung war: ausserhalb von Windows gibt es keinen sinnvollen
    Vorschlag, und einen Windows-Pfad zu vermissen, den es auf dieser Maschine
    nie geben wird, waere schlechter als zu schweigen.

    Das stimmte, **solange wir das Installationsbild auf Linux nicht kannten**.
    Mit Scope C von T1-206 liegt es fest: ein Dienstnutzer mit Heimverzeichnis,
    unter dem sowohl die TWS als auch die Bridge laufen (Entscheidung 7). Damit
    gibt es einen natuerlichen Ort, und er ist genauso gut wie `C:\IBExport`
    auf Windows.

    ## Was die leere Zeichenkette gekostet haette

    Die Bereitschaftspruefung haette auf **jeder** frischen Linux-Installation
    `not_configured` gemeldet, und diese Meldung sagt woertlich, was fehlt: eine
    Fuellung, die passiert, waehrend die Bridge aus ist, kann nicht nachgetragen
    werden. Das ist der teuerste Zustand des ganzen Systems — und er waere auf
    Linux die Voreinstellung gewesen, nicht der Ausnahmefall.

    Die Plattform-Verzweigung bleibt dabei die einzige im Modul. Es kommt kein
    zweiter Entscheidungspunkt dazu, nur ein tragfaehiger Zweig an derselben
    Stelle.
    """
    if sys.platform == "win32":
        return rf"C:\{EXPORT_ORDNERNAME}"
    try:
        return str(Path.home() / EXPORT_ORDNERNAME)
    except (OSError, RuntimeError):
        # Ein Vorgang ohne aufloesbares Heimverzeichnis — ein Dienst ohne
        # `HOME`, ein leeres Passwortverzeichnis. Dann lieber schweigen als
        # einen Pfad vorschlagen, der nirgendwohin zeigt: das ist genau der
        # alte Zustand, und fuer genau diesen Fall war er richtig.
        return ""


#: Der Vorschlag, einmal beim Laden ausgewertet. `config` liest ihn als
#: `DEFAULT_TWS_EXPORT_DIR`.
STANDARD_VERZEICHNIS = standard_verzeichnis()

# ── Spaltennamen, wie die TWS sie schreibt ───────────────────────────────────
SPALTE_KONTO = "Account"
SPALTE_VERMERK = "Order Ref."
SPALTE_KENNUNG = "ID"
SPALTE_MENGE = "Quantity"
SPALTE_KURS = "Price"
SPALTE_TAG = "Date"
SPALTE_ZEIT = "Time"
SPALTE_GEBUEHR = "Commission"
SPALTE_SYMBOL = "Symbol"
SPALTE_RICHTUNG = "Action"

#: Ohne diese sieben ist eine Zeile nicht buchbar. Bewusst enger als die Liste,
#: die die Anleitung dem Kunden nennt: `Commission`, `Symbol` und `Action`
#: sollen dabei sein, aber eine Datei ohne sie ist immer noch besser als keine.
#: Eine fehlende Gebuehr ist dasselbe wie „IBKR hat keine geliefert" — ein
#: Zustand, den der Abgleich seit T1-105 kennt.
PFLICHTSPALTEN = (
    SPALTE_KONTO,
    SPALTE_VERMERK,
    SPALTE_KENNUNG,
    SPALTE_MENGE,
    SPALTE_KURS,
    SPALTE_TAG,
    SPALTE_ZEIT,
)

#: Nur diese beiden bietet der Dialog an. Erkannt wird an der Kopfzeile, damit
#: ein Kunde mit der anderen Einstellung trotzdem gelesen wird: die
#: Spaltennamen verwenden Punkte (`Comb.`, `Exch.`, `Undr. Symbol`), nie
#: Kommas oder Semikolons.
TRENNZEICHEN = (";", ",")

#: `trades.20260918.csv` → `20260918`. Bewusst nicht an einen Dateinamen
#: gebunden: welchen Standardnamen die TWS vergibt, ist eine Einstellung ihrer
#: Fassung, der Tag in der Datei dagegen steht in der Spalte `Date`.
_TAG_IM_NAMEN = re.compile(r"(?<!\d)(20\d{6})(?!\d)")


@dataclass(frozen=True)
class ArchivAusfuehrung:
    """Sieht aus wie eine `Execution`, soweit der Abgleich hinsieht.

    Die Feldnamen folgen absichtlich IBKRs Schreibweise und nicht der des
    Repos: `fills_by_dispatch` liest sie ueber `getattr`, und eine zweite
    Namensgebung waere eine zweite Stelle, an der etwas auseinanderlaufen kann.
    """

    execId: str
    orderRef: str
    shares: float
    price: float | None
    time: datetime
    acctNumber: str
    side: str
    symbol: str


@dataclass(frozen=True)
class ArchivGebuehr:
    execId: str
    commission: float


@dataclass(frozen=True)
class ArchivFuellung:
    execution: ArchivAusfuehrung
    commissionReport: ArchivGebuehr | None


@dataclass
class Lesung:
    """Was ein Lauf ueber das Archiv ergeben hat."""

    fuellungen: list[ArchivFuellung] = field(default_factory=list)
    #: Zeilen im eigenen Konto ohne unseren Vermerk — der Nutzer hat von Hand
    #: gehandelt. Gezaehlt, nicht gebucht: das ist T1-208.
    fremde: int = 0
    #: Zeilen eines anderen Kontos in derselben Datei (Mehrkonto-Login, oder
    #: Papier- und Echtkonto schreiben denselben Ordner).
    fremdes_konto: int = 0
    #: Zeilen, deren Feldzahl nicht zur Kopfzeile passt, mit Ort und Grund.
    quarantaene: list[str] = field(default_factory=list)
    #: Dateien, die gar nicht erst gelesen wurden, mit Grund.
    abgelehnt: list[str] = field(default_factory=list)
    gelesene_dateien: int = 0
    #: Juengster Handelstag, der in einer gebuchten Zeile stand (`YYYYMMDD`).
    neuester_tag: str | None = None
    #: Juengster Tag, den eine angefasste DATEI trug — unabhaengig davon, ob
    #: sie etwas fuer uns enthielt. Daran zieht die Wasserstandsmarke weiter:
    #: eine ruhige Woche ohne eigene Fuellungen darf sie nicht stehenlassen.
    neuester_dateitag: str | None = None


@dataclass(frozen=True)
class Bereitschaft:
    """Taugt das Exportverzeichnis als Quelle?

    `zustand` ist die Kennung, an der Protokoll und Cockpit dieselbe Lage
    erkennen; `text` ist der Satz fuer den Nutzer. Englisch, wie alles, was ein
    Nutzer zu sehen bekommt.
    """

    zustand: str
    text: str

    @property
    def ok(self) -> bool:
        return self.zustand == "ok"


# ── Dateien finden ───────────────────────────────────────────────────────────


def _tag_aus_name(pfad: Path) -> str | None:
    treffer = _TAG_IM_NAMEN.search(pfad.name)
    return treffer.group(1) if treffer else None


def _tag_der_datei(pfad: Path) -> str:
    """Der Handelstag, den eine Datei mutmasslich traegt.

    Aus dem Namen, sonst aus der Änderungszeit. Das ist nur die Vorauswahl —
    gebucht wird nach der Spalte `Date` in der Zeile selbst. Eine Datei mit
    falsch geratenem Tag wird dadurch hoechstens zu frueh gelesen, nie falsch
    verbucht.
    """
    aus_namen = _tag_aus_name(pfad)
    if aus_namen:
        return aus_namen
    try:
        # Ortszeit, absichtlich: der Tag einer Datei ist der Tag, an dem der
        # Rechner sie geschrieben hat.
        return datetime.fromtimestamp(pfad.stat().st_mtime).strftime("%Y%m%d")  # noqa: DTZ006
    except OSError:
        return "00000000"


def dateien(verzeichnis: Path, *, seit_tag: str | None = None) -> list[tuple[str, Path]]:
    """Die Berichtsdateien ab `seit_tag`, aelteste zuerst.

    `seit_tag` ist **einschliessend**: der Tag der Wasserstandsmarke wird erneut
    gelesen. Die Datei des laufenden Tages waechst ja noch, und die Entdopplung
    ueber die Ausfuehrungskennung macht das folgenlos.
    """
    try:
        roh = [p for p in verzeichnis.iterdir() if p.is_file() and p.suffix.lower() == ".csv"]
    except OSError:
        return []

    mit_tag = [(_tag_der_datei(p), p) for p in roh]
    if seit_tag:
        mit_tag = [(t, p) for t, p in mit_tag if t >= seit_tag]
    return sorted(mit_tag, key=lambda x: (x[0], x[1].name))


# ── Eine Datei lesen ─────────────────────────────────────────────────────────


def _trennzeichen(kopfzeile: str) -> str:
    """Semikolon gewinnt bei Gleichstand nicht — es gewinnt bei Mehrheit.

    Eine Kopfzeile mit 44 Spalten traegt 44 Trennzeichen der richtigen Sorte
    und praktisch keine der anderen. Ein Gleichstand waere keine Kopfzeile.
    """
    zaehlung = {z: kopfzeile.count(z) for z in TRENNZEICHEN}
    bestes = max(TRENNZEICHEN, key=lambda z: zaehlung[z])
    return bestes if zaehlung[bestes] > 0 else ","


def _zahl(roh: str) -> float | None:
    """Streng. Was nicht als Zahl dasteht, ist keine.

    Kein Entfernen von Tausendertrennzeichen, kein Umdeuten eines Kommas zum
    Dezimalpunkt: die gemessene Datei schreibt `244.21` und `1.0002`, trotz
    deutscher Oberflaeche. Raten waere hier teurer als eine Zeile in Quarantaene.
    """
    text = (roh or "").strip()
    if not text:
        return None
    try:
        wert = float(text)
    except ValueError:
        return None
    # `float()` nimmt "nan", "inf" und "1e400" anstandslos an. Eine Menge von
    # `nan` haette jeden Vergleich bestanden — `nan <= 0` ist falsch — und waere
    # als Bestand ins Buch gewandert, wo sie jede weitere Rechnung vergiftet.
    # Gefunden in der Selbst-QA am 2026-09-22, nicht in der Produktion.
    if not math.isfinite(wert):
        return None
    return wert


def _zeitpunkt(tag: str, zeit: str) -> datetime | None:
    """`20260918` + `19:59:00` → ein Zeitpunkt in UTC.

    Gelesen wird als **Ortszeit dieser Maschine**, weil im Export-Dialog „Fuer
    die Uhrzeiten der Trades die lokale Zeitzone verwenden" gesetzt sein muss.
    Die Bridge laeuft auf derselben Maschine wie die TWS — deshalb ist deren
    Ortszeit auch unsere, und die Sommerzeit rechnet das Betriebssystem.
    """
    tag = (tag or "").strip()
    zeit = (zeit or "").strip()
    if not tag:
        return None
    for form in ("%Y%m%d %H:%M:%S", "%Y%m%d %H:%M"):
        try:
            # Naiv ist hier der Punkt: die Datei traegt Ortszeit, und
            # `astimezone()` rechnet sie unten mit der Zone dieser Maschine
            # nach UTC — Sommerzeit inbegriffen.
            naiv = datetime.strptime(f"{tag} {zeit}", form)  # noqa: DTZ007
        except ValueError:
            continue
        return naiv.astimezone(timezone.utc)
    return None


def lies_datei(pfad: Path, konto: str, *, lesung: Lesung) -> None:
    """Eine Berichtsdatei in `lesung` einsammeln.

    Faengt alles ab. Eine unlesbare Datei ist ein Befund, kein Abbruch: der
    Abgleich ist eine Zusatzleistung und darf den Sendeweg nie beruehren.
    """
    try:
        roh = pfad.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        lesung.abgelehnt.append(f"{pfad.name}: cannot read ({exc})")
        return

    zeilen = roh.splitlines()
    kopf_index = next((i for i, z in enumerate(zeilen) if z.strip()), None)
    if kopf_index is None:
        lesung.abgelehnt.append(f"{pfad.name}: empty")
        return

    trenn = _trennzeichen(zeilen[kopf_index])
    leser = csv.reader(zeilen[kopf_index:], delimiter=trenn, quoting=csv.QUOTE_NONE)
    try:
        kopf = next(leser)
    except (StopIteration, csv.Error) as exc:
        lesung.abgelehnt.append(f"{pfad.name}: unreadable header ({exc})")
        return

    spalte = {name.strip(): i for i, name in enumerate(kopf)}
    fehlend = [s for s in PFLICHTSPALTEN if s not in spalte]
    if fehlend:
        # Nicht halb lesen. Eine Datei ohne `Order Ref.` erzeugte lauter
        # fremde Zeilen und saehe aus wie ein Konto ohne Modellhandel.
        lesung.abgelehnt.append(
            f"{pfad.name}: missing column(s) {', '.join(fehlend)}"
        )
        return

    breite = len(kopf)
    lesung.gelesene_dateien += 1

    for nummer, felder in enumerate(leser, start=kopf_index + 2):
        if not felder or not any(f.strip() for f in felder):
            continue
        if len(felder) != breite:
            # Der haeufigste echte Fall ist die letzte Zeile einer Datei, in
            # die die TWS gerade schreibt. Der teuerste waere ein Trennzeichen
            # im Kommentar des Nutzers — dieselbe Pruefung faengt beides.
            lesung.quarantaene.append(
                f"{pfad.name}:{nummer}: {len(felder)} fields, expected {breite}"
            )
            continue

        # Einmal aufloesen statt je Zugriff. Eine Funktion an dieser Stelle
        # haette die Schleifenvariable eingefangen — ein Fehler, der erst bei
        # der zweiten Zeile auffaellt.
        werte = {name: felder[i].strip() for name, i in spalte.items() if i < len(felder)}

        if werte.get(SPALTE_KONTO, "") != konto:
            lesung.fremdes_konto += 1
            continue

        vermerk = werte.get(SPALTE_VERMERK, "")
        if dispatch_id_from_order_ref(vermerk) is None:
            # Von Hand gestellt, oder von einem fremden Werkzeug. Gezaehlt,
            # damit sichtbar ist, dass hier etwas liegt — gebucht wird es in
            # T1-208.
            lesung.fremde += 1
            continue

        kennung = werte.get(SPALTE_KENNUNG, "")
        menge = _zahl(werte.get(SPALTE_MENGE, ""))
        wann = _zeitpunkt(werte.get(SPALTE_TAG, ""), werte.get(SPALTE_ZEIT, ""))
        if not kennung or menge is None or menge <= 0 or wann is None:
            lesung.quarantaene.append(
                f"{pfad.name}:{nummer}: unusable id/quantity/timestamp"
            )
            continue

        gebuehr = _zahl(werte.get(SPALTE_GEBUEHR, ""))
        lesung.fuellungen.append(
            ArchivFuellung(
                execution=ArchivAusfuehrung(
                    execId=kennung,
                    orderRef=vermerk,
                    shares=menge,
                    price=_zahl(werte.get(SPALTE_KURS, "")),
                    time=wann,
                    acctNumber=werte.get(SPALTE_KONTO, ""),
                    side=werte.get(SPALTE_RICHTUNG, ""),
                    symbol=werte.get(SPALTE_SYMBOL, ""),
                ),
                commissionReport=(
                    ArchivGebuehr(execId=kennung, commission=gebuehr)
                    if gebuehr is not None
                    else None
                ),
            )
        )

        tag = werte.get(SPALTE_TAG, "")
        if tag and (lesung.neuester_tag is None or tag > lesung.neuester_tag):
            lesung.neuester_tag = tag


def lies_archiv(
    verzeichnis: Path | str,
    konto: str,
    *,
    seit_tag: str | None = None,
) -> Lesung:
    """Das Archiv ab `seit_tag` lesen.

    `konto` ist Pflicht und darf nicht leer sein. Ohne scharfes Konto wird
    nicht gelesen — auf einer Maschine koennen Papier- und Echtkonto denselben
    Ordner beschreiben, und eine Fuellung dem falschen Buch zuzuschlagen waere
    genau der Fehler, gegen den dieser Vorgang gebaut ist.
    """
    lesung = Lesung()
    if not konto:
        return lesung

    basis = Path(verzeichnis)
    for tag, pfad in dateien(basis, seit_tag=seit_tag):
        vorher = lesung.gelesene_dateien
        lies_datei(pfad, konto, lesung=lesung)
        if lesung.gelesene_dateien == vorher:
            # Abgelehnt oder unlesbar. Die Marke darf daran NICHT vorbeiziehen:
            # sonst ist der Tag endgueltig weg, sobald der Kunde seine
            # Spaltenauswahl repariert. Dasselbe gilt fuer eine Datei, die
            # gerade geschrieben wurde und deren Kopfzeile noch fehlte.
            continue
        if lesung.neuester_dateitag is None or tag > lesung.neuester_dateitag:
            lesung.neuester_dateitag = tag
    return lesung


# ── Taugt das Verzeichnis ueberhaupt? ────────────────────────────────────────


def pruefe(verzeichnis: Path | str, *, heute: str | None = None) -> Bereitschaft:
    """Die Bereitschaftspruefung fuer Protokoll und Cockpit.

    Sie benennt, WAS fehlt. „Export not found" waere die Sorte Warnung, nach
    der ein Nutzer glaubt, geschuetzt zu sein, waehrend er es nicht ist.
    """
    if not str(verzeichnis).strip():
        return Bereitschaft(
            "not_configured",
            "TWS trade reports: TWS_EXPORT_DIR is not set in bridge.env. "
            "Without it a fill that happens while the Bridge is off cannot be "
            "recovered.",
        )

    basis = Path(verzeichnis)
    if not basis.is_dir():
        return Bereitschaft(
            "no_dir",
            f"TWS trade reports: {basis} does not exist. In TWS open "
            f"Global Configuration - Export Reports and set this folder, or "
            f"correct TWS_EXPORT_DIR in bridge.env.",
        )

    try:
        eintraege = [p for p in basis.iterdir() if p.is_file() and p.suffix.lower() == ".csv"]
    except OSError as exc:
        return Bereitschaft(
            "unreadable",
            f"TWS trade reports: cannot read {basis} ({exc}). Fix the read "
            f"permissions for this folder.",
        )

    if not eintraege:
        # T1-206 — dieser Zweig hat behauptet, was er nicht wissen kann.
        #
        # Hier stand: „In TWS open Global Configuration - Export Reports and
        # switch on 'Export trade reports periodically'." Das ist eine Aussage
        # ueber eine Einstellung in einem fremden Programm, und die Bridge
        # sieht sie nicht. Sie sieht einen leeren Ordner.
        #
        # Gemeldet vom Owner am 2026-09-24, beim ersten Lauf auf einer frisch
        # eingerichteten Maschine: Schalter an, Intervall 1, Dateiname leer,
        # alles richtig — und die Bridge sagte ihm, er solle einschalten, was
        # eingeschaltet war. Eine Anweisung, die man gerade befolgt hat, ist
        # die schnellste Art, die naechste nicht mehr ernst zu nehmen.
        #
        # Ein leerer Ordner hat zwei Lesarten, und die harmlose ist direkt nach
        # der Einrichtung die wahrscheinlichere: die TWS exportiert
        # Handelsberichte, und ohne Handel gibt es nichts zu exportieren. Die
        # teure Lesart — die TWS schreibt woanders hin — wird erst dann
        # wahrscheinlich, wenn an diesem Tag etwas gefuellt wurde.
        #
        # Beide stehen jetzt da, die harmlose zuerst, und keine als Befehl.
        return Bereitschaft(
            "no_file",
            f"TWS trade reports: {basis} exists and is empty. If nothing has "
            f"filled since you switched the export on, that is expected - TWS "
            f"writes a report once there is a trade to report. If something "
            f"did fill today, then TWS is writing somewhere else: compare this "
            f"path with the one in Global Configuration - Export Reports, "
            f"character by character.",
        )

    # Die Falle aus dem Dialog: ein eingetragener Dateiname laesst die TWS in
    # jedem Intervall dieselbe Datei schreiben. Der Inhalt ist dann der zuletzt
    # geschriebene Tag, und mit dem naechsten Export ist der vorige weg —
    # dieselbe Sackgasse wie `reqExecutions`, nur mit mehr Schritten.
    if not any(_tag_aus_name(p) for p in eintraege):
        return Bereitschaft(
            "fixed_name",
            f"TWS trade reports: the files in {basis} carry no date in their "
            f"name, so TWS keeps overwriting one file and only the most recent "
            f"day survives. In TWS open Global Configuration - Export Reports "
            f"and clear the field 'Export filename' so TWS uses its dated "
            f"default name.",
        )

    juengster = max(_tag_der_datei(p) for p in eintraege)
    heute = heute or datetime.now().strftime("%Y%m%d")  # noqa: DTZ005 - Ortstag
    if juengster < _tage_zurueck(heute, 4):
        return Bereitschaft(
            "stale",
            f"TWS trade reports: the newest file in {basis} is from {juengster}. "
            f"Either TWS has not been running, or the periodic export is off. "
            f"Fills that happen while the Bridge is off cannot be recovered "
            f"from an archive that is not being written.",
        )

    return Bereitschaft("ok", f"TWS trade reports: reading {basis}.")


# ── T1-206 — die Uebergabe an die TWS nachpruefbar machen ────────────────────

CHECK_FLAG = "--check-reports"


def check_requested(argv: list[str]) -> bool:
    """Steht `--check-reports` auf der Befehlszeile?

    Als reine Funktion, damit die Zusicherung sie ohne Vorgang pruefen kann —
    wie `pair_requested`, `probe_requested` und `console_requested`.
    """
    return CHECK_FLAG in argv


def check_bericht(verzeichnis: Path | str) -> list[str]:
    r"""Der Block, den `--check-reports` ausgibt. Zeile fuer Zeile.

    ## Woher das kommt

    Owner-Befund 2026-09-24: der eine Handgriff, den wir dem Kunden nicht
    abnehmen koennen, ist die **Uebergabe des Verzeichnisses an die TWS**. Wir
    legen den Ordner an, die Bridge liest ihn — aber eintragen muss ihn ein
    Mensch, in einem fremden Dialog, auf der anderen Seite des Bildschirms.

    Auf Windows ist das erprobt und kurz: `C:\IBExport` steht in der Anleitung
    und wird abgetippt. Auf Linux ist der Pfad laenger, traegt einen
    Bindestrich, und der Kunde ist beim Eintragen nicht einmal als der Nutzer
    angemeldet, dem er gehoert. Ein Tippfehler faellt dabei **nicht** auf: die
    TWS legt den Ordner an, den sie bekommt, exportiert fleissig dorthin, und
    alles sieht richtig aus. Bemerkt wird es an einer Fuellung, die nach einer
    Auszeit fehlt — also genau dann, wenn es zu spaet ist.

    ## Warum ein eigener Schalter und nicht nur das Protokoll

    Die Pruefung `pruefe()` gibt es laengst und sie laeuft beim Start. Ihr
    Befund landet im Protokoll und im Cockpit. Nur: beim Einrichten hat der
    Kunde das Cockpit nicht offen (auf einem Server gibt es keins), und das
    Protokoll liest er nicht mit.

    Der Schalter aendert nichts an der Pruefung — er holt sie an die Stelle,
    an der die Frage entsteht. Der Kunde traegt den Pfad in die TWS ein,
    wechselt ins Terminal, tippt einen Befehl und **weiss es**, statt es zu
    glauben.

    Bewusst ohne IBKR-Verbindung und ohne Plattform: die Frage ist „liegt da,
    was ich erwarte", und die laesst sich an der Platte beantworten. Ein
    Pruefbefehl, der eine laufende TWS braucht, waere beim Einrichten
    ausgerechnet dann nicht verfuegbar, wenn er gebraucht wird.
    """
    basis = str(verzeichnis or "").strip()
    zeilen = [
        "",
        "  TWS trade reports",
        "  " + "-" * 64,
        f"  Bridge reads:  {basis or '(not set)'}",
        "",
    ]

    bereit = pruefe(basis)
    zeilen.append(f"  Result: {bereit.zustand}")
    zeilen.append(f"  {bereit.text}")

    if bereit.ok:
        try:
            dateien_hier = sorted(
                p.name for p in Path(basis).iterdir()
                if p.is_file() and p.suffix.lower() == ".csv"
            )
        except OSError:
            dateien_hier = []
        zeilen.append("")
        zeilen.append(f"  {len(dateien_hier)} report file(s) found.")
        for name in dateien_hier[-3:]:
            zeilen.append(f"    {name}")
    else:
        # Die drei Einstellungen, an denen es haengt — in der Reihenfolge des
        # Dialogs. Zwei davon sind Fallen, die sich nicht von selbst zeigen:
        # ein eingetragener Dateiname laesst die TWS dieselbe Datei ueberschreiben,
        # und ein Komma als Trennzeichen zerbricht Zeilen, weil IBKR nicht quotet.
        zeilen.extend([
            "",
            "  In TWS: Global Configuration - Export Reports",
            f"    Directory        {basis or '(set TWS_EXPORT_DIR in bridge.env)'}",
            "    Export filename  leave EMPTY",
            "    Field separator  semicolon",
            "    Export trade reports periodically: on",
            "",
            "  TWS and the Bridge must run under the same user.",
        ])

    zeilen.append("")
    return zeilen


def _tage_zurueck(tag: str, tage: int) -> str:
    """`YYYYMMDD` minus n Kalendertage.

    Vier Tage decken ein langes Wochenende ab, ohne einen Feiertag zu einer
    Falschmeldung zu machen. Ein Boersenkalender waere hier zu viel Maschinerie
    fuer eine Warnung.
    """
    from datetime import timedelta

    try:
        d = datetime.strptime(tag, "%Y%m%d") - timedelta(days=tage)  # noqa: DTZ007
    except ValueError:
        return "00000000"
    return d.strftime("%Y%m%d")
