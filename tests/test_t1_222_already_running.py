"""T1-222 — es laeuft schon eine.

Gemessen am 2026-09-23: der Owner startete die fensterlose EXE ein zweites Mal
und bekam „Something answers on 127.0.0.1:7497, but the API connection was
refused" samt dem Verdacht, in der TWS sei die API-Freigabe aus. Sie war es
nicht — sonst haette die erste Instanz nicht verbunden. Kollidiert war die
Client-ID.

Die Auskunft lag bereit: `runfile.py` schreibt bei jedem Start Adresse und
Prozesskennung. Gelesen hat sie nur nie jemand.

Ohne Netzwerk, ohne zweiten Vorgang.
"""
from __future__ import annotations

import json
from pathlib import Path

from ordertune_bridge_ibkr import failures
from ordertune_bridge_ibkr.cockpit import runfile

WURZEL = Path(__file__).resolve().parent.parent


# ── A — die Datei wird gelesen ───────────────────────────────────────────────


def test_the_run_file_is_finally_read() -> None:
    """Der Befund selbst, als Zusicherung.

    Bis zum 2026-09-23 fand ein Grep ueber den Quellbaum `runfile.write` und
    `runfile.remove` — und keinen einzigen Leser.
    """
    quelle = (WURZEL / "src/ordertune_bridge_ibkr/main.py").read_text("utf-8")
    assert "laufende_instanz(" in quelle
    # Und zwar VOR dem Verbindungsversuch: danach waere die Kollision laengst
    # passiert und die Meldung wieder geraten.
    assert quelle.index("laufende_instanz(") < quelle.index("ibkr = IbkrClient(")


def test_a_missing_file_is_not_a_running_bridge(tmp_path) -> None:
    assert runfile.read(17, tmp_path) is None
    assert runfile.laufende_instanz(17, tmp_path) is None


def test_a_half_written_file_is_not_a_running_bridge(tmp_path) -> None:
    (tmp_path / "cockpit-17.json").write_text('{"url": "http://12', encoding="utf-8")
    assert runfile.read(17, tmp_path) is None
    assert runfile.laufende_instanz(17, tmp_path) is None


def test_something_that_is_not_an_object_is_refused(tmp_path) -> None:
    (tmp_path / "cockpit-17.json").write_text("[1, 2, 3]", encoding="utf-8")
    assert runfile.read(17, tmp_path) is None


# ── B — nur die Rueckschleife ────────────────────────────────────────────────


def test_only_loopback_addresses_are_ever_called() -> None:
    """AC-A4 — die Datei liegt im Nutzerprofil, aber sie ist kein Grund, beim
    Start irgendwohin zu verbinden."""
    for gut in (
        "http://127.0.0.1:52359/?t=abc",
        "http://localhost:8080/",
        "https://127.0.0.1:1/",
    ):
        assert runfile.ist_lokale_adresse(gut) is True, gut
    for schlecht in (
        "http://192.168.0.5:52359/",
        "http://example.com/?t=abc",
        "file:///C:/Windows/System32",
        "ftp://127.0.0.1/",
        "",
        None,
        12345,
    ):
        assert runfile.ist_lokale_adresse(schlecht) is False, schlecht


def test_a_foreign_address_is_never_probed(tmp_path, monkeypatch) -> None:
    gerufen: list[str] = []

    def darf_nicht(*a, **k):  # pragma: no cover - soll nie laufen
        gerufen.append("abruf")
        raise AssertionError("Es wurde eine fremde Adresse abgerufen.")

    import httpx

    monkeypatch.setattr(httpx, "Client", darf_nicht)
    assert runfile.laeuft_dort_eine("http://example.com/") is False
    assert gerufen == []


# ── C — liegengeblieben haelt niemanden auf ──────────────────────────────────


def test_a_stale_file_is_removed_and_the_start_continues(tmp_path, monkeypatch) -> None:
    """AC-D1 — ein abgewuergter Vorgang kommt nicht mehr zum Aufraeumen."""
    datei = tmp_path / "cockpit-17.json"
    datei.write_text(
        json.dumps({"url": "http://127.0.0.1:52359/?t=x", "pid": 999999}),
        encoding="utf-8",
    )
    monkeypatch.setattr(runfile, "laeuft_dort_eine", lambda url, timeout=1.0: False)

    assert runfile.laufende_instanz(17, tmp_path) is None
    assert not datei.exists(), "Die liegengebliebene Datei muss fort sein."


def test_a_live_cockpit_is_reported(tmp_path, monkeypatch) -> None:
    datei = tmp_path / "cockpit-17.json"
    datei.write_text(
        json.dumps({"url": "http://127.0.0.1:52359/?t=x", "pid": 4242}),
        encoding="utf-8",
    )
    monkeypatch.setattr(runfile, "laeuft_dort_eine", lambda url, timeout=1.0: True)

    assert runfile.laufende_instanz(17, tmp_path) == "http://127.0.0.1:52359/?t=x"
    assert datei.exists(), "Eine LEBENDE Instanz darf ihre Datei nicht verlieren."


def test_two_client_ids_do_not_see_each_other(tmp_path, monkeypatch) -> None:
    """AC-E1 — zwei Konten auf einer Maschine stoeren einander nicht."""
    (tmp_path / "cockpit-17.json").write_text(
        json.dumps({"url": "http://127.0.0.1:1/?t=x"}), encoding="utf-8"
    )
    monkeypatch.setattr(runfile, "laeuft_dort_eine", lambda url, timeout=1.0: True)

    assert runfile.laufende_instanz(17, tmp_path) is not None
    assert runfile.laufende_instanz(18, tmp_path) is None


# ── D — was die Meldung sagt, und was sie NICHT sagt ─────────────────────────


def test_the_message_names_the_window_and_no_suspect() -> None:
    text = failures.render(
        failures.bridge_laeuft_bereits("http://127.0.0.1:52359/?t=abc")
    )
    assert "already running" in text
    assert "127.0.0.1:52359" in text

    unten = text.lower()
    for falsche_faehrte in ("activex", "socket clients", "client id", "read-only"):
        assert falsche_faehrte not in unten, (
            f"Die Meldung verdaechtigt {falsche_faehrte!r} — genau die falsche "
            "Faehrte, die den Owner am 23.09. in die TWS-Einstellungen geschickt "
            "haette."
        )


def test_the_second_start_ends_with_zero() -> None:
    """AC-C1/C2 — der gewuenschte Zustand ist hergestellt.

    Eine 1 braechte eine geplante Aufgabe oder IBC dazu, es sofort wieder zu
    versuchen, in einer Schleife, die nie endet.
    """
    quelle = (WURZEL / "src/ordertune_bridge_ibkr/main.py").read_text("utf-8")
    block = quelle.split("laeuft_bereits = ", 1)[1].split("ibkr = IbkrClient(", 1)[0]
    assert "return 0" in block
    assert "return 1" not in block


def test_headless_gets_no_window_and_no_dialog() -> None:
    quelle = (WURZEL / "src/ordertune_bridge_ibkr/main.py").read_text("utf-8")
    block = quelle.split("laeuft_bereits = ", 1)[1].split("ibkr = IbkrClient(", 1)[0]
    # Fenster und Dialog haengen beide an einer Bedingung, die `--headless`
    # ausschliesst.
    assert "console.headless_requested(argv)" in block
    assert "console.dialog_wanted(argv)" in block
    assert block.index("console.headless_requested(argv)") < block.index("open_window")


# ── E — der echte Fall bleibt, wie er war ────────────────────────────────────


def test_a_genuinely_refused_api_still_says_so() -> None:
    """AC-E3 — diese Spec verengt `tws_api_refused`, sie ersetzt es nicht.

    Ein fremdes Programm auf der Client-ID hinterlaesst keine Ablagedatei; dann
    schweigt die Erkennung, und die alte Auskunft ist die richtige.
    """
    failure = failures.classify_connect_error(
        "127.0.0.1", 7497, OSError("refused"), answering=((7497, "TWS paper"),), client_id=17
    )
    assert failure.code == "tws_api_refused"
    assert "ActiveX" in failures.render(failure)


# ── F — der Text verspricht nichts, was es nicht gibt ────────────────────────


def test_the_message_does_not_promise_controls_that_do_not_exist() -> None:
    """Owner-Befund vom 2026-09-23, zweiter Probelauf.

    Die erste Fassung dieser Meldung sagte „close the running one first (its
    window has the controls)". Das Cockpit hat keine. Ein Grep nach Stop, Quit
    oder Shutdown findet in `page.py` nichts.

    Dahinter liegt eine Folge von T1-213, die beim Entwurf niemand
    ausgesprochen hat: bis dahin beendete der Kunde die Bridge, indem er ihr
    Konsolenfenster schloss. Das Fenster gibt es nicht mehr, ein Ersatz wurde
    nie gebaut — gemessen hat es der Owner, indem er beide Browserfenster
    schloss und der Herzschlag weiterlief.

    ## Warum diese Zusicherung BEIDE Seiten misst

    Sie verlangt den Verweis auf den Task-Manager **nur so lange**, wie das
    Cockpit wirklich keinen Knopf hat. Sobald jemand einen baut, wird sie rot
    und zwingt dazu, den Text mitzuziehen. Ein Text und eine Oberflaeche, die
    auseinanderlaufen koennen, ohne dass es jemand merkt, sind genau die Sorte
    Drift, gegen die dieses Projekt an einem Dutzend Stellen gebaut hat.
    """
    seite = (WURZEL / "src/ordertune_bridge_ibkr/cockpit/page.py").read_text("utf-8")
    hat_knopf = any(
        wort in seite
        for wort in ('id="stop"', 'id="quit"', "/shutdown", '"stopBridge"')
    )
    text = failures.render(failures.bridge_laeuft_bereits("http://127.0.0.1:1/?t=x"))

    if hat_knopf:
        assert "Task Manager" not in text, (
            "Das Cockpit hat jetzt einen Knopf — die Meldung muss ihn nennen "
            "statt den Task-Manager."
        )
    else:
        assert "Task Manager" in text, (
            "Ohne Knopf im Cockpit ist der Task-Manager der einzige wahre Weg."
        )
        assert "has the controls" not in text, (
            "Das war das falsche Versprechen vom 2026-09-23."
        )

    # Und die Aussage, die der Owner sich erarbeiten musste, steht jetzt da.
    assert "does not stop the Bridge" in text
