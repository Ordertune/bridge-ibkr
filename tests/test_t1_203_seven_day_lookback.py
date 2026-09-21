"""T1-203 — der 7-Tage-Abruf heilt eine Fuellung von gestern exakt.

## Der Befund

`ib.fills()` haelt nur den LAUFENDEN Tag. War die Bridge zum Zeitpunkt der
Ausfuehrung aus, kennt sie die Fuellung am naechsten Tag nicht mehr — die
Position landet unter „Held outside Ordertune", obwohl der Auftragsvermerk
`ot-<dispatchId>` sie eindeutig zuordnen wuerde. `reqExecutions` MIT Zeitfilter
reicht weiter zurueck.

Geprueft wird die ORCHESTRIERUNG in `_handle_order_reconcile`:

  A  frisch verbunden → executions_since wird abgefragt, und eine Fuellung, die
     NUR dort liegt (nicht in fills()), wird als `filled` mit exakter Menge
     gemeldet.
  B  laenger verbunden → executions_since wird NICHT abgefragt (kein
     7-Tage-reqExecutions je Herzschlag), und der Auftrag bleibt `unknown`.
  C  faellt der Zeitfilter aus (aeltere TWS-Version), bleibt es beim laufenden
     Tag — rein additiv, der Abgleich bricht nicht.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

from ordertune_bridge_ibkr import main
from ordertune_bridge_ibkr.main import (
    DEEP_RECONCILE_WINDOW_S,
    RECONCILE_LOOKBACK_DAYS,
    _handle_order_reconcile,
)

DISP = "11111111-2222-3333-4444-555555555555"


def _fill(ref: str, *, exec_id: str, shares: float, price: float) -> Any:
    return SimpleNamespace(
        execution=SimpleNamespace(
            orderRef=ref, execId=exec_id, shares=shares, price=price
        ),
        commissionReport=None,
    )


class FakeIbkr:
    def __init__(self, heutige: list[Any], aeltere: list[Any], *, since_raises: bool = False):
        self._heutige = heutige
        self._aeltere = aeltere
        self._since_raises = since_raises
        self.executions_since_called = False
        self.utc_days_asked: int | None = None

    def fills(self) -> list[Any]:
        return self._heutige

    def utc_minus_days(self, days: int) -> str:
        self.utc_days_asked = days
        return f"utc-{days}d"

    def executions_since(self, seit: Any) -> list[Any]:
        self.executions_since_called = True
        if self._since_raises:
            raise RuntimeError("older TWS: filter not supported")
        return self._aeltere

    def open_trades(self) -> list[Any]:
        return []

    def completed_trades(self, api_only: bool = False) -> list[Any]:
        return []

    def trading_account(self) -> Any:
        return None


class FakeApi:
    def __init__(self, unresolved: list[dict[str, Any]]):
        self._unresolved = unresolved
        self.results: list[tuple[str, dict[str, Any]]] = []

    def get_unresolved(self) -> list[dict[str, Any]]:
        return self._unresolved

    def result_order(self, dispatch_id: str, **kw: Any) -> None:
        self.results.append((dispatch_id, kw))


def _unresolved_row(submitted: datetime) -> dict[str, Any]:
    return {
        "dispatchId": DISP,
        "symbol": "MU",
        "submittedAt": submitted.isoformat(),
        "accountId": None,
    }


def _reset_report_state() -> None:
    # `should_report` dedupt ueber ein Modul-Global; frische Tests brauchen es leer.
    with main._REPORTED_LOCK:
        main._LAST_REPORTED.clear()


def test_frisch_verbunden_heilt_die_fuellung_von_gestern() -> None:
    _reset_report_state()
    verbunden = datetime.now(timezone.utc)  # 0 s her → im Tieffenster
    vorgestern = verbunden - timedelta(days=2)

    ibkr = FakeIbkr(
        heutige=[],  # heute nichts
        aeltere=[_fill(f"ot-{DISP}", exec_id="e-alt", shares=21.0, price=927.42)],
    )
    api = FakeApi([_unresolved_row(vorgestern)])

    _handle_order_reconcile(api, ibkr, verbunden)

    assert ibkr.executions_since_called is True
    assert ibkr.utc_days_asked == RECONCILE_LOOKBACK_DAYS
    assert len(api.results) == 1, "genau eine Meldung"
    dispatch_id, kw = api.results[0]
    assert dispatch_id == DISP
    assert kw["status"] == "filled", "die Fuellung von gestern wird exakt gebucht"
    assert float(kw["fill_qty"]) == 21.0
    assert abs(float(kw["fill_price"]) - 927.42) < 1e-6


def test_laenger_verbunden_fragt_nicht_sieben_tage_ab() -> None:
    _reset_report_state()
    # Aelter als das Fenster → kein 7-Tage-reqExecutions je Herzschlag.
    verbunden = datetime.now(timezone.utc) - timedelta(
        seconds=DEEP_RECONCILE_WINDOW_S + 60
    )
    vorgestern = verbunden - timedelta(days=2)

    ibkr = FakeIbkr(
        heutige=[],
        aeltere=[_fill(f"ot-{DISP}", exec_id="e-alt", shares=21.0, price=927.42)],
    )
    api = FakeApi([_unresolved_row(vorgestern)])

    _handle_order_reconcile(api, ibkr, verbunden)

    assert ibkr.executions_since_called is False, "kein Tiefabruf ausserhalb des Fensters"
    assert len(api.results) == 1
    _, kw = api.results[0]
    assert kw["status"] == "unknown", "ohne den Tiefabruf bleibt es beim alten Verhalten"


def test_zeitfilter_faellt_aus_und_der_abgleich_laeuft_weiter() -> None:
    _reset_report_state()
    verbunden = datetime.now(timezone.utc)
    vorgestern = verbunden - timedelta(days=2)

    ibkr = FakeIbkr(
        heutige=[],
        aeltere=[_fill(f"ot-{DISP}", exec_id="e-alt", shares=21.0, price=927.42)],
        since_raises=True,  # aeltere TWS-Version: Filter nicht unterstuetzt
    )
    api = FakeApi([_unresolved_row(vorgestern)])

    _handle_order_reconcile(api, ibkr, verbunden)

    assert ibkr.executions_since_called is True, "es wurde versucht"
    # Rein additiv: ohne den Tiefabruf faellt es auf das alte Verhalten zurueck.
    assert len(api.results) == 1
    _, kw = api.results[0]
    assert kw["status"] == "unknown"
