#!/usr/bin/env python3
"""Fetch the latest Jaeger trace for a service and save as JSON."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from llmmas_otel.jaeger_client import (
    DEFAULT_JAEGER_QUERY_URL,
    default_trace_output_path,
    fetch_and_save_latest_trace,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch latest Jaeger trace JSON")
    parser.add_argument(
        "--service",
        default="chatdev-programdev",
        help="Jaeger service name (default: chatdev-programdev)",
    )
    parser.add_argument(
        "--jaeger-url",
        default=DEFAULT_JAEGER_QUERY_URL,
        help=f"Jaeger query base URL (default: {DEFAULT_JAEGER_QUERY_URL})",
    )
    parser.add_argument(
        "--out",
        type=str,
        default=None,
        help="Output JSON path (default: out/<project>/latest-trace.json if --project set, else out/latest-trace.json)",
    )
    parser.add_argument(
        "--project",
        type=str,
        default=None,
        help="Project name used to derive default output directory",
    )
    parser.add_argument("--retries", type=int, default=8)
    args = parser.parse_args()

    if args.out:
        out_path = Path(args.out)
    elif args.project:
        out_path = default_trace_output_path(args.project)
    else:
        out_path = Path("out/latest-trace.json")

    fetch_and_save_latest_trace(
        service=args.service,
        output_path=out_path,
        base_url=args.jaeger_url,
        retries=args.retries,
    )
    print(out_path.resolve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
