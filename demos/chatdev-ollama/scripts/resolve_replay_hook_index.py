#!/usr/bin/env python3
"""
Print fault hook_index and suggested --replay-until-hook-index from a baseline timeline.

Example:
  python resolve_replay_hook_index.py \\
    --timeline out/baseline-monopoly-run-04-temp0/hook-timeline.jsonl \\
    --a2a-fault ../data/monopoly_cto_to_programmer_truncate.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from llmmas_otel.hook_timeline_store import load_timeline, suggest_replay_until_hook_index
from llmmas_otel.injection.a2a_fault import find_fault_hook_index, load_a2a_fault_spec
from llmmas_otel.jaeger_trace import build_replay_artifacts, load_spans


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Resolve global hook_index for an A2A fault and LLM replay-until value.",
    )
    parser.add_argument("--timeline", type=Path, default=None, help="hook-timeline.jsonl")
    parser.add_argument(
        "--jaeger-trace",
        type=Path,
        default=None,
        help="faulty-jaeger-trace.json (preferred; same source as --replay-jaeger-trace)",
    )
    parser.add_argument("--a2a-fault", required=True, type=Path)
    parser.add_argument("--list", action="store_true", help="Print full ordered timeline")
    args = parser.parse_args()

    if args.jaeger_trace is not None:
        spans = load_spans(args.jaeger_trace)
        _llm, a2a_messages, events = build_replay_artifacts(spans)
        lookup = a2a_messages
        timeline = events
    elif args.timeline is not None:
        timeline = load_timeline(str(args.timeline))
        lookup = timeline
    else:
        parser.error("Provide --jaeger-trace or --timeline")

    fault_spec = load_a2a_fault_spec(args.a2a_fault)
    fault_hook = find_fault_hook_index(lookup, fault_spec)
    replay_until = suggest_replay_until_hook_index(fault_hook, timeline)

    if args.list:
        for row in timeline:
            print(
                f"{row.get('hook_index'):>4}  {row.get('hook_type'):<14}  "
                f"{(row.get('segment') or {}).get('name')!s:<12}  "
                f"{row.get('edge_id') or row.get('tool_name') or row.get('model') or ''}"
            )
        print()

    print(f"fault_hook_index={fault_hook}")
    print(f"replay_until_hook_index={replay_until}")
    print()
    print("Fault run (prefix replay stops before replay_until; A2A replays until fault row):")
    print(f"  --replay-until-hook-index {replay_until}")


if __name__ == "__main__":
    main()
