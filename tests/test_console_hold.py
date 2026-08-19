"""T1-101 A-1 — gehalten wird beim Doppelklick, und sonst nie.

Der Halt loest ein Problem und darf dabei kein groesseres schaffen: ein
Dauerbetrieb, der auf eine Eingabe wartet, die nie kommt, meldet keinen
Herzschlag und ist fuer die Plattform nicht von einem Absturz zu unterscheiden.
Deshalb steht hier jede Bedingung einzeln unter Zusicherung.
"""
from __future__ import annotations

import builtins

import pytest

from ordertune_bridge_ibkr import console

# ── Der Schalter ─────────────────────────────────────────────────────────────


def test_the_flag_is_recognised() -> None:
    assert console.headless_requested(["--headless"]) is True
    assert console.headless_requested(["--probe-foreign", "--headless"]) is True


def test_without_the_flag_the_bridge_is_interactive() -> None:
    assert console.headless_requested([]) is False
    assert console.headless_requested(["--head"]) is False, (
        "Eine Teilzeichenkette darf den Dauerbetrieb nicht ausloesen."
    )


# ── Wann gehalten wird ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("frozen", "argv", "expected"),
    [
        (True, [], True),
        (True, ["--headless"], False),
        (False, [], False),
        (False, ["--headless"], False),
    ],
)
def test_holding_needs_a_packed_exe_and_no_headless_flag(
    monkeypatch, frozen: bool, argv: list[str], expected: bool
) -> None:
    monkeypatch.setattr(console, "is_frozen", lambda: frozen)
    assert console.should_hold(argv) is expected


def test_running_from_source_never_waits(monkeypatch) -> None:
    """Aus der Entwicklungsumgebung heraus schliesst sich kein Fenster."""
    monkeypatch.setattr(console, "is_frozen", lambda: False)
    monkeypatch.setattr(
        builtins, "input", lambda *_: pytest.fail("Es wurde gewartet.")
    )
    console.hold([])


def test_headless_never_waits(monkeypatch) -> None:
    """Unter IBC oder in einer geplanten Aufgabe gibt es niemanden, der tippt."""
    monkeypatch.setattr(console, "is_frozen", lambda: True)
    monkeypatch.setattr(
        builtins, "input", lambda *_: pytest.fail("Es wurde gewartet.")
    )
    console.hold(["--headless"])


# ── Wie gehalten wird ────────────────────────────────────────────────────────


def test_a_double_click_waits_and_says_so(monkeypatch, capsys) -> None:
    monkeypatch.setattr(console, "is_frozen", lambda: True)
    seen: list[bool] = []
    monkeypatch.setattr(builtins, "input", lambda *_: seen.append(True))

    console.hold([])

    assert seen == [True]
    assert "Press Enter" in capsys.readouterr().out


@pytest.mark.parametrize("boom", [EOFError, KeyboardInterrupt, OSError])
def test_a_missing_input_channel_ends_the_wait_quietly(
    monkeypatch, boom: type[BaseException]
) -> None:
    """Ein Fehler beim Anzeigen eines Fehlers darf den Ausgang nicht verdecken."""
    monkeypatch.setattr(console, "is_frozen", lambda: True)

    def _raise(*_: object) -> None:
        raise boom()

    monkeypatch.setattr(builtins, "input", _raise)
    console.hold([])  # darf nicht werfen
