"""Behavior tests for Tkinter calculator outputs."""

from __future__ import annotations

import pytest

from .harness import normalize_numeric


class TestCalculatorArithmetic:
    @pytest.fixture(autouse=True)
    def _clear_before_each(self, calculator_app):
        if calculator_app.has_button("clear"):
            calculator_app.press("clear")
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
        ids=["add", "subtract", "multiply", "divide", "decimal"],
    )
    def test_basic_operations(self, calculator_app, sequence, expected):
        calculator_app.press_sequence(*sequence)
        assert calculator_app.display_contains(expected), (
            f"Expected result {expected!r} in display, got {calculator_app.read_display()!r}"
        )
        numeric = normalize_numeric(calculator_app.read_display())
        assert numeric == expected or expected in numeric

    def test_division_by_zero_shows_error(self, calculator_app):
        calculator_app.press_sequence("1", "/", "0", "=")
        text = calculator_app.read_display().lower()
        assert any(
            token in text
            for token in ("error", "zero", "invalid", "cannot", "inf", "nan")
        ), f"Expected division-by-zero error message, got {text!r}"

    def test_clear_resets_display(self, calculator_app):
        calculator_app.press_sequence("1", "2", "3")
        calculator_app.press("clear")
        display = calculator_app.read_display()
        assert display in ("", "0"), f"Clear should reset display, got {display!r}"

    def test_backspace_removes_last_digit(self, calculator_app):
        calculator_app.press_sequence("1", "2", "3")
        calculator_app.press("backspace")
        display = calculator_app.read_display()
        assert display.endswith("12") or display == "12", (
            f"Backspace should leave '12', got {display!r}"
        )

    def test_chain_addition(self, calculator_app):
        calculator_app.press_sequence("2", "+", "3", "+", "4", "=")
        assert calculator_app.display_contains("9")

    def test_multiply_after_partial_entry(self, calculator_app):
        calculator_app.press_sequence("6", "*", "7", "=")
        assert calculator_app.display_contains("42")
