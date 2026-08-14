"""T1-96: der Nachweis reist mit — und der Mitschnitt fuer die offene Frage.

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
3. **Der Mitschnitt bewertet nichts.** Er schreibt beide Kanaele nebeneinander
   ins Protokoll, damit die Frage aus B-1 — Storno in TWS oder Verfall zum
   Boersenschluss? — aus Beobachtung beantwortet wird statt aus Vermutung.

## Der Befund, der B-1 vertagt hat

In ib_insync 0.9.86 fuehrt `wrapper.error` den Code 202 unter den Warnungen
(Zeile 1097). Warnungen haengen dem Auftrag KEINEN Protokolleintrag an. Was
`trade.log` bei einer Stornierung durch IBKR traegt, ist der gewoehnliche
Zustandswechsel aus `wrapper.orderStatus` (Zeile 438) — mit `errorCode = 0`,
dem Feld-Default. Ein Storno in TWS und ein Verfall zum Boersenschluss sind
darin nicht zu unterscheiden: beide Male `status='Cancelled'`, `message=''`,
`errorCode=0`.

Fuer den Riegel genuegt das trotzdem, denn die 0 beantwortet genau seine
Frage: IBKR hat den Zustand gesetzt, nicht ib_insync. Fuer die Beschriftung
Storno gegen Verfall genuegt es nicht — die haengt an Kanaelen, die diese
Fassung nur noch mitschreibt.
"""
from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import pytest

from ordertune_bridge_ibkr import main as m


@pytest.fixture(autouse=True)
def _reset():
    m._LAST_REPORTED.clear()
    m._ORDER_NOTICES.clear()
    yield
    m._LAST_REPORTED.clear()
    m._ORDER_NOTICES.clear()


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


# ── 2) Der Mitschnitt fuer B-1 ───────────────────────────────────────────────


def test_system_messages_are_not_recorded_against_an_order() -> None:
    """reqId -1 sind Verbindungs- und Marktdatenmeldungen ohne Auftragsbezug."""
    m.record_order_notice(-1, 2104, "Market data farm connection is OK")

    assert m._ORDER_NOTICES == {}


def test_the_notice_log_stays_bounded() -> None:
    """Ein monatelang laufender Client darf nicht unbegrenzt wachsen."""
    for i in range(m._ORDER_NOTICES_MAX + 50):
        m.record_order_notice(i, 202, "Order Canceled - reason:")

    assert len(m._ORDER_NOTICES) == m._ORDER_NOTICES_MAX
    # Der juengste Eintrag ist da, der aelteste nicht mehr.
    assert m.order_notice_for(m._ORDER_NOTICES_MAX + 49) is not None
    assert m.order_notice_for(0) is None


def test_the_error_callback_survives_an_unexpected_signature() -> None:
    """Eine Ausnahme hier laege im Ereignis-Thread von ib_insync.

    An dem Thread haengt der ganze Auftragsweg. Ein Mitschnitt, der nur
    protokolliert, darf ihn unter keinen Umstaenden anhalten.
    """
    on_error = m._make_on_ibkr_error()
    on_error(7, 202, "Order Canceled - reason:", None)
    on_error()  # aeltere Fassung, keine Argumente
    on_error("kein int", None, object())

    assert m.order_notice_for(7) == (202, "Order Canceled - reason:")


def test_both_channels_end_up_side_by_side_in_the_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Die Zeile, aus der B-1 entschieden wird.

    Beide Kanaele nebeneinander: was in `trade.log` steht und was ueber
    `errorEvent` kam. Aus `trade.log` allein ist ein Storno in TWS von einem
    Verfall zum Boersenschluss nicht zu unterscheiden — beide erzeugen
    `status='Cancelled'`, `message=''`, `errorCode=0`.
    """
    m.record_order_notice(42, 202, "Order Canceled - reason:")
    api = FakeApi()

    with caplog.at_level(logging.INFO):
        m._report_status(api, "d-6", make_trade("Cancelled", error_code=0), "cancelled")

    zeile = next(r.getMessage() for r in caplog.records if "T1-96-EVIDENCE" in r.getMessage())
    assert "dispatch=d-6" in zeile
    assert "log.errorCode=0" in zeile
    assert "notice.code=202" in zeile
    assert "tif=DAY" in zeile


def test_a_live_state_writes_no_evidence_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Nur Endzustaende. Ein lebender Auftrag meldet sich mehrfach je Sekunde."""
    api = FakeApi()

    with caplog.at_level(logging.INFO):
        m._report_status(api, "d-7", make_trade("Submitted"), "working")

    assert not any("T1-96-EVIDENCE" in r.getMessage() for r in caplog.records)
