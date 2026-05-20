#!/usr/bin/env python3
"""Fetch the latest ChatDev trace from Jaeger and save raw API JSON for replay."""
from __future__ import annotations

import argparse
import json
import sys

from llmmas_otel.jaeger_client import fetch_and_save_trace
from llmmas_otel.jaeger_trace import build_replay_artifacts, load_spans


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch Jaeger trace JSON for llmmas replay.")
    parser.add_argument("--out", required=True, help="Output path, e.g. out/baseline/faulty-jaeger-trace.json")
    parser.add_argument("--base-url", default="http://localhost:16686")
    parser.add_argument("--service", default="chatdev-programdev")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--lookback", default="2h")
    parser.add_argument(
        "--session-contains",
        default=None,
        help="Keep traces whose llmmas.session.id contains this substring (e.g. MonopolyGo)",
    )
    parser.add_argument("--save-all", action="store_true", help="Save full API response, not one trace")
    args = parser.parse_args()

    info = fetch_and_save_trace(
        args.out,
        base_url=args.base_url,
        service=args.service,
        limit=args.limit,
        lookback=args.lookback,
        session_contains=args.session_contains,
        save_all_candidates=args.save_all,
    )
    print(json.dumps(info, indent=2))

    try:
        spans = load_spans(args.out)
        llm_records, a2a_messages, events = build_replay_artifacts(spans)
        print(
            f"Replayable: {len(llm_records)} LLM hooks, {len(a2a_messages)} A2A messages, "
            f"{len(events)} ordered hook events",
            file=sys.stderr,
        )
        if events:
            hook_min = min(e["hook_index"] for e in events if isinstance(e.get("hook_index"), int))
            hook_max = max(e["hook_index"] for e in events if isinstance(e.get("hook_index"), int))
            print(f"hook_index range in events: {hook_min}..{hook_max}", file=sys.stderr)
    except ValueError as exc:
        print(f"WARNING: {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
