"""T1-136 — der Ausstieg reist mit dem Einstieg.

Geprueft wird hier die Bauform des Paares, nicht die Sendeschleife: was
`_attached_exit` als Bein durchlaesst, und wie Parent und Kind zueinander
stehen, wenn sie IBKR erreichen. Die Schleife selbst haengt an einer
IBKR-Verbindung und steht im Papiertest, den der Spec als Ausrollsperre nennt.
"""

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
