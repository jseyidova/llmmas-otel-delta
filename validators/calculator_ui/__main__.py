from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .validator import validate_project


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a generated CalculatorUI Tkinter project against the ProgramDev spec.",
    )
    parser.add_argument(
        "project_dir",
        type=str,
        help="Path to generated software directory (contains main.py)",
    )
    args = parser.parse_args()

    result = validate_project(Path(args.project_dir))
    for check in result.checks:
        status = "PASS" if check.passed else "FAIL"
        print(f"[{status}] {check.name}: {check.message}")

    print()
    if result.passed:
        print("VALIDATION PASSED")
        return 0
    print("VALIDATION FAILED")
    return 1


if __name__ == "__main__":
    sys.exit(main())
