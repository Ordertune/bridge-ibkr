"""T1-405 — der Auftragszugriff ueberlebt das Neuverbinden.

## Der Befund (2026-11-13)

Auf mehreren Kunden-VPS stand im Fenster der Bridge 0.35.1 grau „Order access
unknown", obwohl TWS verbunden war, Herzschlaege rausgingen und Kontodaten
ankamen. Nur ein Neustart der Bridge half. Der Broker-Tab sagte daneben
„Setup complete".

Die Ursache: `report_disconnect` setzt den Zugriff beim Verbindungsverlust auf
„unknown" (T1-251, richtig), `connect()` misst ihn beim Neuverbinden neu
(T1-152d, richtig) — und `report_reconnect` hat das Ergebnis nie
zurueckgeschrieben. Die Lampe blieb bis zum naechsten Start der Bridge grau.

Dazu zwei Ergaenzungen: der Zugriff reist im Herzschlag zur Plattform, und ein
Zugriff, der nicht `writable` ist, wird in Abstaenden nachgemessen.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from ordertune_bridge_ibkr import main
from ordertune_bridge_ibkr import write_access as wa
from ordertune_bridge_ibkr.ibkr_client import (
    WRITE_ACCESS_RECHECK_INTERVAL_S,
    IbkrClient,
)


class _Ablage:
    def __init__(self) -> None:
        self.zustand: dict[str, Any] = {}

    def update(self, **werte: Any) -> None:
        self.zustand.update(werte)


def test_nach_dem_neuverbinden_steht_der_neue_befund_im_fenster() -> None:
    """Der Fall vom 2026-11-13, in zwei Schritten: Verlust, dann Rueckkehr."""
    ablage = _Ablage()
    cockpit = SimpleNamespace(store=ablage)

    main.report_disconnect(cockpit)
    assert ablage.zustand["write_access"] == "unknown"

    main.report_reconnect(
        cockpit,
        datetime(2026, 11, 13, 8, 6, tzinfo=timezone.utc),
        wa.WriteAccess(wa.WRITABLE),
    )

    assert ablage.zustand["tws_connected"] is True
    assert ablage.zustand["write_access"] == "writable", (
        "Nach dem Neuverbinden blieb „Order access unknown“ stehen — genau "
        "der Befund, der nur mit einem Neustart der Bridge heilte."
    )


def test_ein_read_only_nach_dem_neustart_wird_auch_gemeldet() -> None:
    """Die Gegenrichtung: eine TWS, die nach dem Neustart schreibgeschuetzt
    hochkommt, muss rot werden — mit IBKRs Wortlaut."""
    ablage = _Ablage()
    main.report_reconnect(
        SimpleNamespace(store=ablage),
        datetime(2026, 11, 13, tzinfo=timezone.utc),
        wa.WriteAccess(wa.CONFIRMED, "The API is in read-only mode."),
    )
    assert ablage.zustand["write_access"] == wa.CONFIRMED
    assert ablage.zustand["write_access_detail"] == "The API is in read-only mode."


def test_der_herzschlag_traegt_den_zugriff_ins_fenster() -> None:
    """Jeder Takt schreibt den Zugriff, nicht nur Start und Rueckkehr."""
    ablage = _Ablage()
    main.report_heartbeat(
        SimpleNamespace(store=ablage),
        True,
        None,
        write_access=wa.WriteAccess(wa.WRITABLE),
    )
    assert ablage.zustand["write_access"] == "writable"


def test_ohne_verbindung_bleibt_der_zugriff_unbekannt() -> None:
    """Ohne TWS ist der Befund Vergangenheit — er darf nicht zurueckkommen."""
    ablage = _Ablage()
    main.report_disconnect(SimpleNamespace(store=ablage))
    main.report_heartbeat(
        SimpleNamespace(store=ablage),
        False,
        None,
        write_access=wa.WriteAccess(wa.WRITABLE),
    )
    assert ablage.zustand["write_access"] == "unknown"


# ── Nachmessung ──────────────────────────────────────────────────────────────


class _FakeIB:
    def __init__(self, *, answers: bool) -> None:
        self.answers = answers
        self.calls = 0

    def reqOpenOrdersAsync(self):
        return object()

    def run(self, _coro, timeout=None):
        self.calls += 1
        if not self.answers:
            raise TimeoutError("open orders request timed out")
        return []


def _client(answers: bool) -> IbkrClient:
    client = IbkrClient(host="127.0.0.1", port=7496, client_id=17)
    client._ib = _FakeIB(answers=answers)
    return client


def test_eine_vermutung_wird_nach_der_frist_nachgemessen() -> None:
    """Ein langsamer TWS-Start ergibt `suspected` — das darf nicht bis zum
    naechsten Neustart stehen bleiben."""
    client = _client(answers=False)
    client._confirm_write_access()
    assert client.write_access().state == wa.SUSPECTED
    t0 = client._write_access_checked_at
    assert t0 is not None

    # Innerhalb der Frist: keine Anfrage.
    assert client.recheck_write_access_if_due(now=t0 + 60) is False
    assert client._ib.calls == 1

    # TWS antwortet inzwischen.
    client._ib.answers = True
    assert (
        client.recheck_write_access_if_due(now=t0 + WRITE_ACCESS_RECHECK_INTERVAL_S)
        is True
    )
    assert client.write_access().state == wa.WRITABLE


def test_ein_offener_zugriff_wird_nicht_nachgemessen() -> None:
    """`writable` kostet keine Anfrage: der Schalter wirkt erst nach einem
    TWS-Neustart, und dann misst `connect()`."""
    client = _client(answers=True)
    client._confirm_write_access()
    assert client.recheck_write_access_if_due(now=10**9) is False
    assert client._ib.calls == 1


def test_eine_bestaetigung_faellt_nicht_auf_eine_vermutung_zurueck() -> None:
    """Die 321er stammen aus dem Verbinden. Werden sie vor der Nachmessung
    geleert, stuende nach zehn Minuten „vermutet" statt „bestaetigt"."""
    client = _client(answers=False)
    client._on_error(-1, wa.VALIDATION_ERROR_CODE, "read-only mode")
    client._confirm_write_access()
    assert client.write_access().state == wa.CONFIRMED

    t0 = client._write_access_checked_at
    assert t0 is not None
    client.recheck_write_access_if_due(now=t0 + WRITE_ACCESS_RECHECK_INTERVAL_S)
    assert client.write_access().state == wa.CONFIRMED
