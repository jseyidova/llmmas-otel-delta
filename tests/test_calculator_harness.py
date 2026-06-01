from __future__ import annotations

import unittest
from pathlib import Path

import tkinter as tk

from validators.calculator_ui.harness import (
    _resolve_tk_root,
    enrich_main_with_sibling_methods,
    strip_phantom_imports,
)


class StripPhantomImportsTest(unittest.TestCase):
    def test_removes_import_when_class_defined_locally(self) -> None:
        source = """import tkinter as tk
from button_handler import ButtonHandler

class ButtonHandler:
    pass
"""
        cleaned = strip_phantom_imports(source, Path("/tmp/project"))
        self.assertNotIn("button_handler", cleaned)
        self.assertIn("class ButtonHandler", cleaned)

    def test_keeps_valid_sibling_import(self) -> None:
        project = Path(__file__).parent / "fixtures" / "calculator_reference"
        source = (project / "main.py").read_text(encoding="utf-8")
        cleaned = strip_phantom_imports(source, project)
        self.assertEqual(source, cleaned)

    def test_resolve_tk_root_prefers_root_variable(self) -> None:
        root = object.__new__(tk.Tk)
        other = object.__new__(tk.Tk)
        resolved = _resolve_tk_root({"root": root, "app": other})
        self.assertIs(resolved, root)

    def test_resolve_tk_root_finds_tk_subclass_app(self) -> None:
        class CalcApp(tk.Tk):
            pass

        app = object.__new__(CalcApp)
        self.assertIs(_resolve_tk_root({"app": app}), app)

    def test_enrich_main_copies_methods_from_sibling_class(self) -> None:
        project = Path(__file__).parent / "fixtures" / "split_class_stub"
        project.mkdir(exist_ok=True)
        try:
            (project / "main.py").write_text(
                "import tkinter as tk\n"
                "from grid import ButtonGrid\n"
                "class CalculatorApp:\n"
                "    def __init__(self, root):\n"
                "        self.root = root\n"
                "        ButtonGrid(root, self)\n",
                encoding="utf-8",
            )
            (project / "grid.py").write_text(
                "class CalculatorApp:\n"
                "    def calculate(self):\n"
                "        return 1\n",
                encoding="utf-8",
            )
            main_src = (project / "main.py").read_text(encoding="utf-8")
            enriched = enrich_main_with_sibling_methods(main_src, project)
            self.assertIn("def calculate", enriched)
        finally:
            for name in ("main.py", "grid.py"):
                path = project / name
                if path.exists():
                    path.unlink()
            if project.exists() and not any(project.iterdir()):
                project.rmdir()


if __name__ == "__main__":
    unittest.main()
