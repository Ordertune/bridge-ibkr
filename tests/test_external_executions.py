"""T1-94: fremde Ausfuehrungen erkennen, ohne die eigenen mitzunehmen.

## Der gemessene Fall

Am 2026-08-17 hat der Owner in TWS von Hand FTNT gekauft und wieder verkauft.
Die Sonde lieferte:

    [FOREIGN] FTNT BOT shares=1.0 price=157.21 time=2026-08-17 13:49:53+00:00
              permId=1433603962 execId=00015963.6a82ffde.01.01 commission=1.9
    [FOREIGN] FTNT SLD shares=1.0 price=156.88 time=2026-08-17 13:53:49+00:00
              permId=1433603965 execId=00018d30.6a830453.01.01 commission=1.9

Genau diese Zahlen stehen hier in den Attrappen. Was hier geprueft wird, ist
die Auswahl — die Stelle, an der ein Fehler doppelten Bestand erzeugen wuerde:

  1. Eine Ausfuehrung MIT unserem Vermerk darf nie als fremd gemeldet werden.
     Sie hat ihren eigenen Weg ueber /orders/{id}/result und stuende sonst
     zweimal in den Buechern.
  2. Eine Gebuehr von 0.0 ist kein Messwert, solange die Abrechnung fehlt.
     Unterscheidbar allein an der `execId` des Berichts.
  3. Die Richtung wird nie geraten.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from ordertune_bridge_ibkr import external_executions as ee


def make_fill(
    *,
    exec_id: str = "00015963.6a82ffde.01.01",
    perm_id: int = 1433603962,
    symbol: str = "FTNT",
    side: str = "BOT",
    shares: float = 1.0,
    price: float = 157.21,
    order_ref: str = "",
    commission: float | None = 1.9,
    zeit: datetime | None = None,
) -> SimpleNamespace:
    """Ein Fill, wie ib_insync ihn fuehrt.

    `commission=None` steht fuer „die Abrechnung ist noch nicht da" — dann
    traegt der Bericht eine leere `execId`, genau wie `CommissionReport()` sie
    beim Anlegen bekommt.
    """
    report = (
        SimpleNamespace(execId="", commission=0.0)
        if commission is None
        else SimpleNamespace(execId=exec_id, commission=commission)
    )
    return SimpleNamespace(
        contract=SimpleNamespace(symbol=symbol),
        execution=SimpleNamespace(
            execId=exec_id,
            permId=perm_id,
            side=side,
            shares=shares,
            price=price,
            orderRef=order_ref,
            time=zeit or datetime(2026, 8, 17, 13, 49, 53, tzinfo=timezone.utc),
        ),
        commissionReport=report,
    )


# ── 1) Eigen gegen fremd ─────────────────────────────────────────────────────


def test_one_of_ours_is_never_reported_as_external() -> None:
    """Der Riegel gegen doppelten Bestand.

    Eine Ausfuehrung mit `ot-`-Vermerk kommt ueber den Ergebnis-Endpunkt und
    ist dort einer Strategie zugeordnet. Zusaetzlich als extern gemeldet,
    stuende dasselbe Stueck zweimal im Depot — einmal zugeordnet, einmal
    herkunftslos.
    """
    unsere = make_fill(order_ref="ot-bc0bb7e5-a974-4638-ad56-09e443e17427")

    assert ee.external_execution_bodies([unsere], {}, set()) == []


@pytest.mark.parametrize("ref", ["", "manual", "OT-gross", "xot-1"])
def test_everything_without_our_mark_is_foreign(ref: str) -> None:
    bodies = ee.external_execution_bodies([make_fill(order_ref=ref)], {}, set())

    assert len(bodies) == 1
    assert bodies[0]["orderRef"] == ref


# ── 2) Die gemessenen Zahlen ─────────────────────────────────────────────────


def test_the_measured_buy_becomes_a_complete_body() -> None:
    bodies = ee.external_execution_bodies(
        [make_fill()], {"1433603962": "MKT"}, set()
    )

    assert bodies == [
        {
            "brokerExecId": "00015963.6a82ffde.01.01",
            "brokerPermId": "1433603962",
            "symbol": "FTNT",
            "side": "buy",
            "qty": 1.0,
            "price": 157.21,
            "executedAt": "2026-08-17T13:49:53Z",
            "orderType": "MKT",
            "orderRef": "",
            "commissionUsd": 1.9,
        }
    ]


def test_the_measured_sell_keeps_its_direction() -> None:
    verkauf = make_fill(
        exec_id="00018d30.6a830453.01.01",
        perm_id=1433603965,
        side="SLD",
        price=156.88,
        zeit=datetime(2026, 8, 17, 13, 53, 49, tzinfo=timezone.utc),
    )
    bodies = ee.external_execution_bodies([verkauf], {}, set())

    assert bodies[0]["side"] == "sell"
    assert bodies[0]["price"] == 156.88


def test_the_timestamp_is_the_z_form() -> None:
    """Python liefert `+00:00`, die Plattform weist den Offset mit 422 ab.

    Derselbe Fallstrick, den T1-78 an Ack und Ergebnis schon einmal gefunden
    hat — beide Seiten sahen fuer sich genommen plausibel aus.
    """
    body = ee.external_execution_bodies([make_fill()], {}, set())[0]

    assert body["executedAt"].endswith("Z")
    assert "+00:00" not in body["executedAt"]


# ── 3) Die Gebuehr ───────────────────────────────────────────────────────────


def test_a_missing_commission_is_omitted_not_zero() -> None:
    """Der Fehler, den die Sonde am 2026-08-17 gemacht hat.

    `CommissionReport()` traegt `commission = 0.0` als Vorgabewert. Wer ihn
    meldet, behauptet, es sei keine Gebuehr angefallen. Die Plattform schreibt
    ohne das Feld NULL — unbekannt statt null.
    """
    body = ee.external_execution_bodies(
        [make_fill(commission=None)], {}, set()
    )[0]

    assert "commissionUsd" not in body


def test_a_commission_of_zero_is_reported_when_it_is_real() -> None:
    """Eine echte Null ist eine Aussage und wird gemeldet.

    Unterschieden wird an der `execId` des Berichts, nicht am Betrag.
    """
    body = ee.external_execution_bodies(
        [make_fill(commission=0.0)], {}, set()
    )[0]

    assert body["commissionUsd"] == 0.0


# ── 4) Der Ordertyp ──────────────────────────────────────────────────────────


def test_the_order_type_comes_from_the_order_via_perm_id() -> None:
    """Die Ausfuehrung traegt ihn nicht — IBKR fuehrt ihn am Auftrag."""
    trades = [
        SimpleNamespace(order=SimpleNamespace(permId=1433603962, orderType="LMT"))
    ]
    typen = ee.order_types_by_perm_id(trades)
    body = ee.external_execution_bodies([make_fill()], typen, set())[0]

    assert body["orderType"] == "LMT"


def test_an_undeterminable_order_type_is_named_as_such() -> None:
    """Kein Raten. `UNKNOWN` sagt IBKR nie — der Wert ist als Nichtwissen lesbar.

    Die Alternative waere, die Ausfuehrung gar nicht zu melden. Dann ginge die
    Zeile verloren, und das ist der teurere Fehler: der Ordertyp ist an einer
    externen Zeile Beiwerk, die Ausfuehrung selbst ist der Zweck.
    """
    body = ee.external_execution_bodies([make_fill()], {}, set())[0]

    assert body["orderType"] == ee.UNKNOWN_ORDER_TYPE


# ── 5) Sparsamkeit und Vorsicht ──────────────────────────────────────────────


def test_what_was_already_reported_is_not_sent_again() -> None:
    """Der Abruf laeuft im Minutentakt — ohne das waeren es 60 Meldungen/Stunde."""
    bereits = {"00015963.6a82ffde.01.01"}

    assert ee.external_execution_bodies([make_fill()], {}, bereits) == []


def test_an_unknown_side_is_not_guessed() -> None:
    """Die Richtung eines Handels zu raten ist das Einzige, was hier verboten ist."""
    assert ee.external_execution_bodies(
        [make_fill(side="XYZ")], {}, set()
    ) == []


@pytest.mark.parametrize(
    "kaputt",
    [
        {"shares": 0.0},
        {"price": 0.0},
        {"exec_id": ""},
        {"symbol": ""},
    ],
)
def test_an_incomplete_execution_is_not_reported(kaputt: dict[str, Any]) -> None:
    """Lieber gar nichts als eine Zeile, die etwas Falsches behauptet."""
    assert ee.external_execution_bodies([make_fill(**kaputt)], {}, set()) == []


def test_a_fill_without_an_execution_does_not_crash() -> None:
    assert ee.external_execution_bodies([SimpleNamespace()], {}, set()) == []
