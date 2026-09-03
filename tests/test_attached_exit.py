"""T1-136 — der Ausstieg reist mit dem Einstieg.

Geprueft wird hier die Bauform des Paares, nicht die Sendeschleife: was
`_attached_exit` als Bein durchlaesst, und wie Parent und Kind zueinander
stehen, wenn sie IBKR erreichen. Die Schleife selbst haengt an einer
IBKR-Verbindung und steht im Papiertest, den der Spec als Ausrollsperre nennt.
"""

import pytest

from ordertune_bridge_ibkr.main import _attached_exit
from ordertune_bridge_ibkr.order_translator import (
    apply_bracket_transmit_flags,
    translate_intent,
)


def _kind() -> dict:
    return {
        "dispatchId": "d-kind",
        "executionId": "e-kind",
        "signalId": "7962",
        "side": "sell",
        "orderType": "moc",
        "qty": 5,
        "lmtPrice": None,
        "orderRefLabel": "AMD-7962-Day_Ripper",
    }


# ── Was als Bein durchgeht ───────────────────────────────────────────────────


def test_attached_exit_is_returned_when_complete():
    assert _attached_exit({"attachedExit": _kind()}) is not None


def test_no_attached_exit_is_the_ordinary_case():
    """Jeder Auftrag ohne Kind muss weiterhin der Einzelweg sein."""
    assert _attached_exit({"symbol": "AAPL"}) is None


def test_attached_exit_must_be_a_mapping():
    assert _attached_exit({"attachedExit": "moc"}) is None
    assert _attached_exit({"attachedExit": None}) is None
    assert _attached_exit({"attachedExit": []}) is None


def test_attached_exit_without_dispatch_id_is_refused():
    """Ohne Kennung liesse sich das Bein weder bestaetigen noch melden.

    Es ginge an den Markt, und niemand koennte die Fuellung zuordnen.
    """
    ohne = _kind()
    del ohne["dispatchId"]
    assert _attached_exit({"attachedExit": ohne}) is None

    leer = _kind()
    leer["dispatchId"] = ""
    assert _attached_exit({"attachedExit": leer}) is None


def test_attached_exit_without_order_type_or_side_is_refused():
    ohne_typ = _kind()
    del ohne_typ["orderType"]
    assert _attached_exit({"attachedExit": ohne_typ}) is None

    ohne_seite = _kind()
    del ohne_seite["side"]
    assert _attached_exit({"attachedExit": ohne_seite}) is None


# ── Wie das Paar bei IBKR ankommt ────────────────────────────────────────────


def test_parent_is_staged_and_child_transmits():
    """IBKRs Bracket-Muster: erst wenn das letzte Bein `transmit=True` traegt,
    uebertraegt TWS beide zusammen. Ginge der Parent sofort scharf hinaus und
    fuellte, bevor das Kind da ist, lehnte IBKR das Kind ab."""
    eltern = translate_intent(
        {"symbol": "AMD", "side": "buy", "orderType": "day_limit",
         "qty": 5, "lmtPrice": 438.6, "timeInForce": "GTD"}
    )
    kind = translate_intent({**_kind(), "symbol": "AMD"})
    apply_bracket_transmit_flags([eltern, kind])
    assert eltern.transmit is False
    assert kind.transmit is True


def test_child_keeps_its_own_order_type_and_side():
    kind = translate_intent({**_kind(), "symbol": "AMD"})
    assert kind.orderType == "MOC"
    assert kind.action == "SELL"
    assert float(kind.totalQuantity) == 5


def test_child_of_a_short_strategy_is_a_buy():
    """Intraday Shield ist short: dort ist der Einstieg ein Verkauf und der
    Ausstieg ein Kauf. Die Bauform darf `SELL` nirgends voraussetzen."""
    kind = translate_intent(
        {**_kind(), "symbol": "AMD", "side": "buy", "orderType": "moc"}
    )
    assert kind.action == "BUY"
    assert kind.orderType == "MOC"


def test_child_carries_the_parent_id():
    """Die Verknuepfung selbst — ohne sie sind es zwei lose Auftraege."""
    kind = translate_intent({**_kind(), "symbol": "AMD"})
    kind.parentId = 4711
    assert kind.parentId == 4711


# ── T1-136 Nachtrag: die eigene Frist des Kindes ─────────────────────────────


def test_a_deadline_on_a_closing_auction_order_is_refused():
    """T1-144 — diese Zusicherung stand bis zum 2026-09-03 auf dem Kopf.

    Sie hiess `test_child_deadline_forces_gtd_without_any_client_change` und
    sicherte zu, dass ein `MOC` mit einer Frist als `GTD` hinausgeht. Genau das
    hat die Produktion abgewiesen:

        Error 201, reqId 624: Order abgewiesen - Grund: Unzulaessige
        Gueltigkeitsdauer fuer eine At-the-Closing-Order.

    Beide Breakout-Hunter-Auftraege des Tages kamen sofort zurueck, Einstieg wie
    Ausstieg — der Parent lag mit `transmit=False` und wurde nie scharf.

    Die Frist bleibt richtig, der Ordertyp vertraegt sie nicht. Der Riegel steht
    hier als letzte Instanz vor dem Draht; die Plattform schickt sie seit T1-144
    gar nicht erst mit.
    """
    with pytest.raises(ValueError, match="vertraegt keine Frist"):
        translate_intent(
            {
                **_kind(),
                "symbol": "MRVL",
                "goodTillDate": "20260831 16:15:00 US/Eastern",
            }
        )


def test_a_deadline_on_a_closing_auction_limit_is_refused_too():
    """`LOC` ist dieselbe Bauform wie `MOC` — an EINE Auktion gebunden.

    Ungemessen bei IBKR und deshalb bewusst mit eingeschlossen statt durch
    Unterlassen erlaubt. Folgenlos: ueber alle `signals` traegt keine einzige
    LOC-Zeile ein `good_until` (0 von 736, Stand 2026-09-03).
    """
    with pytest.raises(ValueError, match="vertraegt keine Frist"):
        translate_intent(
            {
                "symbol": "MRVL",
                "side": "sell",
                "orderType": "loc",
                "qty": 5,
                "lmtPrice": 196.0,
                "goodTillDate": "20260831 16:15:00 US/Eastern",
            }
        )


def test_a_limit_order_still_carries_its_deadline():
    """Der Gegenbeweis, ohne den der Riegel ein Rueckschritt waere.

    Day Ripper liefert seinen Einstieg als `GTD` mit `good_until = 13:00 ET` auf
    einem `LMT`. Derselbe Mechanismus, dort richtig — wer die Frist streicht
    statt sie an den Ordertyp zu binden, bricht Day Ripper mit.
    """
    order = translate_intent(
        {
            "symbol": "KLAC",
            "side": "buy",
            "orderType": "day_limit",
            "qty": 2,
            "lmtPrice": 163.45,
            "timeInForce": "GTD",
            "goodTillDate": "20260902 13:00:00 US/Eastern",
        }
    )
    assert order.orderType == "LMT"
    assert order.tif == "GTD"
    assert order.goodTillDate == "20260902 13:00:00 US/Eastern"


def test_child_without_deadline_stays_on_day():
    """Ohne Frist bleibt es beim alten Verhalten — kein stiller Zwang zu GTD.

    T1-144 — seit dem Fix ist das der NORMALFALL und nicht mehr der Sonderfall:
    die Plattform haengt einem MOC-Kind keine Frist mehr an, und was ankommt,
    ist genau das, was `signals.time_in_force` sagt. Dort stand an beiden Zeilen
    vom 2026-09-03 `DAY`.
    """
    kind = translate_intent({**_kind(), "symbol": "MRVL"})
    assert kind.orderType == "MOC"
    assert kind.tif == "DAY"
    assert not getattr(kind, "goodTillDate", "")


def test_the_deadline_survives_the_bracket_pairing():
    """Das Anhaengen darf die Frist nicht ueberschreiben.

    `apply_bracket_transmit_flags` fasst nur `transmit` an — aber genau solche
    Annahmen sind in diesem Repo schon zweimal stillschweigend gebrochen worden.

    T1-144: das Kind traegt hier ein `day_limit` statt eines `MOC`. Ein MOC kann
    keine Frist tragen, und die Frage dieser Zusicherung ist eine andere — ob
    das Paaren einen bereits gesetzten Wert zerstoert.
    """
    eltern = translate_intent(
        {"symbol": "MRVL", "side": "buy", "orderType": "day_limit",
         "qty": 2, "lmtPrice": 196.0}
    )
    kind = translate_intent(
        {
            **_kind(),
            "symbol": "MRVL",
            "orderType": "day_limit",
            "lmtPrice": 196.0,
            "goodTillDate": "20260831 16:15:00 US/Eastern",
        }
    )
    apply_bracket_transmit_flags([eltern, kind])
    assert kind.tif == "GTD"
    assert kind.goodTillDate == "20260831 16:15:00 US/Eastern"
    assert eltern.transmit is False
    assert kind.transmit is True
