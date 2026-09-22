"""T1-207 — was die TWS auf die Platte schreibt, kommt in die Buecher.

## Der gemessene Fall

Konto …2572, 15.09.: zwei Kaeufe von je 21 MU in der Schlussauktion, die Bridge
25 Minuten vorher aus. Nachfragen geht nicht — `reqExecutions` verlaesst den
laufenden Tag auch mit Zeitfilter nicht (am 22.09. mit `probe.py` gemessen:
fuenf Fuellungen vom 18.09. lagen im Fenster, null kamen zurueck).

Die Kopfzeile und die fuenf Datenzeilen weiter unten sind KEINE erfundenen
Beispiele: sie stammen aus einer echten Exportdatei des Papierkontos DUN950877
vom 18.09.2026, 44 Spalten. Daran haengen drei Befunde, die den Entwurf
bestimmt haben — das Etikett im Vermerk ist unterschiedlich gekuerzt, die
Zahlen tragen einen Punkt als Dezimaltrenner, und in der ganzen Datei steht
kein einziges Anfuehrungszeichen.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from ordertune_bridge_ibkr import trade_reports
from ordertune_bridge_ibkr.order_reconcile import (
    UnresolvedDispatch,
    fills_by_dispatch,
    reconcile_open_dispatches,
)
from ordertune_bridge_ibkr.trade_report_store import (
    SICHERHEITSABSTAND_TAGE,
    TradeReportStore,
)

KONTO = "DUN950877"

# Die Kopfzeile der echten Datei, ungekuerzt. Die Reihenfolge ist Absicht: der
# Leser darf sich auf keine Position verlassen, und diese Kopfzeile ist der
# Beleg, dass die Spalten, auf die es ankommt, weit hinten stehen.
KOPF = (
    "Drill Down,Security Type,Last Trading Day,Strike,Put/Call,Currency,"
    "Fin Instrument,Action,Action Sub-Type,Quantity,Comb.,Symbol,Price,Time,"
    "Date,Exch.,Vwap Time,Comment,Account,Order Ref.,ID,Clearing,Clearing Acct,"
    "Yield,Tx Yield,Commission,Realized P&L,Economic Value Rule,Currency Price,"
    "Vol. Link,Savings,Key,Soft Dollars,Destination,Order ID,Exch. Exec. ID,"
    "Exch. Order ID,Ticket ID,Executing Broker Commission,More Info,"
    "Trading Class,Cash Qty,External User ID,Undr. Symbol,"
)

# Drei Zeilen derselben Strategie, drei verschieden gekuerzte Etiketten.
ZEILEN = [
    ",STK,,,,USD,MRVL,BOT,,53,,MRVL,244.21,19:59:00,20260918,NASDAQ,,,DUN950877,"
    "ot-MRVL-7728-Momentum_Power-25189a17-8537-4f3a-ab88-8ecd807fb118,"
    "00025b45.6aafdd10.01.01,,,,,1.0002,,,,,,,,,"
    "02092032.0001fec3.6aacbf0f.0001,346016200B,"
    "02092032.00019112.79994bf2[2],,,,,,,MRVL,",
    ",STK,,,,USD,MU,BOT,,14,,MU,1015.01,19:59:00,20260918,IBKRATS,,,DUN950877,"
    "ot-MU-7451-Momentum_Powerho-db9d141a-9abe-41ab-a0e7-4fc1ac5cead1,"
    "0000dc8f.6ba88092.01.01,,,,,1.00004,,,,,,,,,"
    "02092032.0001fec3.6aacbf10.0001,345898814B,"
    "02092032.00019114.71b53290[2],,,,,,,MU,",
    ",STK,,,,USD,STX,BOT,,16,,STX,858.98,19:59:00,20260918,IBKRATS,,,DUN950877,"
    "ot-STX-8135-Momentum_Powerh-ab33f71b-2c20-4f0f-902c-6e9316cdd7ed,"
    "0000dc8f.6ba88094.01.01,,,,,1.00005,,,,,,,,,"
    "02092032.0001fec3.6aacbf12.0001,345898817B,"
    "02092032.00019114.71b53297[2],,,,,,,STX,",
    ",STK,,,,USD,CRWD,BOT,,37,,CRWD,237.72,19:59:00,20260918,IBKRATS,,,DUN950877,"
    "ot-CRWD-10690-Rotator-a3745a60-c608-4564-af70-ed2fa140175f,"
    "0000dc8f.6ba88096.01.01,,,,,1.0001,,,,,,,,,"
    "02092032.0001fec3.6aacbf11.0001,345898819B,"
    "02092032.00019114.71b53294[2],,,,,,,CRWD,",
    ",STK,,,,USD,AMD,BOT,,18,,AMD,559.46,19:59:00,20260918,ARCA,,,DUN950877,"
    "ot-AMD-9249-Rotator-1e65ae0a-1849-4cff-a725-5648747f6471,"
    "0000e0d5.6aadb0fd.01.01,,,,,1.00005,,,,,,,,,"
    "02092032.0001fec3.6aacbf13.0001,345860744B,"
    "02092032.0001910d.7a56880b[2],,,,,,,AMD,",
]

MU_DISPATCH = "db9d141a-9abe-41ab-a0e7-4fc1ac5cead1"
MU_EXEC_ID = "0000dc8f.6ba88092.01.01"


def _schreibe(
    ordner: Path,
    name: str = "trades.20260918.csv",
    *,
    kopf: str = KOPF,
    zeilen: list[str] | None = None,
) -> Path:
    pfad = ordner / name
    pfad.write_text(
        "\n".join([kopf, *(ZEILEN if zeilen is None else zeilen)]) + "\n",
        encoding="utf-8",
    )
    return pfad


def _als_semikolon(text: str) -> str:
    return text.replace(",", ";")


# ── Der Durchstich ───────────────────────────────────────────────────────────


def test_echte_datei_ergibt_fuenf_fuellungen(tmp_path: Path) -> None:
    """Die Datei vom 18.09., unveraendert: fuenf Zeilen, fuenf Zuordnungen."""
    _schreibe(tmp_path)
    lesung = trade_reports.lies_archiv(tmp_path, KONTO)

    assert len(lesung.fuellungen) == 5
    assert lesung.fremde == 0
    assert lesung.quarantaene == []
    assert lesung.abgelehnt == []
    assert lesung.gelesene_dateien == 1


def test_die_uuid_zaehlt_nicht_das_etikett(tmp_path: Path) -> None:
    """Drei Zeilen derselben Strategie tragen drei verschiedene Etiketten.

    `Momentum_Power`, `Momentum_Powerho`, `Momentum_Powerh` — die Plattform
    kuerzt je nach Laenge von Symbol und Nummer. Wer daraus die Strategie
    liest, baut die naechste Fehlzuordnung.
    """
    _schreibe(tmp_path)
    nach_dispatch = fills_by_dispatch(trade_reports.lies_archiv(tmp_path, KONTO).fuellungen)

    assert MU_DISPATCH in nach_dispatch
    assert nach_dispatch[MU_DISPATCH].qty == 14
    assert nach_dispatch[MU_DISPATCH].price == 1015.01
    # Fuenf verschiedene Auftraege, nicht drei plus zwei zusammengeworfene.
    assert len(nach_dispatch) == 5


def test_gebuehr_und_dezimalpunkt(tmp_path: Path) -> None:
    """Die Zahlen tragen Punkte, trotz deutscher Oberflaeche."""
    _schreibe(tmp_path)
    nach_dispatch = fills_by_dispatch(trade_reports.lies_archiv(tmp_path, KONTO).fuellungen)
    assert nach_dispatch[MU_DISPATCH].commission == 1.00004


# ── Trennzeichen ─────────────────────────────────────────────────────────────


def test_semikolon_wird_an_der_kopfzeile_erkannt(tmp_path: Path) -> None:
    """Der Dialog bietet Komma und Semikolon. Beide muessen gelesen werden."""
    _schreibe(
        tmp_path,
        kopf=_als_semikolon(KOPF),
        zeilen=[_als_semikolon(z) for z in ZEILEN],
    )
    assert len(trade_reports.lies_archiv(tmp_path, KONTO).fuellungen) == 5


def test_anfuehrungszeichen_zieht_keine_felder_zusammen(tmp_path: Path) -> None:
    """IBKR quotet nicht — also darf ein `"` im Kommentar nichts anfangen.

    Ohne `QUOTE_NONE` frisst der Leser ab dem Anfuehrungszeichen alles bis zum
    naechsten, die Feldzahl kippt, und die Zeile waere verloren statt gelesen.
    """
    mit_zitat = ZEILEN[0].replace(",,,DUN950877,", ',a "note" ,,DUN950877,', 1)
    _schreibe(tmp_path, zeilen=[mit_zitat])
    lesung = trade_reports.lies_archiv(tmp_path, KONTO)
    assert len(lesung.fuellungen) == 1
    assert lesung.quarantaene == []


# ── Die Riegel ───────────────────────────────────────────────────────────────


def test_fremdes_konto_wird_nicht_gelesen(tmp_path: Path) -> None:
    """Papier- und Echtkonto koennen denselben Ordner beschreiben."""
    _schreibe(tmp_path)
    lesung = trade_reports.lies_archiv(tmp_path, "U1234567")
    assert lesung.fuellungen == []
    assert lesung.fremdes_konto == 5


def test_ohne_konto_wird_gar_nicht_gelesen(tmp_path: Path) -> None:
    """Ohne scharfes Konto ist jede Buchung geraten."""
    _schreibe(tmp_path)
    assert trade_reports.lies_archiv(tmp_path, "").fuellungen == []


def test_fremde_zeile_wird_gezaehlt_nicht_gebucht(tmp_path: Path) -> None:
    """Von Hand in der TWS gestellt — das bucht erst T1-208."""
    ohne_vermerk = ZEILEN[0].replace(
        "ot-MRVL-7728-Momentum_Power-25189a17-8537-4f3a-ab88-8ecd807fb118", ""
    )
    _schreibe(tmp_path, zeilen=[ohne_vermerk])
    lesung = trade_reports.lies_archiv(tmp_path, KONTO)
    assert lesung.fuellungen == []
    assert lesung.fremde == 1


def test_fremdes_praefix_bleibt_fremd(tmp_path: Path) -> None:
    """Ein anderes Werkzeug am selben Konto gehoert uns nicht."""
    fremd = ZEILEN[0].replace("ot-MRVL-7728", "xy-MRVL-7728")
    _schreibe(tmp_path, zeilen=[fremd])
    lesung = trade_reports.lies_archiv(tmp_path, KONTO)
    assert lesung.fuellungen == []
    assert lesung.fremde == 1


def test_verschobene_zeile_kommt_in_quarantaene(tmp_path: Path) -> None:
    """Ein Trennzeichen im Kommentar verschiebt alles dahinter.

    Die verschobene Zeile saehe aus wie eine gueltige — das ist der
    Unterschied zwischen einem Datenverlust, den man sieht, und einer
    Falschbuchung, die man nicht sieht.
    """
    verschoben = ZEILEN[0].replace(",,,DUN950877,", ",a,note,,DUN950877,", 1)
    _schreibe(tmp_path, zeilen=[verschoben])
    lesung = trade_reports.lies_archiv(tmp_path, KONTO)

    assert lesung.fuellungen == []
    assert len(lesung.quarantaene) == 1
    # Ort und Grund, nicht nur „eine Zeile war kaputt".
    assert "trades.20260918.csv:2" in lesung.quarantaene[0]
    assert "expected" in lesung.quarantaene[0]


def test_abgeschnittene_letzte_zeile_verwirft_nicht_die_datei(tmp_path: Path) -> None:
    """Bei Intervall 1 liest die Bridge, waehrend die TWS schreibt."""
    pfad = tmp_path / "trades.20260918.csv"
    pfad.write_text(
        "\n".join([KOPF, *ZEILEN]) + "\n" + ",STK,,,,USD,NVDA,BOT,,10,,NV",
        encoding="utf-8",
    )
    lesung = trade_reports.lies_archiv(tmp_path, KONTO)
    assert len(lesung.fuellungen) == 5
    assert len(lesung.quarantaene) == 1


def test_fehlende_pflichtspalte_lehnt_die_datei_ab(tmp_path: Path) -> None:
    """Nicht halb lesen. Eine Datei ohne `Order Ref.` saehe aus wie ein Konto
    ohne Modellhandel — und daraus wuerde „nichts zu heilen"."""
    _schreibe(tmp_path, kopf=KOPF.replace("Order Ref.,", "Irgendwas,"))
    lesung = trade_reports.lies_archiv(tmp_path, KONTO)

    assert lesung.fuellungen == []
    assert len(lesung.abgelehnt) == 1
    assert "Order Ref." in lesung.abgelehnt[0]


def test_unlesbare_menge_kommt_in_quarantaene(tmp_path: Path) -> None:
    """Streng statt klug: eine Zahl, die keine ist, wird nicht umgedeutet."""
    kaputt = ZEILEN[0].replace(",BOT,,53,,MRVL,244.21,", ",BOT,,n/a,,MRVL,244.21,")
    _schreibe(tmp_path, zeilen=[kaputt])
    lesung = trade_reports.lies_archiv(tmp_path, KONTO)
    assert lesung.fuellungen == []
    assert len(lesung.quarantaene) == 1


# ── Zeit ─────────────────────────────────────────────────────────────────────


def test_zeit_wird_als_ortszeit_gelesen_und_nach_utc_gerechnet(tmp_path: Path) -> None:
    """Im Dialog ist „lokale Zeitzone" gesetzt; die Bridge laeuft auf derselben
    Maschine. Also ist die Ortszeit der Datei unsere Ortszeit."""
    _schreibe(tmp_path)
    lesung = trade_reports.lies_archiv(tmp_path, KONTO)
    erwartet = datetime(2026, 9, 18, 19, 59, 0).astimezone(timezone.utc)

    wann = {f.execution.execId: f.execution.time for f in lesung.fuellungen}
    assert wann[MU_EXEC_ID] == erwartet
    assert wann[MU_EXEC_ID].tzinfo is not None


def test_der_abgleich_meldet_den_gemessenen_zeitpunkt(tmp_path: Path) -> None:
    """Der Kalendertag einer Buchung haengt daran.

    Vor T1-207 meldete der Abgleich `datetime.now()`. Bei einer Fuellung aus dem
    laufenden Tag waren das Sekunden daneben; bei einer aus dem Archiv
    nachgetragenen sind es Tage.
    """
    _schreibe(tmp_path)
    nach_dispatch = fills_by_dispatch(trade_reports.lies_archiv(tmp_path, KONTO).fuellungen)
    verbunden = datetime(2026, 9, 22, 10, 0, tzinfo=timezone.utc)

    aktionen = reconcile_open_dispatches(
        unresolved=[
            UnresolvedDispatch(
                dispatch_id=MU_DISPATCH,
                symbol="MU",
                submitted_at=verbunden - timedelta(days=4),
            )
        ],
        open_by_ref={},
        completed_by_ref={},
        session_connected_at=verbunden,
        fills_by_ref=nach_dispatch,
    )

    assert len(aktionen) == 1
    assert aktionen[0].status == "filled"
    assert aktionen[0].fill_qty == 14
    assert aktionen[0].filled_at is not None
    # Der 18., nicht der 22.
    assert aktionen[0].filled_at.astimezone(timezone.utc).date().isoformat() != "2026-09-22"


# ── Entdopplung ──────────────────────────────────────────────────────────────


def test_dieselbe_ausfuehrung_zaehlt_einmal(tmp_path: Path) -> None:
    """Der Live-Bericht und die Datei tragen dieselbe Kennung.

    Ohne Entdopplung stuende die doppelte Menge im Buch — und ein spaeterer
    Ausstieg verkaufte zu viel.
    """
    _schreibe(tmp_path)
    aus_datei = trade_reports.lies_archiv(tmp_path, KONTO).fuellungen
    live = SimpleNamespace(
        execution=SimpleNamespace(
            execId=MU_EXEC_ID,
            orderRef=f"ot-MU-7451-Momentum_Powerho-{MU_DISPATCH}",
            shares=14,
            price=1015.01,
            time=datetime(2026, 9, 18, 17, 59, tzinfo=timezone.utc),
        ),
        commissionReport=SimpleNamespace(execId=MU_EXEC_ID, commission=1.00004),
    )

    nach_dispatch = fills_by_dispatch([live, *aus_datei])
    assert nach_dispatch[MU_DISPATCH].qty == 14


def test_zweimal_lesen_aendert_nichts(tmp_path: Path) -> None:
    """Derselbe Ordner zweimal gelesen ergibt dieselbe Menge, nicht die doppelte."""
    _schreibe(tmp_path)
    erst = fills_by_dispatch(trade_reports.lies_archiv(tmp_path, KONTO).fuellungen)
    beide = fills_by_dispatch(
        trade_reports.lies_archiv(tmp_path, KONTO).fuellungen
        + trade_reports.lies_archiv(tmp_path, KONTO).fuellungen
    )
    assert beide[MU_DISPATCH].qty == erst[MU_DISPATCH].qty


# ── Wasserstandsmarke ────────────────────────────────────────────────────────


def test_erstlauf_greift_nicht_ins_ganze_archiv(tmp_path: Path) -> None:
    """Ein Kunde kann zwei Jahre liegen haben. Das ist keine Heilung mehr."""
    store = TradeReportStore(tmp_path, erstlauf_tage=7)
    seit = store.seit_tag(heute=datetime(2026, 9, 22))
    assert store.erstlauf
    assert seit == "20260915"


def test_marke_ueberlebt_den_neustart(tmp_path: Path) -> None:
    """Der Neustart ist der Normalfall — taeglich gegen 05:00."""
    TradeReportStore(tmp_path).vermerken("20260918")
    wieder = TradeReportStore(tmp_path)

    assert not wieder.erstlauf
    # Mit Sicherheitsabstand: der Tag einer Datei wird geraten, nicht gewusst.
    assert wieder.seit_tag() == "20260916"
    assert SICHERHEITSABSTAND_TAGE == 2


def test_marke_geht_nur_vorwaerts(tmp_path: Path) -> None:
    """Eine Datei mit zu alt geratenem Tag darf die Lesemenge nicht aufblaehen."""
    store = TradeReportStore(tmp_path)
    store.vermerken("20260918")
    store.vermerken("20260901")
    assert store.seit_tag() == "20260916"


def test_leere_marke_schreibt_nichts(tmp_path: Path) -> None:
    """Ein Lauf ohne Dateien darf die Marke nicht zuruecksetzen."""
    store = TradeReportStore(tmp_path)
    store.vermerken("20260918")
    store.vermerken(None)
    assert store.seit_tag() == "20260916"


def test_dateiauswahl_respektiert_die_marke(tmp_path: Path) -> None:
    _schreibe(tmp_path, "trades.20260901.csv")
    _schreibe(tmp_path, "trades.20260918.csv")

    alle = trade_reports.dateien(tmp_path)
    ab = trade_reports.dateien(tmp_path, seit_tag="20260916")

    assert len(alle) == 2
    assert [p.name for _t, p in ab] == ["trades.20260918.csv"]


# ── Bereitschaft ─────────────────────────────────────────────────────────────


def test_fehlendes_verzeichnis_wird_benannt(tmp_path: Path) -> None:
    bereit = trade_reports.pruefe(tmp_path / "gibtsnicht")
    assert bereit.zustand == "no_dir"
    assert not bereit.ok
    assert "does not exist" in bereit.text


def test_nicht_eingerichtet_ist_ein_eigener_zustand() -> None:
    bereit = trade_reports.pruefe("")
    assert bereit.zustand == "not_configured"
    assert "TWS_EXPORT_DIR" in bereit.text


def test_leerer_ordner_sagt_was_fehlt(tmp_path: Path) -> None:
    bereit = trade_reports.pruefe(tmp_path)
    assert bereit.zustand == "no_file"
    assert "Export Reports" in bereit.text


def test_fester_dateiname_wird_erkannt(tmp_path: Path) -> None:
    """Die Falle aus dem Dialog, und der teuerste Einstellfehler ueberhaupt.

    Belegt: `IBTrades7497.csv` enthielt am 22.09. die Fuellungen vom 18.09. Mit
    dem naechsten Export waeren sie weg gewesen.
    """
    _schreibe(tmp_path, "IBTrades7497.csv")
    bereit = trade_reports.pruefe(tmp_path, heute="20260918")

    assert bereit.zustand == "fixed_name"
    assert "Export filename" in bereit.text


def test_altes_archiv_wird_benannt(tmp_path: Path) -> None:
    _schreibe(tmp_path, "trades.20260901.csv")
    bereit = trade_reports.pruefe(tmp_path, heute="20260922")
    assert bereit.zustand == "stale"
    assert "20260901" in bereit.text


def test_gutes_verzeichnis_ist_ok(tmp_path: Path) -> None:
    _schreibe(tmp_path, "trades.20260918.csv")
    bereit = trade_reports.pruefe(tmp_path, heute="20260918")
    assert bereit.ok


# ── Die Verdrahtung ──────────────────────────────────────────────────────────


def test_archiv_fuellungen_zieht_die_marke_nach(tmp_path: Path) -> None:
    """Der Weg von der Datei bis zur Ablage nach Dispatch, in einem Stueck."""
    from ordertune_bridge_ibkr.main import _archiv_fuellungen

    ordner = tmp_path / "export"
    ordner.mkdir()
    _schreibe(ordner)
    store = TradeReportStore(tmp_path / "state")

    fuellungen = _archiv_fuellungen(str(ordner), store, KONTO)

    assert len(fuellungen) == 5
    assert not store.erstlauf
    assert store.seit_tag() == "20260916"


def test_archiv_ohne_konto_liest_nicht(tmp_path: Path) -> None:
    """Der Riegel sitzt auch im Aufrufer, nicht nur im Leser."""
    from ordertune_bridge_ibkr.main import _archiv_fuellungen

    ordner = tmp_path / "export"
    ordner.mkdir()
    _schreibe(ordner)
    store = TradeReportStore(tmp_path / "state")

    assert _archiv_fuellungen(str(ordner), store, None) == []
    assert _archiv_fuellungen(str(ordner), store, "") == []
    # Ohne Konto wurde nichts gelesen, also darf auch die Marke nicht wandern.
    assert store.erstlauf


def test_archiv_ohne_verzeichnis_liest_nicht(tmp_path: Path) -> None:
    from ordertune_bridge_ibkr.main import _archiv_fuellungen

    store = TradeReportStore(tmp_path / "state")
    assert _archiv_fuellungen("", store, KONTO) == []
    assert _archiv_fuellungen(None, store, KONTO) == []


def test_unbrauchbares_setup_warnt_und_steht_im_cockpit(tmp_path: Path, caplog) -> None:
    """Die Warnung muss sagen, WAS fehlt — sonst haelt ein Kunde sich fuer
    geschuetzt, waehrend er es nicht ist."""
    import logging

    from ordertune_bridge_ibkr.main import _pruefe_export

    class _Store:
        def __init__(self) -> None:
            self.changes: dict[str, object] = {}

        def update(self, **kw: object) -> None:
            self.changes.update(kw)

    cockpit = SimpleNamespace(store=_Store())
    with caplog.at_level(logging.WARNING):
        bereit = _pruefe_export(str(tmp_path / "gibtsnicht"), cockpit)

    assert bereit.zustand == "no_dir"
    assert cockpit.store.changes["trade_export"] == "no_dir"
    assert "does not exist" in str(cockpit.store.changes["trade_export_detail"])
    assert any("does not exist" in r.getMessage() for r in caplog.records)


def test_gutes_setup_meldet_ok_ins_cockpit(tmp_path: Path) -> None:
    from ordertune_bridge_ibkr.main import _pruefe_export

    _schreibe(tmp_path, f"trades.{datetime.now().strftime('%Y%m%d')}.csv")

    class _Store:
        def __init__(self) -> None:
            self.changes: dict[str, object] = {}

        def update(self, **kw: object) -> None:
            self.changes.update(kw)

    cockpit = SimpleNamespace(store=_Store())
    assert _pruefe_export(str(tmp_path), cockpit).ok
    assert cockpit.store.changes["trade_export"] == "ok"


# ── Befunde der Selbst-QA vom 2026-09-22 ─────────────────────────────────────


def test_nan_wird_nicht_gebucht(tmp_path: Path) -> None:
    """`float("nan")` gelingt, und `nan <= 0` ist falsch.

    Die Zeile rutschte damit durch jede Mengenpruefung und haette `nan` als
    Bestand ins Buch geschrieben, wo sie jede weitere Rechnung vergiftet.
    """
    kaputt = ZEILEN[0].replace(",BOT,,53,,MRVL,244.21,", ",BOT,,nan,,MRVL,244.21,")
    _schreibe(tmp_path, zeilen=[kaputt])
    lesung = trade_reports.lies_archiv(tmp_path, KONTO)

    assert lesung.fuellungen == []
    assert len(lesung.quarantaene) == 1


def test_unendlich_wird_nicht_gebucht(tmp_path: Path) -> None:
    """`inf` und `1e400` ebenfalls — dieselbe Falle, andere Schreibweise."""
    kaputt = ZEILEN[0].replace(",BOT,,53,,MRVL,244.21,", ",BOT,,inf,,MRVL,1e400,")
    _schreibe(tmp_path, zeilen=[kaputt])
    assert trade_reports.lies_archiv(tmp_path, KONTO).fuellungen == []


def test_marke_zieht_nicht_an_einer_abgelehnten_datei_vorbei(tmp_path: Path) -> None:
    """Sonst ist der Tag weg, sobald der Kunde seine Spaltenauswahl repariert."""
    _schreibe(tmp_path, kopf=KOPF.replace("Order Ref.,", "Weg,"))
    lesung = trade_reports.lies_archiv(tmp_path, KONTO)

    assert len(lesung.abgelehnt) == 1
    assert lesung.neuester_dateitag is None


def test_marke_zieht_an_gelesenen_dateien_weiter(tmp_path: Path) -> None:
    """Der Gegenbeweis: eine lesbare Datei bewegt die Marke sehr wohl."""
    _schreibe(tmp_path)
    assert trade_reports.lies_archiv(tmp_path, KONTO).neuester_dateitag == "20260918"


def test_kontoabweichung_wird_laut(tmp_path: Path, caplog) -> None:
    """Der stille Totalausfall.

    Passt die Kennung am Draht nicht zu der in der Datei, liest die Bridge
    jeden Tag brav ein Archiv, verwirft jede Zeile — und die
    Bereitschaftspruefung sagt trotzdem „ok".
    """
    import logging

    from ordertune_bridge_ibkr.main import _archiv_fuellungen

    ordner = tmp_path / "export"
    ordner.mkdir()
    _schreibe(ordner)
    store = TradeReportStore(tmp_path / "state")

    with caplog.at_level(logging.WARNING):
        assert _archiv_fuellungen(str(ordner), store, "DU1234567") == []

    meldungen = [r.getMessage() for r in caplog.records]
    assert any("none belong to account" in m for m in meldungen)
    # Maskiert. Eine Kontonummer gehoert nicht ins Protokoll.
    assert not any("DU1234567" in m for m in meldungen)


def test_erstlauf_deckt_das_fenster_der_plattform_ab() -> None:
    """Die Plattform fragt 14 Tage zurueck (`ABGLEICH_FENSTER_TAGE`).

    Ein engeres Fenster hier liesse genau die Tage liegen, nach denen drueben
    noch gefragt wird.
    """
    from ordertune_bridge_ibkr.trade_report_store import ERSTLAUF_TAGE

    assert ERSTLAUF_TAGE == 14


# ── Der Zeitzonen-Riegel ─────────────────────────────────────────────────────


def _live(exec_id: str, wann: datetime) -> SimpleNamespace:
    return SimpleNamespace(
        execution=SimpleNamespace(
            execId=exec_id,
            orderRef=f"ot-MU-7451-Momentum_Powerho-{MU_DISPATCH}",
            shares=14,
            price=1015.01,
            time=wann,
        ),
        commissionReport=SimpleNamespace(execId=exec_id, commission=1.00004),
    )


def test_zeitzone_stimmt_auf_einer_utc_maschine(tmp_path: Path, caplog) -> None:
    """Der gemessene Fall: der Server laeuft auf UTC+0.

    `19:59:00` in der Datei ist dann 19:59 UTC — 15:59 Eastern, eine Minute vor
    der Schlussauktion. Die Umrechnung ist auf dieser Maschine ein No-Op, und
    genau das muss der Riegel als „in Ordnung" lesen.
    """
    import logging

    from ordertune_bridge_ibkr.main import _pruefe_zeitzone

    _schreibe(tmp_path)
    archiv = trade_reports.lies_archiv(tmp_path, KONTO).fuellungen
    aus_datei = {f.execution.execId: f.execution.time for f in archiv}

    with caplog.at_level(logging.WARNING):
        versatz = _pruefe_zeitzone([_live(MU_EXEC_ID, aus_datei[MU_EXEC_ID])], archiv)

    assert versatz == 0.0
    assert not [r for r in caplog.records if "off by up to" in r.getMessage()]


def test_vergessener_haken_wird_gemessen(tmp_path: Path, caplog) -> None:
    """Der unsichtbare Fehler.

    Ohne den Haken schreibt die TWS UTC. Auf einer Maschine mit deutscher Zeit
    liegt jede nachgetragene Fuellung zwei Stunden daneben — und an der
    Tagesgrenze wird daraus ein falscher Kalendertag. Von aussen sieht eine
    Uhrzeit nie falsch aus; vergleichbar ist sie nur gegen den Live-Bericht.
    """
    import logging

    from ordertune_bridge_ibkr.main import _pruefe_zeitzone

    _schreibe(tmp_path)
    archiv = trade_reports.lies_archiv(tmp_path, KONTO).fuellungen
    aus_datei = {f.execution.execId: f.execution.time for f in archiv}
    echt = aus_datei[MU_EXEC_ID] - timedelta(hours=2)

    with caplog.at_level(logging.WARNING):
        versatz = _pruefe_zeitzone([_live(MU_EXEC_ID, echt)], archiv)

    assert versatz == 7200.0
    meldung = [r.getMessage() for r in caplog.records if "off by up to" in r.getMessage()]
    assert meldung and "120 minutes" in meldung[0]
    assert "local time zone" in meldung[0]


def test_ohne_gemeinsame_ausfuehrung_wird_nichts_behauptet(tmp_path: Path) -> None:
    """Kein Vergleichsstueck heisst keine Aussage — nicht „alles in Ordnung"."""
    from ordertune_bridge_ibkr.main import _pruefe_zeitzone

    _schreibe(tmp_path)
    archiv = trade_reports.lies_archiv(tmp_path, KONTO).fuellungen

    assert _pruefe_zeitzone([], archiv) is None
    assert _pruefe_zeitzone([_live("fremde.kennung.01.01", datetime.now(timezone.utc))], archiv) is None
