"""T1-94-Sonde: sie fragt, sie horcht nicht — und sie schickt nichts.

Am 2026-08-15 blieb das Protokoll leer, nachdem die Master API client ID auf 17
stand und der Owner von Hand eine Order gestellt hatte. Nicht einmal eine
Fehlermeldung. Die Sonde klaert, ob die Auskunft ueberhaupt erreichbar ist,
wenn man danach fragt statt darauf zu warten.

Geprueft wird hier alles, was ohne TWS pruefbar ist: die Erkennung des
Schalters, die Zuordnung eigener gegen fremde Auftraege, die Angaben, an denen
T1-94 haengt, und die Zusage, dass ein ausgefallener Abruf die anderen nicht
mitreisst.
"""
from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import pytest

from ordertune_bridge_ibkr import probe


# ── Der Schalter ─────────────────────────────────────────────────────────────


def test_the_flag_is_recognised() -> None:
    assert probe.probe_requested(["--probe-foreign"]) is True
    assert probe.probe_requested(["--verbose", "--probe-foreign"]) is True


def test_without_the_flag_the_bridge_runs_normally() -> None:
    assert probe.probe_requested([]) is False
    assert probe.probe_requested(["--probe"]) is False, (
        "Eine Teilzeichenkette darf die Sonde nicht ausloesen — sonst startet "
        "jemand die Bridge und sie liest nur."
    )


# ── Eigen gegen fremd ────────────────────────────────────────────────────────


def test_our_own_orders_carry_the_mark() -> None:
    assert probe.is_ours("ot-8f1d2c3e-4a5b-6c7d-8e9f-0a1b2c3d4e5f") is True


@pytest.mark.parametrize("ref", [None, "", "manual", "OT-gross", "xot-1"])
def test_everything_else_is_foreign(ref: Any) -> None:
    """Ohne unseren Vermerk gehoert der Auftrag uns nicht.

    Auch die Grossschreibung nicht: `orderRef` wird von uns kleingeschrieben
    gesetzt, und eine grosszuegige Pruefung wuerde einen fremden Auftrag als
    eigenen ausweisen — genau die Verwechslung, die T1-94 vermeiden muss.
    """
    assert probe.is_ours(ref) is False


# ── Die Angaben, an denen T1-94 haengt ───────────────────────────────────────


def _fremder_auftrag() -> SimpleNamespace:
    return SimpleNamespace(
        contract=SimpleNamespace(symbol="TXN"),
        order=SimpleNamespace(
            action="BUY", orderType="MKT", totalQuantity=1.0, lmtPrice=0.0,
            tif="DAY", orderId=61, clientId=0, permId=421610881, orderRef="",
        ),
        orderStatus=SimpleNamespace(status="Cancelled", filled=0.0),
    )


def test_a_foreign_order_is_marked_as_foreign() -> None:
    zeile = probe.describe_trade(_fremder_auftrag())
    assert "[FOREIGN]" in zeile
    assert "TXN" in zeile
    # Ohne diese vier ist eine fremde Zeile nicht buchbar.
    for feld in ("qty=1.0", "status=Cancelled", "orderId=61", "permId=421610881"):
        assert feld in zeile, feld


def test_one_of_ours_is_marked_as_ours() -> None:
    auftrag = _fremder_auftrag()
    auftrag.order.orderRef = "ot-8f1d2c3e"
    assert "[OURS" in probe.describe_trade(auftrag)


def test_a_fill_carries_what_an_external_row_would_need() -> None:
    """Herkunft, Menge, Kurs, Zeitpunkt, Gebuehr."""
    fill = SimpleNamespace(
        contract=SimpleNamespace(symbol="TXN"),
        execution=SimpleNamespace(
            side="BOT", shares=1.0, price=280.54, time="2026-08-17T13:31:07Z",
            orderId=61, clientId=0, permId=421610881, execId="0001a.01",
            orderRef="",
        ),
        commissionReport=SimpleNamespace(commission=1.0),
    )
    zeile = probe.describe_fill(fill)
    assert "[FOREIGN]" in zeile
    for feld in ("shares=1.0", "price=280.54", "time=", "commission=1.0"):
        assert feld in zeile, feld


# ── Verhalten der Sonde ──────────────────────────────────────────────────────


class FakeIbkr:
    """Antwortet auf die drei Abrufe. `fehler` laesst einen davon ausfallen."""

    def __init__(self, fehler: str | None = None) -> None:
        self.fehler = fehler
        self.aufgerufen: list[str] = []
        self.api_only_wert: Any = "nicht aufgerufen"

    def _vielleicht(self, name: str) -> None:
        self.aufgerufen.append(name)
        if self.fehler == name:
            raise RuntimeError(f"TWS verweigert {name}")

    def all_open_trades(self) -> list[Any]:
        self._vielleicht("all_open_trades")
        return [_fremder_auftrag()]

    def completed_trades(self, api_only: bool = False) -> list[Any]:
        self._vielleicht("completed_trades")
        self.api_only_wert = api_only
        return []

    def executions(self) -> list[Any]:
        self._vielleicht("executions")
        return []


def test_the_probe_asks_all_three_channels(caplog: pytest.LogCaptureFixture) -> None:
    ibkr = FakeIbkr()
    with caplog.at_level(logging.INFO):
        probe.run_probe(ibkr)

    assert ibkr.aufgerufen == ["all_open_trades", "completed_trades", "executions"]
    assert ibkr.api_only_wert is False, (
        "Mit apiOnly=True fielen genau die von Hand gestellten Auftraege heraus "
        "— also das, wonach gesucht wird."
    )


def test_a_refused_channel_does_not_take_the_others_down(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Eine Verweigerung ist selbst ein Ergebnis und darf den Rest nicht kosten."""
    ibkr = FakeIbkr(fehler="all_open_trades")
    with caplog.at_level(logging.INFO):
        probe.run_probe(ibkr)

    assert ibkr.aufgerufen == ["all_open_trades", "completed_trades", "executions"]
    assert any("ist gescheitert" in r.getMessage() for r in caplog.records)


def test_the_probe_never_sends_anything() -> None:
    """Die Zusage, die den ganzen Entwurf traegt: nur lesen.

    Ein Fake ohne Schreibmethoden. Griffe die Sonde nach `place_order` oder
    `cancel_order`, schluege der Aufruf hier fehl statt in der Produktion.
    """
    ibkr = FakeIbkr()
    probe.run_probe(ibkr)
    assert not hasattr(ibkr, "place_order")
    assert not hasattr(ibkr, "cancel_order")
