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
            if record.get("kind") == "llm_call" and record.get("hook_index") == hook_index:
                return record
    raise ValueError(f"No LLM replay record found with hook_index={hook_index}")


def _content(record: dict[str, Any]) -> str:
    try:
        value = record["response"]["choices"][0]["message"]["content"]
    except Exception as exc:
        raise ValueError("Replay record does not contain response.choices[0].message.content") from exc
    if not isinstance(value, str):
        raise ValueError("LLM response content is not a string")
    return value


def _truncate_content(content: str, *, fraction: float, cut_before: str | None) -> tuple[str, str]:
    if cut_before is not None:
        idx = content.find(cut_before)
        if idx < 0:
            raise ValueError(f"Cut marker not found in LLM response: {cut_before!r}")
        return content[:idx].rstrip(), f"marker {cut_before!r}"

    if fraction <= 0 or fraction > 1:
        raise ValueError("--fraction must be in the range (0, 1]")
    max_chars = int(len(content) * fraction)
    return content[:max_chars], f"fraction {fraction}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate an llm.malformed_response fault with truncated original content.")
    parser.add_argument("--replay", required=True, type=Path)
    parser.add_argument("--hook-index", required=True, type=int)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--fraction", type=float, default=0.5)
    parser.add_argument("--cut-before", default=None)
    parser.add_argument("--fault-id", default=None)
    args = parser.parse_args()

    target = _load_target(args.replay, args.hook_index)
    content = _content(target)
    truncated, mode = _truncate_content(
        content,
        fraction=args.fraction,
        cut_before=args.cut_before,
    )
    fault_id = args.fault_id or f"TRUNCATE_LLM_HOOK_{args.hook_index}"

    spec = {
        "faults": [
            {
                "id": fault_id,
                "hook": "llm_call",
                "selector": {
                    "hook_index": args.hook_index,
                },
                "action": {
                    "type": "llm.malformed_response",
                    "params": {
                        "return_value": truncated,
                    },
                },
                "limits": {
                    "probability": 1.0,
                    "max_times": 1,
                },
            }
        ]
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"Wrote llm_call truncation fault for hook_index={args.hook_index}, "
        f"mode={mode}, chars={len(truncated)}/{len(content)}"
    )


if __name__ == "__main__":
    main()
