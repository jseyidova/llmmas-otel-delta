#!/usr/bin/env python3
"""Convert a Jaeger trace JSON export into a readable A2A hook timeline."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from llmmas_otel.injection.trace_timeline import format_timeline, write_timeline


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "List A2A hooks from a Jaeger trace JSON: hook #, phase, agents, message. "
            "Uses the same hook numbering as trace replay (inject_at_hook, etc.)."
        ),
    )
    parser.add_argument(
        "trace_json",
        type=str,
        help="Path to Jaeger trace JSON (e.g. out/calculator/first-trace-full.json)",
    )
    parser.add_argument(
        "-o",
        "--out",
        type=str,
        default=None,
        help="Write to this file (default: <trace>.timeline.txt next to input)",
    )
    parser.add_argument(
        "--format",
        choices=["text", "md", "json"],
        default="text",
        help="Output format (default: text)",
    )
    parser.add_argument(
        "--full-messages",
        action="store_true",
        help="Do not truncate message bodies",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=2000,
        help="Max message characters when not using --full-messages (default: 2000)",
    )
    args = parser.parse_args()

    trace_path = Path(args.trace_json)
    if not trace_path.exists():
        print(f"File not found: {trace_path}", file=sys.stderr)
        return 1

    max_chars = None if args.full_messages else args.max_chars

    if args.out or args.format != "text":
        out_path = write_timeline(
            trace_path,
            args.out,
            output_format=args.format,
            max_message_chars=max_chars,
        )
        print(out_path.resolve())
    else:
        print(
            format_timeline(
                trace_path,
                output_format=args.format,
                max_message_chars=max_chars,
            ),
            end="",
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
