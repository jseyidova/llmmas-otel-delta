from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from .a2a_fault import A2AFaultInjector, A2AInjectionResult, load_a2a_fault_spec

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class A2AReplayConfig:
    path: str
    strict: bool = True


_config: Optional[A2AReplayConfig] = None
_records: list[dict[str, Any]] = []
_index: int = 0
_replay_active: bool = False
_injector: A2AFaultInjector = A2AFaultInjector.disabled()
_last_injection: Optional[A2AInjectionResult] = None


def _load_jsonl(path: str) -> list[dict[str, Any]]:
    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise FileNotFoundError(
            f"A2A replay trace not found: {resolved}\n"
            "Record a baseline first (no --replay-a2a-trace / --a2a-fault), e.g.:\n"
            "  --a2a-messages out/baseline-monopoly/a2a-messages.jsonl\n"
            "  --llm-messages out/baseline-monopoly/llm-calls.jsonl\n"
            "Then point --replay-a2a-trace at that file for the fault run."
        )
    records: list[dict[str, Any]] = []
    with open(resolved, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError(f"Expected JSON object at line {line_no} in {path}")
            records.append(record)
    return records


def enable_from_records(
    records: list[dict[str, Any]],
    *,
    fault_spec: Optional[dict[str, Any]] = None,
    strict: bool = True,
) -> None:
    """Replay A2A bodies from in-memory message-store rows (e.g. parsed Jaeger trace)."""
    global _config, _records, _index, _replay_active, _injector, _last_injection

    _records = list(records)
    _index = 0
    _replay_active = True
    _last_injection = None
    _injector = (
        A2AFaultInjector.from_dict(fault_spec)
        if fault_spec is not None
        else A2AFaultInjector.disabled()
    )
    _config = A2AReplayConfig(path="<memory>", strict=strict)
    logger.info("A2A trace replay enabled: %s messages from memory", len(_records))


def enable(
    trace_path: str,
    *,
    fault_spec: Optional[dict[str, Any]] = None,
    strict: bool = True,
) -> None:
    """
    Replay A2A bodies from a baseline ``a2a-messages.jsonl`` trace.

    When a fault spec is enabled, replay stops after the first successful injection
    so later A2A hooks use live ChatDev bodies (post-fault continuation).
    """
    global _config, _records, _index, _replay_active, _injector, _last_injection

    enable_from_records(_load_jsonl(trace_path), fault_spec=fault_spec, strict=strict)
    global _config
    _config = A2AReplayConfig(path=trace_path, strict=strict)
    logger.info("A2A trace replay enabled: %s messages from %s", len(_records), trace_path)


def enable_from_files(
    trace_path: str,
    *,
    fault_spec_path: Optional[str] = None,
    strict: bool = True,
) -> None:
    fault_spec = load_a2a_fault_spec(fault_spec_path) if fault_spec_path else None
    enable(trace_path, fault_spec=fault_spec, strict=strict)


def disable() -> None:
    global _config, _records, _index, _replay_active, _injector, _last_injection
    _config = None
    _records = []
    _index = 0
    _replay_active = False
    _injector = A2AFaultInjector.disabled()
    _last_injection = None


def is_enabled() -> bool:
    return _config is not None


def is_replaying() -> bool:
    return _config is not None and _replay_active


def last_injection() -> Optional[A2AInjectionResult]:
    return _last_injection


def active_fault_type() -> Optional[str]:
    if not _injector.enabled:
        return None
    return _injector.fault_type


def _segment_name(record: dict[str, Any]) -> Optional[str]:
    segment = record.get("segment")
    if isinstance(segment, dict):
        return segment.get("name")
    return record.get("segment_name")


def _live_record(
    *,
    session_id: Optional[str],
    direction: str,
    segment_name: Optional[str],
    segment_order: Optional[int],
    source_agent_id: str,
    target_agent_id: str,
    edge_id: str,
    message_id: str,
    body: Optional[str],
) -> dict[str, Any]:
    segment: Optional[dict[str, Any]] = None
    if segment_name is not None:
        segment = {"name": segment_name}
        if segment_order is not None:
            segment["order"] = segment_order
    return {
        "session_id": session_id,
        "segment": segment,
        "direction": direction,
        "message_id": message_id,
        "source_agent_id": source_agent_id,
        "target_agent_id": target_agent_id,
        "edge_id": edge_id,
        "body": body,
    }


def _assert_live_matches_record(live: dict[str, Any], record: dict[str, Any]) -> None:
    if _config is None or not _config.strict:
        return
    mismatches: list[str] = []
    if live.get("direction") != record.get("direction"):
        mismatches.append(
            f"direction: live={live.get('direction')!r} record={record.get('direction')!r}"
        )
    if live.get("edge_id") != record.get("edge_id"):
        mismatches.append(f"edge_id: live={live.get('edge_id')!r} record={record.get('edge_id')!r}")
    if live.get("source_agent_id") != record.get("source_agent_id"):
        mismatches.append(
            "source_agent_id: "
            f"live={live.get('source_agent_id')!r} record={record.get('source_agent_id')!r}"
        )
    if live.get("target_agent_id") != record.get("target_agent_id"):
        mismatches.append(
            "target_agent_id: "
            f"live={live.get('target_agent_id')!r} record={record.get('target_agent_id')!r}"
        )
    live_seg = _segment_name(live)
    record_seg = _segment_name(record)
    # Jaeger exports often omit segment on A2A spans; replay is order-based then.
    if record_seg is not None and live_seg != record_seg:
        mismatches.append(f"segment.name: live={live_seg!r} record={record_seg!r}")
    if mismatches:
        raise ValueError(
            f"A2A replay diverged at index {_index}: " + "; ".join(mismatches)
        )


def apply_body(
    *,
    session_id: Optional[str],
    direction: str,
    segment_name: Optional[str],
    segment_order: Optional[int],
    source_agent_id: str,
    target_agent_id: str,
    edge_id: str,
    message_id: str,
    live_body: Optional[str],
    apply_to_message: Optional[Callable[[str], None]] = None,
) -> Optional[str]:
    global _index, _replay_active, _last_injection

    if _config is None or not _replay_active:
        _last_injection = None
        return None
    if _index >= len(_records):
        if _config.strict:
            raise IndexError(
                f"A2A replay exhausted at index {_index}; no record for "
                f"direction={direction!r} edge_id={edge_id!r}"
            )
        _last_injection = None
        return None

    record = _records[_index]
    live = _live_record(
        session_id=session_id,
        direction=direction,
        segment_name=segment_name,
        segment_order=segment_order,
        source_agent_id=source_agent_id,
        target_agent_id=target_agent_id,
        edge_id=edge_id,
        message_id=message_id,
        body=live_body,
    )
    _assert_live_matches_record(live, record)

    injection = _injector.inject_with_metadata(record)
    _last_injection = injection
    _index += 1
    if injection.injected and _injector.enabled:
        _replay_active = False
        logger.info(
            "A2A trace replay stopped after fault injection (record index %s); "
            "later A2A hooks use live ChatDev messages",
            _index - 1,
        )

    body = str(injection.message.get("body") or "")
    if apply_to_message is not None:
        apply_to_message(body)
    return body
