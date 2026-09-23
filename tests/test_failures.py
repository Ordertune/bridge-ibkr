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


def _fehler_aus_datei(tmp_path, zeilen: str) -> ValidationError:
    """Ein Pydantic-Fehler aus einer ECHTEN Datei.

    T1-214: seit der Port zwei Schreibweisen hat (`IBKR_TWS_PORT` und das alte
    `IBKR_GATEWAY_PORT`), liest Pydantic ihn ueber einen `validation_alias`.
    Ein Schluesselwort-Argument mit dem Feldnamen erreicht ihn dann nicht mehr
    — und ein Test, der den Wert gar nicht erst zustellt, prueft nichts.
    """
    f = tmp_path / "bridge.env"
    f.write_text(
        "ORDERTUNE_BRIDGE_TOKEN=" + "x" * 40 + "\n"
        "ORDERTUNE_BRIDGE_CONNECTION_ID=c0ffee\n" + zeilen,
        encoding="utf-8",
    )
    with pytest.raises(ValidationError) as caught:
        BridgeConfig(_env_file=str(f))  # type: ignore[call-arg]
    return caught.value


def test_the_field_is_named_the_way_it_appears_in_the_file(tmp_path) -> None:
    """Der Name im Block ist der Name, den der Nutzer wirklich geschrieben hat.

    Beide Schreibweisen, beide Male die eigene: wer `IBKR_TWS_PORT` in der Datei
    stehen hat, darf nicht angewiesen werden, `IBKR_GATEWAY_PORT` zu suchen —
    und umgekehrt genauso.
    """
    # T1-214: welche der beiden Schreibweisen Pydantic meldet, entscheidet
    # Pydantic — und das faellt je nach Plattform verschieden aus (gemessen am
    # 2026-09-23: macOS nennt die aus der Datei, Windows die kanonische).
    # Deshalb wird nicht geraten: der Block nennt BEIDE, und die Zusicherung
    # prueft genau das. Eine Erwartung auf nur eine Schreibweise waere auf
    # einem der beiden Systeme dauerhaft rot gewesen.
    for zeile in ("IBKR_TWS_PORT=not-a-number\n", "IBKR_GATEWAY_PORT=not-a-number\n"):
        exc = _fehler_aus_datei(tmp_path, zeile)
        rendered = failures.render(
            failures.classify_config_error(exc, "bridge.env", env_exists=True)
        )
        assert "IBKR_TWS_PORT" in rendered, rendered
        assert "IBKR_GATEWAY_PORT" in rendered, rendered


def test_both_spellings_of_the_port_are_accepted(tmp_path) -> None:
    """T1-214 C-2/C-3 — die alte Schreibweise bleibt unbefristet gueltig.

    Jede ausgelieferte `bridge.env` traegt sie. Eine Installation durch eine
    Umbenennung stehenzulassen waere ein schlechterer Ausgang als ein Feldname,
    der an eine alte Entscheidung erinnert.
    """
    kopf = (
        "ORDERTUNE_BRIDGE_TOKEN=" + "x" * 40 + "\n"
        "ORDERTUNE_BRIDGE_CONNECTION_ID=c0ffee\n"
    )

    def lade(zeilen: str) -> BridgeConfig:
        f = tmp_path / "b.env"
        f.write_text(kopf + zeilen, encoding="utf-8")
        return BridgeConfig(_env_file=str(f))  # type: ignore[call-arg]

    assert lade("IBKR_GATEWAY_PORT=7496\n").ibkr_tws_port == 7496
    assert lade("IBKR_TWS_PORT=7496\n").ibkr_tws_port == 7496
    assert lade("IBKR_GATEWAY_HOST=1.2.3.4\n").ibkr_tws_host == "1.2.3.4"
    assert lade("IBKR_TWS_HOST=1.2.3.4\n").ibkr_tws_host == "1.2.3.4"

    beide = lade("IBKR_GATEWAY_PORT=7496\nIBKR_TWS_PORT=7497\n")
    assert beide.ibkr_tws_port == 7497, "Stehen beide da, gewinnt die neue."

    # Der alte Feldname bleibt als Lesezugriff, damit nichts im Baum zweimal
    # umgestellt werden muss — dieselbe Zahl, keine zweite Quelle.
    assert beide.ibkr_gateway_port == beide.ibkr_tws_port


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


def test_no_startup_failure_tells_the_customer_to_download_a_bridge_env(tmp_path) -> None:
    """T1-213 — Owner-Befund vom 2026-09-23, am ersten Probelauf der EXE.

    Der Assistent legt `bridge.env` seit T1-178 selbst an, sobald die Kopplung
    steht. Eine Startmeldung, die stattdessen zum Herunterladen auffordert,
    schickt den Kunden auf einen Umweg — und zwar an der auffaelligsten Stelle
    der ganzen Anwendung, unmittelbar ueber dem Knopf, der den kurzen Weg geht.

    Geprueft werden beide Faelle, die eine `bridge.env` betreffen: die fehlende
    und die fehlerhafte. Der zweite war in der ersten Fassung dieser Korrektur
    uebersehen worden.
    """
    fehlt = failures.render(
        failures.classify_config_error(
            _validation_error(), "C:\\ot\\bridge.env", env_exists=False
        )
    )
    kaputt = failures.render(
        failures.classify_config_error(
            _fehler_aus_datei(tmp_path, "IBKR_TWS_PORT=nope\n"),
            "C:\\ot\\bridge.env",
            env_exists=True,
        )
    )

    # Geprueft wird die AUFFORDERUNG, nicht das Wort: „nothing to download"
    # ist genau die richtige Aussage und darf nicht mitgefangen werden.
    aufforderungen = ("download the", "download a", "downloaden")
    for block, fall in ((fehlt, "env_missing"), (kaputt, "env_invalid")):
        unten = block.lower()
        for form in aufforderungen:
            assert form not in unten, (
                f"{fall} fordert zum Herunterladen auf ({form!r}):\n{block}"
            )
        assert "settings?tab=broker" not in unten, (
            f"{fall} verweist auf die Download-Flaeche:\n{block}"
        )

    # Und die fehlende Datei nennt den Weg, der wirklich gilt.
    assert "pair" in fehlt.lower()


def test_no_token_failure_tells_the_customer_to_download_a_bridge_env() -> None:
    """Owner-Befund vom 2026-09-23, ZWEITER Probelauf — und eine Lehre ueber
    Zusicherungen.

    Die Zusicherung darueber deckte nur die zwei Konfigurationsfaelle ab, weil
    das die zwei Stellen waren, die der erste Probelauf gezeigt hat. Sechs
    weitere standen in der Token-Familie, darunter der 401-Fall — und den hat
    der Owner beim naechsten Lauf als Meldungsfenster fotografiert.

    Eine Zusicherung, die genau den gemeldeten Fall prueft und nicht seine
    Gattung, findet den naechsten nicht. Diese hier geht ueber ALLE
    Handschlag-Stoerungen.

    Ausnahme mit Grund: `missing_fingerprint`. Dort ist die BRIDGE zu alt, und
    die will wirklich heruntergeladen werden.
    """
    from ordertune_bridge_ibkr.failures import _HANDSHAKE_BY_CODE

    for schluessel, (code, headline, detail, _) in _HANDSHAKE_BY_CODE.items():
        if code == "fingerprint_missing":
            continue
        text = " ".join(detail).lower()
        for form in ("download the", "download a", "download new"):
            assert form not in text, (
                f"{schluessel} fordert zum Herunterladen auf ({form!r}): {detail}"
            )
