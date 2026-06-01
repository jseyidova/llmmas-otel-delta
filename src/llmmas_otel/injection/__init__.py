from .types import HookType, HookContext, DecisionKind, InjectionDecision
from .engine import (
    FaultEngine,
    NoOpFaultEngine,
    enable_fault_injection,
    disable_fault_injection,
    is_enabled,
    get_engine,
    set_fault_trace_visibility,
    is_fault_trace_visible,
)
from .spec import FaultSpec, FaultSelector, FaultAction, FaultLimits
from .loader import load_fault_specs
from .matcher import selector_matches
from .spec_engine import SpecFaultEngine
from .config import enable_fault_injection_from_file
from .api import enable, disable, enabled, set_trace_visibility, trace_visible
from .exceptions import LLMFaultError, LLMRateLimitError, LLMNetworkError, LLMTimeoutError
from .replay_provider import (
    ReplayEvent,
    ReplayFaultConfig,
    SequentialReplayProvider,
    extract_replay_events,
    load_replay_events_from_jaeger,
)
from .trace_replay import (
    TraceReplayConfig,
    apply_trace_replay_to_llm_messages,
    apply_trace_replay_to_message_body,
    disable_trace_replay,
    enable_trace_replay,
    get_replay_provider,
    is_trace_replay_enabled,
    load_trace_replay_config,
)
from .trace_timeline import TimelineEntry, build_timeline, format_timeline, write_timeline
from .chat_env_fault import (
    apply_task_prompt_corruption,
    clear_chat_env_registration,
    register_chat_env,
)

__all__ = [
    "HookType",
    "HookContext",
    "DecisionKind",
    "InjectionDecision",
    "FaultEngine",
    "NoOpFaultEngine",
    "enable_fault_injection",
    "disable_fault_injection",
    "is_enabled",
    "get_engine",
    "set_fault_trace_visibility",
    "is_fault_trace_visible",
    "FaultSpec",
    "FaultSelector",
    "FaultAction",
    "FaultLimits",
    "load_fault_specs",
    "selector_matches",
    "SpecFaultEngine",
    "enable_fault_injection_from_file",
    "enable",
    "disable",
    "enabled",
    "set_trace_visibility",
    "trace_visible",
    "LLMFaultError",
    "LLMRateLimitError",
    "LLMNetworkError",
    "LLMTimeoutError",
    "ReplayEvent",
    "ReplayFaultConfig",
    "SequentialReplayProvider",
    "extract_replay_events",
    "load_replay_events_from_jaeger",
    "TraceReplayConfig",
    "enable_trace_replay",
    "disable_trace_replay",
    "is_trace_replay_enabled",
    "get_replay_provider",
    "load_trace_replay_config",
    "apply_trace_replay_to_message_body",
    "apply_trace_replay_to_llm_messages",
    "TimelineEntry",
    "build_timeline",
    "format_timeline",
    "write_timeline",
    "register_chat_env",
    "clear_chat_env_registration",
    "apply_task_prompt_corruption",
]