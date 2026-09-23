"""T1-178 — die Kopplung: ein Code statt einer Datei.

Die Zusicherung, auf die es ankommt, steht in
`test_the_secret_never_goes_on_the_wire`: der Server darf nur den HASH des
Geheimnisses sehen. Waere das anders, waere der ganze Entwurf sinnlos — dann
genuegte wieder der Code allein, und wer ihn mitliest, koppelt seine eigene
Maschine.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
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
        # T1-214: eine frisch geschriebene Datei traegt die TWS-Schreibweise.
        # Die alte bleibt gueltig, wird aber nicht mehr erzeugt — sonst legte
        # jede neue Installation wieder den Namen an, den wir loswerden wollen.
        "IBKR_TWS_HOST",
        "IBKR_TWS_PORT",
        "IBKR_CLIENT_ID",
        "LOG_LEVEL",
    ):
        assert schluessel in werte, schluessel
    assert werte["ORDERTUNE_BRIDGE_TOKEN"] == "tok"
    assert "IBKR_GATEWAY_PORT" not in werte, (
        "Die alte Schreibweise wird gelesen, aber nicht mehr geschrieben."
    )
    assert "IB Gateway" in p.read_text(encoding="utf-8"), (
        "Der Kopf sagt, WARUM es die TWS sein muss — das ist die Begruendung "
        "aus T1-207 und nicht ein Angebot."
    )


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


def test_the_file_route_is_still_offered() -> None:
    """Der Dateiweg bleibt neben der Kopplung bestehen.

    Ein Einrichtungsweg, der nur online funktioniert, waere ein Rueckschritt
    gegenueber einer Datei, die man auch hinlegen kann — und fuer
    unbeaufsichtigte Starts geht der Assistent ohnehin nicht auf.

    Diese Zusicherung stand zuerst im verify-Skript von t1 und las dafuer ueber
    die Repo-Grenze (`../ordertune-bridge-ibkr/...`). Lokal lief das, in CI ist
    dort nur t1 ausgecheckt und der Lauf starb mit ENOENT. Jede Seite sichert
    ihren eigenen Code zu.
    """
    from ordertune_bridge_ibkr.cockpit import setup as setup_mod
    from ordertune_bridge_ibkr.cockpit.page import PAGE_HTML

    assert hasattr(setup_mod, "replace_credentials")
    # Und die Flaeche bietet ihn an — eingeklappt unter dem neuen Schritt,
    # aber vorhanden.
    assert "Or paste a bridge.env you downloaded" in PAGE_HTML
    assert 'id="envbox"' in PAGE_HTML


# ── T1-181: ein wertloses Token ist dasselbe wie gar keins ───────────────────


def _abgewiesen(code: str, status: int = 401) -> Exception:
    class _A:
        def __init__(self) -> None:
            self.status_code = status
            self.text = '{"error":{"code":"%s","message":"nope"}}'.replace("%s", code)

    exc = RuntimeError("abgewiesen")
    exc.response = _A()  # type: ignore[attr-defined]
    return exc


@pytest.mark.parametrize(
    "code,status",
    [
        ("connection_revoked", 401),
        ("invalid_token", 401),
        ("missing_token", 401),
        ("fingerprint_already_set", 409),
    ],
)
def test_these_are_fixed_by_pairing_again(code: str, status: int) -> None:
    """Der Anlassfall des Owners und seine drei Geschwister.

    Wer im Broker-Tab trennt und die `bridge.env` liegen laesst, bekam beim
    naechsten Start einen Fehler statt eines Assistenten — obwohl der kuerzere
    Weg im selben Fenster steht.

    `fingerprint_already_set` gehoert dazu, obwohl es kein 401 ist: die
    Kopplung rotiert den Token, und das Rotieren loescht den gebundenen
    Fingerabdruck. Das ist der vorgesehene Ausweg beim Maschinenwechsel.
    """
    from ordertune_bridge_ibkr import failures

    assert failures.renewable_failure(_abgewiesen(code, status)) is not None


@pytest.mark.parametrize(
    "code,status",
    [
        ("fingerprint_mismatch", 403),
        ("rate_limited", 429),
        ("invalid_body", 422),
    ],
)
def test_these_are_not(code: str, status: int) -> None:
    """**Der Gegentest.**

    Ein Assistent, der bei jedem Fehlschlag aufgeht, ist kein Assistent — er
    verspricht eine Loesung, die er nicht hat. Wo eine neue Kopplung nichts
    aendert, bleibt es beim gerahmten Block.
    """
    from ordertune_bridge_ibkr import failures

    assert failures.renewable_failure(_abgewiesen(code, status)) is None


def test_a_network_error_does_not_open_the_assistant() -> None:
    from ordertune_bridge_ibkr import failures

    assert failures.renewable_failure(RuntimeError("connection reset")) is None


def test_the_assistant_waits_for_DIFFERENT_credentials(tmp_path, monkeypatch) -> None:
    """Nicht „laedt die Datei" — das tut sie die ganze Zeit.

    Ohne diese Unterscheidung kehrte der Assistent im Widerrufsfall sofort
    zurueck, weil die Vorgabe schon beim ersten Durchgang erfuellt waere.
    """
    from ordertune_bridge_ibkr import main as m

    stand = {"token": "alt"}
    monkeypatch.setattr(
        m, "load_config", lambda: SimpleNamespace(ordertune_bridge_token=stand["token"])
    )

    assert m._token_changed("alt") is False
    stand["token"] = "neu"
    assert m._token_changed("alt") is True


def test_an_unreadable_file_is_not_progress(monkeypatch) -> None:
    """Mitten im Schreiben gelesen: das ist noch kein Fortschritt, nur ein
    halber Zustand. Der naechste Durchgang kommt in zwei Sekunden."""
    from ordertune_bridge_ibkr import main as m

    def kaputt():
        raise ValueError("halb geschrieben")

    monkeypatch.setattr(m, "load_config", kaputt)
    assert m._token_changed("alt") is False
