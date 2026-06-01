"""UI structure tests for Tkinter calculator outputs."""

from __future__ import annotations

import pytest

from .harness import (
    BACKSPACE_ALIASES,
    CLEAR_ALIASES,
    DIGIT_KEYS,
    OPERATOR_ALIASES,
    REQUIRED_UI_KEYS,
)


class TestCalculatorUI:
    def test_display_widget_exists(self, calculator_app):
        assert calculator_app.display_widget is not None

    def test_display_is_visible(self, calculator_app):
        widget = calculator_app.display_widget
        assert widget is not None
        # Headless harness calls root.withdraw(); widget still exists and is usable.
        assert widget.winfo_exists()
        if widget.winfo_ismapped() or widget.winfo_viewable():
            return
        calculator_app.press("7")
        assert "7" in calculator_app.read_display()

    @pytest.mark.parametrize("digit", DIGIT_KEYS)
    def test_digit_button_exists(self, calculator_app, digit):
        assert calculator_app.has_button(digit), f"Missing digit button {digit!r}"

    @pytest.mark.parametrize(
        "op_key,aliases",
        [(k, v) for k, v in OPERATOR_ALIASES.items()],
        ids=[k for k in OPERATOR_ALIASES],
    )
    def test_operator_button_exists(self, calculator_app, op_key, aliases):
        assert calculator_app.has_button(op_key), (
            f"Missing operator button {op_key!r}; accepted labels: {aliases}"
        )

    def test_clear_button_exists(self, calculator_app):
        assert calculator_app.has_button("clear"), (
            f"Missing clear/reset button; accepted labels: {CLEAR_ALIASES}"
        )

    def test_backspace_button_exists(self, calculator_app):
        assert calculator_app.has_button("backspace"), (
            f"Missing backspace button; accepted labels: {BACKSPACE_ALIASES}"
        )

    def test_all_required_controls_present(self, calculator_app):
        missing = [k for k in REQUIRED_UI_KEYS if not calculator_app.has_button(k)]
        assert not missing, f"Missing UI controls: {missing}"

    def test_digit_buttons_update_display(self, calculator_app):
        calculator_app.press("clear")
        calculator_app.press("7")
        assert "7" in calculator_app.read_display()
