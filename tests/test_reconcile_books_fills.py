"""T1-104 — eine Ausfuehrung, die niemand gesehen hat, kommt trotzdem in die Buecher.

## Der gemessene Fall

2026-08-19: INTC (zwei Auftraege) und ALAB wurden bei IBKR ausgefuehrt, waehrend
die Bridge nicht verbunden war. Der Abgleich fand sie als `Filled` — und meldete
`unknown`, weil er eine Fuellung ausdruecklich nicht buchen wollte:

    „Eine Fuellung wird hier NICHT gemeldet. Sie gehoert in den Ergebnisweg mit
    Preis, Menge und Gebuehr — und den bedient der Ereignispfad."

Der Ereignispfad laeuft aber nur, wenn die Bridge im Moment der Ausfuehrung
verbunden ist. Auf t1 standen die Stuecke danach unter „Held outside Ordertune":
der Broker meldet sie, kein Lot ordnet sie einer Strategie zu — und ein
Modell-Ausstieg fasst sie nie an.

Die Annahme war falsch: der abgeschlossene Auftrag TRAEGT die Zahlen.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from ordertune_bridge_ibkr.order_reconcile import (
    UnresolvedDispatch,
    reconcile_open_dispatches,
)

VERBUNDEN = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)
VORHER = VERBUNDEN - timedelta(hours=3)


def _dispatch(kennung: str = "disp-intc") -> UnresolvedDispatch:
    return UnresolvedDispatch(
        dispatch_id=kennung, symbol="INTC", submitted_at=VORHER
    )


def _trade(
    status: str,
    *,
    filled: Any = 0.0,
    avg: Any = 0.0,
    commissions: list[float] | None = None,
    log: list[Any] | None = None,
) -> Any:
    fills = [
        SimpleNamespace(commissionReport=SimpleNamespace(commission=c))
        for c in (commissions or [])
    ]
    return SimpleNamespace(
        orderStatus=SimpleNamespace(status=status, filled=filled, avgFillPrice=avg),
        fills=fills,
        log=log or [],
    )


def _lauf(trade: Any, kennung: str = "disp-intc"):
    return reconcile_open_dispatches(
        unresolved=[_dispatch(kennung)],
        open_by_ref={},
        completed_by_ref={kennung: trade},
        session_connected_at=VERBUNDEN,
    )


# ── Der gemessene Fall ───────────────────────────────────────────────────────


def test_eine_verpasste_ausfuehrung_wird_gemeldet() -> None:
    aktionen = _lauf(_trade("Filled", filled=2.0, avg=92.58, commissions=[1.05]))

    assert len(aktionen) == 1
    a = aktionen[0]
    assert a.status == "filled"
    assert a.fill_qty == 2.0
    assert a.fill_price == 92.58
    assert a.commission_usd == pytest.approx(1.05)
    # Kein Grund und keine Fehlermeldung: eine Ausfuehrung ist kein Fehlschlag.
    assert a.reason_code is None
    assert a.error_message is None


def test_eine_teilausfuehrung_wird_als_teilausfuehrung_gemeldet() -> None:
    a = _lauf(_trade("PartiallyFilled", filled=1.0, avg=95.77))[0]
    assert a.status == "partial"
    assert a.fill_qty == 1.0


def test_die_gebuehr_summiert_ueber_alle_ausfuehrungen() -> None:
    a = _lauf(_trade("Filled", filled=3.0, avg=83.0, commissions=[0.5, 0.35, 0.2]))[0]
    assert a.commission_usd == pytest.approx(1.05)


def test_ohne_gebuehrenmeldung_wird_keine_erfunden() -> None:
    a = _lauf(_trade("Filled", filled=1.0, avg=95.77))[0]
    assert a.commission_usd is None, "0.0 waere eine Aussage ueber Geld"


# ── Die Grenze: ohne Zahlen wird nichts gebucht ──────────────────────────────


def test_eine_fuellung_ohne_menge_bleibt_ungeklaert() -> None:
    """Genau die Meldung, vor der der alte Kommentar gewarnt hat."""
    a = _lauf(_trade("Filled", filled=0.0, avg=0.0))[0]
    assert a.status == "unknown"
    assert a.reason_code == "not_known_at_broker"
    assert a.fill_qty is None


def test_eine_fuellung_mit_unbrauchbarer_menge_bleibt_ungeklaert() -> None:
    for menge in (None, "abc", float("nan"), -1.0):
        a = _lauf(_trade("Filled", filled=menge, avg=95.0))[0]
        assert a.status == "unknown", f"Menge {menge!r} darf nichts buchen"


def test_ohne_durchschnittskurs_wird_die_menge_trotzdem_gebucht() -> None:
    """Die Menge traegt den Bestand, der Preis nur die Bewertung.

    Ohne Menge waere die Position unsichtbar; ohne Preis ist sie nur
    unbewertet. Das eine ist ein Buchungsfehler, das andere eine Luecke.
    """
    a = _lauf(_trade("Filled", filled=2.0, avg=0.0))[0]
    assert a.status == "filled"
    assert a.fill_qty == 2.0
    assert a.fill_price is None


# ── Was unveraendert bleibt ──────────────────────────────────────────────────


def test_ein_offener_auftrag_wird_weiterhin_nicht_angefasst() -> None:
    aktionen = reconcile_open_dispatches(
        unresolved=[_dispatch()],
        open_by_ref={"disp-intc": _trade("Submitted")},
        completed_by_ref={},
        session_connected_at=VERBUNDEN,
    )
    assert aktionen == []


def test_eine_stornierung_bleibt_eine_stornierung() -> None:
    a = _lauf(_trade("Cancelled"))[0]
    assert a.status == "cancelled"
    assert a.fill_qty is None


def test_ein_lebender_zustand_in_der_abgeschlossenen_liste_bleibt_ungeklaert() -> None:
    a = _lauf(_trade("Submitted", filled=2.0, avg=92.0))[0]
    assert a.status == "unknown", (
        "ein Widerspruch wird zugegeben, nicht ausgelegt — auch wenn Zahlen dastehen"
    )


def test_ein_abfragefehler_haelt_weiterhin_alles_an() -> None:
    aktionen = reconcile_open_dispatches(
        unresolved=[_dispatch()],
        open_by_ref={},
        completed_by_ref={},
        session_connected_at=VERBUNDEN,
        open_query_failed=True,
    )
    assert aktionen == []


def test_ein_gerade_abgesendeter_auftrag_wird_nicht_fuer_verschollen_erklaert() -> None:
    """Der Riegel aus T1-98 Fall 4, gegen das Phantom in der Gegenrichtung."""
    aktionen = reconcile_open_dispatches(
        unresolved=[
            UnresolvedDispatch(
                dispatch_id="disp-neu",
                symbol="INTC",
                submitted_at=VERBUNDEN + timedelta(seconds=30),
            )
        ],
        open_by_ref={},
        completed_by_ref={},
        session_connected_at=VERBUNDEN,
    )
    assert aktionen == []
