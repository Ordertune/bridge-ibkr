"""T1-101 C — Erst-Start-Assistent, Einstellungen und das Schreiben.

Die Zusagen, die hier tragen:

  * `bridge.env` bleibt das Format auf der Platte (D8). Kommentarkopf und
    Token ueberleben jedes Speichern.
  * Token und Connection-ID werden nie getippt (D9) — auch nicht ueber einen
    Umweg im Schreibweg.
  * `IBKR_TRADING_MODE` verschwindet aus der Bedienung (D10).
  * Fremde Aenderungen an der Datei werden nicht stillschweigend ueberschrieben.
  * Nichts wird gespeichert, solange ein Auftrag unterwegs ist (C-5).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from ordertune_bridge_ibkr import console, env_file
from ordertune_bridge_ibkr import main as m
from ordertune_bridge_ibkr.cockpit import SetupActions, StateStore
from ordertune_bridge_ibkr.cockpit import setup as setup_mod

KOPF = """\
# Ordertune Bridge configuration
#
# IBKR default ports:
#   TWS 7497 paper / 7496 live, Gateway 4002 paper / 4001 live
ORDERTUNE_API_BASE=https://t1.ordertune.com
ORDERTUNE_BRIDGE_TOKEN=ot_bridge_0123456789abcdef0123456789abcdef
ORDERTUNE_BRIDGE_CONNECTION_ID=11111111-2222-3333-4444-555555555555

IBKR_GATEWAY_PORT=7497
IBKR_CLIENT_ID=17
LOG_LEVEL=INFO
"""


@pytest.fixture()
def env(tmp_path):
    p = tmp_path / "bridge.env"
    p.write_text(KOPF, encoding="utf-8")
    return p


# ── Das Schreiben (C-4 / D8) ─────────────────────────────────────────────────


def test_the_comment_header_survives(env) -> None:
    """Die Porttabelle im Kopf ist genau das, was der Nutzer spaeter braucht."""
    env_file.write_atomic(
        env, env_file.apply_changes(env.read_text("utf-8"), {"IBKR_GATEWAY_PORT": "4002"})
    )
    text = env.read_text("utf-8")
    assert "# Ordertune Bridge configuration" in text
    assert "TWS 7497 paper / 7496 live" in text
    assert "IBKR_GATEWAY_PORT=4002" in text
    assert "IBKR_GATEWAY_PORT=7497" not in text


def test_the_token_is_never_touched(env) -> None:
    vorher = env_file.parse(env.read_text("utf-8"))["ORDERTUNE_BRIDGE_TOKEN"]
    env_file.write_atomic(
        env, env_file.apply_changes(env.read_text("utf-8"), {"LOG_LEVEL": "DEBUG"})
    )
    assert env_file.parse(env.read_text("utf-8"))["ORDERTUNE_BRIDGE_TOKEN"] == vorher


def test_a_missing_key_is_appended_not_lost(env) -> None:
    env_file.write_atomic(
        env,
        env_file.apply_changes(env.read_text("utf-8"), {"UPDATE_CHECK_ENABLED": "false"}),
    )
    assert env_file.parse(env.read_text("utf-8"))["UPDATE_CHECK_ENABLED"] == "false"


def test_a_backup_is_kept(env) -> None:
    """Die Datei traegt den Zugang zu einem Depot. Sparen ist hier am teuersten."""
    env_file.write_atomic(env, "IBKR_CLIENT_ID=18\n")
    sicherung = env.with_suffix(env.suffix + env_file.BACKUP_SUFFIX)
    assert sicherung.exists()
    assert "ot_bridge_" in sicherung.read_text("utf-8")


def test_the_token_value_never_reaches_the_surface(env) -> None:
    sicht = env_file.redacted(env_file.parse(env.read_text("utf-8")))
    assert sicht["ORDERTUNE_BRIDGE_TOKEN"] == "...cdef"
    assert "0123456789" not in sicht["ORDERTUNE_BRIDGE_TOKEN"]
    assert sicht["IBKR_GATEWAY_PORT"] == "7497"


def test_trading_mode_is_not_offered_for_editing() -> None:
    """D10: ein Schalter, der nichts bewirkt, ist im Formular gefaehrlicher
    als in einer Textdatei — dort verspricht er eine Wirkung."""
    assert "IBKR_TRADING_MODE" not in env_file.EDITABLE


# ── Die Einstellungen (C-2 / C-5) ────────────────────────────────────────────


def _actions(env, *, in_flight: bool = False):
    return SetupActions(
        env, store=StateStore(), orders_in_flight=lambda: in_flight
    )


def test_saving_reports_that_a_restart_applies_it(env) -> None:
    a = _actions(env)
    r = a.save({"baseline": env_file.fingerprint(env),
                "changes": {"IBKR_CLIENT_ID": "18"}})
    assert r["ok"] is True
    assert "Restart" in r["message"]
    assert env_file.parse(env.read_text("utf-8"))["IBKR_CLIENT_ID"] == "18"


def test_saving_marks_the_restart_as_pending(env) -> None:
    store = StateStore()
    a = SetupActions(env, store=store, orders_in_flight=lambda: False)
    a.save({"baseline": env_file.fingerprint(env), "changes": {"LOG_LEVEL": "DEBUG"}})
    assert store.get()[0].pending_restart is True


def test_credentials_cannot_be_typed_through_the_settings(env) -> None:
    """D9 — auch nicht ueber den Umweg des Schreibwegs."""
    a = _actions(env)
    r = a.save({"baseline": env_file.fingerprint(env),
                "changes": {"ORDERTUNE_BRIDGE_TOKEN": "kurz"}})
    assert r["ok"] is False
    assert "Not editable" in r["message"]
    assert "ot_bridge_" in env.read_text("utf-8"), "Die Datei wurde trotzdem angefasst."


def test_an_order_in_flight_blocks_the_save(env) -> None:
    """Ein geaenderter Port waehrend eines lebenden Auftrags heisst beim
    naechsten Start: die Verbindung findet ihn nicht mehr."""
    r = _actions(env, in_flight=True).save(
        {"baseline": env_file.fingerprint(env), "changes": {"IBKR_GATEWAY_PORT": "4001"}}
    )
    assert r["ok"] is False
    assert "in flight" in r["message"]
    assert "IBKR_GATEWAY_PORT=7497" in env.read_text("utf-8")


def test_a_foreign_change_is_not_overwritten_silently(env) -> None:
    a = _actions(env)
    alt = env_file.fingerprint(env)

    env.write_text(KOPF + "IBKR_CLIENT_ID=99\n", encoding="utf-8")
    # Der Abdruck haengt an mtime_ns und Groesse; die Groesse hat sich geaendert.
    r = a.save({"baseline": alt, "changes": {"LOG_LEVEL": "DEBUG"}})

    assert r["ok"] is False
    assert r.get("conflict") is True
    assert "LOG_LEVEL=DEBUG" not in env.read_text("utf-8")


# ── Zugangsdaten ersetzen (C-3) ──────────────────────────────────────────────


def test_a_pasted_block_replaces_the_file(env) -> None:
    neu = (
        "ORDERTUNE_API_BASE=https://t1.ordertune.com\n"
        "ORDERTUNE_BRIDGE_TOKEN=ot_bridge_ffffffffffffffffffffffffffffffff\n"
        "ORDERTUNE_BRIDGE_CONNECTION_ID=99999999-8888-7777-6666-555555555555\n"
    )
    r = _actions(env).replace({"content": neu})
    assert r["ok"] is True
    assert env_file.parse(env.read_text("utf-8"))["ORDERTUNE_BRIDGE_TOKEN"].endswith("ffff")


def test_something_that_is_not_a_bridge_env_is_refused(env) -> None:
    r = _actions(env).replace({"content": "hallo, das ist meine Einkaufsliste"})
    assert r["ok"] is False
    assert "missing" in r["message"]
    assert "ot_bridge_0123" in env.read_text("utf-8"), "Die alte Datei wurde zerstoert."


# ── Der Assistent (C-1) ──────────────────────────────────────────────────────


def test_the_assistant_only_opens_when_somebody_is_there(monkeypatch) -> None:
    """Der Assistent wartet ohne Ende. Ist niemand da, ist das kein Assistent."""
    monkeypatch.setattr(console, "is_interactive", lambda: True)

    monkeypatch.setattr(console, "is_frozen", lambda: False)
    assert console.setup_wanted([]) is False
    assert console.setup_wanted(["--setup"]) is True

    monkeypatch.setattr(console, "is_frozen", lambda: True)
    assert console.setup_wanted([]) is True
    assert console.setup_wanted(["--headless"]) is False, (
        "Ein wartender Vorgang meldet keinen Herzschlag und ist fuer die "
        "Plattform nicht von einem Absturz zu unterscheiden."
    )


def test_a_packed_exe_without_a_console_never_waits(monkeypatch) -> None:
    """Der Fall, der den Release-Build zum Stehen gebracht hat.

    Der Smoke-Test des Workflows startet die fertige EXE in einem leeren
    Verzeichnis. Dort ist `is_frozen()` wahr, eine `bridge.env` gibt es nicht,
    und eine Eingabe kommt nie — der Assistent lief endlos, der Lauf hing
    zwoelf Minuten im Schritt „Smoke-test the built EXE".

    Dahinter der Fall, der nicht nur die Bauumgebung trifft: eine geplante
    Aufgabe oder ein Dienst startet die EXE ohne Konsole.
    """
    monkeypatch.setattr(console, "is_frozen", lambda: True)
    monkeypatch.setattr(console, "is_interactive", lambda: False)

    assert console.setup_wanted([]) is False, (
        "Gepackt, aber ohne Konsole: dort tippt niemand etwas ein."
    )
    assert console.setup_wanted(["--setup"]) is True, (
        "Ausdruecklich angefordert bleibt ausdruecklich angefordert."
    )


def test_the_assistant_does_not_run_headless(monkeypatch) -> None:
    monkeypatch.setattr(console, "is_frozen", lambda: True)
    from ordertune_bridge_ibkr.failures import Failure

    from pathlib import Path

    assert m.run_setup_cockpit(
        Failure(code="env_missing", headline="x"),
        Path("bridge.env"),
        ["--headless"],
    ) is False


def test_the_port_check_names_the_answering_port_instead(monkeypatch) -> None:
    from ordertune_bridge_ibkr import port_probe

    monkeypatch.setattr(
        port_probe, "port_answers", lambda h, p, timeout=0.0: p == 4002
    )
    r = setup_mod.check_socket("127.0.0.1", 7497)
    assert r["ok"] is False
    assert "4002" in r["message"]


def test_the_port_check_does_not_claim_more_than_it_knows(monkeypatch) -> None:
    """Ein offener Socket ist kein Beweis fuer TWS."""
    from ordertune_bridge_ibkr import port_probe

    monkeypatch.setattr(port_probe, "port_answers", lambda h, p, timeout=0.0: True)
    r = setup_mod.check_socket("127.0.0.1", 7497)
    assert r["ok"] is True
    assert "Something is listening" in r["message"]
    assert "TWS is running" not in r["message"]


# ── Der Riegel im Kern (C-5) ─────────────────────────────────────────────────


def test_orders_in_flight_sees_a_live_order() -> None:
    m._TRADES_BY_DISPATCH.clear()
    m._TRADES_BY_DISPATCH["d1"] = SimpleNamespace(
        order=SimpleNamespace(orderId=1),
        orderStatus=SimpleNamespace(status="Submitted"),
    )
    try:
        assert m.orders_in_flight() is True
    finally:
        m._TRADES_BY_DISPATCH.clear()


def test_orders_in_flight_ignores_settled_ones() -> None:
    m._TRADES_BY_DISPATCH.clear()
    m._TRADES_BY_DISPATCH["d1"] = SimpleNamespace(
        order=SimpleNamespace(orderId=1),
        orderStatus=SimpleNamespace(status="Filled"),
    )
    try:
        assert m.orders_in_flight() is False
    finally:
        m._TRADES_BY_DISPATCH.clear()
