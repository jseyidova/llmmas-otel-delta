from __future__ import annotations

import os
from pathlib import Path

import pytest

from .harness import CalculatorApp, bootstrap_calculator, destroy
from .validator import find_project_root

_REFERENCE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "calculator_reference"
_PROJECT_ENV = "CALCULATOR_PROJECT_DIR"


def _resolve_project_dir() -> Path:
    raw = os.environ.get(_PROJECT_ENV)
    if raw:
        return find_project_root(Path(raw))
    return find_project_root(_REFERENCE)


@pytest.fixture(scope="session")
def calculator_app() -> CalculatorApp:
    project_dir = _resolve_project_dir()
    harness = bootstrap_calculator(project_dir)
    app = CalculatorApp(harness)
    yield app
    destroy(harness)
