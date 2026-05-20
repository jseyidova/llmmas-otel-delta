from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional

from .injection import a2a_replay
from .injection.api import enable as enable_hook_faults
from .injection.a2a_fault import load_a2a_fault_spec
from .hook_timeline_store import enable_hook_timeline
from .llm_call_store import enable_llm_call_store
from .message_store import enable_message_store
from .jaeger_trace import configure_replay_from_jaeger_trace
from .replay_store import enable_prefix_replay, enable_replay_recording


@dataclass(frozen=True)
class RunConfiguration:
    """What was enabled for a ChatDev run."""

    baseline: bool
    hook_faults: bool
    a2a_trace_replay: bool
    a2a_message_fault: bool
    llm_replay_record: bool
    llm_prefix_replay: bool
    llm_call_log: bool
    hook_timeline: bool


def configure_chatdev_run(
    *,
    # --- Faults (pick at most one family, or combine hook + a2a as documented) ---
    hook_faults: Optional[str] = None,
    a2a_fault: Optional[str] = None,
    fault_seed: str = "0",
    fault_trace_visible: bool = True,
    # --- A2A trace replay (baseline a2a-messages.jsonl) ---
    replay_a2a_trace: Optional[str] = None,
    a2a_replay_strict: bool = True,
    # --- LLM replay ---
    record_llm_replay: Optional[str] = None,
    replay_llm_prefix: Optional[str] = None,
    replay_llm_until_hook_index: Optional[int] = None,
    replay_llm_events: Optional[str] = None,
    replay_llm_strict: bool = True,
    # --- Logging ---
    a2a_messages_log: Optional[str] = None,
    llm_calls_log: Optional[str] = None,
    record_hook_timeline: Optional[str] = None,
    # --- Jaeger trace JSON (preferred replay source) ---
    replay_jaeger_trace: Optional[str] = None,
    auto_replay_until_from_fault: bool = True,
) -> RunConfiguration:
    """
    Configure llmmas-otel for a ChatDev dataset run.

    Fault injection paths (explicit, not mutually exclusive where noted):

    1. ``hook_faults`` — YAML hook specs (``a2a.truncate``, ``llm.timeout``, …) applied
       at instrumentation boundaries via the spec engine.

    2. ``a2a_fault`` + ``replay_a2a_trace`` — replay baseline A2A bodies in order until the
       fault selector fires (truncate), then stop A2A replay and continue with live messages.
       Requires ``replay_a2a_trace``. Pair with ``replay_llm_prefix`` so LLM hooks before
       ``replay_llm_until_hook_index`` also match baseline.

    You may combine (1) with (2): hook faults on LLM/tool hooks, A2A trace fault on messages.

    ``record_llm_replay`` + ``replay_llm_prefix`` on the same run writes a full
    faulty ``llm-replay.jsonl``: replayed baseline rows before ``until_hook_index``,
    then live LLM responses after the fault point.

    **Baseline (recommended):** ``--trace-full-payloads`` + ``--fetch-jaeger-trace PATH``.
    Replay/fault runs use ``--replay-jaeger-trace PATH``. No ``record_llm_replay``,
    ``a2a_messages_log``, or ``llm_calls_log`` required — payloads live in the Jaeger JSON.

    Legacy baseline: ``record_llm_replay`` + ``a2a_messages_log`` instead of Jaeger JSON.
    """
    if replay_jaeger_trace and (replay_a2a_trace or replay_llm_prefix):
        raise ValueError(
            "Use either replay_jaeger_trace OR replay_a2a_trace/replay_llm_prefix, not both"
        )

    if a2a_fault is not None and replay_a2a_trace is None and replay_jaeger_trace is None:
        raise ValueError(
            "a2a_fault requires replay_jaeger_trace or replay_a2a_trace (baseline trace)"
        )

    if replay_jaeger_trace and replay_llm_until_hook_index is None and a2a_fault is None:
        raise ValueError(
            "replay_llm_until_hook_index is required with replay_jaeger_trace when no a2a_fault"
        )

    plan = RunConfiguration(
        baseline=hook_faults is None
        and a2a_fault is None
        and replay_a2a_trace is None
        and replay_jaeger_trace is None,
        hook_faults=False,
        a2a_trace_replay=False,
        a2a_message_fault=False,
        llm_replay_record=record_llm_replay is not None,
        llm_prefix_replay=replay_llm_prefix is not None,
        llm_call_log=llm_calls_log is not None,
        hook_timeline=record_hook_timeline is not None,
    )

    if hook_faults:
        enable_hook_faults(hook_faults, seed=fault_seed, trace_visible=fault_trace_visible)
        plan = replace(plan, hook_faults=True, baseline=False)

    if replay_jaeger_trace:
        configure_replay_from_jaeger_trace(
            replay_jaeger_trace,
            replay_until_hook_index=replay_llm_until_hook_index,
            a2a_fault=a2a_fault,
            a2a_replay_strict=a2a_replay_strict,
            replay_llm_strict=replay_llm_strict,
            auto_until_from_fault=auto_replay_until_from_fault,
        )
        plan = replace(
            plan,
            a2a_trace_replay=True,
            llm_prefix_replay=True,
            a2a_message_fault=a2a_fault is not None,
            baseline=False,
        )

    elif replay_a2a_trace:
        fault_spec = load_a2a_fault_spec(a2a_fault) if a2a_fault else None
        a2a_replay.enable(replay_a2a_trace, fault_spec=fault_spec, strict=a2a_replay_strict)
        plan = replace(
            plan,
            a2a_trace_replay=True,
            a2a_message_fault=fault_spec is not None and bool(fault_spec.get("enabled", True)),
            baseline=False,
        )

    if record_llm_replay:
        enable_replay_recording(record_llm_replay)

    if replay_llm_prefix and not replay_jaeger_trace:
        if replay_llm_until_hook_index is None:
            raise ValueError("replay_llm_until_hook_index is required with replay_llm_prefix")
        enable_prefix_replay(
            replay_llm_prefix,
            until_hook_index=replay_llm_until_hook_index,
            strict=replay_llm_strict,
            events_path=replay_llm_events,
        )

    if a2a_messages_log:
        enable_message_store(a2a_messages_log)

    if llm_calls_log:
        enable_llm_call_store(llm_calls_log)

    if record_hook_timeline:
        enable_hook_timeline(record_hook_timeline)

    return plan

