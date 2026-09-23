"""T1-214 — die Bridge kennt nur noch die TWS.

Folgt aus T1-207: das IB Gateway hat keine Berichtsfunktion, und seit 0.25.0
haengt der Ausfallschutz genau daran. Die Entscheidung war gefallen, die
Oberflaechen boten das Gateway trotzdem weiter an.

Zwei Dinge bleiben ausdruecklich stehen, und beide haben hier ihre Zusicherung:
die alte Schreibweise in `bridge.env` und der Vertragsname `gatewayStatus` auf
dem Draht.
"""
from __future__ import annotations

from pathlib import Path

from ordertune_bridge_ibkr import failures, port_probe
from ordertune_bridge_ibkr.cockpit import state as state_mod

WURZEL = Path(__file__).resolve().parent.parent
QUELLE = WURZEL / "src" / "ordertune_bridge_ibkr"


def lies(rel: str) -> str:
    return (QUELLE / rel).read_text("utf-8")


# ── A — angeboten wird nur noch die TWS ──────────────────────────────────────


def test_the_generated_env_file_offers_tws_only() -> None:
    vorlage = lies("pairing.py")
    kopf = vorlage.split("IBKR local socket", 1)[1].split("Optional behavior", 1)[0]
    assert "IBKR_TWS_PORT={port}" in kopf
    assert "IBKR_GATEWAY_PORT=" not in kopf
    assert "paper 4002" not in kopf and "live 4001" not in kopf, (
        "Wer den Gateway-Ports folgt, baut ein Setup ohne Ausfallschutz."
    )
    assert "no such export function" in kopf, (
        "Der Kopf nennt den Grund. Eine Regel ohne Grund wird beim naechsten "
        "Durchgang zurueckgedreht."
    )


def test_the_assistant_never_names_the_gateway_as_an_option() -> None:
    for datei in ("cockpit/setup.py", "cockpit/page.py"):
        quelle = lies(datei)
        assert "Start TWS or IB Gateway" not in quelle, datei


def test_the_failure_texts_point_at_tws() -> None:
    quelle = lies("failures.py")
    assert "In IB Gateway: Configure" not in quelle
    assert "IBKR_GATEWAY_PORT={port}" not in quelle
    assert "IB Gateway 4002 paper / 4001 live." not in quelle


# ── B — wer schon auf dem Gateway sitzt, wird nicht im Dunkeln gelassen ───────


def test_a_gateway_only_machine_gets_its_own_answer() -> None:
    failure = failures.gateway_statt_tws(4001, ((4001, "IB Gateway live"),))
    assert failure.code == "gateway_not_tws"
    text = failures.render(failure)
    assert "needs TWS" in text
    assert "4001" in text
    assert "has no export function" in text, "Der Grund gehoert in die Auskunft."
    assert "keeps trading" in text, (
        "Es ist ein Hinweis und keine Sperre. Ein Riegel, der den Kunden "
        "haerter trifft als das Problem, ist keine Verbesserung."
    )


def test_the_detection_is_a_pure_function() -> None:
    assert port_probe.nur_gateway(((4002, "IB Gateway paper"),)) is True
    assert port_probe.nur_gateway(((7497, "TWS paper"), (4002, "x"))) is False
    assert port_probe.nur_gateway(()) is False


def test_the_running_bridge_never_stops_for_it() -> None:
    """Der Merker fuehrt zu einer Karte, nicht zu einem Abbruch."""
    quelle = (QUELLE / "main.py").read_text("utf-8")
    # Nur der Block selbst, nicht alles bis zur naechsten Marke: dazwischen
    # liegen die Sonde und der Verbindungsfehler, und beide duerfen sehr wohl
    # abbrechen.
    block = quelle.split("auf_gateway = ", 1)[1].split("\n    try:", 1)[0]
    assert "return" not in block, "Hier darf nichts abbrechen."
    assert "sys.exit" not in block
    assert "log.warning" in block


def test_the_hint_reaches_the_cockpit_not_just_the_log() -> None:
    assert hasattr(state_mod.CockpitState(), "gateway_instead_of_tws")
    seite = lies("cockpit/page.py")
    assert "gateway_instead_of_tws" in seite
    assert "gatewayInstead" in seite
    # Vor dem Export-Befund: das Gateway ist dessen Ursache.
    assert seite.index("if (gatewayInstead(s))") < seite.index("if (exportBroken(s))")


# ── C — die alte Schreibweise bleibt gueltig ─────────────────────────────────


def test_both_spellings_keep_working() -> None:
    quelle = lies("config.py")
    assert 'AliasChoices("IBKR_TWS_PORT", "IBKR_GATEWAY_PORT")' in quelle
    assert 'AliasChoices("IBKR_TWS_HOST", "IBKR_GATEWAY_HOST")' in quelle


def test_the_cockpit_still_reads_an_old_file() -> None:
    """Ein Kunde mit alter `bridge.env` darf kein leeres Feld sehen."""
    seite = lies("cockpit/page.py")
    assert "v.IBKR_TWS_PORT || v.IBKR_GATEWAY_PORT" in seite


# ── D — der Draht bleibt ─────────────────────────────────────────────────────


def test_the_wire_name_is_untouched() -> None:
    """`gatewayStatus` ist ein Vertragsname, kein Text fuer Menschen.

    Er steht im Vertrag aus T1-78, in den Fixtures, in der Heartbeat-Route und
    in einer Datenbankspalte. Ihn umzubenennen kostet eine Migration und einen
    Bruch gegenueber jeder ausgelieferten Fassung — und bringt dem Kunden
    nichts, weil er das Wort nie sieht.
    """
    assert '"gatewayStatus"' in lies("api_client.py")
    fixtures = (WURZEL / "tests/contract/wire_fixtures.json").read_text("utf-8")
    assert "gatewayStatus" in fixtures
    assert "gateway_status" in lies("ibkr_client.py")
