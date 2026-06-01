from __future__ import annotations

import ast
import importlib.util
import sys
import tkinter as tk
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional
from unittest.mock import patch

DIGIT_KEYS = [str(d) for d in range(10)]
OPERATOR_ALIASES: dict[str, list[str]] = {
    "+": ["+"],
    "-": ["-"],
    "*": ["*", "×", "x", "X"],
    "/": ["/", "÷"],
    ".": ["."],
    "=": ["="],
}
CLEAR_ALIASES = ["C", "Clear", "clear", "AC", "CE", "Reset"]
BACKSPACE_ALIASES = ["⌫", "Back", "Backspace", "DEL", "BS", "←"]
REQUIRED_UI_KEYS = [*DIGIT_KEYS, *OPERATOR_ALIASES.keys(), "clear", "backspace"]

LOGICAL_KEY_ALIASES: dict[str, list[str]] = {
    "clear": CLEAR_ALIASES,
    "backspace": BACKSPACE_ALIASES,
    **{d: [d] for d in DIGIT_KEYS},
    **OPERATOR_ALIASES,
}


@dataclass
class CalculatorHarness:
    root: tk.Tk
    project_dir: Path
    buttons: dict[str, tk.Widget] = field(default_factory=dict)
    display_widget: Optional[tk.Widget] = None
    display_var: Optional[tk.StringVar] = None

    def update(self) -> None:
        self.root.update_idletasks()
        self.root.update()


class CalculatorApp:
    """Logical-key API for driving a Tkinter calculator in tests."""

    def __init__(self, harness: CalculatorHarness) -> None:
        self._harness = harness

    @property
    def display_widget(self) -> Optional[tk.Widget]:
        return self._harness.display_widget

    def has_button(self, logical_key: str) -> bool:
        return self._button_widget(logical_key) is not None

    def press(self, logical_key: str) -> None:
        widget = self._button_widget(logical_key)
        if widget is None:
            aliases = LOGICAL_KEY_ALIASES.get(logical_key, [logical_key])
            raise KeyError(f"Button {logical_key!r} not found (tried {aliases})")
        widget.invoke()
        self._harness.update()

    def press_sequence(self, *logical_keys: str) -> None:
        for key in logical_keys:
            self.press(key)

    def read_display(self) -> str:
        return read_display(self._harness)

    def display_contains(self, expected: str) -> bool:
        text = self.read_display()
        if expected in text:
            return True
        return normalize_numeric(text) == normalize_numeric(expected)

    def _button_widget(self, logical_key: str) -> Optional[tk.Widget]:
        for label in LOGICAL_KEY_ALIASES.get(logical_key, [logical_key]):
            widget = self._harness.buttons.get(label)
            if widget is not None:
                return widget
        return None


def normalize_numeric(display: str) -> str:
    text = (display or "").strip()
    if not text:
        return ""
    try:
        value = float(text)
        if value.is_integer():
            return str(int(value))
        return str(value).rstrip("0").rstrip(".")
    except ValueError:
        return text


def _normalize_button_text(text: str) -> str:
    return (text or "").strip()


def _walk_widgets(widget: tk.Misc) -> Iterable[tk.Widget]:
    for child in widget.winfo_children():
        yield child  # type: ignore[misc]
        yield from _walk_widgets(child)


def _find_buttons(root: tk.Tk) -> dict[str, tk.Widget]:
    found: dict[str, tk.Widget] = {}
    for widget in _walk_widgets(root):
        if not isinstance(widget, tk.Button):
            continue
        label = _normalize_button_text(widget.cget("text"))
        if label:
            found.setdefault(label, widget)
    return found


def _find_display(root: tk.Tk) -> tuple[Optional[tk.Widget], Optional[tk.StringVar]]:
    entries: list[tk.Entry] = []
    labels: list[tk.Label] = []
    for widget in _walk_widgets(root):
        if isinstance(widget, tk.Entry):
            entries.append(widget)
        elif isinstance(widget, tk.Label):
            labels.append(widget)

    if entries:
        entry = entries[0]
        var_name = entry.cget("textvariable")
        display_var: Optional[tk.StringVar] = None
        if var_name:
            try:
                display_var = root.nametowidget(var_name)  # type: ignore[assignment]
            except Exception:
                pass
            if not isinstance(display_var, tk.StringVar):
                try:
                    display_var = root.globalgetvar(var_name)  # type: ignore[assignment]
                except Exception:
                    display_var = None
        if not isinstance(display_var, tk.StringVar):
            display_var = None
        return entry, display_var

    if labels:
        return labels[0], None

    return None, None


def read_display(harness: CalculatorHarness) -> str:
    harness.update()
    if harness.display_var is not None:
        return str(harness.display_var.get())
    if harness.display_widget is None:
        return ""
    if isinstance(harness.display_widget, tk.Entry):
        return harness.display_widget.get()
    if isinstance(harness.display_widget, tk.Label):
        return str(harness.display_widget.cget("text"))
    return ""


def click(harness: CalculatorHarness, label: str) -> None:
    CalculatorApp(harness).press(label)


def press_sequence(harness: CalculatorHarness, keys: Iterable[str]) -> str:
    app = CalculatorApp(harness)
    app.press_sequence(*keys)
    return app.read_display()


def _top_level_defined_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
    return names


def strip_phantom_imports(source: str, project_dir: Path) -> str:
    """
    Remove imports from missing sibling .py files when the symbol is defined in the same file.

    ChatDev sometimes emits ``from button_handler import ButtonHandler`` while also defining
    ``class ButtonHandler`` in the same module.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source

    lines = source.splitlines(keepends=True)
    sibling_modules = {p.stem for p in project_dir.glob("*.py")}
    remove_ranges: list[tuple[int, int]] = []

    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            if node.module in sibling_modules:
                continue
            imported = [alias.name for alias in node.names if alias.name != "*"]
            if imported and all(name in _top_level_defined_names(tree) for name in imported):
                end = node.end_lineno or node.lineno
                remove_ranges.append((node.lineno, end))

    if not remove_ranges:
        return source

    for start, end in sorted(remove_ranges, reverse=True):
        del lines[start - 1 : end]

    return "".join(lines)


def _load_project_modules(project_dir: Path) -> None:
    """Pre-load local modules so multi-file ChatDev apps import cleanly in tests."""
    for path in sorted(project_dir.glob("*.py")):
        if path.name == "main.py":
            continue
        mod_name = path.stem
        if mod_name in sys.modules:
            continue
        source = strip_phantom_imports(path.read_text(encoding="utf-8"), project_dir)
        module = importlib.util.module_from_spec(
            importlib.util.spec_from_loader(mod_name, loader=None)
        )
        module.__file__ = str(path)
        module.__name__ = mod_name
        module.__package__ = None
        sys.modules[mod_name] = module
        exec(compile(source, str(path), "exec"), module.__dict__)


def bootstrap_calculator(project_dir: Path) -> CalculatorHarness:
    project_dir = project_dir.resolve()
    main_path = project_dir / "main.py"
    if not main_path.exists():
        raise FileNotFoundError(f"main.py not found in {project_dir}")

    if str(project_dir) not in sys.path:
        sys.path.insert(0, str(project_dir))

    _load_project_modules(project_dir)

    def _noop_mainloop(self, *args, **kwargs):
        return None

    namespace = {
        "__name__": "__main__",
        "__file__": str(main_path),
        "__package__": None,
    }
    code = strip_phantom_imports(main_path.read_text(encoding="utf-8"), project_dir)
    with patch.object(tk.Tk, "mainloop", _noop_mainloop):
        exec(compile(code, str(main_path), "exec"), namespace)

    ui_root = namespace.get("root")
    if not isinstance(ui_root, tk.Tk):
        raise RuntimeError(
            "main.py must create a tk.Tk instance named 'root' in the __main__ block"
        )

    try:
        ui_root.withdraw()
    except Exception:
        pass

    display_widget, display_var = _find_display(ui_root)
    buttons = _find_buttons(ui_root)

    return CalculatorHarness(
        root=ui_root,
        project_dir=project_dir,
        buttons=buttons,
        display_widget=display_widget,
        display_var=display_var,
    )


def bootstrap_app(project_dir: Path) -> CalculatorApp:
    return CalculatorApp(bootstrap_calculator(project_dir))


def destroy(harness: CalculatorHarness) -> None:
    try:
        harness.root.destroy()
    except Exception:
        pass


# Backward compatibility for validator module
REQUIRED_BUTTONS = set(DIGIT_KEYS) | set(OPERATOR_ALIASES) | {".", "="}
for _labels in (CLEAR_ALIASES, BACKSPACE_ALIASES):
    REQUIRED_BUTTONS.update(_labels)
