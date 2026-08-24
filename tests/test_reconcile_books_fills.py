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

from ordertune_bridge_ibkr.external_executions import is_ours
from ordertune_bridge_ibkr.order_reconcile import (
    DispatchFill,
    UnresolvedDispatch,
    dispatch_id_from_ref,
    fills_by_dispatch,
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


# ── T1-105: die Ausfuehrungsberichte tragen die Zahlen ───────────────────────
#
# Der gemessene Fall vom 2026-08-19, zweiter Durchgang: die Bridge lief mit
# 0.9.1, der Abgleich fand die drei Auftraege als `Filled` — und meldete
# trotzdem `unknown`, mit der Begruendung „IBKR reports this order as filled
# but gives no quantity". Der Riegel hielt richtig; nur standen die Zahlen
# nirgends, wo T1-104 gesucht hat.
#
# Sie stehen im Ausfuehrungsbericht, und der wird in jedem Herzschlag
# abgeholt — `external_executions` wirft die eigenen nur weg.

def _fill(
    ref: str | None,
    *,
    exec_id: str = "e1",
    shares: Any = 1.0,
    price: Any = 100.0,
    commission: float | None = None,
    commission_exec_id: str | None = None,
) -> Any:
    report = None
    if commission is not None:
        report = SimpleNamespace(
            commission=commission,
            execId=commission_exec_id if commission_exec_id is not None else exec_id,
        )
    return SimpleNamespace(
        execution=SimpleNamespace(
            orderRef=ref, execId=exec_id, shares=shares, price=price
        ),
        commissionReport=report,
    )


def test_der_vermerk_wird_zum_dispatch() -> None:
    assert dispatch_id_from_ref("ot-e99a18c4-28cb-48d5-8260-853678922e03") == "e99a18c4-28cb-48d5-8260-853678922e03"
    assert dispatch_id_from_ref("  ot-e99a18c4-28cb-48d5-8260-853678922e03  ") == "e99a18c4-28cb-48d5-8260-853678922e03"
    assert dispatch_id_from_ref("abc123") is None, "fremde Ausfuehrung"
    assert dispatch_id_from_ref("") is None
    assert dispatch_id_from_ref(None) is None
    assert dispatch_id_from_ref("ot-") is None, "leere Kennung ist keine"


def test_fremde_ausfuehrungen_bleiben_draussen() -> None:
    """Die Gegenprobe zu `external_executions.is_ours`."""
    assert fills_by_dispatch([_fill(None), _fill(""), _fill("manuell")]) == {}


def test_teilausfuehrungen_werden_zusammengefasst() -> None:
    ergebnis = fills_by_dispatch(
        [
            _fill("ot-9948c645-c094-4477-84f4-c7acdbeb2bb6", exec_id="a", shares=1.0, price=100.0, commission=0.5),
            _fill("ot-9948c645-c094-4477-84f4-c7acdbeb2bb6", exec_id="b", shares=3.0, price=104.0, commission=0.7),
        ]
    )
    f = ergebnis["9948c645-c094-4477-84f4-c7acdbeb2bb6"]
    assert f.qty == 4.0
    # Mengengewichtet: (1*100 + 3*104) / 4 = 103.0
    assert f.price == pytest.approx(103.0)
    assert f.commission == pytest.approx(1.2)


def test_dieselbe_ausfuehrung_zaehlt_einmal() -> None:
    """Eine Korrekturmeldung traegt dieselbe execId.

    Ohne Entdopplung addierte sich die Menge ein zweites Mal — und aus einem
    Buchungsdetail wuerde ein zu grosser Bestand und ein zu grosser Ausstieg.
    """
    ergebnis = fills_by_dispatch(
        [_fill("ot-9948c645-c094-4477-84f4-c7acdbeb2bb6", exec_id="a", shares=2.0), _fill("ot-9948c645-c094-4477-84f4-c7acdbeb2bb6", exec_id="a", shares=2.0)]
    )
    assert ergebnis["9948c645-c094-4477-84f4-c7acdbeb2bb6"].qty == 2.0


def test_ohne_echten_gebuehrenbericht_wird_keine_gebuehr_gebucht() -> None:
    """ib_insync legt das Feld mit 0.0 an, bevor IBKR es fuellt."""
    ergebnis = fills_by_dispatch(
        [_fill("ot-9948c645-c094-4477-84f4-c7acdbeb2bb6", commission=0.0, commission_exec_id="")]
    )
    assert ergebnis["9948c645-c094-4477-84f4-c7acdbeb2bb6"].commission is None


def test_unbrauchbare_mengen_fallen_heraus() -> None:
    for menge in (0.0, -1.0, None, "abc"):
        assert fills_by_dispatch([_fill("ot-9948c645-c094-4477-84f4-c7acdbeb2bb6", shares=menge)]) == {}


def test_ohne_kurs_bleibt_die_menge_erhalten() -> None:
    f = fills_by_dispatch([_fill("ot-9948c645-c094-4477-84f4-c7acdbeb2bb6", shares=2.0, price=0.0)])["9948c645-c094-4477-84f4-c7acdbeb2bb6"]
    assert f.qty == 2.0
    assert f.price is None


# ── Das Zusammenspiel: der gemessene Fall, jetzt vollstaendig ────────────────


def test_gefuellt_ohne_menge_am_auftrag_wird_aus_der_ausfuehrung_gebucht() -> None:
    """Genau der Fall vom 2026-08-19, zweiter Durchgang."""
    aktionen = reconcile_open_dispatches(
        unresolved=[_dispatch()],
        open_by_ref={},
        completed_by_ref={"disp-intc": _trade("Filled", filled=0.0, avg=0.0)},
        session_connected_at=VERBUNDEN,
        fills_by_ref={"disp-intc": DispatchFill(qty=2.0, price=92.58, commission=1.05)},
    )
    a = aktionen[0]
    assert a.status == "filled"
    assert a.fill_qty == 2.0
    assert a.fill_price == 92.58
    assert a.commission_usd == pytest.approx(1.05)


def test_der_auftrag_gewinnt_wenn_er_zahlen_traegt() -> None:
    """Der Ausfuehrungsbericht ist der Rueckfall, nicht die erste Quelle."""
    a = reconcile_open_dispatches(
        unresolved=[_dispatch()],
        open_by_ref={},
        completed_by_ref={"disp-intc": _trade("Filled", filled=5.0, avg=90.0)},
        session_connected_at=VERBUNDEN,
        fills_by_ref={"disp-intc": DispatchFill(qty=2.0, price=92.58, commission=1.05)},
    )[0]
    assert a.fill_qty == 5.0
    assert a.fill_price == 90.0


def test_ohne_auftrag_aber_mit_ausfuehrung_wird_trotzdem_gebucht() -> None:
    """`reqCompletedOrders` haelt nur den laufenden Tag vor und ist lueckenhaft.

    Der Ausfuehrungsbericht ist dagegen eine Tatsache ueber das Konto: er
    existiert, weil Stuecke den Besitzer gewechselt haben.
    """
    a = reconcile_open_dispatches(
        unresolved=[_dispatch()],
        open_by_ref={},
        completed_by_ref={},
        session_connected_at=VERBUNDEN,
        fills_by_ref={"disp-intc": DispatchFill(qty=1.0, price=283.13, commission=None)},
    )[0]
    assert a.status == "filled"
    assert a.fill_qty == 1.0
    assert a.commission_usd is None


def test_ein_lebender_auftrag_wird_auch_mit_ausfuehrung_nicht_angefasst() -> None:
    """Solange er offen ist, gehoert er dem Ereignispfad."""
    aktionen = reconcile_open_dispatches(
        unresolved=[_dispatch()],
        open_by_ref={"disp-intc": _trade("Submitted")},
        completed_by_ref={},
        session_connected_at=VERBUNDEN,
        fills_by_ref={"disp-intc": DispatchFill(qty=1.0, price=95.0, commission=None)},
    )
    assert aktionen == []


def test_ohne_ausfuehrung_bleibt_es_bei_der_ehrlichen_antwort() -> None:
    a = reconcile_open_dispatches(
        unresolved=[_dispatch()],
        open_by_ref={},
        completed_by_ref={"disp-intc": _trade("Filled", filled=0.0)},
        session_connected_at=VERBUNDEN,
        fills_by_ref={},
    )[0]
    assert a.status == "unknown"
    assert a.fill_qty is None


# ── Die beiden Haelften derselben Regel ──────────────────────────────────────


@pytest.mark.parametrize(
    "ref",
    ["ot-90015098-3cd2-4fb0-8696-3f7d28e17f72", "ot-6eca593e-9792-451f-8601-0e2f8bfb92d7", "manuell", "", None, "ot-"],
)
def test_die_beiden_haelften_der_orderref_regel_stimmen_ueberein(ref) -> None:
    """`is_ours` und `dispatch_id_from_ref` beantworten dieselbe Frage.

    Die eine entscheidet in `external_executions`, dass eine Ausfuehrung dem
    Nutzer gehoert und als fremd gemeldet wird. Die andere entscheidet hier,
    dass sie uns gehoert und in die Buecher kommt. Laufen sie auseinander,
    faellt eine Ausfuehrung entweder durch beide Raster — dann fehlt sie
    ueberall — oder durch keines, und dann steht sie zweimal.

    `ot-` ohne Kennung ist der eine Fall, in dem sie sich absichtlich
    unterscheiden duerfen: `is_ours` sagt „nicht fremd", und das ist richtig;
    buchen laesst sich daraus trotzdem nichts.
    """
    kennung = dispatch_id_from_ref(ref)
    if kennung is not None:
        assert is_ours(ref), "was wir buchen, darf nicht als fremd gemeldet werden"
    if not is_ours(ref):
        assert kennung is None, "was fremd gemeldet wird, darf nicht gebucht werden"
