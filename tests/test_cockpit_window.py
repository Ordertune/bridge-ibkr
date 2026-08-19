"""T1-101 B-6 — die Kette Edge -> Browser -> URL.

Drei Stufen, jede fuer sich ausreichend. Der Rueckgabewert sagt, welche
gegriffen hat — anders liesse sich „es hat funktioniert" nicht pruefen, ohne
ein Fenster aufgehen zu lassen.

Der tragende Satz: **keine Stufe darf den Handel aufhalten.** Schlaegt alles
fehl, steht die Adresse in der Konsole und der Kern laeuft weiter.
"""
from __future__ import annotations

from ordertune_bridge_ibkr.cockpit import window as w

URL = "http://127.0.0.1:1234/?t=geheim"


def test_edge_app_mode_is_the_first_choice(monkeypatch) -> None:
    gestartet: list[list[str]] = []
    monkeypatch.setattr(w.sys, "platform", "win32")
    monkeypatch.setattr(w, "find_edge", lambda: r"C:\Edge\msedge.exe")
    monkeypatch.setattr(w.subprocess, "Popen", lambda cmd, **kw: gestartet.append(cmd))

    assert w.open_window(URL) == "app_mode"
    assert gestartet[0][1] == f"--app={URL}", (
        "Ohne --app waere es ein gewoehnlicher Reiter mit Adresszeile — dann "
        "koennte man sich den Aufwand sparen."
    )


def test_without_edge_the_default_browser_takes_over(monkeypatch) -> None:
    monkeypatch.setattr(w, "find_edge", lambda: None)
    monkeypatch.setattr(w.webbrowser, "open", lambda url: True)
    assert w.open_window(URL) == "browser"


def test_a_failing_edge_falls_through_instead_of_dying(monkeypatch) -> None:
    """Auf Windows Server ist eine kaputte Installation der Normalfall, nicht die Ausnahme."""
    monkeypatch.setattr(w.sys, "platform", "win32")
    monkeypatch.setattr(w, "find_edge", lambda: r"C:\Edge\msedge.exe")

    def _boom(*_a, **_k):
        raise OSError("nicht ausfuehrbar")

    monkeypatch.setattr(w.subprocess, "Popen", _boom)
    monkeypatch.setattr(w.webbrowser, "open", lambda url: True)
    assert w.open_window(URL) == "browser"


def test_with_no_window_at_all_the_url_is_printed(monkeypatch, caplog) -> None:
    monkeypatch.setattr(w, "find_edge", lambda: None)
    monkeypatch.setattr(w.webbrowser, "open", lambda url: False)

    with caplog.at_level("INFO"):
        assert w.open_window(URL) == "url_only"

    assert URL in caplog.text, (
        "Auf einem VPS ohne Browser ist die Adresse genau das, was jemand "
        "braucht, der sich per RDP verbindet."
    )


def test_nothing_here_ever_raises(monkeypatch) -> None:
    """Das Fenster ist die Huelle. Der Server ist das Fundament."""
    monkeypatch.setattr(w, "find_edge", lambda: None)

    def _boom(*_a, **_k):
        raise RuntimeError("kein Browser, kein gar nichts")

    monkeypatch.setattr(w.webbrowser, "open", _boom)
    assert w.open_window(URL) == "url_only"


def test_edge_is_not_looked_for_outside_windows(monkeypatch) -> None:
    """Der App-Modus ist die Windows-Antwort; anderswo waere sie eine Attrappe."""
    monkeypatch.setattr(w.sys, "platform", "darwin")
    monkeypatch.setattr(w, "find_edge", lambda: (_ for _ in ()).throw(AssertionError))
    monkeypatch.setattr(w.webbrowser, "open", lambda url: True)
    assert w.open_window(URL) == "browser"
