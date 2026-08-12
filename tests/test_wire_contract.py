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
        cash_usd=snap["cashUsd"],
        equity_usd=snap["equityUsd"],
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


def test_heartbeat_omits_unknown_broker_fields() -> None:
    """Serverschema ist strict — ein durchgereichtes Broker-Feld waere ein 422."""
    rec = _Recorder()
    api = _client(rec)
    api.heartbeat(
        cash_usd=1.0,
        equity_usd=2.0,
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
    "key", ["handshake", "heartbeat", "orderAck", "orderResultFilled"]
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
