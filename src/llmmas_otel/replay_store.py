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
_events_by_hook: dict[int, list[dict[str, Any]]] = {}


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


def _load_prefix_replay_events(events_path: str) -> None:
    global _events_by_hook
    _events_by_hook = {}
    with open(events_path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            hook_index = record.get("hook_index")
            if hook_index is None:
                continue
            if not isinstance(hook_index, int):
                raise ValueError(f"Replay event at line {line_no} is missing integer hook_index")
            _events_by_hook.setdefault(hook_index, []).append(record)


def _index_llm_records(records: list[dict[str, Any]]) -> dict[tuple[Optional[str], int], dict[str, Any]]:
    indexed: dict[tuple[Optional[str], int], dict[str, Any]] = {}
    for line_no, record in enumerate(records, start=1):
        if record.get("kind") != "llm_call":
            continue
        hook_index = record.get("hook_index")
        if not isinstance(hook_index, int):
            raise ValueError(f"LLM replay record at index {line_no} is missing integer hook_index")
        indexed[(record.get("session_id"), hook_index)] = record
    return indexed


def _index_events_from_records(events: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    indexed: dict[int, list[dict[str, Any]]] = {}
    for record in events:
        hook_index = record.get("hook_index")
        if hook_index is None:
            continue
        if not isinstance(hook_index, int):
            raise ValueError("Replay event is missing integer hook_index")
        indexed.setdefault(hook_index, []).append(record)
    return indexed


def enable_prefix_replay_from_records(
    records: list[dict[str, Any]],
    *,
    until_hook_index: int,
    strict: bool = True,
    events: Optional[list[dict[str, Any]]] = None,
) -> None:
    """Replay LLM responses from in-memory records (e.g. parsed Jaeger trace)."""
    if until_hook_index <= 0:
        raise ValueError("until_hook_index must be a positive integer")

    global _prefix_replay_config, _llm_replay_by_hook, _events_by_hook
    _prefix_replay_config = PrefixReplayConfig(
        path="<memory>",
        until_hook_index=until_hook_index,
        strict=strict,
    )
    _llm_replay_by_hook = _index_llm_records(records)
    _events_by_hook = _index_events_from_records(events) if events is not None else {}


def enable_prefix_replay(
    path: str,
    *,
    until_hook_index: int,
    strict: bool = True,
    events_path: Optional[str] = None,
) -> None:
    """
    Replay recorded LLM responses for hook indices before `until_hook_index`.

    The target hook itself is not replayed; execution switches back to live mode
    there so a fault can be injected at that exact point.
    """
    records: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    events: Optional[list[dict[str, Any]]] = None
    if events_path is not None:
        events = []
        with open(events_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    events.append(json.loads(line))
    enable_prefix_replay_from_records(
        records,
        until_hook_index=until_hook_index,
        strict=strict,
        events=events,
    )


def disable_prefix_replay() -> None:
    global _prefix_replay_config, _llm_replay_by_hook, _events_by_hook
    _prefix_replay_config = None
    _llm_replay_by_hook = {}
    _events_by_hook = {}


def is_replay_recording_enabled() -> bool:
    return _record_config is not None


def is_prefix_replay_enabled() -> bool:
    return _prefix_replay_config is not None


def should_replay_hook(hook_index: int) -> bool:
    return _prefix_replay_config is not None and hook_index < _prefix_replay_config.until_hook_index


def should_validate_hook(hook_index: int) -> bool:
    return should_replay_hook(hook_index)


def validate_a2a_event(
    *,
    hook_index: int,
    direction: str,
    source_agent_id: str,
    target_agent_id: str,
    message_id: str,
    body: str,
    skip: bool = False,
) -> None:
    if skip or _prefix_replay_config is None or not should_validate_hook(hook_index):
        return
    if not _events_by_hook:
        return

    actual_sha = _sha256_hex(body)
    matches = [
        event
        for event in _events_by_hook.get(hook_index, [])
        if str(event.get("kind")) == f"a2a_{direction}"
    ]
    if not matches:
        msg = f"No baseline A2A {direction} event for hook_index={hook_index}"
        if _prefix_replay_config.strict:
            raise ValueError(msg)
        return

    expected = matches[0]
    mismatches: list[str] = []
    for key, actual in (
        ("source_agent_id", source_agent_id),
        ("target_agent_id", target_agent_id),
        ("message_id", message_id),
    ):
        expected_value = expected.get(key)
        if expected_value is not None and expected_value != actual:
            mismatches.append(f"{key}: expected {expected_value!r}, got {actual!r}")

    expected_sha = expected.get("message_sha256")
    if expected_sha is not None and expected_sha != actual_sha:
        mismatches.append(f"message_sha256: expected {expected_sha!r}, got {actual_sha!r}")

    if mismatches and _prefix_replay_config.strict:
        raise ValueError(
            f"A2A prefix diverged at hook_index={hook_index}, direction={direction}: "
            + "; ".join(mismatches)
        )


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
    agent_id: Optional[str] = None,
) -> None:
    if _record_config is None:
        return

    record = {
        "kind": "llm_call",
        "session_id": session_id,
        "agent_id": agent_id,
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
        # Jaeger exports may not include the session span. In that case the
        # converter writes replay records with a null session_id; allow those
        # to replay for the matching hook in the current session.
        record = _llm_replay_by_hook.get((None, hook_index))
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

    response = record.get("response")
    # When recording on a fault run, persist replayed prefix rows too so the
    # output file is a complete faulty-trajectory replay (prefix + live suffix).
    if _record_config is not None and response is not None:
        write_llm_record(
            session_id=session_id if session_id is not None else record.get("session_id"),
            agent_id=record.get("agent_id"),
            hook_index=hook_index,
            hook_type_index=int(record.get("hook_type_index") or 0),
            provider_name=str(record.get("provider") or "ollama"),
            model=str(record.get("model") or ""),
            operation_name=str(record.get("operation") or "chat.completions"),
            request_id=str(record.get("request_id") or ""),
            input_text=input_text,
            response=response,
        )

    return response
