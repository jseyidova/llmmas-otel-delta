from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_target(path: Path, hook_index: int) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("hook_index") == hook_index:
                return record
    raise ValueError(f"No A2A point found with hook_index={hook_index}")


def _yaml_quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _selector_block(target: dict[str, Any], hook_index: int) -> str:
    return f"""    selector:
      hook_index: {hook_index}
      source_agent_id: {_yaml_quote(str(target.get("source_agent_id") or ""))}
      target_agent_id: {_yaml_quote(str(target.get("target_agent_id") or ""))}
      message_id: {_yaml_quote(str(target.get("message_id") or ""))}"""


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Generate an A2A fault spec from an extracted A2A point. "
            "Use --max-chars for position-based truncation, or --body-file for a manually truncated body."
        )
    )
    parser.add_argument("--a2a", required=True, type=Path)
    parser.add_argument("--hook-index", required=True, type=int)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--fraction", type=float, default=None)
    parser.add_argument("--max-chars", type=int, default=None)
    parser.add_argument(
        "--body-file",
        type=Path,
        default=None,
        help="Path to a file containing the manually truncated message body (uses a2a.replace_body)",
    )
    parser.add_argument("--fault-id", default=None)
    args = parser.parse_args()

    target = _load_target(args.a2a, args.hook_index)
    body = target.get("body") or ""
    direction = target.get("direction")
    hook = "a2a_receive" if direction == "receive" else "a2a_send"
    fault_id = args.fault_id or f"TRUNCATE_HOOK_{args.hook_index}"
    selector = _selector_block(target, args.hook_index)

    if args.body_file is not None:
        truncated = args.body_file.read_text(encoding="utf-8")
        action = f"""    action:
      type: a2a.replace_body
      params:
        body: {_yaml_quote(truncated)}"""
        summary = f"replace_body fault, body_len={len(truncated)}"
    else:
        if args.max_chars is not None:
            if args.max_chars < 0:
                raise ValueError("--max-chars must be >= 0")
            max_chars = args.max_chars
        elif args.fraction is not None:
            if args.fraction <= 0 or args.fraction > 1:
                raise ValueError("--fraction must be in the range (0, 1]")
            max_chars = int(len(body) * args.fraction)
        else:
            max_chars = int(len(body) * 0.5)
        action = f"""    action:
      type: a2a.truncate
      params:
        max_chars: {max_chars}"""
        summary = f"truncate fault, max_chars={max_chars}"

    text = f"""faults:
  - id: {fault_id}
    hook: {hook}
{selector}
{action}
    limits:
      probability: 1.0
      max_times: 1
"""

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print(f"Wrote {hook} {summary} for hook_index={args.hook_index}")


if __name__ == "__main__":
    main()
