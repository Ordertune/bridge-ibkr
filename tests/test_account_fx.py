"""T1-252: der Kurs, mit dem aus einem EUR-Depotwert eine Stueckzahl wird.

## Woher diese Zusicherungen kommen

T1-85 hat 2026-08-13 einen Riegel gesetzt: ist die Kontowaehrung nicht USD,
traegt der Depotwert die Mengenrechnung nicht. Die Umrechnung wurde als
„Schritt 3, eigener Entwurf" vertagt, weil sie vier Festlegungen verlangt —
Kursquelle, Aktualitaet, Ausfallverhalten, Nachweis.

Die Messung am 2026-09-28 auf `DUT106306` hat drei davon erledigt: der Kurs
kommt in derselben Antwort wie der Depotwert. Was bleibt, ist die Richtung —
und die ist die gefaehrliche Haelfte. IBKR fuehrt seine Kurse gegen die
BASISWAEHRUNG des Kontos, nicht gegen USD. Bei einem EUR-Konto heisst
`0,8797124` also *1 USD = 0,8797124 EUR*, die Gegenrichtung zu der gebrauchten.

Haette der Entwurf sie geraten und falsch geraten, laege jede Stueckzahl um
22,6 Prozent daneben. Ohne Absturz, ohne Meldung, ohne Protokollzeile. Genau
deshalb rechnet die Bridge die Richtung an der Sammelzeile `BASE` nach, statt
sie anzunehmen — und deshalb steht hier ein Gegentest fuer jede Zusicherung,
die eine Richtung behauptet.
"""
from __future__ import annotations

from dataclasses import dataclass

from ordertune_bridge_ibkr.account_fx import (
    loese_kurs_auf,
    normalisiere_tag,
    richtung_ist_segment_zu_basis,
    segmente,
)


@dataclass
class FakeAccountValue:
    """Nur die drei Felder, die die Aufloesung liest."""

    tag: str
    value: str
    currency: str


def _w(tag: str, currency: str, value: str) -> FakeAccountValue:
    return FakeAccountValue(tag=tag, value=value, currency=currency)


# ── Die echten Zeilen von DUT106306, gemessen 2026-09-28 ────────────────────
#
# Nicht erfunden und nicht gerundet. Jede andere Zusicherung in dieser Datei
# variiert diesen Fall; er ist der Anker.
ECHT = [
    _w("$LEDGER-NetLiquidationByCurrency", "BASE", "997317.877"),
    _w("$LEDGER-NetLiquidationByCurrency", "EUR", "1000775.19"),
    _w("$LEDGER-NetLiquidationByCurrency", "USD", "-3930.049"),
    _w("$LEDGER-ExchangeRate", "BASE", "1.00"),
    _w("$LEDGER-ExchangeRate", "EUR", "1.00"),
    _w("$LEDGER-ExchangeRate", "USD", "0.8797124"),
    # Die Kontozeile: gleicher Stamm, ANDERE Zahl. Darf nie in eine Summe.
    _w("NetLiquidation", "EUR", "997317.88"),
    # Unterkonten (Paxos, CFD). Duerfen nie in eine Summe.
    _w("NetLiquidation-P", "EUR", "0.00"),
    _w("$LEDGER-ExchangeRate-S", "USD", "99.0"),
]


def test_das_praefix_wird_abgestreift() -> None:
    assert normalisiere_tag("$LEDGER-ExchangeRate") == "ExchangeRate"
    assert normalisiere_tag("ExchangeRate") == "ExchangeRate"
    # GEGENTEST: die Suffixe bleiben stehen, sonst sammelt die Suche
    # Unterkonto-Zeilen ein.
    assert normalisiere_tag("$LEDGER-ExchangeRate-S") == "ExchangeRate-S"


def test_nur_echte_waehrungssegmente_zaehlen() -> None:
    assert segmente(ECHT, "ExchangeRate") == {"EUR": 1.00, "USD": 0.8797124}
    # Die Sammelzeile BASE ist keine Waehrung.
    assert "BASE" not in segmente(ECHT, "ExchangeRate")
    # Die Kontozeile faelscht den Ledger nicht.
    assert segmente(ECHT, "NetLiquidationByCurrency") == {
        "EUR": 1000775.19,
        "USD": -3930.049,
    }
    # GEGENTEST: `NetLiquidation` und `NetLiquidationByCurrency` sind zwei
    # Gegenstaende, und die Kontozeile traegt eine andere Zahl.
    assert segmente(ECHT, "NetLiquidation") == {"EUR": 997317.88}


def test_die_richtung_wird_an_der_sammelzeile_belegt() -> None:
    assert richtung_ist_segment_zu_basis(ECHT) is True


def test_gegentest_die_umgekehrte_richtung_wird_auch_erkannt() -> None:
    """Dieselben Betraege, Kurse in der Gegenrichtung.

    Ohne diesen Fall belegte der Test oben nur, dass die Funktion `True` sagt.
    """
    gedreht = [
        _w("$LEDGER-NetLiquidationByCurrency", "BASE", "997317.877"),
        _w("$LEDGER-NetLiquidationByCurrency", "EUR", "1000775.19"),
        _w("$LEDGER-NetLiquidationByCurrency", "USD", "-3930.049"),
        _w("$LEDGER-ExchangeRate", "EUR", "1.00"),
        _w("$LEDGER-ExchangeRate", "USD", str(1.0 / 0.8797124)),
    ]
    assert richtung_ist_segment_zu_basis(gedreht) is False


def test_die_knappe_lage_wird_sicher_entschieden() -> None:
    """An den echten Zahlen lag die FALSCHE Hypothese nur 0,1013 % daneben.

    Eine schlichte Toleranzgrenze von 0,1 % haette die Entscheidung an der
    dritten Nachkommastelle haengen lassen. Deshalb gilt: der Sieger muss
    praktisch exakt treffen, der Verlierer spuerbar danebenliegen.
    """
    betraege = {"EUR": 1000775.19, "USD": -3930.049}
    kurse = {"EUR": 1.00, "USD": 0.8797124}
    basis = 997317.877
    falsch = sum(betraege[c] / kurse[c] for c in betraege)
    rel = abs(falsch - basis) / basis
    assert 0.0009 < rel < 0.0011, f"Lage hat sich geaendert: {rel:.6f}"
    assert richtung_ist_segment_zu_basis(ECHT) is True


def test_der_gedrehte_kurs_rechnet_nach_usd() -> None:
    ergebnis = loese_kurs_auf(ECHT, "EUR")
    assert ergebnis.kurs is not None
    # 997.317,88 EUR x Kurs = 1.133.686,28 USD
    assert abs(997317.88 * ergebnis.kurs - 1133686.28) < 0.01
    # GEGENTEST: die ungedrehte Richtung laege 22,6 % daneben und darf nicht
    # herauskommen.
    assert abs(997317.88 * 0.8797124 - 877352.91) < 0.01
    assert abs(ergebnis.kurs - 0.8797124) > 0.2


def test_ein_usd_konto_bekommt_den_kurs_eins() -> None:
    """Damit auf der Plattform EINE Regel gilt statt einer mit Ausnahme."""
    usd = [
        _w("$LEDGER-NetLiquidationByCurrency", "BASE", "309018.00"),
        _w("$LEDGER-NetLiquidationByCurrency", "USD", "309018.00"),
        _w("$LEDGER-ExchangeRate", "USD", "1.00"),
    ]
    ergebnis = loese_kurs_auf(usd, "USD")
    assert ergebnis.kurs == 1.0


def test_ohne_kurszeile_gibt_es_keinen_kurs() -> None:
    ohne = [
        _w("$LEDGER-NetLiquidationByCurrency", "BASE", "997317.877"),
        _w("$LEDGER-NetLiquidationByCurrency", "EUR", "1000775.19"),
    ]
    ergebnis = loese_kurs_auf(ohne, "EUR")
    assert ergebnis.kurs is None
    assert "ExchangeRate" in ergebnis.grund


def test_ohne_eindeutige_kontowaehrung_gibt_es_keinen_kurs() -> None:
    """Der Mehrkonten- und Mehrsegmentfall aus T1-85 bleibt gesperrt."""
    assert loese_kurs_auf(ECHT, None).kurs is None


def test_die_probe_auf_die_basiswaehrung_greift() -> None:
    """Der Kurs der Kontowaehrung ist per Definition 1,0.

    `$LEDGER-Currency BASE` traegt den Wert "BASE" und nennt die Waehrung
    NICHT. Diese Probe ist der Ersatz: passt die Waehrungsangabe nicht zur
    Kurstabelle, wird blockiert statt gerechnet.
    """
    krumm = [
        _w("$LEDGER-NetLiquidationByCurrency", "BASE", "997317.877"),
        _w("$LEDGER-NetLiquidationByCurrency", "EUR", "1000775.19"),
        _w("$LEDGER-NetLiquidationByCurrency", "USD", "-3930.049"),
        _w("$LEDGER-ExchangeRate", "EUR", "1.13"),  # nicht 1,0
        _w("$LEDGER-ExchangeRate", "USD", "0.8797124"),
    ]
    ergebnis = loese_kurs_auf(krumm, "EUR")
    assert ergebnis.kurs is None
    assert "not 1.0" in ergebnis.grund
    # GEGENTEST: mit 1,0 an derselben Stelle kommt sehr wohl ein Kurs heraus —
    # der Beleg, dass die Probe und nicht etwas anderes gegriffen hat.
    krumm[3] = _w("$LEDGER-ExchangeRate", "EUR", "1.00")
    assert loese_kurs_auf(krumm, "EUR").kurs is not None


def test_ein_winziges_fremdsegment_entscheidet_die_richtung_nicht() -> None:
    """Dann liegen beide Hypothesen nah beieinander — und geraten wird nicht."""
    winzig = [
        _w("$LEDGER-NetLiquidationByCurrency", "BASE", "996998.07"),
        _w("$LEDGER-NetLiquidationByCurrency", "EUR", "996914.07"),
        _w("$LEDGER-NetLiquidationByCurrency", "USD", "100.00"),
        _w("$LEDGER-ExchangeRate", "EUR", "1.00"),
        _w("$LEDGER-ExchangeRate", "USD", "0.84"),
    ]
    assert richtung_ist_segment_zu_basis(winzig) is None
    ergebnis = loese_kurs_auf(winzig, "EUR")
    assert ergebnis.kurs is None
    assert "guessed" in ergebnis.grund


def test_rundung_bricht_die_probe_nicht() -> None:
    """Die Grenze muss echte Zahlen ueberleben, sonst ist sie unbrauchbar."""
    gerundet = [
        _w("$LEDGER-NetLiquidationByCurrency", "BASE", "997317.91"),  # 3 ct daneben
        _w("$LEDGER-NetLiquidationByCurrency", "EUR", "1000775.19"),
        _w("$LEDGER-NetLiquidationByCurrency", "USD", "-3930.049"),
        _w("$LEDGER-ExchangeRate", "EUR", "1.00"),
        _w("$LEDGER-ExchangeRate", "USD", "0.8797124"),
    ]
    assert richtung_ist_segment_zu_basis(gerundet) is True


def test_unbrauchbare_zahlen_ergeben_keinen_kurs() -> None:
    for kaputt in ("0", "-1", "nan", "inf", "", "abc"):
        werte = [
            _w("$LEDGER-NetLiquidationByCurrency", "BASE", "997317.877"),
            _w("$LEDGER-NetLiquidationByCurrency", "EUR", "1000775.19"),
            _w("$LEDGER-NetLiquidationByCurrency", "USD", "-3930.049"),
            _w("$LEDGER-ExchangeRate", "EUR", "1.00"),
            _w("$LEDGER-ExchangeRate", "USD", kaputt),
        ]
        assert loese_kurs_auf(werte, "EUR").kurs is None, kaputt


# ── Der Sizing-Abgleich rechnet mit ─────────────────────────────────────────
#
# QA-Befund T1-252 (BUG-1): `get_live_equity` gab bei fremder Waehrung 0
# zurueck, und der Aufrufer ueberspringt den Abgleich bei `live_equity > 0`.
# Damit war der Riegel gegen einen veralteten serverseitigen Depotwert fuer
# genau die Konten abgeschaltet, die T1-252 freischaltet. Die Begruendung im
# Quelltext endete mit „und in `full_equity` laesst die Plattform es gar nicht
# erst bis hierher kommen" — ein Satz, der durch T1-252 selbst falsch wurde.


class _FakeIB:
    def __init__(self, werte: list[FakeAccountValue]) -> None:
        self._werte = werte

    def accountValues(self) -> list[FakeAccountValue]:
        return self._werte


def _client(werte: list[FakeAccountValue]):
    from ordertune_bridge_ibkr.ibkr_client import IbkrClient

    c = IbkrClient(host="127.0.0.1", port=7497, client_id=991)
    c._ib = _FakeIB(werte)  # type: ignore[assignment]
    return c


def test_der_abgleich_rechnet_ein_eur_konto_um() -> None:
    werte = [*ECHT, _w("NetLiquidation", "EUR", "997317.88")]
    # Die Kontozeile steht schon in ECHT; doppelt schadet nicht, die Suche
    # nimmt die erste.
    equity = _client(werte).get_live_equity()
    assert abs(equity - 1_133_686.28) < 0.02, equity


def test_gegentest_ohne_kurs_bleibt_der_abgleich_aus() -> None:
    """Ohne Kurs ist 0 weiterhin richtig — dann sperrt die Plattform ohnehin."""
    ohne = [
        _w("NetLiquidation", "EUR", "997317.88"),
        _w("$LEDGER-NetLiquidationByCurrency", "BASE", "997317.877"),
        _w("$LEDGER-NetLiquidationByCurrency", "EUR", "1000775.19"),
    ]
    assert _client(ohne).get_live_equity() == 0.0


def test_ein_usd_konto_bleibt_unveraendert() -> None:
    usd = [
        _w("NetLiquidation", "USD", "309018.00"),
        _w("$LEDGER-NetLiquidationByCurrency", "BASE", "309018.00"),
        _w("$LEDGER-NetLiquidationByCurrency", "USD", "309018.00"),
        _w("$LEDGER-ExchangeRate", "USD", "1.00"),
    ]
    assert _client(usd).get_live_equity() == 309_018.00


def test_ohne_eindeutige_waehrung_bleibt_es_bei_null() -> None:
    mehrdeutig = [
        _w("NetLiquidation", "EUR", "997317.88"),
        _w("NetLiquidation", "USD", "50000.00"),
    ]
    assert _client(mehrdeutig).get_live_equity() == 0.0


def test_die_drift_verschwindet_durch_die_umrechnung() -> None:
    """Der eigentliche Beleg: Server und Bridge kommen auf dieselbe Menge.

    Ohne die Umrechnung rechnete die Bridge mit 997.317,88 (EUR) gegen die
    serverseitigen 1.133.686,28 (USD) — 12,3 % Drift, und jeder Einstieg auf
    einem EUR-Konto waere als `sizing_drift` abgelehnt worden, sobald der
    Abgleich ueberhaupt liefe.
    """
    from ordertune_bridge_ibkr.position_sizing import (
        SizingConfig,
        recompute_qty,
        sizing_drift_exceeds_threshold,
    )

    cfg = SizingConfig(
        equity_mode="full_equity", position_size_pct=2.0, base_equity_amount=None
    )
    server_qty = round(1_133_686.28 * 0.02 / 100.0)

    equity = _client([*ECHT, _w("NetLiquidation", "EUR", "997317.88")]).get_live_equity()
    assert not sizing_drift_exceeds_threshold(
        server_qty, recompute_qty(cfg, 100.0, equity)
    )
    # GEGENTEST: mit dem alten Verhalten (EUR ungerechnet) haette es gedriftet.
    assert sizing_drift_exceeds_threshold(
        server_qty, recompute_qty(cfg, 100.0, 997_317.88)
    )


def test_der_grund_ist_englisch() -> None:
    """QA-Befund T1-252 (BUG-5): `grund` geht in das Protokoll des Kunden.

    `_log_fx` baut daraus eine englische Zeile. Ein deutscher Halbsatz darin
    ist kein Stilfehler, sondern ein Nutzertext in der falschen Sprache.
    """
    deutsch = ("waehrung", "waehrung", "kurs", "nicht", "keine", "der ", "die ", "das ")
    faelle = [
        loese_kurs_auf(ECHT, None),
        loese_kurs_auf([_w("NetLiquidation", "EUR", "1")], "EUR"),
        loese_kurs_auf(ECHT, "EUR"),
    ]
    for f in faelle:
        klein = f.grund.lower()
        treffer = [d for d in deutsch if d in klein]
        assert not treffer, f"{f.grund!r} enthaelt {treffer}"
