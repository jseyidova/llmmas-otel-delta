#!/usr/bin/env python3
"""Optional: split a Jaeger trace JSON into JSONL sidecars (legacy). Prefer --replay-jaeger-trace."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from llmmas_otel.jaeger_trace import build_replay_artifacts, load_spans


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert Jaeger trace JSON into JSONL replay sidecars.")
    parser.add_argument("--trace", required=True, type=Path)
    parser.add_argument("--out-replay", required=True, type=Path)
    parser.add_argument("--out-a2a", required=True, type=Path)
    parser.add_argument("--out-events", type=Path)
    args = parser.parse_args()

    spans = load_spans(args.trace)
    llm_records, a2a_messages, events = build_replay_artifacts(spans)
    _write_jsonl(args.out_replay, llm_records)
    _write_jsonl(args.out_a2a, a2a_messages)
    if args.out_events is not None:
        _write_jsonl(args.out_events, events)
    print(f"Wrote {len(llm_records)} LLM replay records to {args.out_replay}")
    print(f"Wrote {len(a2a_messages)} A2A messages to {args.out_a2a}")
    if args.out_events is not None:
        print(f"Wrote {len(events)} trace events to {args.out_events}")


if __name__ == "__main__":
    main()
