from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any, Optional


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ReplayRecordConfig:
    path: str


@dataclass(frozen=True)
class PrefixReplayConfig:
    path: str
    until_hook_index: int
    strict: bool = True


_record_config: Optional[ReplayRecordConfig] = None
_prefix_replay_config: Optional[PrefixReplayConfig] = None
_llm_replay_by_hook: dict[tuple[Optional[str], int], dict[str, Any]] = {}


def enable_replay_recording(path: str, *, append: bool = False) -> None:
    """
    Record full LLM responses to JSONL so a later run can replay a known prefix.
    """
    global _record_config
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if not append:
        open(path, "w", encoding="utf-8").close()
    _record_config = ReplayRecordConfig(path=path)


def disable_replay_recording() -> None:
    global _record_config
    _record_config = None


def enable_prefix_replay(path: str, *, until_hook_index: int, strict: bool = True) -> None:
    """
    Replay recorded LLM responses for hook indices before `until_hook_index`.

    The target hook itself is not replayed; execution switches back to live mode
    there so a fault can be injected at that exact point.
    """
    if until_hook_index <= 0:
        raise ValueError("until_hook_index must be a positive integer")

    global _prefix_replay_config, _llm_replay_by_hook
    _prefix_replay_config = PrefixReplayConfig(
        path=path,
        until_hook_index=until_hook_index,
        strict=strict,
    )
    _llm_replay_by_hook = {}

    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("kind") != "llm_call":
                continue
            hook_index = record.get("hook_index")
            if not isinstance(hook_index, int):
                raise ValueError(f"Replay record at line {line_no} is missing integer hook_index")
            _llm_replay_by_hook[(record.get("session_id"), hook_index)] = record


def disable_prefix_replay() -> None:
    global _prefix_replay_config, _llm_replay_by_hook
    _prefix_replay_config = None
    _llm_replay_by_hook = {}


def is_replay_recording_enabled() -> bool:
    return _record_config is not None


def is_prefix_replay_enabled() -> bool:
    return _prefix_replay_config is not None


def should_replay_hook(hook_index: int) -> bool:
    return _prefix_replay_config is not None and hook_index < _prefix_replay_config.until_hook_index


def write_llm_record(
    *,
    session_id: Optional[str],
    hook_index: int,
    hook_type_index: int,
    provider_name: str,
    model: str,
    operation_name: str,
    request_id: str,
    input_text: str,
    response: Any,
) -> None:
    if _record_config is None:
        return

    record = {
        "kind": "llm_call",
        "session_id": session_id,
        "hook_index": hook_index,
        "hook_type_index": hook_type_index,
        "provider": provider_name,
        "model": model,
        "operation": operation_name,
        "request_id": request_id,
        "input_sha256": _sha256_hex(input_text),
        "response": response,
    }
    with open(_record_config.path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def get_llm_replay_response(
    *,
    session_id: Optional[str],
    hook_index: int,
    input_text: str,
) -> Optional[Any]:
    if _prefix_replay_config is None or not should_replay_hook(hook_index):
        return None

    record = _llm_replay_by_hook.get((session_id, hook_index))
    if record is None:
        if _prefix_replay_config.strict:
            raise KeyError(f"No replay record for session_id={session_id!r}, hook_index={hook_index}")
        return None

    recorded_input_sha = record.get("input_sha256")
    actual_input_sha = _sha256_hex(input_text)
    if recorded_input_sha != actual_input_sha:
        msg = (
            f"Replay prefix diverged at hook_index={hook_index}: "
            f"expected input_sha256={recorded_input_sha}, got {actual_input_sha}"
        )
        if _prefix_replay_config.strict:
            raise ValueError(msg)
        return None

    return record.get("response")
