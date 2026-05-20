from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from .hook_timeline_store import suggest_replay_until_hook_index
from .injection.a2a_fault import find_fault_hook_index
from .injection import a2a_replay
from .injection.a2a_fault import load_a2a_fault_spec
from .replay_store import enable_prefix_replay_from_records


def _field_map(items: list[dict[str, Any]] | None) -> dict[str, Any]:
    return {item.get("key"): item.get("value") for item in (items or [])}


def span_tags(span: dict[str, Any]) -> dict[str, Any]:
    return _field_map(span.get("tags"))


def _log_fields(log: dict[str, Any]) -> dict[str, Any]:
    return _field_map(log.get("fields"))


def _first_log_value(span: dict[str, Any], key: str) -> Optional[Any]:
    for log in span.get("logs") or []:
        fields = _log_fields(log)
        if key in fields:
            return fields[key]
    return None


def load_spans(trace_json: dict[str, Any] | Path | str) -> list[dict[str, Any]]:
    if isinstance(trace_json, (str, Path)):
        data = json.loads(Path(trace_json).read_text(encoding="utf-8"))
    else:
        data = trace_json

    traces = data.get("data")
    if not isinstance(traces, list) or not traces:
        raise ValueError("Expected Jaeger JSON with a non-empty top-level 'data' list")

    spans: list[dict[str, Any]] = []
    for trace in traces:
        spans.extend(trace.get("spans") or [])
    if not spans:
        raise ValueError("Jaeger trace contains no spans")
    return spans


def session_id(spans: list[dict[str, Any]]) -> Optional[str]:
    for span in spans:
        tags = span_tags(span)
        sid = tags.get("llmmas.session.id")
        if sid:
            return str(sid)
    return None


def _is_llm_span(span: dict[str, Any], tags: dict[str, Any]) -> bool:
    operation = str(tags.get("gen_ai.operation.name") or span.get("operationName") or "")
    return operation.startswith("chat.completions") or operation == "inference"


def _is_a2a_span(tags: dict[str, Any]) -> bool:
    return bool(tags.get("llmmas.source_agent.id") and tags.get("llmmas.target_agent.id"))


def _is_tool_span(span: dict[str, Any], tags: dict[str, Any]) -> bool:
    operation = str(tags.get("gen_ai.operation.name") or span.get("operationName") or "")
    return operation == "execute_tool" or bool(tags.get("gen_ai.tool.name"))


def _segment_dict(tags: dict[str, Any]) -> Optional[dict[str, Any]]:
    name = tags.get("llmmas.segment.name")
    order = tags.get("llmmas.segment.order")
    if name is None:
        return None
    seg: dict[str, Any] = {"name": name}
    if order is not None:
        seg["order"] = int(order)
    return seg


def _base_event(span: dict[str, Any], tags: dict[str, Any], sid: Optional[str]) -> dict[str, Any]:
    hook_index = tags.get("llmmas.hook.index")
    hook_type_index = tags.get("llmmas.hook.type_index")
    event: dict[str, Any] = {
        "trace_id": span.get("traceID"),
        "span_id": span.get("spanID"),
        "operation_name": span.get("operationName"),
        "session_id": tags.get("llmmas.session.id") or sid,
        "start_time": span.get("startTime"),
        "duration": span.get("duration"),
        "phase_name": tags.get("llmmas.segment.name"),
        "phase_order": tags.get("llmmas.segment.order"),
        "agent_id": tags.get("llmmas.agent.id"),
        "segment": _segment_dict(tags),
    }
    if hook_index is not None:
        event["hook_index"] = int(hook_index)
    if hook_type_index is not None:
        event["hook_type_index"] = int(hook_type_index)
    return event


def _openai_response_from_trace(span: dict[str, Any], tags: dict[str, Any], output: str) -> dict[str, Any]:
    model = str(tags.get("gen_ai.request.model") or "unknown")
    created = int((span.get("startTime") or 0) // 1_000_000)
    return {
        "id": f"trace-replay-{span.get('spanID')}",
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": output},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def build_replay_artifacts(
    spans: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Extract LLM replay records, A2A message-store rows, and ordered hook events from Jaeger spans.

    Baseline runs must use ``--trace-full-payloads`` so LLM input/output and A2A bodies exist on spans.
    """
    sid = session_id(spans)
    llm_records: list[dict[str, Any]] = []
    a2a_messages: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    missing_llm: list[int] = []

    for span in spans:
        tags = span_tags(span)
        hook_index = tags.get("llmmas.hook.index")

        if _is_llm_span(span, tags) and hook_index is not None:
            output = tags.get("llmmas.llm.output")
            input_text = tags.get("llmmas.llm.input")
            input_sha = tags.get("llmmas.llm.input.sha256")
            if output is None or input_sha is None:
                missing_llm.append(int(hook_index))
                continue
            llm_record: dict[str, Any] = {
                "kind": "llm_call",
                "session_id": tags.get("llmmas.session.id") or sid,
                "agent_id": tags.get("llmmas.agent.id"),
                "hook_index": int(hook_index),
                "hook_type_index": int(tags.get("llmmas.hook.type_index") or 0),
                "provider": tags.get("gen_ai.provider.name") or "ollama",
                "model": tags.get("gen_ai.request.model") or "unknown",
                "operation": tags.get("gen_ai.operation.name") or span.get("operationName"),
                "request_id": tags.get("gen_ai.request.id") or span.get("spanID"),
                "input_sha256": input_sha,
                "response": _openai_response_from_trace(span, tags, str(output)),
            }
            if input_text is not None:
                llm_record["input"] = input_text
            llm_records.append(llm_record)

            event = _base_event(span, tags, sid)
            event.update(
                {
                    "hook_type": "llm_call",
                    "kind": "llm_call",
                    "provider": llm_record["provider"],
                    "model": llm_record["model"],
                    "request_id": llm_record["request_id"],
                    "input_sha256": input_sha,
                    "output_sha256": tags.get("llmmas.llm.output.sha256"),
                    "input": input_text,
                    "output": output,
                }
            )
            events.append(event)

        if _is_a2a_span(tags) and hook_index is not None:
            body = tags.get("llmmas.message.body")
            if body is None:
                body = _first_log_value(span, "llmmas.message.body")
            direction = tags.get("llmmas.message.direction")
            if direction is None:
                direction = _first_log_value(span, "llmmas.message.direction")
            if direction is None:
                operation = str(span.get("operationName") or "")
                if operation.startswith("send "):
                    direction = "send"
                elif operation.startswith("process "):
                    direction = "receive"
            msg = {
                "session_id": tags.get("llmmas.session.id") or sid,
                "segment": _segment_dict(tags),
                "direction": direction,
                "message_id": tags.get("llmmas.message.id"),
                "sha256": tags.get("llmmas.message.sha256"),
                "source_agent_id": tags.get("llmmas.source_agent.id"),
                "target_agent_id": tags.get("llmmas.target_agent.id"),
                "edge_id": tags.get("llmmas.edge.id"),
                "channel": tags.get("llmmas.channel"),
                "body": body,
                "hook_index": int(hook_index),
                "hook_type": f"a2a_{direction}" if direction else "a2a_message",
                "operation_name": span.get("operationName"),
            }
            a2a_messages.append(msg)

            a2a_event = _base_event(span, tags, sid)
            a2a_event.update(
                {
                    "hook_type": f"a2a_{direction}" if direction else "a2a_message",
                    "kind": f"a2a_{direction or 'message'}",
                    "direction": direction,
                    "operation_name": span.get("operationName"),
                    "source_agent_id": msg["source_agent_id"],
                    "target_agent_id": msg["target_agent_id"],
                    "edge_id": msg["edge_id"],
                    "message_id": msg["message_id"],
                    "message_sha256": msg.get("sha256"),
                    "body": body,
                }
            )
            events.append(a2a_event)

        if _is_tool_span(span, tags) and hook_index is not None:
            event = _base_event(span, tags, sid)
            event.update(
                {
                    "hook_type": "tool_call",
                    "kind": "tool_call",
                    "tool_name": tags.get("gen_ai.tool.name"),
                    "tool_type": tags.get("gen_ai.tool.type"),
                    "tool_call_id": tags.get("gen_ai.tool.call.id"),
                    "tool_args_sha256": tags.get("llmmas.tool.args.sha256"),
                    "tool_args": tags.get("llmmas.tool.args"),
                    "tool_result_sha256": tags.get("llmmas.tool.result.sha256"),
                    "tool_result": tags.get("llmmas.tool.result"),
                }
            )
            events.append(event)

        # Spans without llmmas.hook.index (session, segment, agent_step, …) stay in raw JSON only.

    if missing_llm:
        raise ValueError(
            "Jaeger trace is missing LLM input/output on hook_index="
            + ", ".join(str(i) for i in sorted(missing_llm)[:8])
            + ("..." if len(missing_llm) > 8 else "")
            + ". Re-run baseline with --trace-full-payloads."
        )

    llm_records.sort(key=lambda r: r["hook_index"])
    a2a_messages.sort(key=lambda r: r["hook_index"])
    events.sort(
        key=lambda r: (
            r.get("hook_index") is None,
            r.get("hook_index") or 0,
            r.get("start_time") or 0,
        )
    )
    return llm_records, a2a_messages, events


def resolve_replay_until_hook_index(
    events: list[dict[str, Any]],
    *,
    a2a_messages: Optional[list[dict[str, Any]]] = None,
    a2a_fault: Optional[dict[str, Any]] = None,
    explicit_until: Optional[int] = None,
) -> int:
    if explicit_until is not None:
        return explicit_until
    if a2a_fault is None:
        raise ValueError(
            "replay_until_hook_index is required when no a2a_fault spec is provided"
        )
    lookup = a2a_messages if a2a_messages is not None else events
    fault_hook = find_fault_hook_index(lookup, a2a_fault)
    return suggest_replay_until_hook_index(fault_hook, events)


def configure_replay_from_jaeger_trace(
    trace_path: str | Path,
    *,
    replay_until_hook_index: Optional[int] = None,
    a2a_fault: Optional[str | Path | dict[str, Any]] = None,
    a2a_replay_strict: bool = True,
    replay_llm_strict: bool = True,
    auto_until_from_fault: bool = True,
) -> dict[str, Any]:
    """
    Load a Jaeger trace JSON file (API ``/api/traces`` response) and enable LLM + A2A replay.
    """
    path = Path(trace_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    spans = load_spans(data)
    llm_records, a2a_messages, events = build_replay_artifacts(spans)

    fault_spec: Optional[dict[str, Any]] = None
    if a2a_fault is not None:
        if isinstance(a2a_fault, dict):
            fault_spec = a2a_fault
        else:
            fault_spec = load_a2a_fault_spec(a2a_fault)

    until = replay_until_hook_index
    if until is None and auto_until_from_fault and fault_spec is not None:
        until = resolve_replay_until_hook_index(
            events,
            a2a_messages=a2a_messages,
            a2a_fault=fault_spec,
        )
    if until is None:
        raise ValueError("replay_until_hook_index is required (or pass a2a_fault for auto resolution)")

    # A2A replay from Jaeger is sequential (edge/agents/direction), not body-hash locked.
    # Fault injection mutates the target message; do not run strict A2A prefix checks.
    enable_prefix_replay_from_records(
        llm_records,
        until_hook_index=until,
        strict=replay_llm_strict,
        events=None,
    )
    a2a_replay.enable_from_records(a2a_messages, fault_spec=fault_spec, strict=a2a_replay_strict)

    return {
        "trace_path": str(path.resolve()),
        "span_count": len(spans),
        "llm_record_count": len(llm_records),
        "a2a_message_count": len(a2a_messages),
        "event_count": len(events),
        "replay_until_hook_index": until,
        "session_id": session_id(spans),
    }
