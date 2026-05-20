from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from .injection.a2a_fault import A2AFaultInjector
from .jaeger_trace import build_replay_artifacts, load_spans, span_tags


def _preview(text: Optional[str], max_chars: int = 240) -> str:
    if text is None:
        return ""
    one_line = " ".join(str(text).split())
    if len(one_line) <= max_chars:
        return one_line
    return one_line[: max_chars - 3] + "..."


def _span_kind(span: dict[str, Any], tags: dict[str, Any]) -> str:
    if tags.get("llmmas.hook.index") is not None:
        direction = tags.get("llmmas.message.direction")
        if direction == "send" or str(span.get("operationName", "")).startswith("send "):
            return "a2a_send"
        if direction == "receive" or str(span.get("operationName", "")).startswith("process "):
            return "a2a_receive"
        if tags.get("gen_ai.operation.name", "").startswith("chat.completions"):
            return "llm_call"
        if tags.get("gen_ai.tool.name"):
            return "tool_call"
        return "hook"
    op = str(span.get("operationName") or "")
    if op.startswith("llmmas."):
        return op.replace("llmmas.", "", 1)
    return op or "span"


def _a2a_occurrence_key(message: dict[str, Any]) -> tuple[Any, ...]:
    seg = message.get("segment") or {}
    seg_name = seg.get("name") if isinstance(seg, dict) else message.get("phase_name")
    injector = A2AFaultInjector.disabled()
    direction = injector._effective_direction(message)
    return (
        seg_name,
        message.get("edge_id"),
        direction,
        message.get("source_agent_id"),
        message.get("target_agent_id"),
    )


def build_readable_report(
    trace_path: str | Path,
    *,
    body_preview_chars: int = 320,
    include_non_hook_spans: bool = True,
) -> str:
    spans = load_spans(trace_path)
    llm_records, a2a_messages, events = build_replay_artifacts(spans)

    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("LLMMAS TRACE REPORT (from Jaeger JSON)")
    lines.append(f"Source: {Path(trace_path).resolve()}")
    lines.append(f"Spans: {len(spans)}  |  LLM hooks: {len(llm_records)}  |  A2A messages: {len(a2a_messages)}")
    lines.append("=" * 72)
    lines.append("")

    if include_non_hook_spans:
        lines.append("## Spans without hook_index (workflow / session — not replay hooks)")
        lines.append("")
        for span in sorted(spans, key=lambda s: int(s.get("startTime") or 0)):
            tags = span_tags(span)
            if tags.get("llmmas.hook.index") is not None:
                continue
            lines.append(
                f"  {span.get('operationName')}  "
                f"segment={tags.get('llmmas.segment.name')!r}  "
                f"session={tags.get('llmmas.session.id')!r}"
            )
        lines.append("")

    lines.append("## Hook timeline (execution order — use hook_index for replay / faults)")
    lines.append("")
    lines.append(
        f"{'hook':>5}  {'type':<14}  {'segment':<18}  {'agents / detail':<40}  preview"
    )
    lines.append("-" * 120)

    occurrence_counts: dict[tuple[Any, ...], int] = {}

    for event in events:
        hook = event.get("hook_index")
        hook_type = event.get("hook_type") or event.get("kind") or "?"
        seg = event.get("segment") or {}
        seg_name = (seg.get("name") if isinstance(seg, dict) else None) or event.get("phase_name") or ""

        detail = ""
        preview = ""

        if hook_type.startswith("a2a_") or str(event.get("kind", "")).startswith("a2a_"):
            direction = A2AFaultInjector.disabled()._effective_direction(event)
            key = _a2a_occurrence_key(event)
            occ = occurrence_counts.get(key, 0)
            occurrence_counts[key] = occ + 1
            detail = (
                f"{event.get('source_agent_id')} -> {event.get('target_agent_id')} "
                f"[{direction}] occ={occ}"
            )
            preview = _preview(event.get("body"), body_preview_chars)
        elif hook_type == "llm_call":
            detail = f"agent={event.get('agent_id') or '?'} model={event.get('model') or '?'}"
            preview = _preview(event.get("output"), body_preview_chars)
        elif hook_type == "tool_call":
            detail = f"tool={event.get('tool_name') or '?'}"
            preview = _preview(event.get("tool_args"), body_preview_chars)
        else:
            detail = str(event.get("operation_name") or "")
            preview = ""

        lines.append(
            f"{hook:>5}  {hook_type:<14}  {str(seg_name):<18}  {detail:<40}  {preview}"
        )

    lines.append("")
    lines.append("## A2A catalog (for fault JSON selectors)")
    lines.append("")
    lines.append(
        "Copy segment_name, edge_id, direction, source_agent_id, target_agent_id, occurrence "
        "into your --a2a-fault JSON."
    )
    lines.append("")

    occurrence_counts = {}
    for msg in a2a_messages:
        key = _a2a_occurrence_key(msg)
        occ = occurrence_counts.get(key, 0)
        occurrence_counts[key] = occ + 1
        seg = msg.get("segment") or {}
        seg_name = seg.get("name") if isinstance(seg, dict) else "?"
        direction = A2AFaultInjector.disabled()._effective_direction(msg)
        lines.append(f"--- hook_index={msg.get('hook_index')} occurrence={occ} ---")
        lines.append(f"  segment_name:     {seg_name!r}")
        lines.append(f"  edge_id:          {msg.get('edge_id')!r}")
        lines.append(f"  direction:        {direction!r}")
        lines.append(f"  source_agent_id:  {msg.get('source_agent_id')!r}")
        lines.append(f"  target_agent_id:  {msg.get('target_agent_id')!r}")
        lines.append(f"  message_id:       {msg.get('message_id')!r}")
        lines.append(f"  body_preview:     {_preview(msg.get('body'), body_preview_chars)!r}")
        body = str(msg.get("body") or "")
        if "buying them, collecting rent," in body:
            lines.append(
                "  NOTE: contains cut anchor 'buying them, collecting rent,' "
                "(monopoly fault example)"
            )
        lines.append("")

    return "\n".join(lines) + "\n"


def write_report_files(
    trace_path: str | Path,
    out_dir: str | Path,
    *,
    body_preview_chars: int = 320,
) -> dict[str, str]:
    """Write readable .txt report plus JSONL sidecars extracted from Jaeger."""
    trace_path = Path(trace_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    spans = load_spans(trace_path)
    llm_records, a2a_messages, events = build_replay_artifacts(spans)

    report_txt = out_dir / "trace-report.txt"
    report_txt.write_text(
        build_readable_report(trace_path, body_preview_chars=body_preview_chars),
        encoding="utf-8",
    )

    timeline_jsonl = out_dir / "hook-timeline.jsonl"
    with timeline_jsonl.open("w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    a2a_jsonl = out_dir / "a2a-messages.jsonl"
    with a2a_jsonl.open("w", encoding="utf-8") as f:
        for msg in a2a_messages:
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")

    llm_jsonl = out_dir / "llm-calls.jsonl"
    with llm_jsonl.open("w", encoding="utf-8") as f:
        for row in llm_records:
            slim = {
                "hook_index": row.get("hook_index"),
                "agent_id": row.get("agent_id"),
                "model": row.get("model"),
                "input": row.get("input"),
                "output": row["response"]["choices"][0]["message"]["content"]
                if row.get("response")
                else None,
            }
            f.write(json.dumps(slim, ensure_ascii=False) + "\n")

    return {
        "report_txt": str(report_txt.resolve()),
        "hook_timeline_jsonl": str(timeline_jsonl.resolve()),
        "a2a_messages_jsonl": str(a2a_jsonl.resolve()),
        "llm_calls_jsonl": str(llm_jsonl.resolve()),
    }
