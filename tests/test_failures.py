"""T1-101 A-2 — die Zuordnung von Ursache zu Klartext und Handlung.

Geprueft wird alles, was ohne TWS und ohne Plattform pruefbar ist: dass die
haeufigsten Verwechslungen auseinandergehalten werden, dass kein Geheimnis in
der Ausgabe landet, dass eine Formulierung nicht mehr behauptet als sie weiss,
und dass der Block auf jeder Windows-Codepage ausgebbar bleibt.
"""
from __future__ import annotations

import json

import httpx
import pytest
from pydantic import ValidationError

from ordertune_bridge_ibkr import failures
from ordertune_bridge_ibkr.config import BridgeConfig

# ── Konfiguration ────────────────────────────────────────────────────────────


def _validation_error(**values: object) -> ValidationError:
    """Ein echter Pydantic-Fehler, kein nachgebauter."""
    missing = "/nonexistent/does-not-exist.env"
    with pytest.raises(ValidationError) as caught:
        BridgeConfig(_env_file=missing, **values)  # type: ignore[call-arg]
    return caught.value


def test_a_missing_file_and_a_missing_field_are_told_apart() -> None:
    exc = _validation_error()

    missing = failures.classify_config_error(exc, "C:\\ot\\bridge.env", env_exists=False)
    present = failures.classify_config_error(exc, "C:\\ot\\bridge.env", env_exists=True)

    assert missing.code == "env_missing"
    assert present.code == "env_invalid", (
        "Fehlt die Datei ganz, meldet Pydantic dasselbe wie bei einer "
        "vorhandenen Datei mit fehlenden Zeilen. Ohne den Blick aufs "
        "Dateisystem bekaeme der haeufigste Fall die falsche Auskunft."
    )


def test_the_missing_file_message_names_where_it_looked() -> None:
    exc = _validation_error()
    failure = failures.classify_config_error(exc, "C:\\ot\\bridge.env", env_exists=False)
    assert "C:\\ot\\bridge.env" in "\n".join(failure.detail)


def test_the_token_value_is_never_printed() -> None:
    """Ein zu kurzer Token ist haeufig — sein Wert gehoert trotzdem nirgendwo hin."""
    secret = "ot_bridge_much_too_short"
    exc = _validation_error(
        ordertune_bridge_token=secret,
        ordertune_bridge_connection_id="c0ffee",
    )

    failure = failures.classify_config_error(exc, "bridge.env", env_exists=True)
    rendered = failures.render(failure)

    assert secret not in rendered, (
        "Der Wert landete sonst in der Konsole, im Protokoll und im naechsten "
        "Screenshot an den Support."
    )
    assert "ORDERTUNE_BRIDGE_TOKEN" in rendered, (
        "Das Feld muss benannt werden — sonst weiss der Nutzer nicht, welche "
        "Zeile er anfassen soll."
    )
    assert f"<{len(secret)} characters>" in rendered


def test_the_field_is_named_the_way_it_appears_in_the_file() -> None:
    exc = _validation_error(
        ordertune_bridge_token="x" * 40,
        ordertune_bridge_connection_id="c0ffee",
        ibkr_gateway_port="not-a-number",
    )
    rendered = failures.render(
        failures.classify_config_error(exc, "bridge.env", env_exists=True)
    )
    assert "IBKR_GATEWAY_PORT" in rendered


# ── TWS / Gateway ────────────────────────────────────────────────────────────

_BOOM = OSError("connection refused")


def test_a_different_answering_port_names_both_numbers() -> None:
    failure = failures.classify_connect_error(
        "127.0.0.1", 7497, _BOOM, answering=((7496, "TWS live"),)
    )
    rendered = failures.render(failure)

    assert failure.code == "tws_wrong_port"
    assert "7497" in rendered and "7496" in rendered, (
        "Die haeufigste Einrichtungsfalle ist in einem Satz erledigt — aber "
        "nur, wenn beide Zahlen darin vorkommen."
    )


def test_an_open_port_is_not_claimed_to_be_tws() -> None:
    """Auf 7496 koennte irgendein Dienst lauschen. Der Text darf das offenlassen."""
    rendered = failures.render(
        failures.classify_connect_error(
            "127.0.0.1", 7497, _BOOM, answering=((7496, "TWS live"),)
        )
    )
    assert "TWS runs on" not in rendered
    assert "not proof" in rendered


def test_an_answering_configured_port_points_at_the_api_switch() -> None:
    failure = failures.classify_connect_error(
        "127.0.0.1", 7497, _BOOM, answering=((7497, "TWS paper"),), client_id=17
    )
    rendered = failures.render(failure)

    assert failure.code == "tws_api_refused"
    assert "ActiveX and Socket Clients" in rendered
    assert "17" in rendered, "Die belegte Client-ID gehoert in die Meldung."


def test_nothing_answering_means_tws_is_not_running() -> None:
    failure = failures.classify_connect_error("127.0.0.1", 7497, _BOOM, answering=())
    assert failure.code == "tws_unreachable"
    assert "05:00 CET" in failures.render(failure), (
        "Der taegliche Abmeldezwang ist der zweite Grund, aus dem hier nichts "
        "antwortet — und der einzige, auf den niemand von selbst kommt."
    )


# ── Plattform ────────────────────────────────────────────────────────────────


def _http_error(status: int, body: str) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://t1.ordertune.com/api/bridge/v1/handshake")
    response = httpx.Response(status, text=body, request=request)
    return httpx.HTTPStatusError("boom", request=request, response=response)


@pytest.mark.parametrize(
    ("status", "wire_code", "expected"),
    [
        (401, "invalid_token", "token_invalid"),
        (401, "missing_token", "token_invalid"),
        (401, "connection_revoked", "connection_revoked"),
        (403, "ip_mismatch", "ip_mismatch"),
        (403, "fingerprint_mismatch", "fingerprint_mismatch"),
        (409, "fingerprint_already_set", "fingerprint_already_set"),
        (400, "missing_fingerprint", "fingerprint_missing"),
        (429, "rate_limited", "rate_limited"),
    ],
)
def test_every_platform_error_code_maps_to_its_own_failure(
    status: int, wire_code: str, expected: str
) -> None:
    body = json.dumps({"error": {"code": wire_code, "message": "nope"}})
    failure = failures.classify_handshake_error(_http_error(status, body))
    assert failure.code == expected


def test_a_wire_contract_mismatch_says_restarting_will_not_help() -> None:
    failure = failures.classify_handshake_error(_http_error(422, "{}"))
    rendered = failures.render(failure)

    assert failure.code == "wire_contract_mismatch"
    assert "Restarting will not fix it" in rendered
    assert "releases/latest" in rendered


def test_an_unreachable_platform_is_not_a_rejected_handshake() -> None:
    """Ohne HTTP-Status gab es keine Antwort — das ist eine andere Ursache."""
    failure = failures.classify_handshake_error(httpx.ConnectError("no route"))
    assert failure.code == "platform_unreachable"
    assert "no inbound port" in failures.render(failure)


def test_an_unknown_status_still_produces_a_usable_block() -> None:
    failure = failures.classify_handshake_error(_http_error(418, "teapot"))
    assert failure.code == "handshake_failed"
    assert "418" in failures.render(failure)


# ── Darstellung ──────────────────────────────────────────────────────────────


def test_the_block_is_pure_ascii() -> None:
    """Die Windows-Konsole laeuft je nach Gebietsschema ohne Rahmenzeichen.

    Ein UnicodeEncodeError beim Ausgeben der Fehlermeldung waere genau der
    Fehler, den dieser Baustein verhindern soll.
    """
    failure = failures.classify_connect_error(
        "127.0.0.1", 7497, OSError("Verbindung abgelehnt — kein Zugang"), answering=()
    )
    rendered = failures.render(failure, log_path="C:\\ordertune\\logs\\bridge.log")
    rendered.encode("ascii")  # wirft, wenn ein Zeichen durchgerutscht ist


def test_the_block_names_the_log_file_when_there_is_one() -> None:
    failure = failures.classify_connect_error("127.0.0.1", 7497, _BOOM, answering=())
    with_log = failures.render(failure, log_path="C:\\ot\\logs\\bridge.log")
    without_log = failures.render(failure)

    assert "C:\\ot\\logs\\bridge.log" in with_log
    assert "Log file:" not in without_log, (
        "Vor dem Einrichten des Protokolls gibt es keine Datei — auf eine zu "
        "verweisen, die nicht existiert, schickt den Nutzer ins Leere."
    )


def test_every_block_carries_its_reference_code() -> None:
    failure = failures.classify_handshake_error(
        _http_error(403, '{"error":{"code":"fingerprint_mismatch","message":"x"}}')
    )
    assert "Reference: fingerprint_mismatch" in failures.render(failure)


def test_the_settings_link_follows_a_custom_server() -> None:
    assert failures.settings_url("https://staging.example.com/") == (
        "https://staging.example.com/settings?tab=broker"
    )
    assert failures.settings_url() == "https://t1.ordertune.com/settings?tab=broker"
