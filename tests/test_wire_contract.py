"""T1-78: Vertragstest Client-Seite.

Prueft, dass `OrdertuneApiClient` exakt die Koerper erzeugt, die in
tests/contract/wire_fixtures.json stehen — und damit exakt das, was die
Zod-Schemata der Plattform akzeptieren.

Der Test faengt die Requests mit httpx.MockTransport ab, statt sie zu
verschicken. Kein Netz, kein Server, keine Zugangsdaten noetig.

Warum es diesen Test gibt: bis v0.1.0 hat niemand die beiden Seiten
gegeneinander gehalten. Der Handshake war seit dem ersten Tag inkompatibel
(422, Prozessende), und der Ergebnis-Endpunkt hat Menge und Preis
stillschweigend verworfen, weil die Feldnamen auseinanderliefen und
serverseitig alles optional war. Beides waere hier in der ersten Sekunde
aufgefallen.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from ordertune_bridge_ibkr import __version__
from ordertune_bridge_ibkr.api_client import OrdertuneApiClient

FIXTURES = json.loads(
    (Path(__file__).parent / "contract" / "wire_fixtures.json").read_text("utf-8")
)

DISPATCH_ID = "8f1d2c3e-4a5b-6c7d-8e9f-0a1b2c3d4e5f"


class _Recorder:
    """Faengt den letzten Request-Koerper ab."""

    def __init__(self) -> None:
        self.body: Any = None
        self.url: str = ""
        self.method: str = ""

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.method = request.method
        self.url = str(request.url)
        raw = request.content
        self.body = json.loads(raw) if raw else {}
        return httpx.Response(200, json={"ok": True})


def _client(rec: _Recorder) -> OrdertuneApiClient:
    api = OrdertuneApiClient(
        base_url="https://t1.ordertune.com",
        token="test-token",
        connection_id="conn-1",
        fingerprint="a" * 64,
    )
    # Ersetzt den Transport, laesst Header und Basis-URL unberuehrt.
    api._client = httpx.Client(
        transport=httpx.MockTransport(rec.handler),
        headers=dict(api._client.headers),
        base_url="",
    )
    return api


def test_bridge_version_matches_fixture() -> None:
    """Die Fixture nennt eine Version. Weicht der Build ab, ist die Fixture alt."""
    assert __version__ == FIXTURES["bridgeVersion"], (
        "Bridge-Version und Vertrags-Fixture laufen auseinander. Nach einem "
        "Versionssprung muessen BEIDE Kopien der Fixture angefasst werden — "
        "hier und in der Plattform unter scripts/fixtures/."
    )


def test_handshake_body_matches_contract() -> None:
    rec = _Recorder()
    api = _client(rec)
    api.handshake(capabilities=FIXTURES["handshake"]["body"]["capabilities"])

    assert rec.method == FIXTURES["handshake"]["method"]
    assert rec.url.endswith(FIXTURES["handshake"]["path"])
    assert rec.body == FIXTURES["handshake"]["body"], (
        "Handshake-Koerper weicht vom Vertrag ab. Genau diese Abweichung hat "
        "v0.1.0 daran gehindert, jemals eine Verbindung aufzubauen."
    )


def test_heartbeat_body_matches_contract() -> None:
    expected = FIXTURES["heartbeat"]["body"]
    snap = expected["accountSnapshot"]
    pos = snap["positions"][0]

    rec = _Recorder()
    api = _client(rec)
    # Bewusst im IBKR-Format hereingereicht (snake_case, avg_cost,
    # market_price) — die Uebersetzung ins Drahtformat ist genau das,
    # was hier geprueft wird.
    api.heartbeat(
        cash=snap["cash"],
        equity=snap["equity"],
        currency=snap["currency"],
        positions=[
            {
                "symbol": pos["symbol"],
                "qty": pos["qty"],
                "avg_cost": pos["avgEntryPriceUsd"],
                "market_price": 193.35,  # darf NICHT auf der Leitung landen
                "market_value": pos["marketValueUsd"],
                "unrealized_pnl": pos["unrealizedPlUsd"],
            }
        ],
        gateway_status="connected",
        capabilities=snap["capabilities"],
    )

    assert rec.method == FIXTURES["heartbeat"]["method"]
    assert rec.body == expected, (
        "Heartbeat-Koerper weicht vom Vertrag ab. v0.1.0 schickte hier "
        "{'snapshot': {...}} und wurde 60 Sekunden lang, endlos, mit 422 "
        "abgewiesen — als Warnung weggeloggt, nie bemerkt."
    )
    # cpuLoad ist optional und wird bewusst nicht gesendet: Telemetrie von
    # fremder Hardware, die niemand liest.
    assert "cpuLoad" not in rec.body


@pytest.mark.parametrize(
    "key", ["heartbeatForeignCurrency", "heartbeatUnknownCurrency"]
)
def test_heartbeat_carries_the_account_currency(key: str) -> None:
    """T1-85 — Betrag und Einheit reisen zusammen.

    Der EUR-Fall ist der Grund fuer diesen Vertragsbruch: bis 0.2.x hiess das
    Feld `equityUsd`, der Client konnte darin keinen EUR-Betrag unterbringen
    und meldete 0. Die Verbindung sah gesund aus und trug nie eine Order.

    `null` ist der zweite Fall und keine Abkuerzung fuer USD: er heisst, dass
    der Client die Waehrung nicht eindeutig bestimmen konnte.
    """
    expected = FIXTURES[key]["body"]
    snap = expected["accountSnapshot"]

    rec = _Recorder()
    api = _client(rec)
    api.heartbeat(
        cash=snap["cash"],
        equity=snap["equity"],
        currency=snap["currency"],
        positions=[],
        gateway_status="connected",
    )
    assert rec.body == expected
    assert "currency" in rec.body["accountSnapshot"], (
        "Die Waehrung ist Pflicht auf der Leitung. Fehlt sie, muesste die "
        "Plattform sie erraten — genau das soll T1-85 beenden."
    )


def test_heartbeat_no_longer_speaks_the_0_2_x_dialect() -> None:
    """Die alten Feldnamen duerfen nirgends mehr auftauchen.

    Gegen das strikte Serverschema waere `equityUsd` ein 422. Das ist gewollt:
    ein 0.2.x-Client soll laut scheitern statt einen EUR-Betrag als USD
    einzuliefern.
    """
    rec = _Recorder()
    api = _client(rec)
    api.heartbeat(
        cash=1.0,
        equity=2.0,
        currency="USD",
        positions=[],
        gateway_status="connected",
    )
    keys = set(rec.body["accountSnapshot"].keys())
    assert keys == {"cash", "equity", "currency", "positions"}
    assert "equityUsd" not in keys and "cashUsd" not in keys


def test_heartbeat_omits_unknown_broker_fields() -> None:
    """Serverschema ist strict — ein durchgereichtes Broker-Feld waere ein 422."""
    rec = _Recorder()
    api = _client(rec)
    api.heartbeat(
        cash=1.0,
        equity=2.0,
        currency="USD",
        positions=[
            {
                "symbol": "MSFT",
                "qty": 3.0,
                "avg_cost": 4.0,
                "market_price": 5.0,
                "market_value": 6.0,
                "unrealized_pnl": 7.0,
                "conId": 272093,  # IBKR-Eigenheit, gehoert nicht auf die Leitung
            }
        ],
        gateway_status="connected",
    )
    assert set(rec.body["accountSnapshot"]["positions"][0].keys()) == {
        "symbol",
        "qty",
        "avgEntryPriceUsd",
        "marketValueUsd",
        "unrealizedPlUsd",
    }


def test_ack_body_matches_contract() -> None:
    expected = FIXTURES["orderAck"]["body"]
    rec = _Recorder()
    api = _client(rec)
    api.ack_order(
        DISPATCH_ID,
        broker_order_id=int(expected["brokerOrderId"]),
        submitted_at=expected["submittedAtClient"],
    )
    assert rec.body == expected
    assert f"/orders/{DISPATCH_ID}/ack" in rec.url


def test_result_filled_matches_contract() -> None:
    expected = FIXTURES["orderResultFilled"]["body"]
    rec = _Recorder()
    api = _client(rec)
    api.result_order(
        DISPATCH_ID,
        status="filled",
        fill_qty=expected["fillQty"],
        fill_price=expected["fillPrice"],
        commission_usd=expected["commissionUsd"],
        filled_at=expected["filledAtClient"],
        broker_order_id=int(expected["brokerOrderId"]),
    )
    assert rec.body == expected, (
        "Ergebnis-Koerper weicht vom Vertrag ab. Genau hier gingen "
        "filled_qty und avg_fill_price verloren — der Server antwortete 200 "
        "und schrieb NULL."
    )
    # Die eine Zahl, an der die Bestandsfuehrung je Strategie haengt.
    assert rec.body["fillQty"] == 5.0


def test_result_limit_not_reached_matches_contract() -> None:
    """Nicht ausgefuehrt ist eine eigene Aussage, kein blosses 'cancelled'."""
    expected = FIXTURES["orderResultLimitNotReached"]["body"]
    rec = _Recorder()
    api = _client(rec)
    api.result_order(
        DISPATCH_ID,
        status="cancelled",
        fill_qty=0.0,
        fill_price=None,  # kein Handel, kein Preis
        filled_at=expected["filledAtClient"],
        reason_code="limit_not_reached",
        broker_order_id=int(expected["brokerOrderId"]),
    )
    assert rec.body == expected
    assert "fillPrice" not in rec.body, (
        "Ein Preis fuer eine nicht ausgefuehrte Order waere eine Erfindung."
    )


def test_result_cancel_confirmed_matches_contract() -> None:
    """T1-96 — der Nachweis reist mit, statt in der Bridge zu verpuffen.

    `cancel_is_genuine` unterscheidet seit T1-88b die Stornierung von IBKR von
    der, die ib_insync sich ausgedacht hat. Das Ergebnis blieb bis hierher im
    Client; auf der Leitung stand nur `cancelled`. Die Plattform musste daraus
    raten, ob das Ende belegt ist — und liess im Zweifel gesperrt, was ein
    Signal gekostet hat.
    """
    expected = FIXTURES["orderResultCancelConfirmed"]["body"]
    rec = _Recorder()
    api = _client(rec)
    api.result_order(
        DISPATCH_ID,
        status="cancelled",
        fill_qty=0.0,
        fill_price=None,
        filled_at=expected["filledAtClient"],
        reason_code="limit_not_reached",
        broker_order_id=int(expected["brokerOrderId"]),
        broker_confirmed_end=True,
    )
    assert rec.body == expected
    assert rec.body["brokerConfirmedEnd"] is True


def test_result_cancel_unconfirmed_is_an_explicit_false() -> None:
    """`False` ist eine Aussage und darf nicht als „nichts" durchrutschen.

    Faellt das Feld hier weg, liest die Plattform „keine Aussage" — und
    behandelt eine unbestaetigte Stornierung wie eine bestaetigte, sobald sie
    ihre Regel darauf stuetzt. Genau der Rueckschritt, gegen den T1-88b
    entstanden ist.
    """
    expected = FIXTURES["orderResultCancelUnconfirmed"]["body"]
    rec = _Recorder()
    api = _client(rec)
    api.result_order(
        DISPATCH_ID,
        status="cancelled",
        fill_qty=0.0,
        fill_price=None,
        filled_at=expected["filledAtClient"],
        reason_code="limit_not_reached",
        broker_order_id=int(expected["brokerOrderId"]),
        broker_confirmed_end=False,
    )
    assert rec.body == expected
    assert rec.body["brokerConfirmedEnd"] is False


def test_result_without_confirmation_omits_the_field() -> None:
    """Ohne Aussage kein Feld — das ist der Koerper jeder Bridge vor 0.4.0."""
    expected = FIXTURES["orderResultLimitNotReached"]["body"]
    rec = _Recorder()
    api = _client(rec)
    api.result_order(
        DISPATCH_ID,
        status="cancelled",
        fill_qty=0.0,
        fill_price=None,
        filled_at=expected["filledAtClient"],
        reason_code="limit_not_reached",
        broker_order_id=int(expected["brokerOrderId"]),
        broker_confirmed_end=None,
    )
    assert rec.body == expected
    assert "brokerConfirmedEnd" not in rec.body


def test_result_rejected_matches_contract() -> None:
    expected = FIXTURES["orderResultRejected"]["body"]
    rec = _Recorder()
    api = _client(rec)
    api.result_order(
        DISPATCH_ID,
        status="rejected",
        reason_code="sizing_drift",
        error_message=expected["errorMessage"],
    )
    assert rec.body == expected


@pytest.mark.parametrize(
    "key",
    [
        "handshake",
        "heartbeat",
        "heartbeatForeignCurrency",
        "heartbeatUnknownCurrency",
        "orderAck",
        "orderResultFilled",
        "orderResultCancelConfirmed",
        "orderResultCancelUnconfirmed",
    ],
)
def test_no_snake_case_keys_on_the_wire(key: str) -> None:
    """Kein Feldname im Drahtformat darf einen Unterstrich tragen.

    Der gesamte Ausfall von v0.1.0 laesst sich auf diese eine Regel
    zurueckfuehren.
    """

    def walk(node: Any) -> list[str]:
        found: list[str] = []
        if isinstance(node, dict):
            for k, v in node.items():
                if "_" in k:
                    found.append(k)
                found.extend(walk(v))
        elif isinstance(node, list):
            for item in node:
                found.extend(walk(item))
        return found

    assert walk(FIXTURES[key]["body"]) == []
