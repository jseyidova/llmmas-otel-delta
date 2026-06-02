from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Optional

from .jaeger_parser import tags_dict
from .replay_provider import ReplayEvent, extract_replay_events, load_replay_events_from_jaeger

OutputFormat = Literal["text", "md", "json"]

# Indented block (no markdown fences) so message boundaries stay obvious in .md/.txt
_MESSAGE_CONTENT_INDENT = "\t\t\t"
_MESSAGE_CLOSE_INDENT = "\t"


def format_message_content_block(message: str) -> str:
    """
    Render message body with explicit start/end markers and tab-indented lines.

    Example::

        message_content: {
                line one
                line two
        }
    """
    lines = ["message_content: {"]
    for line in message.splitlines() or [""]:
        lines.append(f"{_MESSAGE_CONTENT_INDENT}{line}")
    lines.append(f"{_MESSAGE_CLOSE_INDENT}}}")
    return "\n".join(lines)


@dataclass(frozen=True)
class TimelineEntry:
    hook_index: int  # 0-based (matches replay)
    hook_number: int  # 1-based (config inject_at_hook, etc.)
    hook_type: str
    phase: Optional[str]
    sender: Optional[str]
    receiver: Optional[str]
    operation: str
    message: str
    message_source: str  # body | preview | log
    replay_action: Optional[str] = None  # replay | inject | live | skipped

    def to_dict(self) -> dict[str, Any]:
        return {
            "hook_index": self.hook_index,
            "hook_number": self.hook_number,
            "hook_type": self.hook_type,
            "phase": self.phase,
            "sender": self.sender,
            "receiver": self.receiver,
            "operation": self.operation,
            "message": self.message,
            "message_source": self.message_source,
            "replay_action": self.replay_action,
        }


def _message_source(span: dict[str, Any]) -> str:
    tags = tags_dict(span)
    if tags.get("llmmas.message.body"):
        return "body"
    for log_entry in span.get("logs") or []:
        fields = {f.get("key"): f.get("value") for f in log_entry.get("fields") or []}
        if fields.get("event") == "a2a.message" and fields.get("llmmas.message.body"):
            return "log"
    if tags.get("llmmas.message.preview"):
        return "preview"
    return "unknown"


def _phase_for_event(event: ReplayEvent) -> Optional[str]:
    span = event.raw_span
    tags = tags_dict(span)
    for key in ("llmmas.phase.name", "llmmas.segment.name"):
        value = tags.get(key)
        if isinstance(value, str) and value:
            return value
    return event.segment_name


def build_timeline(
    trace_path: str | Path,
    *,
    hooks: Optional[list[str]] = None,
) -> list[TimelineEntry]:
    events = load_replay_events_from_jaeger(str(trace_path), hooks=hooks)
    entries: list[TimelineEntry] = []
    for event in events:
        span = event.raw_span
        op = str(span.get("operationName") or "")
        tags = tags_dict(span)
        replay_action = tags.get("llmmas.trace_replay.action")
        if replay_action is not None:
            replay_action = str(replay_action)
        entries.append(
            TimelineEntry(
                hook_index=event.event_index,
                hook_number=event.event_index + 1,
                hook_type=event.hook_type,
                phase=_phase_for_event(event),
                sender=event.sender,
                receiver=event.receiver,
                operation=op,
                message=event.message_body,
                message_source=_message_source(span),
                replay_action=replay_action,
            )
        )
    return entries


def format_timeline_text(
    entries: list[TimelineEntry],
    *,
    max_message_chars: Optional[int] = 2000,
    trace_path: Optional[str] = None,
) -> str:
    lines: list[str] = []
    if trace_path:
        lines.append(f"# Trace timeline: {trace_path}")
        lines.append(f"# A2A hooks: {len(entries)} (same numbering as trace replay)")
        lines.append("")

    for e in entries:
        direction = "send" if e.hook_type == "a2a_send" else "receive"
        agents = f"{e.sender or '?'} -> {e.receiver or '?'}"
        phase = e.phase or "(unknown phase)"
        msg = e.message
        if max_message_chars is not None and len(msg) > max_message_chars:
            msg = msg[: max_message_chars - 3] + "..."
        lines.append("=" * 72)
        lines.append(
            f"Hook #{e.hook_number}  (index {e.hook_index})  [{direction}]  phase={phase}"
        )
        lines.append(f"  agents: {agents}")
        lines.append(f"  operation: {e.operation}")
        lines.append(f"  message_source: {e.message_source}")
        for block_line in format_message_content_block(msg).splitlines():
            lines.append(f"  {block_line}")
        lines.append("")

    if not entries:
        lines.append("(no replayable A2A hooks with message body/preview found)")
    return "\n".join(lines).rstrip() + "\n"


def format_timeline_markdown(
    entries: list[TimelineEntry],
    *,
    max_message_chars: Optional[int] = 2000,
    trace_path: Optional[str] = None,
) -> str:
    lines: list[str] = []
    title = trace_path or "Jaeger trace"
    lines.append(f"# A2A timeline: `{title}`")
    lines.append("")
    lines.append(f"**{len(entries)} hooks** — numbering matches `inject_at_hook` / `live_from_hook_number` in replay config.")
    lines.append("")
    lines.append(
        "Replay column (`replay` / `inject` / `live` / `skipped`) comes from span tag "
        "`llmmas.trace_replay.action` on new runs. Hooks 3+ after inject are **live**, not baseline replay."
    )
    lines.append("")
    lines.append(
        "| Hook # | Index | Type | Phase | Sender | Receiver | Replay | Msg source |"
    )
    lines.append(
        "|--------|-------|------|-------|--------|----------|--------|------------|"
    )
    for e in entries:
        kind = "send" if e.hook_type == "a2a_send" else "recv"
        lines.append(
            f"| {e.hook_number} | {e.hook_index} | {kind} | {e.phase or ''} | "
            f"{e.sender or ''} | {e.receiver or ''} | {e.replay_action or ''} | {e.message_source} |"
        )
    lines.append("")

    for e in entries:
        msg = e.message
        if max_message_chars is not None and len(msg) > max_message_chars:
            msg = msg[: max_message_chars - 3] + "..."
        kind = "send" if e.hook_type == "a2a_send" else "receive"
        lines.append(f"## Hook {e.hook_number} — {kind} ({e.phase or 'unknown phase'})")
        lines.append("")
        lines.append(f"- **Agents:** `{e.sender}` → `{e.receiver}`")
        lines.append(f"- **Operation:** `{e.operation}`")
        if e.replay_action:
            lines.append(f"- **Trace replay:** `{e.replay_action}`")
        lines.append(f"- **Message source:** `{e.message_source}`")
        lines.append("")
        lines.append(format_message_content_block(msg))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def format_timeline(
    trace_path: str | Path,
    *,
    output_format: OutputFormat = "text",
    max_message_chars: Optional[int] = 2000,
    hooks: Optional[list[str]] = None,
) -> str:
    entries = build_timeline(trace_path, hooks=hooks)
    path_str = str(trace_path)
    if output_format == "json":
        payload = {
            "trace_path": path_str,
            "hook_count": len(entries),
            "hooks": [e.to_dict() for e in entries],
        }
        return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if output_format == "md":
        return format_timeline_markdown(
            entries, max_message_chars=max_message_chars, trace_path=path_str
        )
    return format_timeline_text(
        entries, max_message_chars=max_message_chars, trace_path=path_str
    )


def write_timeline(
    trace_path: str | Path,
    output_path: Optional[str | Path] = None,
    *,
    output_format: OutputFormat = "text",
    max_message_chars: Optional[int] = 2000,
    hooks: Optional[list[str]] = None,
) -> Path:
    trace_path = Path(trace_path)
    if output_path is None:
        suffix = {"text": ".timeline.txt", "md": ".timeline.md", "json": ".timeline.json"}[
            output_format
        ]
        output_path = trace_path.with_suffix(suffix).with_name(trace_path.stem + suffix)
    out = Path(output_path)
    content = format_timeline(
        trace_path,
        output_format=output_format,
        max_message_chars=max_message_chars,
        hooks=hooks,
    )
    out.write_text(content, encoding="utf-8")
    return out
