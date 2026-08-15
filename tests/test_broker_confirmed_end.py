"""T1-96: der Nachweis reist mit.

## Woher das kommt

Der Smoke-Test des Owners am 2026-08-14: Storno direkt in TWS. IBKR bestaetigt
ihn, die Meldung erreicht t1, und danach liess sich dasselbe Signal nicht mehr
freigeben. Der Riegel gegen Doppelauftraege fragte, WER storniert hat, und
haette fragen muessen, OB der Broker das Ende bestaetigt hat. Die Antwort lag
in der Bridge bereits vor — `cancel_is_genuine` — und wurde weggeworfen.

## Was hier geprueft wird

1. **Nur bei `cancelled`.** Fuer die anderen Endzustaende ist die Pruefung
   nicht gemacht. Ein Feld, das mehr behauptet als es geprueft hat, waere
   derselbe Fehler in Gruen.
2. **`False` ist eine Aussage, kein Weglassen.** Eine erfundene Stornierung
   muss als unbestaetigt ankommen, sonst oeffnet sie den Riegel — genau der
   Rueckschritt, gegen den T1-88b entstanden ist.
## Der Befund aus der Messung nach Handelsschluss

In ib_insync 0.9.86 fuehrt `wrapper.error` den Code 202 unter den Warnungen
(Zeile 1097). Warnungen haengen dem Auftrag KEINEN Protokolleintrag an. Was
`trade.log` bei einer Stornierung durch IBKR traegt, ist der gewoehnliche
Zustandswechsel aus `wrapper.orderStatus` (Zeile 438) — mit `errorCode = 0`,
dem Feld-Default. Ein Storno in TWS und ein Verfall zum Boersenschluss sind
darin nicht zu unterscheiden: beide Male `status='Cancelled'`, `message=''`,
`errorCode=0`.

Am 2026-08-14 nach Handelsschluss zu Ende gemessen: auch `errorEvent` trennt
die beiden nicht. Beide senden `Warning 202, "Order storniert – Grund:"` mit
leerem Grund — Order 58 (Verfall um 20:00:13 UTC) gegen die Orders 46 und 47
(von Hand in TWS storniert um 13:24).

Fuer den Riegel genuegt das trotzdem, denn die 0 beantwortet genau seine
Frage: IBKR hat den Zustand gesetzt, nicht ib_insync. Die Beschriftung Storno
gegen Verfall faellt seit T1-96 B-1 auf der Plattform, ueber den Zeitpunkt
gegen den Sitzungsschluss.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from ordertune_bridge_ibkr import main as m


@pytest.fixture(autouse=True)
def _reset():
    m._LAST_REPORTED.clear()
    yield
    m._LAST_REPORTED.clear()


class FakeApi:
    """Faengt die Meldung ab, statt sie zu verschicken."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def result_order(self, dispatch_id: str, **kwargs: Any) -> None:
        self.calls.append({"dispatchId": dispatch_id, **kwargs})


def make_trade(
    status: str,
    *,
    error_code: int | None = 0,
    filled: float = 0.0,
    order_id: int = 42,
    order_type: str = "LMT",
) -> SimpleNamespace:
    """Ein Auftrag, wie ihn ib_insync fortschreibt.

    `error_code=None` steht fuer einen Protokolleintrag ohne Code — das ist
    NICHT dasselbe wie 0 und darf nicht als Bestaetigung gelten.
    """
    return SimpleNamespace(
        order=SimpleNamespace(orderId=order_id, orderType=order_type, tif="DAY"),
        orderStatus=SimpleNamespace(
            status=status, filled=filled, avgFillPrice=0.0 if filled == 0 else 10.0
        ),
        log=[SimpleNamespace(status=status, message="", errorCode=error_code)],
        fills=[],
    )


# ── 1) Der Nachweis auf der Leitung ──────────────────────────────────────────


def test_a_cancellation_from_ibkr_travels_as_confirmed() -> None:
    """Der Fall aus dem Smoke-Test: Storno in TWS, `errorCode = 0`.

    Das ist der gewoehnliche Zustandswechsel aus `wrapper.orderStatus` — IBKR
    hat ihn gesetzt. Ohne dieses Feld stand auf der Leitung nur `cancelled`,
    und die Plattform liess im Zweifel gesperrt.
    """
    api = FakeApi()
    m._report_status(api, "d-1", make_trade("Cancelled", error_code=0), "cancelled")

    assert api.calls[0]["broker_confirmed_end"] is True


def test_an_invented_cancellation_travels_as_unconfirmed() -> None:
    """10349 ist der Code vom 2026-08-13 — ib_insync hat den Zustand gesetzt.

    Der Auftrag kann weiterleben. Als `True` gemeldet oeffnete er den Riegel
    und kostete einen zweiten Echtauftrag.
    """
    api = FakeApi()
    m._report_status(api, "d-2", make_trade("Cancelled", error_code=10349), "cancelled")

    assert api.calls[0]["broker_confirmed_end"] is False


def test_a_log_entry_without_a_code_is_not_a_confirmation() -> None:
    """Kein Code heisst keine Begruendung — und keine Begruendung ist kein Ja."""
    api = FakeApi()
    m._report_status(api, "d-3", make_trade("Cancelled", error_code=None), "cancelled")

    assert api.calls[0]["broker_confirmed_end"] is False


def test_a_fill_carries_no_claim_about_confirmation() -> None:
    """Fuer eine Ausfuehrung ist diese Pruefung nicht gemacht.

    `None` heisst „keine Aussage" und faellt im Client aus dem Koerper. Ein
    `True` waere hier geraten — und die Ausfuehrung braucht es nicht: sie ist
    am Konto passiert und traegt sich selbst.
    """
    api = FakeApi()
    m._report_status(api, "d-4", make_trade("Filled", filled=5.0), "filled")

    assert api.calls[0]["broker_confirmed_end"] is None


def test_the_deferred_path_re_reads_the_proof() -> None:
    """Die Nachbeobachtung meldet spaeter — mit dem dann geltenden Nachweis.

    T1-88b haelt eine verdaechtige Stornierung drei Sekunden zurueck und liest
    den Auftrag danach erneut. Kommt IBKRs eigene Bestaetigung in dieser Zeit
    an, ist der Nachweis da; bleibt es beim erfundenen Zustand, nicht. Der
    Nachweis wird deshalb beim Melden bestimmt und nicht beim Verdacht.
    """
    trade = make_trade("Cancelled", error_code=10349)
    api = FakeApi()

    # In der Zwischenzeit trifft die Bestaetigung von IBKR ein.
    trade.log.append(SimpleNamespace(status="Cancelled", message="", errorCode=0))

    m._report_status(api, "d-5", trade, "cancelled")
    assert api.calls[0]["broker_confirmed_end"] is True
