"""T1-231 Stufe 2 / T1-233 — der Stop-Ordertyp und die Klammer mit zwei Kindern.

Zwei Vorgaenge, ein Release. Sie gehoeren in eine Datei, weil sie dieselbe
Sache pruefen: was eine Intraday-Klammer bei IBKR ausmacht.

## Was hier belegt wird

  A  Der Stop legt seinen Ausloeser in `auxPrice`, nicht in `lmtPrice`.
  B  Die Klammer traegt ein ODER zwei Kinder, und nur das letzte uebertraegt.
  C  Die Deutung des Feldes ist eng — ein halbes Paar faellt ganz durch.

## Warum A nicht trivial ist

IBKR fuehrt zwei Preisfelder. `lmtPrice` ist die Zusage „nicht schlechter
als", `auxPrice` der Ausloeser „ab hier geht es an den Markt". Stuende der
Ausloeser in `lmtPrice`, waere der Auftrag ein Limit: er laege still am Markt
und loeste nie aus.

Auf der Plattformseite reist der Ausloeser im Feld `lmtPrice` des Intents —
der Draht fuehrt EINEN Preis je Auftrag, und welches IBKR-Feld daraus wird,
entscheidet der Ordertyp. Genau diese Uebersetzung steht hier.
"""
from __future__ import annotations

import pytest

from ordertune_bridge_ibkr.main import _attached_exits
from ordertune_bridge_ibkr.order_translator import (
    apply_bracket_transmit_flags,
    translate_intent,
)


def _intent(**over):
    basis = {
        "executionId": "e-1",
        "symbol": "DASH",
        "side": "sell",
        "orderType": "stop",
        "qty": 30,
        "lmtPrice": 169.42,
        "isSandbox": False,
        "clientOrderId": "ot-abc",
    }
    basis.update(over)
    return basis


def _kind(**over):
    basis = {
        "dispatchId": "d-kind",
        "executionId": "e-kind",
        "signalId": "11389",
        "side": "sell",
        "orderType": "moc",
        "qty": 30,
        "lmtPrice": None,
    }
    basis.update(over)
    return basis


# ── A — der Stop ────────────────────────────────────────────────────────────


def test_stop_puts_the_trigger_in_aux_price():
    """Der gemessene Fall vom 2026-09-24: DASH, Ausloeser 169,42."""
    o = translate_intent(_intent())
    assert o.orderType == "STP"
    assert o.auxPrice == pytest.approx(169.42)
    # `lmtPrice` bleibt 0.0 — sonst waere es ein Stop-Limit, und das gibt es in
    # 300 von 300 Zeilen der Anlieferung nicht.
    assert o.lmtPrice == 0.0


def test_stop_keeps_its_direction_and_quantity():
    o = translate_intent(_intent())
    assert o.action == "SELL"
    assert o.totalQuantity == 30


def test_stop_without_a_trigger_is_refused():
    """Ein Stop ohne Ausloeser ist kein Stop.

    Ihn als Marktauftrag abzusetzen waere genau der Fehler, gegen den T1-231
    gebaut ist: aus einem Auftrag, dessen Zweck das Warten ist, wuerde ein
    sofort ausgefuehrter Verkauf.
    """
    with pytest.raises(ValueError, match="Ausloeserpreis"):
        translate_intent(_intent(lmtPrice=None))


def test_an_unknown_order_type_is_still_refused():
    """Fail-closed bleibt fail-closed — der Stop macht daraus keine Einladung."""
    with pytest.raises(ValueError, match="Unsupported orderType"):
        translate_intent(_intent(orderType="trailing_stop"))


def test_the_other_order_types_are_untouched():
    assert translate_intent(_intent(orderType="moc", lmtPrice=None)).orderType == "MOC"
    assert translate_intent(_intent(orderType="market")).orderType == "MKT"
    lmt = translate_intent(_intent(orderType="day_limit", lmtPrice=198.30))
    assert lmt.orderType == "LMT"
    # Beim Limit gehoert der Preis in `lmtPrice` — die Gegenprobe zu A.
    assert lmt.lmtPrice == pytest.approx(198.30)


# ── B — die Klammer ─────────────────────────────────────────────────────────


def test_only_the_last_child_transmits():
    """Das IBKR-Bracket-Muster, jetzt mit zwei Kindern.

    Ginge der Parent frueher scharf hinaus und fuellte, lehnte IBKR die noch
    fehlenden Kinder ab — der Auftrag, an den sie sich haengen sollen, waere
    schon abgeschlossen. Bei einem Limit im Geld sind das Millisekunden.
    """
    eltern = translate_intent(_intent(orderType="day_limit", side="buy"))
    stop = translate_intent(_intent())
    moc = translate_intent(_intent(orderType="moc", lmtPrice=None))

    apply_bracket_transmit_flags([eltern, stop, moc])

    assert eltern.transmit is False
    assert stop.transmit is False
    assert moc.transmit is True


def test_a_single_child_still_works():
    """Bis zum 3. September war das der Normalfall."""
    eltern = translate_intent(_intent(orderType="day_limit", side="buy"))
    moc = translate_intent(_intent(orderType="moc", lmtPrice=None))
    apply_bracket_transmit_flags([eltern, moc])
    assert eltern.transmit is False
    assert moc.transmit is True


def test_the_children_carry_their_own_oca_group():
    """Fuellt eines, muss das andere verschwinden.

    Ob die Klammer das bei IBKR von sich aus leistet, ist noch nicht gemessen —
    bis dahin setzt die Plattform die Gruppe, und sie muss durchkommen.
    """
    o = translate_intent(_intent(ocaGroup="OCA_DASH_2026-09-24_entry11306", ocaType=3))
    assert o.ocaGroup == "OCA_DASH_2026-09-24_entry11306"
    assert o.ocaType == 3


# ── C — die Deutung des Feldes ──────────────────────────────────────────────


def test_two_children_are_read():
    kinder = _attached_exits(
        {"attachedExits": [_kind(dispatchId="d-stop", orderType="stop"), _kind()]}
    )
    assert len(kinder) == 2
    assert [k["orderType"] for k in kinder] == ["stop", "moc"]


def test_the_order_from_the_platform_is_kept():
    """Die Plattform sortiert: Stop zuerst, Schlussauktion zuletzt.

    Die Bridge sortiert NICHT nach. Zwei Stellen, die dieselbe Reihenfolge
    festlegen, laufen beim naechsten Ordertyp auseinander.
    """
    kinder = _attached_exits(
        {"attachedExits": [_kind(dispatchId="a", orderType="stop"), _kind(dispatchId="b")]}
    )
    assert [k["dispatchId"] for k in kinder] == ["a", "b"]


def test_a_half_broken_pair_falls_through_completely():
    """Ein Stop ohne seinen Partner ist kein Schutz, sondern ein Verkauf.

    Faellt EIN Bein durch die Pruefung, faellt die ganze Klammer — sonst laege
    ein einzelner Verkaufsauftrag am Markt, und das ist schlimmer als keine
    Klammer.
    """
    assert _attached_exits({"attachedExits": [_kind(), {"kaputt": True}]}) == []
    assert _attached_exits({"attachedExits": [_kind(), _kind(dispatchId="")]}) == []
    assert _attached_exits({"attachedExits": [_kind(), _kind(side=None)]}) == []


def test_the_old_single_key_is_not_read_any_more():
    """Eine Plattform, die noch `attachedExit` schickt, ist aelter als diese
    Bridge. Sie bekaeme sonst eine halbe Klammer."""
    assert _attached_exits({"attachedExit": _kind()}) == []
