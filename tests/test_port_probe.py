"""T1-101 A-3 — die Portsuche klopft an und schickt nichts.

Gegen einen echten, selbst geoeffneten Socket geprueft, nicht gegen eine
Attrappe: die Zusage „ein reiner Verbindungsversuch, danach sofort zu" ist
sonst nicht belegt.
"""
from __future__ import annotations

import socket
from contextlib import closing

from ordertune_bridge_ibkr import port_probe


def _listening_port() -> tuple[socket.socket, int]:
    """Ein echter horchender Socket auf der Rueckschleife."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    return srv, srv.getsockname()[1]


def _closed_port() -> int:
    """Eine Portnummer, auf der garantiert nichts horcht."""
    with closing(socket.socket()) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


# ── Der Verbindungsversuch ───────────────────────────────────────────────────


def test_an_open_port_answers() -> None:
    srv, port = _listening_port()
    try:
        assert port_probe.port_answers("127.0.0.1", port) is True
    finally:
        srv.close()


def test_a_closed_port_does_not_answer() -> None:
    assert port_probe.port_answers("127.0.0.1", _closed_port()) is False


def test_the_probe_leaves_no_connection_behind() -> None:
    """Nach dem Klopfen darf der Socket nicht offen bleiben.

    Der Beleg: der horchende Socket nimmt die Verbindung an, und danach ist sie
    von der anderen Seite bereits geschlossen — `recv` liefert sofort leer
    statt zu blockieren.
    """
    srv, port = _listening_port()
    try:
        assert port_probe.port_answers("127.0.0.1", port) is True
        conn, _ = srv.accept()
        with closing(conn):
            conn.settimeout(2.0)
            assert conn.recv(16) == b"", (
                "Die Gegenseite hat entweder etwas gesendet oder haelt die "
                "Verbindung offen. Beides waere mehr als Anklopfen."
            )
    finally:
        srv.close()


# ── Die Auswahl der Ports ────────────────────────────────────────────────────


def test_only_the_four_ibkr_defaults_are_probed() -> None:
    """Ein breiterer Scan waere auf einem fremden VPS eine andere Handlung."""
    assert tuple(p for p, _ in port_probe.KNOWN_PORTS) == (7497, 7496, 4002, 4001)


def test_every_port_carries_the_label_the_user_sees_in_tws() -> None:
    labels = dict(port_probe.KNOWN_PORTS)
    assert labels[7497] == "TWS paper"
    assert labels[7496] == "TWS live"
    assert labels[4002] == "IB Gateway paper"
    assert labels[4001] == "IB Gateway live"


def test_the_scan_reports_only_what_answered(monkeypatch) -> None:
    monkeypatch.setattr(
        port_probe,
        "port_answers",
        lambda host, port, timeout=0.0: port in (7496, 4001),
    )
    assert port_probe.scan("127.0.0.1") == (
        (7496, "TWS live"),
        (4001, "IB Gateway live"),
    )


def test_a_silent_machine_yields_an_empty_result(monkeypatch) -> None:
    monkeypatch.setattr(
        port_probe, "port_answers", lambda host, port, timeout=0.0: False
    )
    assert port_probe.scan("127.0.0.1") == ()
