from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .jaeger_parser import (
    hook_type_from_operation,
    iter_trace_spans,
    load_jaeger_trace,
    message_body_from_span,
    segment_name_for_span,
    tags_dict,
)
from .types import HookType

logger = logging.getLogger("llmmas.trace_replay")


def _record_trace_replay_action(action: str) -> None:
    from .trace_replay import set_trace_replay_action

    set_trace_replay_action(action)

_SYSTEM_TASK_PATTERN = re.compile(
    r"(Here is a new customer's task:\s*).*?(\.\s*To complete the task)",
    re.DOTALL,
)

_A2A_TASK_PATTERN = re.compile(r'(Task:\s*")([^"]*)(")', re.DOTALL)


def extract_truncated_task_prompt(injected_body: str) -> str:
    """Best-effort task text for system-prompt propagation from an injected A2A body."""
    match = re.search(r'Task:\s*"([^"]*)', injected_body, re.DOTALL)
    if match:
        return match.group(1).strip()
    return injected_body.strip()


def truncate_system_task_content(content: str, truncated_task: str) -> str:
    if "Here is a new customer's task:" not in content:
        return content
    return _SYSTEM_TASK_PATTERN.sub(
        lambda m: f"{m.group(1)}{truncated_task}{m.group(2)}",
        content,
        count=1,
    )


def truncate_a2a_task_content(content: str, truncated_task: str) -> str:
    """Replace the first Task: \"...\" block (ChatDev phase handoff messages)."""
    if 'Task: "' not in content:
        return content
    return _A2A_TASK_PATTERN.sub(
        lambda m: f"{m.group(1)}{truncated_task}{m.group(3)}",
        content,
        count=1,
    )


@dataclass(frozen=True)
class ReplayEvent:
    event_index: int
    hook_type: str
    sender: Optional[str]
    receiver: Optional[str]
    segment_name: Optional[str]
    message_body: str
    raw_span: dict[str, Any] = field(repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_index": self.event_index,
            "hook_type": self.hook_type,
            "sender": self.sender,
            "receiver": self.receiver,
            "segment_name": self.segment_name,
            "message_body": self.message_body,
            "raw_span": self.raw_span,
        }


def extract_replay_events(
    trace_doc: dict[str, Any],
    *,
    hooks: Optional[list[str]] = None,
) -> list[ReplayEvent]:
    """
    Extract replayable A2A events from a Jaeger trace export, sorted by span startTime.

    event_index is the global chronological hook index (0-based) across send/receive.
    """
    allowed = set(hooks or ["a2a_send", "a2a_receive"])
    spans = iter_trace_spans(trace_doc)
    spans_by_id = {str(s.get("spanID")): s for s in spans if s.get("spanID")}

    candidates: list[tuple[int, dict[str, Any], str]] = []
    for span in spans:
        hook_type = hook_type_from_operation(str(span.get("operationName") or ""))
        if hook_type is None or hook_type not in allowed:
            continue
        body = message_body_from_span(span)
        if body is None:
            continue
        start_time = int(span.get("startTime") or 0)
        candidates.append((start_time, span, hook_type))

    candidates.sort(key=lambda item: item[0])

    events: list[ReplayEvent] = []
    for event_index, (_start, span, hook_type) in enumerate(candidates):
        msg_body = message_body_from_span(span)
        if msg_body is None:
            continue

        tags = tags_dict(span)
        sender = tags.get("llmmas.source_agent.id")
        receiver = tags.get("llmmas.target_agent.id")
        if not isinstance(sender, str):
            sender = None
        if not isinstance(receiver, str):
            receiver = None

        events.append(
            ReplayEvent(
                event_index=event_index,
                hook_type=hook_type,
                sender=sender,
                receiver=receiver,
                segment_name=segment_name_for_span(span, spans_by_id),
                message_body=msg_body,
                raw_span=span,
            )
        )

    return events


def load_replay_events_from_jaeger(
    trace_path: str,
    *,
    hooks: Optional[list[str]] = None,
) -> list[ReplayEvent]:
    return extract_replay_events(load_jaeger_trace(trace_path), hooks=hooks)


@dataclass(frozen=True)
class ReplayFaultConfig:
    """Inject a replacement message at one global hook, then resume live execution."""

    inject_at_hook_index: int  # 0-based (hook 15 → index 14)
    fault_type: str = "truncate"
    replacement_message: Optional[str] = None
    truncate_length: int = 80
    # After A2A inject, also truncate what the next LLM call(s) see (system task leak).
    propagate_to_llm: bool = True
    llm_propagate_calls: int = 1
    propagate_to_live_a2a: bool = True
    truncated_task_prompt: Optional[str] = None

    def validate(self) -> None:
        if self.inject_at_hook_index < 0:
            raise ValueError("inject_at_hook_index must be >= 0")
        if self.fault_type not in ("truncate", "replace"):
            raise ValueError(f"Unsupported fault_type: {self.fault_type!r}")
        if self.fault_type == "replace" and not self.replacement_message:
            raise ValueError("replacement_message is required when fault_type is 'replace'")
        if self.llm_propagate_calls < 0:
            raise ValueError("llm_propagate_calls must be >= 0")


@dataclass
class SequentialReplayProvider:
    """
    Replays A2A message bodies in global chronological hook order (matching baseline trace).

    live_from_hook_index (0-based): hooks with index < N are replayed; index >= N use live payloads.
    Example: live_from_hook_index=14 → replay hooks 0..13, hook 14+ are live (15th hook live if counting from 1).

    fault (ReplayFaultConfig): replay hooks 0..inject_at-1, inject at inject_at, live from inject_at+1.
    Example: inject_at_hook_index=14 (hook 15) → replay 1-14, fault at 15, live from 16+.
    """

    events: list[ReplayEvent]
    hooks: list[str] = field(default_factory=lambda: ["a2a_send", "a2a_receive"])
    live_from_hook_index: Optional[int] = None
    fault: Optional[ReplayFaultConfig] = None
    _global_runtime_index: int = 0
    _llm_propagate_remaining: int = 0
    _llm_truncated_task: Optional[str] = None

    def apply_llm_messages(self, messages: list[dict[str, str]]) -> list[dict[str, str]]:
        """
        Truncate leaked full task text in system prompts for the next N LLM calls after A2A inject.
        """
        if self._llm_propagate_remaining <= 0 or not self._llm_truncated_task:
            return messages

        self._llm_propagate_remaining -= 1
        updated: list[dict[str, str]] = []
        changed = False
        for msg in messages:
            if msg.get("role") == "system":
                old = msg.get("content") or ""
                new = truncate_system_task_content(old, self._llm_truncated_task)
                if new != old:
                    changed = True
                updated.append({**msg, "content": new})
            else:
                updated.append(dict(msg))

        logger.info(
            "trace_replay llm_propagate applied changed=%s truncated_task_preview=%s remaining=%s",
            changed,
            _preview(self._llm_truncated_task, 120),
            self._llm_propagate_remaining,
        )
        return updated

    def _arm_llm_propagation(self, injected_body: str) -> None:
        if self.fault is None:
            self._llm_propagate_remaining = 0
            self._llm_truncated_task = None
            return

        llm_on = self.fault.propagate_to_llm and self.fault.llm_propagate_calls > 0
        a2a_on = self.fault.propagate_to_live_a2a
        if not llm_on and not a2a_on:
            self._llm_propagate_remaining = 0
            self._llm_truncated_task = None
            return

        if self.fault.truncated_task_prompt:
            task = self.fault.truncated_task_prompt
        else:
            task = extract_truncated_task_prompt(injected_body)
        self._llm_truncated_task = task
        self._llm_propagate_remaining = self.fault.llm_propagate_calls if llm_on else 0
        logger.info(
            "trace_replay task_propagate armed llm_calls=%s live_a2a=%s task_preview=%s",
            self._llm_propagate_remaining,
            a2a_on,
            _preview(task, 120),
        )

    def _apply_live_a2a_truncation(self, body: Optional[str]) -> Optional[str]:
        if body is None or not self._llm_truncated_task:
            return body
        if self.fault is None or not self.fault.propagate_to_live_a2a:
            return body
        new = truncate_a2a_task_content(body, self._llm_truncated_task)
        if new != body:
            logger.info(
                "trace_replay live_a2a_propagate applied=true task_preview=%s body_preview=%s",
                _preview(self._llm_truncated_task, 120),
                _preview(new, 160),
            )
        return new

    @classmethod
    def from_jaeger_trace(
        cls,
        trace_path: str,
        *,
        hooks: Optional[list[str]] = None,
        live_from_hook_index: Optional[int] = None,
        fault: Optional[ReplayFaultConfig] = None,
    ) -> "SequentialReplayProvider":
        hook_list = list(hooks or ["a2a_send", "a2a_receive"])
        events = load_replay_events_from_jaeger(trace_path, hooks=hook_list)
        return cls(
            events=events,
            hooks=hook_list,
            live_from_hook_index=live_from_hook_index,
            fault=fault,
        )

    def _effective_live_from_hook_index(self) -> Optional[int]:
        if self.fault is not None:
            return self.fault.inject_at_hook_index + 1
        return self.live_from_hook_index

    def _injected_body_for_hook(self, hook_index: int) -> str:
        assert self.fault is not None
        if self.fault.replacement_message is not None:
            return self.fault.replacement_message
        baseline = ""
        if hook_index < len(self.events):
            baseline = self.events[hook_index].message_body
        if self.fault.fault_type == "truncate":
            limit = self.fault.truncate_length
            if len(baseline) <= limit:
                return baseline
            return baseline[:limit] + "..."
        return baseline

    def replay_message_body(
        self,
        hook_type: HookType | str,
        current_body: Optional[str],
        *,
        sender: Optional[str] = None,
        receiver: Optional[str] = None,
        apply_mutation: Optional[Callable[[str], None]] = None,
    ) -> Optional[str]:
        hook_key = hook_type.value if isinstance(hook_type, HookType) else str(hook_type)
        if hook_key not in self.hooks:
            return current_body

        hook_index = self._global_runtime_index
        self._global_runtime_index += 1
        hook_number = hook_index + 1
        live_from = self._effective_live_from_hook_index()

        if live_from is not None and hook_index >= live_from:
            reason = "after_fault_injection" if self.fault is not None else "live_mode"
            live_body = self._apply_live_a2a_truncation(current_body)
            _record_trace_replay_action("live")
            logger.info(
                "trace_replay live hook_type=%s global_hook_index=%s hook_number=%s "
                "live_from_hook_index=%s applied=false reason=%s sender=%s receiver=%s preview=%s",
                hook_key,
                hook_index,
                hook_number,
                live_from,
                reason,
                sender,
                receiver,
                _preview(live_body),
            )
            return live_body

        if (
            self.fault is not None
            and hook_index == self.fault.inject_at_hook_index
        ):
            injected_body = self._injected_body_for_hook(hook_index)
            baseline_preview = (
                _preview(self.events[hook_index].message_body)
                if hook_index < len(self.events)
                else ""
            )
            if apply_mutation is not None:
                apply_mutation(injected_body)
            self._arm_llm_propagation(injected_body)
            _record_trace_replay_action("fault_inject")
            logger.info(
                "trace_replay fault_injected hook_type=%s global_hook_index=%s hook_number=%s "
                "fault_type=%s applied=true sender=%s receiver=%s baseline_preview=%s injected_preview=%s",
                hook_key,
                hook_index,
                hook_number,
                self.fault.fault_type,
                sender,
                receiver,
                baseline_preview,
                _preview(injected_body),
            )
            return injected_body

        if hook_index >= len(self.events):
            _record_trace_replay_action("skipped")
            logger.info(
                "trace_replay skipped hook_type=%s global_hook_index=%s hook_number=%s "
                "replay_event_index=n/a applied=false reason=baseline_exhausted "
                "sender=%s receiver=%s preview=%s",
                hook_key,
                hook_index,
                hook_number,
                sender,
                receiver,
                _preview(current_body),
            )
            return current_body

        replay_event = self.events[hook_index]
        replayed_body = replay_event.message_body
        if apply_mutation is not None:
            apply_mutation(replayed_body)
        _record_trace_replay_action("replay")

        logger.info(
            "trace_replay applied hook_type=%s global_hook_index=%s hook_number=%s "
            "replay_event_index=%s applied=true sender=%s receiver=%s "
            "replay_sender=%s replay_receiver=%s preview=%s",
            hook_key,
            hook_index,
            hook_number,
            replay_event.event_index,
            sender,
            receiver,
            replay_event.sender,
            replay_event.receiver,
            _preview(replayed_body),
        )
        return replayed_body


def _preview(text: Optional[str], n: int = 100) -> str:
    if text is None:
        return ""
    if len(text) <= n:
        return text
    return text[:n] + "..."
