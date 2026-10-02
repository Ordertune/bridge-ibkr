"""T1-276 / T1-277 — die Bridge nennt ihre Depots und ihre Instanz.

Zugesichert wird vor allem, was NICHT passieren darf:

  1. „Nicht erhoben“ und „leere Liste“ bleiben auf der Leitung unterscheidbar.
  2. `_trading_account()` raet weiterhin nicht, und die neue Liste aendert daran
     nichts — sonst waere BUG-99-1 zurueck.
  3. Die Instanzkennung steht auf JEDER Anfrage, nicht nur am Herzschlag.
  4. Sie leitet sich NICHT aus der Maschine ab — sonst waere sie eine zweite
     Kopie des Fingerprints und trennte genau das nicht, wozu sie da ist.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest

from ordertune_bridge_ibkr.api_client import OrdertuneApiClient
from ordertune_bridge_ibkr.ibkr_client import IbkrClient
from ordertune_bridge_ibkr.instance_id import instanzkennung

FIXTURES = json.loads(
    (Path(__file__).parent / "contract" / "wire_fixtures.json").read_text("utf-8")
)

#: Muss mit `INSTANZ_KENNUNG_RE` auf der Plattform uebereinstimmen. Weicht das
#: eine ab, gilt die Kennung dort als „nicht angegeben“ — kein Fehler, aber eine
#: stille Luecke in der Zaehlung, und niemand saehe sie.
PLATTFORM_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


# ─── Aufzeichnung des Drahtverkehrs ──────────────────────────────────────────


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, str], Any]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        koerper: Any = None
        if request.content:
            koerper = json.loads(request.content)
        self.calls.append(
            (request.method, str(request.url), dict(request.headers), koerper)
        )
        return httpx.Response(200, json={"ok": True, "status": "ready"})


def _client(rec: _Recorder) -> OrdertuneApiClient:
    api = OrdertuneApiClient(
        base_url="https://t1.ordertune.com",
        token="test-token",
        connection_id="conn-1",
        fingerprint="a" * 64,
    )
    api._client = httpx.Client(
        transport=httpx.MockTransport(rec.handler),
        headers=dict(api._client.headers),
        base_url="",
    )
    return api


# ─── T1-277: die Kopfzeile auf JEDER Anfrage ─────────────────────────────────


def test_die_kennung_steht_auf_jeder_anfrage() -> None:
    """Nicht nur am Herzschlag — das ist der ganze Punkt.

    Herzschlag und Auftrags-Poll sind getrennte Endpunkte mit getrennten
    Intervallen. Eine Kopie, die den Herzschlag weglaesst und nur pollt, bekommt
    weiter Auftraege — und waere in einer Zaehlung, die am Herzschlag haengt,
    unsichtbar. Deshalb wird hier jeder Endpunkt einzeln geprueft.
    """
    rec = _Recorder()
    api = _client(rec)

    api.handshake(capabilities=None)
    api.heartbeat(
        cash=1.0, equity=2.0, currency="USD", positions=None, gateway_status="ok"
    )
    api.get_pending()
    api.ack_order("d-1", broker_order_id="42", submitted_at="2026-10-02T10:00:00Z")

    assert len(rec.calls) == 4, "nicht jeder Endpunkt wurde angefasst"
    for methode, url, header, _ in rec.calls:
        assert "x-bridge-instance" in header, (
            f"{methode} {url} ging OHNE Instanzkennung hinaus. Genau dieser "
            "Endpunkt waere dann in der Zaehlung unsichtbar."
        )
        assert PLATTFORM_RE.match(header["x-bridge-instance"]), (
            "Die Kennung passt nicht auf das Muster der Plattform — dort gilt "
            "sie damit als „nicht angegeben“, und die Luecke ist still."
        )


def test_die_kennung_ist_im_prozess_stabil() -> None:
    """Zwei Anfragen, eine Kennung. Sonst saehe jeder Schlag wie ein neuer Prozess aus."""
    rec = _Recorder()
    api = _client(rec)
    api.heartbeat(
        cash=1.0, equity=2.0, currency="USD", positions=None, gateway_status="ok"
    )
    api.heartbeat(
        cash=1.0, equity=2.0, currency="USD", positions=None, gateway_status="ok"
    )
    erste = rec.calls[0][2]["x-bridge-instance"]
    zweite = rec.calls[1][2]["x-bridge-instance"]
    assert erste == zweite


def test_die_kennung_leitet_sich_nicht_aus_der_maschine_ab() -> None:
    """Die tragende Eigenschaft, und sie ist eine Verneinung.

    Der Fingerprint ist maschinenweit: Hostname, Maschinenkennung, erste MAC.
    Eine Kennung, die daraus abgeleitet waere, trennte zwei Prozesse auf
    derselben Maschine NICHT — also genau den Fall, fuer den sie existiert.
    """
    import platform
    import uuid

    kennung = instanzkennung()
    assert kennung != platform.node()
    assert platform.node() not in kennung
    assert f"{uuid.getnode():012x}" not in kennung
    assert kennung != "a" * 64  # nicht der Fingerprint selbst


# ─── T1-276: die Depotliste auf der Leitung ──────────────────────────────────


def test_ohne_liste_fehlt_das_feld() -> None:
    """`None` heisst „nicht erhoben“, und das sagt man durch Weglassen.

    Dieselbe Regel wie bei `positions` (T1-99): ein leeres Array ist eine
    Aussage, ein fehlendes Feld ist Unwissen. Die beiden zu verwechseln hat am
    2026-08-18 zwei echte Positionen aus den Buechern genommen.
    """
    rec = _Recorder()
    api = _client(rec)
    api.heartbeat(
        cash=1.0,
        equity=2.0,
        currency="USD",
        positions=None,
        gateway_status="ok",
        managed_accounts=None,
    )
    snapshot = rec.calls[0][3]["accountSnapshot"]
    assert "managedAccounts" not in snapshot


def test_leere_liste_geht_als_aussage_hinaus() -> None:
    rec = _Recorder()
    api = _client(rec)
    api.heartbeat(
        cash=1.0,
        equity=2.0,
        currency="USD",
        positions=None,
        gateway_status="ok",
        managed_accounts=[],
    )
    snapshot = rec.calls[0][3]["accountSnapshot"]
    assert snapshot["managedAccounts"] == []


@pytest.mark.parametrize(
    "schluessel",
    ["heartbeatWithManagedAccounts", "heartbeatWithEmptyManagedAccounts"],
)
def test_herzschlag_trifft_den_vertrag(schluessel: str) -> None:
    erwartet = FIXTURES[schluessel]["body"]
    snap = erwartet["accountSnapshot"]
    pos = snap["positions"][0]

    rec = _Recorder()
    api = _client(rec)
    api.heartbeat(
        cash=snap["cash"],
        equity=snap["equity"],
        currency=snap["currency"],
        positions=[
            {
                "symbol": pos["symbol"],
                "qty": pos["qty"],
                "avg_cost": pos["avgEntryPriceUsd"],
                "market_value": pos["marketValueUsd"],
                "unrealized_pnl": pos["unrealizedPlUsd"],
                "market_price": pos["lastPrice"],
                "currency": pos["lastPriceCurrency"],
            }
        ],
        gateway_status=erwartet["gatewayStatus"],
        capabilities=snap["capabilities"],
        managed_accounts=snap["managedAccounts"],
    )
    assert rec.calls[0][3] == erwartet


def test_handschlag_trifft_den_vertrag() -> None:
    erwartet = FIXTURES["handshakeWithManagedAccounts"]["body"]
    rec = _Recorder()
    api = _client(rec)
    api.handshake(
        capabilities=erwartet["capabilities"],
        managed_accounts=erwartet["managedAccounts"],
    )
    assert rec.calls[0][3] == erwartet


# ─── T1-276: die Liste aendert die Kontowahl NICHT ───────────────────────────


@dataclass
class FakeIB:
    _accounts: list[str] = field(default_factory=lambda: ["DU1234567"])
    raises: bool = False

    def managedAccounts(self) -> list[str]:
        if self.raises:
            raise RuntimeError("kein Kontakt zur TWS")
        return self._accounts

    def isConnected(self) -> bool:
        return True


def _ibkr(ib: FakeIB) -> IbkrClient:
    c = IbkrClient(host="127.0.0.1", port=7496, client_id=17)
    c._ib = ib  # type: ignore[assignment]
    return c


def test_ein_konto_liste_und_handelskonto_stimmen_ueberein() -> None:
    c = _ibkr(FakeIB(_accounts=["DU1234567"]))
    assert c.managed_accounts() == ["DU1234567"]
    assert c._trading_account() == "DU1234567"


def test_mehrere_konten_liste_voll_handelskonto_leer() -> None:
    """Der Kern von T1-276, und die Grenze von BUG-99-1 in einem Test.

    Die Liste wird vollstaendig gemeldet — und `_trading_account()` raet
    weiterhin nicht. Wuerde es hier das erste Konto zurueckgeben, waere die
    Positionsgrenze aus BUG-99-1 gefallen und mit ihr die Mengenrechnung.
    """
    c = _ibkr(FakeIB(_accounts=["DU1111111", "DU2222222", "DU3333333"]))
    assert c.managed_accounts() == ["DU1111111", "DU2222222", "DU3333333"]
    assert c._trading_account() is None


def test_leere_liste_heisst_nicht_erhoben_nicht_keine_konten() -> None:
    """QA-Befund B1 — der Randfall, der eine Luege war.

    `ib_insync` fuellt `managedAccounts()` erst, wenn der Broker antwortet. Ein
    angemeldetes Login hat immer mindestens ein Konto, also kann eine leere Liste
    nie „keine Konten" heissen. Sie als Aussage weiterzugeben hiesse: die Flaeche
    behauptet „none are managed", und das Pruefprotokoll bekommt einen
    Depotzuwachs `0 → 3`, den es nie gab.
    """
    c = _ibkr(FakeIB(_accounts=[]))
    assert c.managed_accounts() is None


def test_leere_liste_wird_auf_der_leitung_weggelassen() -> None:
    """Und die Folge auf der Leitung: kein Feld, also „nicht erhoben"."""
    rec = _Recorder()
    api = _client(rec)
    c = _ibkr(FakeIB(_accounts=[]))
    api.heartbeat(
        cash=1.0,
        equity=2.0,
        currency="USD",
        positions=None,
        gateway_status="ok",
        managed_accounts=c.managed_accounts(),
    )
    assert "managedAccounts" not in rec.calls[0][3]["accountSnapshot"]


def test_kein_kontakt_heisst_nicht_erhoben_und_nicht_leer() -> None:
    """`None` statt `[]` — sonst meldete ein Verbindungsabriss „keine Depots“."""
    c = _ibkr(FakeIB(raises=True))
    assert c.managed_accounts() is None
