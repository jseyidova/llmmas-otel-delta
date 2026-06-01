"""Auto-increment run IDs (calculator-01, calculator-02, ...) for traces and WareHouse."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class RunPaths:
    run_id: str
    series: str
    series_dir: Path  # e.g. out/calculator
    run_dir: Path  # e.g. out/calculator/calculator-01
    trace_json: Path
    messages_jsonl: Path
    run_meta_json: Path

    @property
    def out_dir(self) -> Path:
        """Series output root (parent of per-run directories)."""
        return self.series_dir

    def warehouse_glob(self, org_name: str) -> str:
        return f"{self.run_id}_{org_name}_*"


def series_from_dataset(dataset_path: Path) -> str:
    stem = dataset_path.stem.lower()
    if stem.endswith("ui") and len(stem) > 2:
        stem = stem[:-2]
    return stem.strip("_-") or "run"


def _existing_run_numbers(series: str, warehouse: Path, series_out: Path) -> list[int]:
    """Collect NN from WareHouse dirs and out/<series>/calculator-NN/ (or legacy flat files)."""
    dir_pattern = re.compile(rf"^{re.escape(series)}-(\d{{2,}})$")
    name_pattern = re.compile(rf"^{re.escape(series)}-(\d{{2,}})")
    nums: list[int] = [0]

    if warehouse.is_dir():
        for child in warehouse.iterdir():
            m = name_pattern.match(child.name)
            if m:
                nums.append(int(m.group(1)))

    if series_out.is_dir():
        for child in series_out.iterdir():
            if child.is_dir():
                m = dir_pattern.match(child.name)
                if m:
                    nums.append(int(m.group(1)))
            elif child.is_file():
                m = name_pattern.match(child.stem)
                if m:
                    nums.append(int(m.group(1)))

    return nums


def allocate_run_id(
    series: str,
    *,
    cwd: Path,
    explicit_run_id: str | None = None,
) -> str:
    if explicit_run_id:
        return explicit_run_id
    warehouse = cwd / "WareHouse"
    series_out = cwd / "out" / series
    n = max(_existing_run_numbers(series, warehouse, series_out)) + 1
    return f"{series}-{n:02d}"


def run_paths(series: str, run_id: str, *, cwd: Path) -> RunPaths:
    series_dir = cwd / "out" / series
    run_dir = series_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return RunPaths(
        run_id=run_id,
        series=series,
        series_dir=series_dir,
        run_dir=run_dir,
        trace_json=run_dir / "jaeger-trace.json",
        messages_jsonl=run_dir / "messages.jsonl",
        run_meta_json=run_dir / "run.json",
    )


def find_warehouse_dir(cwd: Path, run_id: str, org_name: str) -> Path | None:
    warehouse = cwd / "WareHouse"
    if not warehouse.is_dir():
        return None
    matches = [
        p
        for p in warehouse.iterdir()
        if p.is_dir() and p.name.startswith(f"{run_id}_{org_name}_")
    ]
    if not matches:
        return None
    return max(matches, key=lambda p: p.stat().st_mtime)


def write_run_meta(
    paths: RunPaths,
    *,
    cwd: Path,
    org_name: str,
    dataset: str,
    warehouse_dir: Path | None,
    trace_saved: Path | None,
    extra: dict | None = None,
) -> Path:
    payload = {
        "run_id": paths.run_id,
        "series": paths.series,
        "run_dir": str(paths.run_dir.resolve()),
        "org_name": org_name,
        "dataset": dataset,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "trace_json": str(trace_saved.resolve()) if trace_saved else None,
        "messages_jsonl": str(paths.messages_jsonl.resolve()),
        "warehouse_dir": str(warehouse_dir.resolve()) if warehouse_dir else None,
    }
    if extra:
        payload.update(extra)
    paths.run_meta_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    paths.series_dir.mkdir(parents=True, exist_ok=True)
    (paths.series_dir / "latest-run.txt").write_text(paths.run_id + "\n", encoding="utf-8")
    return paths.run_meta_json
