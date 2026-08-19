"""T1-101 B-1 — das Geruest des Cockpits.

Geprueft wird gegen einen **echten** laufenden Server, nicht gegen Attrappen:
die beiden Zusagen, die hier tragen, sind Aussagen ueber Sockets und lassen
sich nur so belegen.

  * Gebunden wird ausschliesslich auf die Rueckschleife. Eine Bindung auf
    0.0.0.0 loeste den Windows-Firewall-Dialog aus und stellte ein depotnahes
    Interface ins Netz.
  * Ohne Token geht nichts.

Dazu die Richtungsregel: der Server liest den Zustandsblock und schreibt nie
hinein.
"""
from __future__ import annotations

import json
import socket
import threading
import urllib.error
import urllib.request

import pytest

from ordertune_bridge_ibkr.cockpit import CockpitServer, CockpitState, StateStore
from ordertune_bridge_ibkr.cockpit.server import BIND_HOST


@pytest.fixture()
def server():
    srv = CockpitServer(StateStore(CockpitState(bridge_version="9.9.9")))
    srv.start()
    yield srv
    srv.stop()


def _get(url: str, timeout: float = 5.0) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


# ── Die Zugriffsgrenze ───────────────────────────────────────────────────────


def test_it_binds_the_loopback_only(server) -> None:
    """Gefragt wird das Betriebssystem, nicht die eigene Konstante.

    `server_address` setzt `socketserver` nach dem Binden aus `getsockname()`
    — es ist die Antwort des Kernels darauf, woran der Socket tatsaechlich
    haengt, und nicht der Wert, den wir hineingegeben haben.

    ## Warum hier zuerst etwas Klaemmeres stand

    Der erste Anlauf versuchte einen Beweis ueber das Verhalten: ein zweiter
    Socket bindet dieselbe Portnummer auf `0.0.0.0`; klappt das, kann der
    Server dort nicht haengen. Auf macOS geht das mit `SO_REUSEADDR` — auf
    Linux nicht, dort kollidiert ein Wildcard-Bind mit einem spezifischen auf
    demselben Port. Der Test war auf der einen Plattform gruen aus einem
    BSD-Detail und auf der anderen rot, obwohl der Server beide Male richtig
    gebunden war.

    Eine Zusicherung, deren Ergebnis von der Plattform abhaengt, sagt nichts
    ueber das Programm. Die schlichtere Frage ist auch die belastbarere.
    """
    assert server._httpd is not None
    gebunden = server._httpd.socket.getsockname()[0]
    assert gebunden == BIND_HOST, (
        f"Der Server haengt an {gebunden} statt an {BIND_HOST}. Das loest den "
        "Windows-Firewall-Dialog aus und stellt ein depotnahes Interface ins "
        "Netz."
    )


def test_without_the_token_nothing_is_served(server) -> None:
    for weg in ("/", "/state", "/events"):
        status, _ = _get(f"http://127.0.0.1:{server.port}{weg}")
        assert status == 403, f"{weg} war ohne Token erreichbar"


def test_a_wrong_token_is_rejected(server) -> None:
    status, _ = _get(f"http://127.0.0.1:{server.port}/state?t=raten-wir-mal")
    assert status == 403


def test_each_start_mints_a_new_token() -> None:
    """Eine liegengebliebene URL aus einer alten Sitzung ist nichts wert."""
    a = CockpitServer(StateStore())
    b = CockpitServer(StateStore())
    assert a.token != b.token
    assert len(a.token) >= 32


# ── Was ausgeliefert wird ────────────────────────────────────────────────────


def test_the_page_is_served(server) -> None:
    status, body = _get(server.url)
    assert status == 200
    assert "Ordertune Bridge" in body


def test_the_page_pulls_nothing_from_the_network(server) -> None:
    """Ein Fenster, das ohne Internet anders aussieht, ist dann kaputt, wenn es
    gebraucht wird.

    Gesucht wird nach **geladenen Quellen**, nicht nach dem blossen Vorkommen
    einer Adresse: seit dem Assistenten steht `https://t1.ordertune.com` als
    Platzhalter in einem Eingabefeld, und das ist Text und kein Nachladen. Der
    erste Anlauf dieser Zusicherung hat genau daran geschlagen — zu grob
    gefasst ist auch falsch.
    """
    _, body = _get(server.url)

    # Ein Ladevorgang braucht eines dieser Schluesselwoerter vor der Adresse.
    for muster in (
        'src="http', "src='http",
        'href="http', "href='http",
        "url(http", "@import",
        'fetch("http', "fetch('http",
    ):
        assert muster not in body, (
            f"Die Seite laedt eine externe Quelle: {muster}"
        )

    # Und keine Schrift von aussen, auch nicht ueber eine relative Angabe.
    assert "@font-face" not in body


def test_the_state_is_served_as_json(server) -> None:
    status, body = _get(f"http://127.0.0.1:{server.port}/state?t={server.token}")
    assert status == 200
    daten = json.loads(body)
    assert daten["state"]["bridge_version"] == "9.9.9"
    assert daten["version"] == 0


def test_an_unknown_path_is_a_404(server) -> None:
    status, _ = _get(f"http://127.0.0.1:{server.port}/nirgendwo?t={server.token}")
    assert status == 404


# ── Der Ereignisstrom ────────────────────────────────────────────────────────


def test_the_stream_pushes_the_current_state_and_then_changes(server) -> None:
    empfangen: list[dict] = []

    def lesen() -> None:
        with urllib.request.urlopen(  # noqa: S310
            f"http://127.0.0.1:{server.port}/events?t={server.token}", timeout=10
        ) as strom:
            for zeile in strom:
                if zeile.startswith(b"data: "):
                    empfangen.append(json.loads(zeile[6:].decode("utf-8")))
                    if len(empfangen) >= 2:
                        return

    leser = threading.Thread(target=lesen, daemon=True)
    leser.start()

    frist = 0.0
    while not empfangen and frist < 5.0:
        frist += 0.1
        threading.Event().wait(0.1)
    assert empfangen, "Der Strom hat den Ausgangszustand nie geschickt."

    server.store.update(bridge_version="1.2.3")
    leser.join(timeout=6.0)

    assert len(empfangen) >= 2, "Die Aenderung kam nie an."
    assert empfangen[-1]["state"]["bridge_version"] == "1.2.3"
    assert empfangen[-1]["version"] > empfangen[0]["version"]


# ── Die Richtungsregel ───────────────────────────────────────────────────────


def test_the_server_never_writes_to_the_state(server) -> None:
    """Der Kern schreibt, das Cockpit liest — durch die Bauform, nicht durch Disziplin."""
    _, vorher = server.store.get()
    for _ in range(3):
        _get(f"http://127.0.0.1:{server.port}/state?t={server.token}")
        _get(server.url)
    _, nachher = server.store.get()
    assert vorher == nachher, (
        "Der Zaehler hat sich durch blosses Lesen bewegt — dann schreibt der "
        "Server doch."
    )
