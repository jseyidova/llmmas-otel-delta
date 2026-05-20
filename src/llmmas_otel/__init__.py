from .decorators import (
    observe_session,
    observe_segment,
    observe_phase,
    observe_agent_step,
    observe_a2a_send,
    observe_a2a_receive,
    observe_tool_call,
    observe_llm_call,
    segment,
    phase,
)

from .message_store import enable_message_store, disable_message_store
from .llm_call_store import enable_llm_call_store, disable_llm_call_store
from .hook_timeline_store import (
    enable_hook_timeline,
    disable_hook_timeline,
    load_timeline,
    find_fault_hook_index,
    suggest_replay_until_hook_index,
)
from .replay_store import (
    enable_replay_recording,
    disable_replay_recording,
    enable_prefix_replay,
    enable_prefix_replay_from_records,
    disable_prefix_replay,
)
from .jaeger_trace import configure_replay_from_jaeger_trace, build_replay_artifacts, load_spans
from .jaeger_client import fetch_and_save_trace, fetch_traces, pick_trace
from .experiment import RunConfiguration, configure_chatdev_run
from .injection.a2a_fault import A2AFaultInjector, load_a2a_fault_spec
from .injection import a2a_replay
from .injection.api import enable as enable_hook_faults
from .injection.api import disable as disable_fault_injection
from .injection.api import enabled as fault_injection_enabled

# Backward-compatible names
enable_fault_injection = enable_hook_faults

__all__ = [
    "observe_session",
    "observe_segment",
    "observe_phase",
    "observe_agent_step",
    "observe_a2a_send",
    "observe_a2a_receive",
    "observe_tool_call",
    "observe_llm_call",
    "segment",
    "phase",
    "enable_message_store",
    "disable_message_store",
    "enable_llm_call_store",
    "disable_llm_call_store",
    "enable_hook_timeline",
    "disable_hook_timeline",
    "load_timeline",
    "find_fault_hook_index",
    "suggest_replay_until_hook_index",
    "enable_fault_injection",
    "enable_hook_faults",
    "disable_fault_injection",
    "fault_injection_enabled",
    "enable_replay_recording",
    "disable_replay_recording",
    "enable_prefix_replay",
    "enable_prefix_replay_from_records",
    "disable_prefix_replay",
    "configure_replay_from_jaeger_trace",
    "build_replay_artifacts",
    "load_spans",
    "fetch_and_save_trace",
    "fetch_traces",
    "pick_trace",
    "configure_chatdev_run",
    "RunConfiguration",
    "A2AFaultInjector",
    "load_a2a_fault_spec",
    "a2a_replay",
]
