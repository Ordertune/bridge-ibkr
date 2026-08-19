"""T1-101 B-2 — die Regel aus der Messung vom 2026-08-19.

Der Owner hat den Schalter „Schreibgeschuetzte API" ein- und ausgeschaltet und
beide Protokolle geliefert. Mit Schreibschutz kam `Error 321` rund eine
Zehntelsekunde nach den Positionen, dazu vier Sekunden spaeter der
Zeitueberlauf von `open orders` und `completed orders`. Ohne: nichts von beidem.

Zwei Dinge stehen hier deshalb unter Zusicherung, und beide sind Fallen:

  * Erkannt wird am **Code**, nie am lokalisierten Text.
  * 321 allein reicht nicht — der Code ist allgemein.
"""
from __future__ import annotations

import pytest

from ordertune_bridge_ibkr import write_access as wa
from ordertune_bridge_ibkr.ibkr_client import WRITE_ACCESS_TIMEOUT_S, IbkrClient

# Woertlich aus dem Protokoll des Owners.
GEMESSEN_DE = (
    "Bei der Validierung der Anfrage ist ein Fehler aufgetreten.-'cp' : "
    "cause - Die API befindet sich im schreibgeschuetzten Modus."
)


def test_the_measured_case_is_a_verdict() -> None:
    """Beide Signale zusammen: das ist der gemessene Durchgang."""
    ergebnis = wa.classify(validation_errors=[GEMESSEN_DE], open_orders_answered=False)
    assert ergebnis.state == wa.CONFIRMED
    assert ergebnis.blocks_orders is True
    assert ergebnis.detail == GEMESSEN_DE, (
        "IBKRs Wortlaut gehoert an die Anzeige — er beantwortet die Frage des "
        "Nutzers vollstaendig."
    )


def test_a_healthy_connection_is_writable() -> None:
    """Die Gegenprobe: kein 321, kein Zeitueberlauf."""
    assert wa.classify(validation_errors=[], open_orders_answered=True).state == wa.WRITABLE


def test_a_timeout_without_the_error_is_only_a_suspicion() -> None:
    ergebnis = wa.classify(validation_errors=[], open_orders_answered=False)
    assert ergebnis.state == wa.SUSPECTED
    assert ergebnis.blocks_orders is True
    assert ergebnis.detail is None, "Ohne Meldung von IBKR gibt es nichts zu zitieren."


def test_a_lone_321_does_not_raise_the_alarm() -> None:
    """321 heisst „Fehler bei der Validierung" und kann auch anderes bedeuten.

    Antwortet der Auftragskanal, ist Schreiben erlaubt — dann darf ein
    einzelnes 321 aus anderem Anlass keinen Alarm ausloesen.
    """
    ergebnis = wa.classify(validation_errors=["irgendein anderer Validierungsfehler"],
                           open_orders_answered=True)
    assert ergebnis.state == wa.WRITABLE
    assert ergebnis.blocks_orders is False


@pytest.mark.parametrize(
    "text",
    [
        GEMESSEN_DE,
        "Error validating request.-'cp' : cause - The API is in read-only mode.",
        "La API se encuentra en modo de solo lectura.",
        "",
    ],
)
def test_the_wording_never_decides_anything(text: str) -> None:
    """Der Text ist lokalisiert. Eine Pruefung darauf funktionierte nur auf
    deutschen Installationen — und der Fehler faellt niemandem auf, weil die
    Bridge in beiden Faellen gesund aussieht."""
    assert wa.classify(validation_errors=[text], open_orders_answered=False).state == (
        wa.CONFIRMED
    )


# ── Die Verdrahtung im Client ────────────────────────────────────────────────


class _FakeIB:
    """Gerade so viel IB, wie `_confirm_write_access` anfasst."""

    def __init__(self, *, answers: bool) -> None:
        self._answers = answers
        self.calls = 0
        self.gefragt: list[str] = []
        self.fristen: list[float | None] = []

    def reqOpenOrdersAsync(self):  # noqa: N802 - Name kommt von ib_insync
        self.gefragt.append("reqOpenOrders")
        return object()

    def reqAllOpenOrdersAsync(self):  # noqa: N802 - Name kommt von ib_insync
        self.gefragt.append("reqAllOpenOrders")
        return object()

    def run(self, _coro, timeout=None):
        self.calls += 1
        self.fristen.append(timeout)
        if not self._answers:
            raise TimeoutError("open orders request timed out")
        return []


def _client(answers: bool):
    client = IbkrClient(host="127.0.0.1", port=7496, client_id=17)
    client._ib = _FakeIB(answers=answers)
    return client


def test_the_client_asks_the_order_channel_and_reads_the_answer() -> None:
    client = _client(answers=True)
    client._confirm_write_access()

    assert client._ib.calls == 1, "Die Anfrage wurde nicht gestellt."
    assert client.write_access().state == wa.WRITABLE


def test_it_asks_for_our_own_orders_not_for_all_of_them() -> None:
    """Am 2026-08-19 gemessen — und der Unterschied ist die ganze Erkennung.

    Unter Schreibschutz verweigert TWS `reqOpenOrders` (die eigenen), aber
    `reqAllOpenOrders` (alle Clients) antwortet weiterhin und liefert sogar die
    von Hand gestellte Order. Wer hier auf `reqAllOpenOrders` umstellt, weil es
    „dasselbe" tut, schaltet die Erkennung stumm ab.
    """
    client = _client(answers=True)
    client._confirm_write_access()

    assert client._ib.gefragt == ["reqOpenOrders"], (
        f"Gefragt wurde {client._ib.gefragt}. `reqAllOpenOrders` antwortet auch "
        "unter Schreibschutz — damit wuerde nie wieder etwas erkannt."
    )


def test_the_request_carries_a_deadline() -> None:
    """Ohne Frist haengt der Aufruf unter Schreibschutz endlos.

    `IB.reqCompletedOrders` und `IB.reqAllOpenOrders` laufen ueber `_run()`
    **ohne** Frist; Fehler 321 kommt mit `reqId -1` und loest die wartende
    Anfrage nicht auf. Am 2026-08-19 stand die Sonde deshalb ueber eine Minute
    im selben Aufruf, waehrend die Ereignisschleife weiterlief (T1-103).
    Dieser Weg hier darf denselben Fehler nicht wiederholen.
    """
    client = _client(answers=True)
    client._confirm_write_access()

    assert client._ib.fristen == [WRITE_ACCESS_TIMEOUT_S]
    assert client._ib.fristen[0] is not None


def test_the_client_combines_the_error_with_the_timeout() -> None:
    """Der gemessene Fall, durch die Verdrahtung hindurch."""
    client = _client(answers=False)
    client._on_error(-1, wa.VALIDATION_ERROR_CODE, GEMESSEN_DE)

    client._confirm_write_access()

    zugriff = client.write_access()
    assert zugriff.state == wa.CONFIRMED
    assert zugriff.detail == GEMESSEN_DE


def test_the_client_ignores_every_other_error_code() -> None:
    """Nur 321 wird gesammelt — der Rueckruf darf nichts entscheiden."""
    client = _client(answers=False)
    client._on_error(-1, 2104, "Verbindung zum Marktdatenzentrum ist OK:usfarm")
    client._on_error(-1, 201, "Order abgewiesen")

    client._confirm_write_access()

    assert client.write_access().state == wa.SUSPECTED, (
        "Ein Marktdaten-Hinweis oder eine Auftragsablehnung sind keine Aussage "
        "ueber den Schreibzugriff."
    )


def test_the_default_says_nothing() -> None:
    """Vor der Messung ist der Zustand unbekannt, nicht `gut`."""
    leer = wa.WriteAccess()
    assert leer.state == wa.UNKNOWN
    assert leer.blocks_orders is False, (
        "Unbekannt darf keine Warnung ausloesen — sonst steht sie bei jedem "
        "Start eine Sekunde lang rot da."
    )
