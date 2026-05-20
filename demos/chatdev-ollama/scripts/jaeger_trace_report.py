#!/usr/bin/env python3
"""
Turn a Jaeger trace JSON into a readable report + JSONL sidecars.

Example:
  python jaeger_trace_report.py \\
    --trace out/baseline-monopoly-run-06-temp0/faulty-jaeger-trace.json \\
    --out-dir out/baseline-monopoly-run-06-temp0/readable
"""
from __future__ import annotations

import argparse
import json
import sys

from llmmas_otel.jaeger_trace_report import build_readable_report, write_report_files


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert faulty-jaeger-trace.json into readable report and JSONL catalogs.",
    )
    parser.add_argument("--trace", required=True, help="Path to faulty-jaeger-trace.json")
    parser.add_argument(
        "--out-dir",
        default=None,
        help="Directory for trace-report.txt and JSONL files (default: next to trace)",
    )
    parser.add_argument("--preview-chars", type=int, default=320)
    parser.add_argument(
        "--stdout-only",
        action="store_true",
        help="Print report to stdout only; do not write files",
    )
    args = parser.parse_args()

    if args.stdout_only:
        print(build_readable_report(args.trace, body_preview_chars=args.preview_chars))
        return

    out_dir = args.out_dir
    if out_dir is None:
        from pathlib import Path

        out_dir = Path(args.trace).parent / "readable"

    paths = write_report_files(
        args.trace,
        out_dir,
        body_preview_chars=args.preview_chars,
    )
    print(json.dumps(paths, indent=2))
    print(file=sys.stderr)
    print("Open trace-report.txt for hook order, agents, and message previews.", file=sys.stderr)


if __name__ == "__main__":
    main()
