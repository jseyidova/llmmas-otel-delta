from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional


def load_jaeger_trace(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Jaeger trace file not found: {path}")
    return json.loads(p.read_text(encoding="utf-8"))


def iter_trace_spans(trace_doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Return spans from Jaeger export (data[0].spans or top-level spans)."""
    if isinstance(trace_doc.get("spans"), list):
        return trace_doc["spans"]
    data = trace_doc.get("data")
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict) and isinstance(first.get("spans"), list):
            return first["spans"]
    raise ValueError("Unrecognized Jaeger trace JSON shape (expected data[].spans or spans)")


def tags_dict(span: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for tag in span.get("tags") or []:
        key = tag.get("key")
        if key is not None:
            out[str(key)] = tag.get("value")
    return out


def log_fields(log_entry: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for field in log_entry.get("fields") or []:
        key = field.get("key")
        if key is not None:
            out[str(key)] = field.get("value")
    return out


def hook_type_from_operation(operation_name: str) -> Optional[str]:
    op = (operation_name or "").strip()
    if op.startswith("send "):
        return "a2a_send"
    if op.startswith("process "):
        return "a2a_receive"
    return None


def message_body_from_span(span: dict[str, Any]) -> Optional[str]:
    tags = tags_dict(span)
    body = tags.get("llmmas.message.body")
    if isinstance(body, str) and body:
        return body

    for log_entry in span.get("logs") or []:
        fields = log_fields(log_entry)
        if fields.get("event") == "a2a.message":
            log_body = fields.get("llmmas.message.body")
            if isinstance(log_body, str) and log_body:
                return log_body

    preview = tags.get("llmmas.message.preview")
    if isinstance(preview, str) and preview:
        return preview

    return None


def segment_name_for_span(span: dict[str, Any], spans_by_id: dict[str, dict[str, Any]]) -> Optional[str]:
    current: Optional[dict[str, Any]] = span
    visited: set[str] = set()

    while current is not None:
        span_id = current.get("spanID")
        if isinstance(span_id, str):
            if span_id in visited:
                break
            visited.add(span_id)

        tags = tags_dict(current)
        seg = tags.get("llmmas.segment.name")
        if isinstance(seg, str) and seg:
            return seg

        parent_id: Optional[str] = None
        for ref in current.get("references") or []:
            if ref.get("refType") == "CHILD_OF":
                parent_id = ref.get("spanID")
                break
        if not parent_id:
            break
        current = spans_by_id.get(str(parent_id))

    return None
