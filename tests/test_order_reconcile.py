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


def test_a_live_order_is_left_alone() -> None:
    """Der wichtigste Nein-Fall: was offen ist, wird nicht angefasst."""
    assert _run(open_by_ref={"ot-c4ca4238-a0b9-4382-8dcc-509a6f75849b": FakeTrade(FakeStatus("Submitted"))}) == []


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
    trade = FakeTrade(
        FakeStatus("Cancelled"),
        log=[FakeLogEntry(errorCode=202, message="Order Canceled")],
    )
    actions = _run(completed_by_ref={"ot-c4ca4238-a0b9-4382-8dcc-509a6f75849b": trade})
    assert actions[0].status == "cancelled"
    assert actions[0].reason_code == "cancelled_by_user"
    assert "202" in (actions[0].error_message or "")


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
    assert (
        _run(
            open_by_ref={"ot-c4ca4238-a0b9-4382-8dcc-509a6f75849b": FakeTrade(FakeStatus("Submitted"))},
            completed_by_ref={"ot-c4ca4238-a0b9-4382-8dcc-509a6f75849b": FakeTrade(FakeStatus("Cancelled"))},
        )
        == []
    )


def test_the_measured_batch_reports_exactly_one() -> None:
    """Die Lage vom 2026-08-18: vier leben, einer ist weg."""
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
    assert [a.dispatch_id for a in actions] == ["ot-fb54f3c5-992b-46d0-81bb-16e8e92d968d"]
    assert actions[0].status == "unknown"
