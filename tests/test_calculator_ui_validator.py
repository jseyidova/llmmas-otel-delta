"""Pytest entrypoint: delegates to validators/calculator_ui (reference fixture by default)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

_REFERENCE = Path(__file__).parent / "fixtures" / "calculator_reference"


def test_reference_calculator_pytest_suite():
    """CI: run full UI/behavior suite on in-repo reference app."""
    prev = os.environ.get("CALCULATOR_PROJECT_DIR")
    os.environ.pop("CALCULATOR_PROJECT_DIR", None)
    try:
        exit_code = pytest.main(
            [str(Path(__file__).resolve().parents[1] / "validators" / "calculator_ui"), "-q"],
        )
    finally:
        if prev is not None:
            os.environ["CALCULATOR_PROJECT_DIR"] = prev
    assert exit_code == 0, "Reference calculator pytest suite failed"


@pytest.mark.skipif(
    not os.environ.get("CALCULATOR_PROJECT_DIR"),
    reason="Set CALCULATOR_PROJECT_DIR to validate a ChatDev WareHouse build",
)
def test_generated_calculator_pytest_suite():
    exit_code = pytest.main(
        [str(Path(__file__).resolve().parents[1] / "validators" / "calculator_ui"), "-q"],
    )
    assert exit_code == 0, "Generated calculator pytest suite failed"
