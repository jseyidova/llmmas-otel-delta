"""
Black-box calculator behavior tests (name-agnostic).

Generated ChatDev apps use different class and function names each run. These tests
never import project modules or call app-specific methods. They:

1. Execute ``main.py`` under ``if __name__ == '__main__'`` (see ``bootstrap_calculator``).
2. Find the Tk root window (``root``, ``app``, or a single ``tk.Tk`` subclass instance).
3. Click buttons by **visible label** (digits, operators, ``C``, ``⌫``).
4. Read the display from the first Entry/Label widget.

This matches the ProgramDev task spec: required labels include ``C`` and ``⌫``; behavior
cases are ``2+3=5``, ``9-4=5``, ``3*4=12``, ``8/2=4``, decimals, clear, backspace,
chained ops, and division-by-zero messaging.
"""

from __future__ import annotations

import pytest

from .harness import (
    CLEAR_ALIASES,
    BACKSPACE_ALIASES,
    DIGIT_KEYS,
    OPERATOR_ALIASES,
    normalize_numeric,
)

# Labels required to run the suite (discovered on the widget tree, not in source code).
_REQUIRED_PRESS_KEYS = [
    *DIGIT_KEYS,
    *OPERATOR_ALIASES.keys(),
    "clear",
    "backspace",
]


@pytest.fixture(scope="session", autouse=True)
def _require_pressable_controls(calculator_app):
    """Fail fast if the app is missing buttons needed for behavior tests."""
    missing = [key for key in _REQUIRED_PRESS_KEYS if not calculator_app.has_button(key)]
    if missing:
        pytest.fail(
            "Cannot run behavior tests: missing clickable buttons for "
            f"{missing!r}. Task requires labels C (clear) and ⌫ (backspace) plus "
            f"digits 0-9 and operators; found clear aliases {CLEAR_ALIASES!r}, "
            f"backspace aliases {BACKSPACE_ALIASES!r}."
        )


class TestCalculatorBehavior:
    """Task-required behaviors via button presses only."""

    @pytest.fixture(autouse=True)
    def _clear_before_each(self, calculator_app):
        if calculator_app.has_button("clear"):
            calculator_app.press("clear")
        # Many apps clear to "0" then append digits → "02+3" breaks eval(); manual
        # runs often avoid that. Empty the seeded zero before behavior tests.
        if calculator_app.read_display() == "0" and calculator_app.has_button("backspace"):
            calculator_app.press("backspace")
        yield

    @pytest.mark.parametrize(
        "sequence,expected",
        [
            (("2", "+", "3", "="), "5"),
            (("9", "-", "4", "="), "5"),
            (("3", "*", "4", "="), "12"),
            (("8", "/", "2", "="), "4"),
            (("1", ".", "5", "+", "2", ".", "5", "="), "4"),
        ],
        ids=["2+3=5", "9-4=5", "3*4=12", "8/2=4", "1.5+2.5=4"],
    )
    def test_basic_operations(self, calculator_app, sequence, expected):
        calculator_app.press_sequence(*sequence)
        assert calculator_app.display_contains(expected), (
            f"Expected {expected!r} in display after {sequence!r}, "
            f"got {calculator_app.read_display()!r}"
        )
        assert normalize_numeric(calculator_app.read_display()) == expected

    def test_clear_resets_display(self, calculator_app):
        calculator_app.press_sequence("1", "2", "3")
        calculator_app.press("clear")
        display = calculator_app.read_display()
        assert display in ("", "0"), f"Clear should reset display to empty or 0, got {display!r}"

    def test_backspace_removes_one_character(self, calculator_app):
        calculator_app.press_sequence("1", "2", "3")
        calculator_app.press("backspace")
        display = calculator_app.read_display()
        assert display.endswith("12") or display == "12", (
            f"Backspace should leave '12', got {display!r}"
        )

    def test_chained_operations(self, calculator_app):
        calculator_app.press_sequence("2", "+", "3", "+", "4", "=")
        assert calculator_app.display_contains("9"), (
            f"Chained 2+3+4=9 failed, display={calculator_app.read_display()!r}"
        )

    def test_division_by_zero_shows_error(self, calculator_app):
        calculator_app.press_sequence("1", "/", "0", "=")
        text = calculator_app.read_display().lower()
        assert any(
            token in text for token in ("error", "zero")
        ), f"Division by zero should mention error or zero, got {text!r}"
