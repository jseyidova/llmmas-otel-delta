#!/usr/bin/env python3
"""Launch a WareHouse calculator UI without editing generated files (phantom imports stripped in memory)."""

from __future__ import annotations

import argparse
import sys
import tkinter as tk
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from validators.calculator_ui.harness import bootstrap_calculator, destroy


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Open a generated calculator WareHouse app (read-only on disk).",
    )
    parser.add_argument(
        "project_dir",
        type=str,
        help="WareHouse folder containing main.py",
    )
    args = parser.parse_args()

    project_dir = Path(args.project_dir).resolve()
    harness = bootstrap_calculator(project_dir)
    harness.root.deiconify()
    print(f"Calculator UI: {project_dir}")
    print("Close the window to exit.")
    try:
        harness.root.mainloop()
    finally:
        destroy(harness)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
