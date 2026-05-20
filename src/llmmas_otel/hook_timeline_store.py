from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Optional

from . import message_store


@dataclass(frozen=True)
class HookTimelineConfig:
    path: str


_config: Optional[HookTimelineConfig] = None


def enable_hook_timeline(path: str, *, append: bool = False) -> None:
    """
    Record every instrumentation hook in global execution order (one JSONL line per hook).

    Use this file to see when A2A vs LLM vs tool hooks fire and to pick
    ``--replay-until-hook-index`` for fault runs.
    """
    global _config
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if not append:
        open(path, "w", encoding="utf-8").close()
    _config = HookTimelineConfig(path=path)


def disable_hook_timeline() -> None:
    global _config
    _config = None


def is_enabled() -> bool:
    return _config is not None


def write_hook(
    *,
    hook_type: str,
    hook_index: int,
    hook_type_index: int,
    agent_id: Optional[str] = None,
    replay_used: Optional[bool] = None,
    fault_injected: Optional[bool] = None,
    **fields: Any,
) -> None:
    if _config is None:
        return

    record: dict[str, Any] = {
        "hook_type": hook_type,
        "hook_index": hook_index,
        "hook_type_index": hook_type_index,
        "session_id": message_store.current_session_id(),
        "segment": message_store.current_segment(),
        "agent_id": agent_id,
    }
    if replay_used is not None:
        record["replay_used"] = replay_used
    if fault_injected is not None:
        record["fault_injected"] = fault_injected
    for key, value in fields.items():
        if value is not None:
            record[key] = value

    with open(_config.path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_timeline(path: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError(f"Expected JSON object at line {line_no} in {path}")
            records.append(record)
    records.sort(
        key=lambda r: (
            r.get("hook_index") is None,
            int(r.get("hook_index") or 0),
        )
    )
    return records


def find_fault_hook_index(
    timeline: list[dict[str, Any]],
    fault_spec: dict[str, Any],
) -> int:
    """Delegate to shared A2A fault selector matching (Jaeger rows or hook-timeline JSONL)."""
    from .injection.a2a_fault import find_fault_hook_index as _find

    return _find(timeline, fault_spec)


def suggest_replay_until_hook_index(fault_hook_index: int, timeline: list[dict[str, Any]]) -> int:
    """
    First hook strictly after the fault point — live LLM/A2A continuation starts here.
    """
    for record in timeline:
        hook_index = record.get("hook_index")
        if isinstance(hook_index, int) and hook_index > fault_hook_index:
            return hook_index
    return fault_hook_index + 1
