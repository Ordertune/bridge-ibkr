"""T1-101 D14 — dieselben Worte wie im Order Management.

T1-100 hat auf der Plattform `Working` gestrichen: IBKR-Jargon, und zu nah an
`Submitting`. Ein Cockpit, das denselben Auftrag anders nennt als t1, stellt
genau den Zustand wieder her, den T1-100 beseitigt hat.
"""
from __future__ import annotations

import pytest

from ordertune_bridge_ibkr import order_vocabulary as v


@pytest.mark.parametrize(
    ("intern", "erwartet"),
    [
        ("submitting", "Sending"),
        ("working", "At broker"),
        ("filled", "Filled"),
        ("partial", "Partly filled"),
        ("cancelled", "Cancelled"),
        ("rejected", "Rejected"),
        ("expired", "Expired"),
        ("unknown", "Unknown"),
    ],
)
def test_every_state_gets_the_word_the_user_sees_on_t1(intern: str, erwartet: str) -> None:
    assert v.label(intern) == erwartet


def test_working_is_dead() -> None:
    """Die Vokabel selbst darf nirgends mehr auftauchen."""
    assert "Working" not in v.LABELS.values()
    assert v.label("working") == "At broker"


def test_an_unknown_state_never_leaks_raw_jargon() -> None:
    """Ein durchgereichter Rohwert saehe aus wie eine Aussage und waere keine."""
    assert v.label("PendingSubmit") == "Unknown"
    assert v.label("") == "Unknown"
    assert v.label(None) == "Unknown"


def test_the_lookup_is_forgiving_about_spacing_and_case() -> None:
    assert v.label("  Filled  ") == "Filled"
    assert v.label("REJECTED") == "Rejected"
