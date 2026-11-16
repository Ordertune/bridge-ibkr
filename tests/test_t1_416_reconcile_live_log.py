"""T1-416 — der Abgleich liest IBKRs Ablehnung, wenn diese Sitzung sie kennt.

Welzel 2026-11-12: drei DAY-Limits gingen um 16:00:14 ET hinaus, IBKR wies sie
mit 201 („Die Boerse ist geschlossen“) ab. Auf t1 standen sie danach als
`cancelled` ohne Grund und ohne Text. Genau diese Meldung liefert der Abgleich
(`_from_completed`), wenn er den Auftrag aus `reqCompletedOrders` liest: dort
fehlt das Protokoll, und ohne Protokoll ist eine Ablehnung nicht zu erkennen.

Diese Sitzung hat den Auftrag aber selbst gestellt, und ihr eigener
Gegenstand traegt das Protokoll mit der 201. Der Abgleich nimmt ihn jetzt.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from ordertune_bridge_ibkr import main as m
from ordertune_bridge_ibkr.order_reconcile import (
    UnresolvedDispatch,
    reconcile_open_dispatches,
)

DISPATCH = "9948c645-c094-4477-84f4-c7acdbeb2bb6"
TEXT = "Die Boerse ist geschlossen."


def _trade(log=()):
    return SimpleNamespace(
        order=SimpleNamespace(orderRef=f"ot-{DISPATCH}", orderId=7, action="BUY"),
        contract=SimpleNamespace(symbol="SNDK"),
        orderStatus=SimpleNamespace(status="Cancelled", filled=0.0, avgFillPrice=0.0),
        log=list(log),
    )


@pytest.fixture(autouse=True)
def _leer():
    m._TRADES_BY_DISPATCH.clear()
    yield
    m._TRADES_BY_DISPATCH.clear()


def _entscheide(completed):
    return reconcile_open_dispatches(
        unresolved=[
            UnresolvedDispatch(
                dispatch_id=DISPATCH,
                symbol="SNDK",
                submitted_at=datetime(2026, 11, 12, 21, 0, tzinfo=timezone.utc),
            )
        ],
        open_by_ref={},
        completed_by_ref=completed,
        session_connected_at=datetime(2026, 11, 12, 13, 0, tzinfo=timezone.utc),
    )


def test_ohne_protokoll_bleibt_es_ein_storno_ohne_grund() -> None:
    """Der Ist-Zustand, als Gegenprobe."""
    aktion = _entscheide({DISPATCH: _trade()})[0]
    assert aktion.status == "cancelled"
    assert aktion.reason_code is None


def test_die_eigene_sitzung_liefert_das_protokoll() -> None:
    lebend = _trade(log=[SimpleNamespace(errorCode=201, message=TEXT, time=None)])
    m._TRADES_BY_DISPATCH[DISPATCH] = lebend

    completed = m.mit_eigenem_protokoll({DISPATCH: _trade()})
    aktion = _entscheide(completed)[0]

    assert aktion.status == "rejected"
    assert aktion.reason_code == "rejected_by_broker"
    assert TEXT in (aktion.error_message or "")


def test_ohne_eigenes_protokoll_bleibt_der_abgeschlossene_auftrag() -> None:
    m._TRADES_BY_DISPATCH[DISPATCH] = _trade()
    fremd = _trade()
    assert m.mit_eigenem_protokoll({DISPATCH: fremd})[DISPATCH] is fremd


def test_nur_abgeschlossene_auftraege_werden_ersetzt() -> None:
    """Was IBKR nicht als abgeschlossen fuehrt, kommt nicht hinzu."""
    m._TRADES_BY_DISPATCH[DISPATCH] = _trade(
        log=[SimpleNamespace(errorCode=201, message=TEXT, time=None)]
    )
    assert m.mit_eigenem_protokoll({}) == {}


def test_ein_veralteter_eigener_zustand_verdeckt_keine_fuellung() -> None:
    lebend = _trade(log=[SimpleNamespace(errorCode=0, message="", time=None)])
    lebend.orderStatus.status = "Submitted"
    m._TRADES_BY_DISPATCH[DISPATCH] = lebend
    gefuellt = _trade()
    gefuellt.orderStatus.status = "Filled"
    assert m.mit_eigenem_protokoll({DISPATCH: gefuellt})[DISPATCH] is gefuellt
