from __future__ import annotations

import copy
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class A2AFaultSelector:
    hook_index: Optional[int] = None
    segment_name: Optional[str] = None
    edge_id: Optional[str] = None
    direction: Optional[str] = None
    occurrence: int = 0
    source_agent_id: Optional[str] = None
    target_agent_id: Optional[str] = None


@dataclass(frozen=True)
class A2ATruncateConfig:
    mode: str  # cut_after_text | max_chars
    cut_after_text: Optional[str] = None
    max_chars: Optional[int] = None


@dataclass(frozen=True)
class A2AFaultConfig:
    enabled: bool = False
    fault_type: str = "truncate_message"
    selector: A2AFaultSelector = field(default_factory=A2AFaultSelector)
    truncate: A2ATruncateConfig = field(default_factory=lambda: A2ATruncateConfig(mode="max_chars", max_chars=0))
    on_missing_cut_text: str = "error"  # error | warn


@dataclass(frozen=True)
class A2AInjectionResult:
    message: dict[str, Any]
    injected: bool
    original_body: Optional[str] = None
    truncated_body: Optional[str] = None


class A2AFaultInjector:
    """Truncate an A2A message body during trace replay (deep copy; no in-place mutation)."""

    def __init__(self, config: A2AFaultConfig) -> None:
        self._config = config
        self._occurrence_counts: dict[tuple[Any, ...], int] = {}
        self.last_result: Optional[A2AInjectionResult] = None

    @classmethod
    def disabled(cls) -> A2AFaultInjector:
        return cls(A2AFaultConfig(enabled=False))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> A2AFaultInjector:
        selector_data = data.get("selector") or {}
        truncate_data = data.get("truncate") or {}
        hook_index = selector_data.get("hook_index")
        selector = A2AFaultSelector(
            hook_index=int(hook_index) if hook_index is not None else None,
            segment_name=selector_data.get("segment_name"),
            edge_id=selector_data.get("edge_id"),
            direction=selector_data.get("direction"),
            occurrence=int(selector_data.get("occurrence", 0)),
            source_agent_id=selector_data.get("source_agent_id"),
            target_agent_id=selector_data.get("target_agent_id"),
        )
        truncate = A2ATruncateConfig(
            mode=str(truncate_data.get("mode", "max_chars")),
            cut_after_text=truncate_data.get("cut_after_text"),
            max_chars=truncate_data.get("max_chars"),
        )
        config = A2AFaultConfig(
            enabled=bool(data.get("enabled", False)),
            fault_type=str(data.get("fault_type", "truncate_message")),
            selector=selector,
            truncate=truncate,
            on_missing_cut_text=str(data.get("on_missing_cut_text", "error")),
        )
        return cls(config)

    @classmethod
    def from_json_file(cls, path: str | Path) -> A2AFaultInjector:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(data)

    def reset(self) -> None:
        self._occurrence_counts.clear()
        self.last_result = None

    def inject(self, message: dict[str, Any]) -> dict[str, Any]:
        result = self.inject_with_metadata(message)
        self.last_result = result
        return result.message

    def inject_with_metadata(self, message: dict[str, Any]) -> A2AInjectionResult:
        out = copy.deepcopy(message)
        if not self._config.enabled:
            return A2AInjectionResult(message=out, injected=False)

        if not self._selector_fields_match(message):
            return A2AInjectionResult(message=out, injected=False)

        key = self._selector_key()
        seen = self._occurrence_counts.get(key, 0)
        self._occurrence_counts[key] = seen + 1
        if seen != self._config.selector.occurrence:
            return A2AInjectionResult(message=out, injected=False)

        original_body = str(message.get("body") or "")
        try:
            truncated_body = self._truncate_body(original_body)
        except ValueError:
            self._log_selection(message, original_body, original_body, injected=False)
            raise

        if truncated_body == original_body:
            self._log_selection(message, original_body, original_body, injected=False)
            return A2AInjectionResult(message=out, injected=False)

        out["body"] = truncated_body
        out["fault_injected"] = True
        out["fault_type"] = self._config.fault_type
        out["original_body"] = original_body

        self._log_selection(message, original_body, truncated_body, injected=True)
        return A2AInjectionResult(
            message=out,
            injected=True,
            original_body=original_body,
            truncated_body=truncated_body,
        )

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    @property
    def fault_type(self) -> str:
        return self._config.fault_type

    def _selector_key(self) -> tuple[Any, ...]:
        s = self._config.selector
        return (
            s.hook_index,
            s.segment_name,
            s.edge_id,
            s.direction,
            s.source_agent_id,
            s.target_agent_id,
        )

    def _segment_name(self, message: dict[str, Any]) -> Optional[str]:
        segment = message.get("segment")
        if isinstance(segment, dict):
            return segment.get("name")
        return message.get("segment_name") or message.get("phase_name")

    @staticmethod
    def _effective_direction(message: dict[str, Any]) -> Optional[str]:
        direction = message.get("direction")
        if direction is not None:
            return str(direction)
        hook_type = str(message.get("hook_type") or message.get("kind") or "")
        if hook_type.endswith("_send") or hook_type == "a2a_send":
            return "send"
        if hook_type.endswith("_receive") or hook_type == "a2a_receive":
            return "receive"
        operation = str(message.get("operation_name") or "")
        if operation.startswith("send "):
            return "send"
        if operation.startswith("process "):
            return "receive"
        return None

    def _selector_fields_match(self, message: dict[str, Any]) -> bool:
        sel = self._config.selector
        if sel.hook_index is not None and message.get("hook_index") != sel.hook_index:
            return False
        if sel.segment_name is not None and self._segment_name(message) != sel.segment_name:
            return False
        if sel.edge_id is not None and message.get("edge_id") != sel.edge_id:
            return False
        if sel.direction is not None and self._effective_direction(message) != sel.direction:
            return False
        if sel.source_agent_id is not None and message.get("source_agent_id") != sel.source_agent_id:
            return False
        if sel.target_agent_id is not None and message.get("target_agent_id") != sel.target_agent_id:
            return False
        return True

    def _truncate_body(self, body: str) -> str:
        cfg = self._config.truncate
        if cfg.mode == "max_chars":
            if cfg.max_chars is None:
                raise ValueError("truncate.max_chars is required for max_chars mode")
            if cfg.max_chars < 0:
                raise ValueError("truncate.max_chars must be >= 0")
            return body[: cfg.max_chars]

        if cfg.mode == "cut_after_text":
            if not cfg.cut_after_text:
                raise ValueError("truncate.cut_after_text is required for cut_after_text mode")
            index = body.find(cfg.cut_after_text)
            if index < 0:
                msg = f"cut_after_text not found in message body: {cfg.cut_after_text!r}"
                if self._config.on_missing_cut_text == "warn":
                    logger.warning("A2A fault injection skipped: %s", msg)
                    return body
                raise ValueError(msg)
            end = index + len(cfg.cut_after_text)
            return body[:end]

        raise ValueError(f"Unknown truncate mode: {cfg.mode!r}")

    def _log_selection(
        self,
        message: dict[str, Any],
        original_body: str,
        truncated_body: str,
        *,
        injected: bool,
    ) -> None:
        logger.info(
            "A2A fault injection: injected=%s fault_type=%s segment=%s edge_id=%s "
            "direction=%s source_agent_id=%s target_agent_id=%s message_id=%s "
            "original_len=%s truncated_len=%s",
            injected,
            self._config.fault_type if injected else None,
            self._segment_name(message),
            message.get("edge_id"),
            message.get("direction"),
            message.get("source_agent_id"),
            message.get("target_agent_id"),
            message.get("message_id"),
            len(original_body),
            len(truncated_body),
        )


def find_fault_hook_index(
    messages: list[dict[str, Any]],
    fault_spec: dict[str, Any],
) -> int:
    """
    Return global ``hook_index`` for the first message matching an A2A fault selector.
    Works on Jaeger-derived a2a rows or hook-timeline JSONL.
    """
    injector = A2AFaultInjector.from_dict(fault_spec)

    occurrence = injector._config.selector.occurrence
    counts: dict[tuple[Any, ...], int] = {}
    key = injector._selector_key()

    ordered = sorted(
        messages,
        key=lambda m: (m.get("hook_index") is None, int(m.get("hook_index") or 0)),
    )
    for message in ordered:
        hook_type = str(message.get("hook_type") or message.get("kind") or "")
        if not (
            hook_type.startswith("a2a_")
            or message.get("direction") in ("send", "receive")
            or hook_type in ("a2a_send", "a2a_receive", "a2a_message")
        ):
            continue
        if not injector._selector_fields_match(message):
            continue
        seen = counts.get(key, 0)
        counts[key] = seen + 1
        if seen != occurrence:
            continue
        hook_index = message.get("hook_index")
        if not isinstance(hook_index, int):
            raise ValueError("Matching message row is missing integer hook_index")
        return hook_index

    lines: list[str] = []
    for message in ordered:
        hook_type = str(message.get("hook_type") or message.get("kind") or "")
        if not hook_type.startswith("a2a_") and message.get("direction") not in ("send", "receive"):
            continue
        lines.append(
            f"  hook_index={message.get('hook_index')} "
            f"segment={injector._segment_name(message)!r} "
            f"direction={injector._effective_direction(message)!r} "
            f"edge_id={message.get('edge_id')!r} "
            f"source={message.get('source_agent_id')!r} "
            f"target={message.get('target_agent_id')!r}"
        )
    detail = "\n".join(lines[:40]) if lines else "  (no A2A rows in input)"
    raise ValueError(
        "No message matches the A2A fault selector. Candidates in trace:\n" + detail
    )


def load_a2a_fault_spec(path: str | Path) -> dict[str, Any]:
    """Load a single JSON object describing an A2A truncate_message fault."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"A2A fault spec must be a JSON object: {path}")
    if data.get("fault_type") != "truncate_message":
        raise ValueError(f"A2A fault spec must use fault_type 'truncate_message': {path}")
    if "selector" not in data or "truncate" not in data:
        raise ValueError(f"A2A fault spec must include 'selector' and 'truncate': {path}")
    return data
