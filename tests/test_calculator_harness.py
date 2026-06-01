from __future__ import annotations

import unittest
from pathlib import Path

from validators.calculator_ui.harness import strip_phantom_imports


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


if __name__ == "__main__":
    unittest.main()
