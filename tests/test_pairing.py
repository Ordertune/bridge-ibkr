"""T1-178 — die Kopplung: ein Code statt einer Datei.

Die Zusicherung, auf die es ankommt, steht in
`test_the_secret_never_goes_on_the_wire`: der Server darf nur den HASH des
Geheimnisses sehen. Waere das anders, waere der ganze Entwurf sinnlos — dann
genuegte wieder der Code allein, und wer ihn mitliest, koppelt seine eigene
Maschine.
"""
from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pytest

from ordertune_bridge_ibkr import env_file, pairing
from ordertune_bridge_ibkr.cockpit import SetupActions


class _Antwort:
    def __init__(self, daten: dict) -> None:
        self._daten = daten
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._daten


class _Client:
    """Faengt den Aufruf ab, statt ihn zu machen."""

    letzte: ClassVar[dict] = {}
    antwort: ClassVar[dict] = {}

    def __init__(self, *_, **__) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_) -> None:
        return None

    def post(self, url, json=None):
        type(self).letzte = {"url": url, "json": json or {}}
        return _Antwort(type(self).antwort)


@pytest.fixture()
def leitung(monkeypatch):
    _Client.letzte = {}
    _Client.antwort = {}
    monkeypatch.setattr(pairing.httpx, "Client", _Client)
    return _Client


# ── Der Kern ─────────────────────────────────────────────────────────────────


def test_the_secret_never_goes_on_the_wire(leitung) -> None:
    """**Die Zusicherung, die den Entwurf traegt.**

    Der Server bekommt `verifierHash`, nie `verifier`. Genau deshalb muss der
    Code nicht geheim sein: wer ihn mitliest, kann nichts abholen.
    """
    leitung.antwort = {"code": "ABCDE-FGHIJ", "expiresInSeconds": 600}
    ergebnis = pairing.start("https://t1.ordertune.com")

    koerper = leitung.letzte["json"]
    assert "verifierHash" in koerper
    assert "verifier" not in koerper
    assert koerper["verifierHash"] == pairing.sha256_hex(ergebnis["verifier"])
    assert len(koerper["verifierHash"]) == 64


def test_the_machine_travels_so_the_user_can_compare(leitung) -> None:
    """Hostname und Fingerabdruck gehen mit — sie sind der Riegel gegen
    Kopplungs-Phishing, und ohne sie waere der Bestaetigungsdialog blind."""
    leitung.antwort = {"code": "ABCDE-FGHIJ", "expiresInSeconds": 600}
    ergebnis = pairing.start("https://t1.ordertune.com")

    koerper = leitung.letzte["json"]
    assert koerper["hostname"]
    assert len(koerper["fingerprint"]) == 64
    # Was die Bridge anzeigt, muss der Ausschnitt sein, den t1 ebenfalls zeigt.
    assert ergebnis["fingerprint_prefix"] == koerper["fingerprint"][:16]
    assert pairing.FINGERPRINT_DISPLAY_LENGTH == 16


def test_two_verifiers_are_never_the_same() -> None:
    assert pairing.generate_verifier() != pairing.generate_verifier()
    assert len(pairing.generate_verifier()) >= 40


def test_the_claim_carries_code_and_secret(leitung) -> None:
    leitung.antwort = {"status": "pending"}
    pairing.claim("https://t1.ordertune.com", "ABCDE-FGHIJ", "geheim")

    assert leitung.letzte["json"] == {"code": "ABCDE-FGHIJ", "verifier": "geheim"}
    assert leitung.letzte["url"].endswith("/api/bridge/v1/pairing/claim")


@pytest.mark.parametrize(
    "antwort,erwartet",
    [
        ({"status": "pending"}, "pending"),
        ({"status": "unknown"}, "unknown"),
        ({"status": "ready", "token": "t", "connectionId": "c"}, "ready"),
    ],
)
def test_the_three_answers_are_passed_through(leitung, antwort, erwartet) -> None:
    leitung.antwort = antwort
    assert pairing.claim("https://x", "C", "v")["status"] == erwartet


# ── Die Datei ────────────────────────────────────────────────────────────────

BESTAND = """\
# meine eigene Notiz
ORDERTUNE_API_BASE=https://t1.ordertune.com
ORDERTUNE_BRIDGE_TOKEN=alt
ORDERTUNE_BRIDGE_CONNECTION_ID=alt
IBKR_GATEWAY_PORT=4001
IBKR_CLIENT_ID=42
LOG_LEVEL=DEBUG
"""


def test_an_existing_file_keeps_everything_the_user_set(tmp_path: Path) -> None:
    """Wer seinen Gateway-Port auf 4001 gestellt hat, soll ihn nach einer
    erneuten Kopplung nicht wieder suchen muessen."""
    p = tmp_path / "bridge.env"
    p.write_text(BESTAND, encoding="utf-8")

    pairing.write_credentials(
        p, api_base="https://t1.ordertune.com", token="neu", connection_id="neu-id"
    )

    werte = env_file.parse(p.read_text(encoding="utf-8"))
    assert werte["ORDERTUNE_BRIDGE_TOKEN"] == "neu"
    assert werte["ORDERTUNE_BRIDGE_CONNECTION_ID"] == "neu-id"
    assert werte["IBKR_GATEWAY_PORT"] == "4001"
    assert werte["IBKR_CLIENT_ID"] == "42"
    assert werte["LOG_LEVEL"] == "DEBUG"
    assert "# meine eigene Notiz" in p.read_text(encoding="utf-8")


def test_a_missing_file_is_written_complete(tmp_path: Path) -> None:
    p = tmp_path / "bridge.env"
    pairing.write_credentials(
        p, api_base="https://t1.ordertune.com", token="tok", connection_id="cid"
    )

    werte = env_file.parse(p.read_text(encoding="utf-8"))
    for schluessel in (
        "ORDERTUNE_API_BASE",
        "ORDERTUNE_BRIDGE_TOKEN",
        "ORDERTUNE_BRIDGE_CONNECTION_ID",
        "IBKR_GATEWAY_HOST",
        "IBKR_GATEWAY_PORT",
        "IBKR_CLIENT_ID",
        "LOG_LEVEL",
    ):
        assert schluessel in werte, schluessel
    assert werte["ORDERTUNE_BRIDGE_TOKEN"] == "tok"


# ── Der Vorgang ──────────────────────────────────────────────────────────────


def test_the_surface_never_sees_the_secret(leitung, tmp_path: Path) -> None:
    """Die Flaeche bekommt Code, Rechnernamen und Fingerabdruck — sonst nichts.

    Das Geheimnis lebt ausschliesslich im Vorgang; die Seite braucht es nicht
    und soll es nicht haben.
    """
    leitung.antwort = {"code": "ABCDE-FGHIJ", "expiresInSeconds": 600}
    actions = SetupActions(tmp_path / "bridge.env")

    antwort = actions.pair_start({})

    assert antwort["ok"] is True
    assert antwort["code"] == "ABCDE-FGHIJ"
    assert "verifier" not in antwort
    assert "token" not in antwort


def test_polling_without_a_running_pairing_is_not_a_crash(tmp_path: Path) -> None:
    actions = SetupActions(tmp_path / "bridge.env")
    antwort = actions.pair_poll({})
    assert antwort["ok"] is False
    assert antwort["status"] == "error"


def test_a_finished_pairing_writes_the_file_and_forgets_the_secret(
    leitung, tmp_path: Path
) -> None:
    p = tmp_path / "bridge.env"
    actions = SetupActions(p)

    leitung.antwort = {"code": "ABCDE-FGHIJ", "expiresInSeconds": 600}
    actions.pair_start({})

    leitung.antwort = {"status": "ready", "token": "geheim-tok", "connectionId": "cid"}
    antwort = actions.pair_poll({})

    assert antwort["status"] == "ready"
    assert env_file.parse(p.read_text(encoding="utf-8"))["ORDERTUNE_BRIDGE_TOKEN"] == (
        "geheim-tok"
    )
    # Zweiter Abruf: es gibt nichts mehr abzuholen, die Zeile ist auf der
    # Plattform geloescht.
    assert actions.pair_poll({})["ok"] is False
