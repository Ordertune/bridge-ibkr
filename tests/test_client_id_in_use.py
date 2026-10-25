"""TWS-Fehler 326 — die belegte Client-ID wird benannt, nicht geraten.

Ein Kunde schickte einen Screenshot der Meldung `tws_api_refused`: beide
Vermutungen („API-Freigabe aus" oder „Client-ID belegt") und darueber eine
leere Zeile, wo der Grund haette stehen sollen. Die leere Zeile war ein
`TimeoutError` von ib_insync — so endet der Handshake, wenn TWS mit 326
antwortet und den Socket schliesst.

TWS nennt den Grund also selbst. Gelesen hat ihn bis hierher niemand.

Ohne Netzwerk, ohne TWS.
"""
from __future__ import annotations

import pytest

from ordertune_bridge_ibkr import failures
from ordertune_bridge_ibkr.ibkr_client import (
    CLIENT_ID_IN_USE_CODE,
    ClientIdInUse,
    IbkrClient,
)

# Der englische TWS-Wortlaut. Angezeigt wird er, ausgewertet nie.
TWS_326 = "Unable to connect as the client id is already in use. Retry with a unique client id."


class _ErrorEvent:
    def __init__(self) -> None:
        self.handlers: list = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self


class _FakeIB:
    """Ein Handshake, der mit einem TWS-Fehler und einem Zeitueberlauf endet."""

    def __init__(self, *, error_code: int | None) -> None:
        self.errorEvent = _ErrorEvent()
        self._error_code = error_code

    def connect(self, host, port, clientId):
        if self._error_code is not None:
            for handler in self.errorEvent.handlers:
                handler(-1, self._error_code, TWS_326)
        # So kommt es bei ib_insync an: ohne Text.
        raise TimeoutError()


def _client(error_code: int | None) -> IbkrClient:
    client = IbkrClient(host="127.0.0.1", port=7497, client_id=17)
    client._ib = _FakeIB(error_code=error_code)
    return client


# ── A — der Client hoert hin ─────────────────────────────────────────────────


def test_the_code_constant_matches_on_both_sides() -> None:
    """Zwei Konstanten, weil `failures` ohne `ib_insync` auskommen soll."""
    assert CLIENT_ID_IN_USE_CODE == failures.CLIENT_ID_IN_USE == 326


def test_a_326_during_the_handshake_becomes_its_own_exception() -> None:
    client = _client(error_code=CLIENT_ID_IN_USE_CODE)

    with pytest.raises(ClientIdInUse) as caught:
        client.connect()

    assert caught.value.client_id == 17
    assert caught.value.tws_text == TWS_326
    assert "17" in str(caught.value)
    assert isinstance(caught.value.__cause__, TimeoutError)


def test_it_stays_a_connection_error() -> None:
    """Die Wiederverbindung faengt `Exception`; nichts dort darf sich aendern."""
    assert issubclass(ClientIdInUse, ConnectionError)


def test_without_a_326_the_original_error_passes_through() -> None:
    client = _client(error_code=None)
    with pytest.raises(TimeoutError):
        client.connect()


def test_another_error_code_is_not_read_as_a_busy_id() -> None:
    client = _client(error_code=502)
    with pytest.raises(TimeoutError):
        client.connect()


def test_a_326_from_an_earlier_attempt_does_not_stick() -> None:
    """Je Versuch neu: die Wiederverbindung ruft `connect()` mehrfach."""
    client = _client(error_code=CLIENT_ID_IN_USE_CODE)
    with pytest.raises(ClientIdInUse):
        client.connect()

    client._ib._error_code = None
    with pytest.raises(TimeoutError):
        client.connect()


# ── B — die Meldung sagt, was gewusst wird ───────────────────────────────────


def _failure() -> failures.Failure:
    return failures.classify_connect_error(
        "127.0.0.1",
        7497,
        ClientIdInUse(17, TWS_326),
        answering=((7497, "TWS paper"),),
        client_id=17,
    )


def test_a_known_busy_id_gets_its_own_failure() -> None:
    failure = _failure()
    rendered = failures.render(failure)

    assert failure.code == "tws_client_id_in_use"
    assert "17" in failure.headline
    assert "IBKR_CLIENT_ID" in rendered


def test_it_does_not_send_the_user_into_the_tws_settings() -> None:
    """Die API-Freigabe ist nachweislich an. Sie zu nennen waere die falsche Faehrte."""
    rendered = failures.render(_failure())
    assert "ActiveX" not in rendered
    assert "Read-Only" not in rendered


def test_it_names_the_case_the_run_file_cannot_see() -> None:
    """T1-222 sieht nur Bridges desselben Windows-Benutzers."""
    assert "another Windows user" in failures.render(_failure())


def test_the_text_is_ascii() -> None:
    failures.render(_failure()).encode("ascii")


def test_an_unknown_refusal_still_gets_the_old_answer() -> None:
    """Ohne 326 bleibt `tws_api_refused` — und die Zeile ist nicht mehr leer."""
    failure = failures.classify_connect_error(
        "127.0.0.1", 7497, TimeoutError(), answering=((7497, "TWS paper"),), client_id=17
    )
    assert failure.code == "tws_api_refused"
    assert "TimeoutError" in failure.detail[0]
