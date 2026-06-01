from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "demos" / "chatdev-ollama" / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from run_naming import allocate_run_id, run_paths, series_from_dataset


class RunNamingTest(unittest.TestCase):
    def test_series_from_dataset(self) -> None:
        self.assertEqual(series_from_dataset(Path("calculator.json")), "calculator")

    def test_allocate_increments_from_run_dir(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            run01 = cwd / "out" / "calculator" / "calculator-01"
            run01.mkdir(parents=True)
            (run01 / "jaeger-trace.json").write_text("{}", encoding="utf-8")
            (cwd / "WareHouse" / "calculator-01_ProgramDevOrg_20260101120000").mkdir(parents=True)
            self.assertEqual(allocate_run_id("calculator", cwd=cwd), "calculator-02")

    def test_allocate_increments_legacy_flat_trace(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            (cwd / "out" / "calculator").mkdir(parents=True)
            (cwd / "out" / "calculator" / "calculator-01-jaeger-trace.json").write_text("{}", encoding="utf-8")
            self.assertEqual(allocate_run_id("calculator", cwd=cwd), "calculator-02")

    def test_run_paths_per_run_directory(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            paths = run_paths("calculator", "calculator-03", cwd=Path(td))
            self.assertEqual(paths.run_dir.name, "calculator-03")
            self.assertEqual(paths.trace_json, paths.run_dir / "jaeger-trace.json")
            self.assertTrue(paths.run_dir.is_dir())


if __name__ == "__main__":
    unittest.main()
