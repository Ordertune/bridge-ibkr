"""T1-98: was IBKR nicht kennt, wird gemeldet — und was es kennt, nicht.

## Woher dieser Test kommt

Am 2026-08-18 gingen fuenf Auftraege raus. IBKR nahm vier an und verweigerte den
fuenften (SHOP, orderId 226). Auf t1 stehen bis heute fuenf, alle als `working`.

Die Bridge hat es gesehen und nicht gesagt — ihr eigenes Protokoll zaehlte vier
wiederhergestellte Auftraege, aber es gab keine Zahl, gegen die sie diese Vier
haette halten koennen.

Diese Zusicherungen decken beide Richtungen ab. Die gefaehrlichere ist die
zweite: ein falsch positiver Befund macht eine LEBENDE Order endgueltig und
damit wieder freigebbar, und aus einem Anzeigefehler wuerde ein zweiter
Echtauftrag.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from ordertune_bridge_ibkr.order_reconcile import (
    UnresolvedDispatch,
    reconcile_open_dispatches,
)

VERBUNDEN = datetime(2026, 8, 18, 8, 51, 15, tzinfo=timezone.utc)
VORHER = VERBUNDEN - timedelta(minutes=6)
NACHHER = VERBUNDEN + timedelta(seconds=30)


@dataclass
class FakeLogEntry:
    errorCode: int = 0
    message: str = ""


@dataclass
class FakeStatus:
    status: str


@dataclass
class FakeTrade:
    orderStatus: FakeStatus
    log: list[FakeLogEntry] = field(default_factory=list)
    advancedError: str = ""


def d(dispatch_id: str, *, submitted_at: datetime | None = VORHER):
    return UnresolvedDispatch(
        dispatch_id=dispatch_id, symbol="SHOP", submitted_at=submitted_at
    )


def _run(**over: Any):
    args: dict[str, Any] = {
        "unresolved": [d("ot-c4ca4238-a0b9-4382-8dcc-509a6f75849b")],
        "open_by_ref": {},
        "completed_by_ref": {},
        "session_connected_at": VERBUNDEN,
    }
    args.update(over)
    return reconcile_open_dispatches(**args)


def test_the_measured_case_is_reported() -> None:
    """Der Auftrag, den IBKR nirgends kennt, wird ungeklaert gemeldet.

    Vor T1-98 blieb er den ganzen Handelstag `working`, und erst der
    24-Stunden-Sweep drehte ihn auf `unknown` — ohne Grund und lange nachdem
    jemand etwas damit haette anfangen koennen.
    """
    actions = _run()
    assert len(actions) == 1
    assert actions[0].status == "unknown"
    assert actions[0].reason_code == "not_known_at_broker"
    assert actions[0].error_message


def test_a_live_order_is_reported_as_live() -> None:
    """T1-120 — was offen ist, wird als offen GEMELDET.

    Hier stand bis T1-120 `== []`, unter dem Namen „der wichtigste Nein-Fall".
    Die Entscheidung war falsch, und der Testname hat sie zementiert: eine
    Zeile steht ueberhaupt nur dann in der Frageliste, wenn die Plattform
    ihren Zustand als NICHT abgeschlossen fuehrt. Sie fragt, WEIL sie es nicht
    weiss — und bekam auf die Frage „lebt der noch?" keine Antwort.

    Gemessen am 2026-08-24: fuenf Auftraege lagen offen im Buch des
    verbundenen Kontos, auf t1 standen sie auf `unknown`, und der Abgleich
    schwieg bei jedem Durchgang erneut.
    """
    aktionen = _run(
        open_by_ref={
            "ot-c4ca4238-a0b9-4382-8dcc-509a6f75849b": FakeTrade(FakeStatus("Submitted"))
        }
    )
    assert len(aktionen) == 1
    assert aktionen[0].status == "working"
    assert aktionen[0].fill_qty is None


def test_a_pending_order_keeps_its_own_word() -> None:
    """`PreSubmitted` ist nicht dasselbe wie `Submitted`.

    IBKR unterscheidet „unterwegs" von „am Markt". Beides auf ein Wort zu
    ziehen waere dieselbe Vergroeberung, die T1-91 fuer den Verfall
    zurueckgenommen hat.
    """
    aktionen = _run(
        open_by_ref={
            "ot-c4ca4238-a0b9-4382-8dcc-509a6f75849b": FakeTrade(FakeStatus("PendingSubmit"))
        }
    )
    assert aktionen[0].status == "submitting"


def test_an_open_order_that_claims_a_final_state_says_nothing() -> None:
    """Ein Widerspruch wird nicht aufgeloest, sondern ausgesessen.

    Steht der Auftrag in der Liste der OFFENEN und meldet trotzdem einen
    Endzustand, ist eine der beiden Angaben falsch — und es ist nicht
    entscheidbar welche. Der naechste Durchgang fragt erneut.
    """
    assert (
        _run(
            open_by_ref={
                "ot-c4ca4238-a0b9-4382-8dcc-509a6f75849b": FakeTrade(FakeStatus("Filled"))
            }
        )
        == []
    )


def test_an_order_submitted_after_connecting_is_never_declared_missing() -> None:
    """Der Riegel gegen das Phantom in der Gegenrichtung.

    Die Plattform hat die Zeile geschrieben, IBKR hat sie noch nicht
    bestaetigt, und der Abgleich kommt dazwischen. Ohne diesen Riegel wuerde
    daraus ein Endzustand, aus dem Endzustand eine wieder freigebbare Zeile,
    und aus der ein zweiter Echtauftrag.
    """
    assert _run(unresolved=[d("ot-c4ca4238-a0b9-4382-8dcc-509a6f75849b", submitted_at=NACHHER)]) == []


def test_without_a_submit_time_nothing_is_decided() -> None:
    assert _run(unresolved=[d("ot-c4ca4238-a0b9-4382-8dcc-509a6f75849b", submitted_at=None)]) == []


def test_a_failed_open_query_stops_everything() -> None:
    """Ein Abfragefehler darf nicht wie ein leeres Buch aussehen.

    Sonst wuerde aus einem Netzwerkfehler die Aussage "IBKR kennt keinen
    deiner Auftraege mehr" — und jede laufende Order stuende auf ungeklaert.
    Dieselbe Unterscheidung wie bei den Positionen in T1-99.
    """
    assert _run(open_query_failed=True) == []
    assert (
        _run(
            unresolved=[d("ot-c4ca4238-a0b9-4382-8dcc-509a6f75849b"), d("ot-c81e728d-9d4c-4f63-8f06-7f89cc14862c"), d("ot-eccbc87e-4b5c-42fe-8830-8fd9f2a7baf3")],
            open_query_failed=True,
        )
        == []
    )


def test_a_cancelled_order_is_reported_as_cancelled_with_its_reason() -> None:
    """T1-137 — der Wortlaut reist mit, die Handlung wird nicht behauptet.

    Bis T1-137 stand hier `cancelled_by_user`, fest verdrahtet. Code 202 ist
    IBKRs regulaere Stornobestaetigung und sagt „storniert" — er sagt NICHT,
    wer storniert hat. T1-96 hat genau das gemessen: ein Verfall zum
    Boersenschluss und ein Storno in TWS tragen beide die 202, beide mit
    leerer Begruendung, und sind an dieser Stelle ununterscheidbar.

    Der Abgleichslauf hat damit keinen Beleg fuer eine Nutzerhandlung — also
    behauptet er auch keine. `None` heisst „storniert, Grund unbekannt"; die
    Plattform faellt dafuer auf den Wortlaut des Zustands zurueck.
    """
    trade = FakeTrade(
        FakeStatus("Cancelled"),
        log=[FakeLogEntry(errorCode=202, message="Order Canceled")],
    )
    actions = _run(completed_by_ref={"ot-c4ca4238-a0b9-4382-8dcc-509a6f75849b": trade})
    assert actions[0].status == "cancelled"
    assert actions[0].reason_code is None
    assert "202" in (actions[0].error_message or "")
    # Kein belegtes Ende: `cancelled` allein oeffnet den Riegel nicht.
    assert actions[0].broker_confirmed_end is None


def test_a_rejected_order_carries_the_brokers_words() -> None:
    trade = FakeTrade(
        FakeStatus("Inactive2"),
        log=[
            FakeLogEntry(errorCode=0, message="ignoriert"),
            FakeLogEntry(
                errorCode=201, message="Order rejected - insufficient funds"
            ),
        ],
    )
    actions = _run(completed_by_ref={"ot-c4ca4238-a0b9-4382-8dcc-509a6f75849b": trade})
    assert actions[0].status == "rejected"
    assert actions[0].reason_code == "rejected_by_broker"
    assert "insufficient funds" in (actions[0].error_message or "")


def test_no_reason_is_invented() -> None:
    """Was ib_insync nicht weiss, darf die Bridge nicht behaupten.

    Dieselbe Grenze wie beim Storno: ein Verfall zum Boersenschluss und ein
    Storno in TWS sind im Protokoll ununterscheidbar.
    """
    actions = _run(completed_by_ref={"ot-c4ca4238-a0b9-4382-8dcc-509a6f75849b": FakeTrade(FakeStatus("Cancelled"))})
    assert actions[0].status == "cancelled"
    assert actions[0].error_message is None


# ── T1-137 — eine Ablehnung ist keine Stornierung ───────────────────────────


def test_a_rejection_reported_as_cancelled_is_not_a_user_cancel() -> None:
    """Der Befund vom 2026-08-31, auf dem Weg des Abgleichslaufs.

    IBKR wies vier Auftraege wegen fehlender Deckung ab (Error 201).
    ib_insync setzt daraufhin `orderStatus.status = 'Cancelled'`, ohne dass je
    ein `cancelOrder` ueber die Leitung geht — der Zustand sieht also aus wie
    ein Storno. Dieser Weg machte daraus `cancelled_by_user` und behauptete
    damit eine Handlung des Nutzers, die es nie gab.
    """
    trade = FakeTrade(
        FakeStatus("Cancelled"),
        log=[
            FakeLogEntry(errorCode=0, message="Submitted"),
            FakeLogEntry(
                errorCode=201,
                message=(
                    "Order abgewiesen - Grund: Verfuegbare Mittel in "
                    "Basiswaehrung: 2335.24 USD Barmittel fuer diese und "
                    "weitere offene Orders benoetigt: 2554.04 USD"
                ),
            ),
        ],
    )
    actions = _run(completed_by_ref={"ot-c4ca4238-a0b9-4382-8dcc-509a6f75849b": trade})

    assert actions[0].status == "rejected"
    assert actions[0].reason_code == "rejected_by_broker"
    # Die einzige handlungsrelevante Auskunft. Sie fehlte am 2026-08-31 ganz.
    assert "2335.24" in (actions[0].error_message or "")
    assert "2554.04" in (actions[0].error_message or "")
    # Eine Ablehnung ist ein belegtes Ende: nichts ist hinausgegangen.
    assert actions[0].broker_confirmed_end is True


def test_without_a_log_the_reconcile_path_claims_nothing() -> None:
    """Die Grenze dieses Weges, ausdruecklich festgehalten.

    Ein Auftrag aus `reqCompletedOrders` traegt kein Protokoll — ib_insync baut
    es nur fuer Auftraege, die diese Sitzung selbst platziert hat. Dieser Weg
    kann eine Ablehnung dann gar nicht sehen. Genau dort ist Schweigen die
    richtige Antwort: keine Ablehnung behaupten, aber eben auch keinen
    Nutzer-Storno.
    """
    trade = FakeTrade(FakeStatus("Cancelled"), log=[])
    actions = _run(completed_by_ref={"ot-c4ca4238-a0b9-4382-8dcc-509a6f75849b": trade})

    assert actions[0].status == "cancelled"
    assert actions[0].reason_code is None
    assert actions[0].broker_confirmed_end is None


def test_a_completed_order_that_still_looks_alive_is_not_interpreted() -> None:
    """Ein Widerspruch wird zugegeben, nicht aufgeloest."""
    actions = _run(
        completed_by_ref={"ot-c4ca4238-a0b9-4382-8dcc-509a6f75849b": FakeTrade(FakeStatus("PreSubmitted"))}
    )
    assert actions[0].status == "unknown"


def test_a_fill_is_never_reported_from_here() -> None:
    """Eine Fuellung gehoert in den Ergebnisweg mit Preis, Menge und Gebuehr.

    Von hier gemeldet stuende sie ohne Zahlen — und wuerde einen
    vollstaendigen Bericht ueberschreiben, den der Ereignispfad vielleicht
    noch liefert.
    """
    actions = _run(completed_by_ref={"ot-c4ca4238-a0b9-4382-8dcc-509a6f75849b": FakeTrade(FakeStatus("Filled"))})
    assert actions[0].status == "unknown"
    assert "filled" in (actions[0].error_message or "").lower()


def test_open_wins_over_completed() -> None:
    """Steht ein Auftrag in beiden Listen, gilt er als lebend.

    Der teure Fehler ist, einen lebenden Auftrag fuer beendet zu erklaeren.
    """
    aktionen = _run(
        open_by_ref={"ot-c4ca4238-a0b9-4382-8dcc-509a6f75849b": FakeTrade(FakeStatus("Submitted"))},
        completed_by_ref={"ot-c4ca4238-a0b9-4382-8dcc-509a6f75849b": FakeTrade(FakeStatus("Cancelled"))},
    )
    # T1-120: die Regel ist dieselbe geblieben, ihre Antwort ist staerker
    # geworden. Vorher schwieg der Abgleich und ueberliess der Plattform ihren
    # alten Stand; jetzt widerspricht er der Stornierung ausdruecklich.
    assert len(aktionen) == 1
    assert aktionen[0].status == "working"


def test_the_measured_batch_finds_the_missing_one() -> None:
    """Die Lage vom 2026-08-18: vier leben, einer ist weg.

    T1-98 hat hier „genau eine Meldung" gepruefte — die vier Lebenden waren
    stumm. Seit T1-120 melden sie ihren Zustand, und der Kern des Falls bleibt
    unveraendert: der fuenfte wird als ungeklaert gefunden, und nur er.
    """
    lebend = {
        ref: FakeTrade(FakeStatus("Submitted"))
        for ref in ("ot-2d8fb88c-fc1e-4ab6-8dc7-0f522dc82fe4", "ot-2b923591-22a2-4225-89f3-10ca847829ad", "ot-1e9f1d12-d00f-4aea-8f10-588f8387e5a1", "ot-16b48de9-a2e5-4ef7-86ca-751d23107568")
    }
    actions = _run(
        unresolved=[
            d("ot-2d8fb88c-fc1e-4ab6-8dc7-0f522dc82fe4"),
            d("ot-2b923591-22a2-4225-89f3-10ca847829ad"),
            d("ot-1e9f1d12-d00f-4aea-8f10-588f8387e5a1"),
            d("ot-fb54f3c5-992b-46d0-81bb-16e8e92d968d"),
            d("ot-16b48de9-a2e5-4ef7-86ca-751d23107568"),
        ],
        open_by_ref=lebend,
    )
    ungeklaert = [a for a in actions if a.status == "unknown"]
    assert [a.dispatch_id for a in ungeklaert] == ["ot-fb54f3c5-992b-46d0-81bb-16e8e92d968d"]
    # Die vier Lebenden werden als lebend gemeldet, nicht verschwiegen.
    assert sorted(a.status for a in actions) == ["unknown"] + ["working"] * 4


# ── T1-119 — der Auftrag aus einem anderen Depot ────────────────────────────
#
# Owner am 2026-08-24, nach einem Wechsel von Echtgeld auf Papier in TWS: drei
# Auftraege standen auf t1 als `unknown`. Sie lagen die ganze Zeit gesund im
# Buch des anderen Kontos.

# Zwei Kennungen mit den Praefixen, auf die es ankommt — `U…` fuer Echtgeld,
# `DU…` fuer Papier. Bewusst KEINE echten Konten: dieses Repo ist oeffentlich,
# und fuer diesen Test ist nur wichtig, dass sich die beiden unterscheiden.
LIVE = "U10000001"
PAPIER = "DU20000002"


def _mit_konto(dispatch_id: str, konto: str | None):
    return UnresolvedDispatch(
        dispatch_id=dispatch_id,
        symbol="SHOP",
        submitted_at=VORHER,
        account_id=konto,
    )


def test_fremdes_depot_wird_nicht_als_ungeklaert_gemeldet() -> None:
    """Der gemessene Fall vom 2026-08-24.

    Der Auftrag gehoert zum Echtgeldkonto, verbunden ist das Papierkonto. IBKR
    kennt ihn in dieser Sitzung weder offen noch abgeschlossen — und das ist
    keine Aussage ueber den Auftrag, sondern ueber die Sitzung.
    """
    actions = _run(
        unresolved=[_mit_konto("ot-fremd", LIVE)],
        connected_account=PAPIER,
    )
    assert actions == []


def test_eigenes_depot_wird_weiterhin_gemeldet() -> None:
    """Der Riegel darf den eigentlichen Zweck nicht aushebeln."""
    actions = _run(
        unresolved=[_mit_konto("ot-eigen", PAPIER)],
        connected_account=PAPIER,
    )
    assert len(actions) == 1
    assert actions[0].status == "unknown"


def test_ohne_kennung_am_auftrag_wird_gemeldet() -> None:
    """Auftrag von vor T1-116, oder Plattform vor T1-119.

    Nichtwissen darf keinen verschollenen Auftrag verschlucken — das waere die
    teurere Richtung des Irrtums.
    """
    actions = _run(
        unresolved=[_mit_konto("ot-alt", None)],
        connected_account=PAPIER,
    )
    assert len(actions) == 1


def test_ohne_kennung_der_sitzung_wird_gemeldet() -> None:
    """Login mit mehreren verwalteten Konten: `trading_account` entscheidet
    nicht, und dann entscheidet auch dieser Riegel nicht."""
    actions = _run(
        unresolved=[_mit_konto("ot-mehrfach", LIVE)],
        connected_account=None,
    )
    assert len(actions) == 1


def test_fremdes_depot_schlaegt_den_beleg_aus_dem_buch() -> None:
    """Der Riegel steht VOR den Belegen, und das ist der Zweck.

    Eine Auftragsnummer ist je Konto vergeben. Ein zufaellig gleicher Vermerk
    im verbundenen Depot wuerde dem fremden Auftrag sonst einen Endzustand
    zuschreiben — aus einem Buch, das ihn gar nicht fuehrt.
    """
    actions = _run(
        unresolved=[_mit_konto("ot-kollision", LIVE)],
        connected_account=PAPIER,
        completed_by_ref={
            "ot-kollision": FakeTrade(orderStatus=FakeStatus(status="Cancelled"))
        },
    )
    assert actions == []


def test_die_voreinstellung_bleibt_das_verhalten_von_vorher() -> None:
    """Ohne das neue Argument aendert sich nichts — eine alte Aufrufstelle
    verhaelt sich wie vor T1-119."""
    actions = _run(unresolved=[_mit_konto("ot-default", LIVE)])
    assert len(actions) == 1


# ── T1-120 — der Fall aus dem Owner-Protokoll vom 2026-08-24, 12:59 ─────────


def test_der_gemeldete_fall_vom_2026_08_24() -> None:
    """Fuenf Auftraege offen im Buch, auf t1 stehen sie auf `unknown`.

    Aus dem Protokoll:

        12:59:19  Re-mapped 5 open orders via their order reference.
        12:59:22  Reconciled dispatch 6e68f237… -> unknown (not_known_at_broker)

    Die Bridge sah alle fuenf — `orderStatus='Submitted'`,
    `account='U23076419'` — und meldete darueber nichts. Der sechste, wirklich
    verschollene, war die einzige Zeile, die ueberhaupt eine Meldung ausloeste.

    Nach T1-120 melden alle sechs: fuenf leben, einer ist weg.
    """
    lebend = {
        f"ot-live-{i}": FakeTrade(FakeStatus("Submitted")) for i in range(5)
    }
    aktionen = _run(
        unresolved=[d(f"ot-live-{i}") for i in range(5)] + [d("ot-6e68f237")],
        open_by_ref=lebend,
    )
    nach_id = {a.dispatch_id: a.status for a in aktionen}
    assert nach_id["ot-6e68f237"] == "unknown"
    for i in range(5):
        assert nach_id[f"ot-live-{i}"] == "working", (
            "ein Auftrag, den IBKR offen fuehrt, muss die Plattform aus dem "
            "Zustand `unknown` holen — genau das unterblieb"
        )


def test_ein_fremdes_depot_wird_auch_dann_nicht_gemeldet_wenn_es_offen_scheint() -> None:
    """Der T1-119-Riegel steht VOR Fall 1, und das muss so bleiben.

    Eine Auftragsnummer ist je Konto vergeben. Ein zufaellig gleicher Vermerk
    im verbundenen Depot duerfte dem fremden Auftrag sonst ein `working`
    zuschreiben — dieselbe Behauptung wie ein `cancelled`, nur mit
    freundlicherem Vorzeichen.
    """
    aktionen = _run(
        unresolved=[_mit_konto("ot-fremd", LIVE)],
        connected_account=PAPIER,
        open_by_ref={"ot-fremd": FakeTrade(FakeStatus("Submitted"))},
    )
    assert aktionen == []
