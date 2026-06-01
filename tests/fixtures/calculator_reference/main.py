"""Minimal reference CalculatorUI for validator tests."""
from __future__ import annotations

import tkinter as tk


class CalculatorApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Calculator")
        self.current = ""
        self.pending_op: str | None = None
        self.accumulator: float | None = None

        self.display_var = tk.StringVar(value="")
        self.display = tk.Entry(
            root,
            textvariable=self.display_var,
            justify="right",
            font=("Arial", 16),
        )
        self.display.pack(fill=tk.BOTH, expand=True)

        layout = [
            ["7", "8", "9", "/"],
            ["4", "5", "6", "*"],
            ["1", "2", "3", "-"],
            ["0", ".", "=", "+"],
            ["C", "⌫"],
        ]
        for row in layout:
            frame = tk.Frame(root)
            frame.pack(fill=tk.BOTH, expand=True)
            for label in row:
                tk.Button(frame, text=label, font=("Arial", 14), command=lambda t=label: self.on_press(t)).pack(
                    side=tk.LEFT, fill=tk.BOTH, expand=True
                )

    def _refresh(self) -> None:
        self.display_var.set(self.current)

    def on_press(self, label: str) -> None:
        if label == "C":
            self.current = ""
            self.pending_op = None
            self.accumulator = None
            self._refresh()
            return

        if label == "⌫":
            self.current = self.current[:-1]
            self._refresh()
            return

        if label == "=":
            self._apply_pending()
            return

        if label in {"+", "-", "*", "/"}:
            self._apply_pending()
            self.pending_op = label
            self.current = ""
            self._refresh()
            return

        self.current += label
        self._refresh()

    def _apply_pending(self) -> None:
        if self.current == "" and self.accumulator is None:
            return

        try:
            value = float(self.current or "0")
        except ValueError:
            self.current = "error"
            self.pending_op = None
            self.accumulator = None
            self._refresh()
            return

        if self.accumulator is None:
            self.accumulator = value
        elif self.pending_op is None:
            self.accumulator = value
        else:
            if self.pending_op == "+":
                self.accumulator += value
            elif self.pending_op == "-":
                self.accumulator -= value
            elif self.pending_op == "*":
                self.accumulator *= value
            elif self.pending_op == "/":
                if value == 0:
                    self.current = "error: division by zero"
                    self.accumulator = None
                    self.pending_op = None
                    self._refresh()
                    return
                self.accumulator /= value

        if self.current != "error: division by zero":
            rendered = str(self.accumulator)
            if rendered.endswith(".0"):
                rendered = rendered[:-2]
            self.current = rendered
        self.pending_op = None
        self._refresh()


if __name__ == "__main__":
    root = tk.Tk()
    CalculatorApp(root)
    root.mainloop()
