from __future__ import annotations

import contextvars
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import yaml

logger = logging.getLogger("llmmas.trace_replay")

from .replay_provider import ReplayFaultConfig, SequentialReplayProvider
from .types import HookType

_ACTIVE_PROVIDER: Optional[SequentialReplayProvider] = None
_ENABLED: bool = False
_TRACE_REPLAY_ACTION: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "llmmas_trace_replay_action",
    default=None,
)


def set_trace_replay_action(action: str) -> None:
    _TRACE_REPLAY_ACTION.set(action)


def consume_trace_replay_action() -> Optional[str]:
    return _TRACE_REPLAY_ACTION.get()


@dataclass(frozen=True)
class TraceReplayConfig:
    mode: str
    trace_path: str
    hooks: list[str] = field(default_factory=lambda: ["a2a_send", "a2a_receive"])
    # 0-based global hook index where live ChatDev messages start (earlier hooks replay).
    live_from_hook_index: Optional[int] = None
    # Optional: inject replacement at one hook, then live from the next hook onward.
    fault: Optional[ReplayFaultConfig] = None

    def validate(self) -> None:
        if self.mode != "trace_replay":
            raise ValueError(f"Unsupported replay config mode: {self.mode!r} (expected 'trace_replay')")
        if not self.trace_path:
            raise ValueError("trace_path is required for trace_replay mode")
        if not self.hooks:
            raise ValueError("hooks must be a non-empty list")
        if self.live_from_hook_index is not None and self.live_from_hook_index < 0:
            raise ValueError("live_from_hook_index must be >= 0")
        if self.fault is not None:
            self.fault.validate()
            if (
                self.live_from_hook_index is not None
                and self.live_from_hook_index != self.fault.inject_at_hook_index + 1
            ):
                raise ValueError(
                    "When fault injection is configured, live_from_hook_index must be unset or equal to "
                    "inject_at_hook_index + 1 (live resumes after the injected hook)"
                )


def _normalize_hooks(raw: Any) -> list[str]:
    if raw is None:
        return ["a2a_send", "a2a_receive"]
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list) and all(isinstance(h, str) for h in raw):
        return list(raw)
    raise ValueError("hooks must be a string or list of strings")


def _resolve_live_from_hook_index(data: dict[str, Any]) -> Optional[int]:
    """
    Resolve when live mode starts (0-based global hook index).

    Supported config keys (first match wins):
      - live_from_hook_index: 0-based (hook 14 = 15th hook is live when counting from 1)
      - live_from_hook_number: 1-based convenience (15 → index 14)
      - replay_until_hook_index: alias of live_from_hook_index (same 0-based semantics)
    """
    if "live_from_hook_number" in data:
        number = int(data["live_from_hook_number"])
        if number < 1:
            raise ValueError("live_from_hook_number must be >= 1")
        return number - 1

    if "live_from_hook_index" in data:
        return int(data["live_from_hook_index"])

    if "replay_until_hook_index" in data:
        return int(data["replay_until_hook_index"])

    return None


def _resolve_inject_at_hook_index(data: dict[str, Any]) -> Optional[int]:
    """
    0-based global hook index where a fault is injected (1-based: inject_at_hook / inject_at_hook_number).
    """
    if "inject_at_hook_number" in data:
        number = int(data["inject_at_hook_number"])
        if number < 1:
            raise ValueError("inject_at_hook_number must be >= 1")
        return number - 1

    if "inject_at_hook" in data:
        number = int(data["inject_at_hook"])
        if number < 1:
            raise ValueError("inject_at_hook must be >= 1")
        return number - 1

    if "inject_at_hook_index" in data:
        return int(data["inject_at_hook_index"])

    nested = data.get("fault_injection")
    if isinstance(nested, dict):
        return _resolve_inject_at_hook_index(nested)

    return None


def _resolve_replacement_message(
    source: dict[str, Any],
    data: dict[str, Any],
    *,
    config_dir: Optional[Path] = None,
) -> Optional[str]:
    replacement = source.get("replacement_message", data.get("replacement_message"))
    if replacement is not None:
        return str(replacement)

    rel_file = source.get("replacement_message_file", data.get("replacement_message_file"))
    if not rel_file:
        return None

    path = Path(str(rel_file))
    if not path.is_absolute():
        if config_dir is not None:
            path = (config_dir / path).resolve()
        else:
            path = (Path.cwd() / path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"replacement_message_file not found: {path}")
    return path.read_text(encoding="utf-8")


def _fault_config_from_dict(
    data: dict[str, Any],
    *,
    config_dir: Optional[Path] = None,
) -> Optional[ReplayFaultConfig]:
    nested = data.get("fault_injection")
    source: dict[str, Any] = dict(nested) if isinstance(nested, dict) else dict(data)

    inject_at = _resolve_inject_at_hook_index(source)
    if inject_at is None:
        inject_at = _resolve_inject_at_hook_index(data)
    if inject_at is None:
        return None

    fault_type = str(source.get("fault_type", data.get("fault_type", "truncate"))).strip() or "truncate"
    replacement = _resolve_replacement_message(source, data, config_dir=config_dir)

    truncate_length = int(source.get("truncate_length", data.get("truncate_length", 80)))
    propagate_to_llm = bool(source.get("propagate_to_llm", data.get("propagate_to_llm", True)))
    llm_propagate_calls = int(source.get("llm_propagate_calls", data.get("llm_propagate_calls", 1)))
    if "propagate_to_live_a2a" in source or "propagate_to_live_a2a" in data:
        propagate_to_live_a2a = bool(
            source.get("propagate_to_live_a2a", data.get("propagate_to_live_a2a"))
        )
    else:
        propagate_to_live_a2a = propagate_to_llm
    truncated_task_prompt = source.get("truncated_task_prompt", data.get("truncated_task_prompt"))
    if truncated_task_prompt is not None:
        truncated_task_prompt = str(truncated_task_prompt)

    fault = ReplayFaultConfig(
        inject_at_hook_index=inject_at,
        fault_type=fault_type,
        replacement_message=replacement,
        truncate_length=truncate_length,
        propagate_to_llm=propagate_to_llm,
        llm_propagate_calls=llm_propagate_calls,
        propagate_to_live_a2a=propagate_to_live_a2a,
        truncated_task_prompt=truncated_task_prompt,
    )
    fault.validate()
    return fault


def trace_replay_config_from_dict(
    data: dict[str, Any],
    *,
    config_dir: Optional[Path] = None,
) -> TraceReplayConfig:
    fault = _fault_config_from_dict(data, config_dir=config_dir)
    live_from = _resolve_live_from_hook_index(data)
    if fault is not None and live_from is None:
        live_from = fault.inject_at_hook_index + 1

    cfg = TraceReplayConfig(
        mode=str(data.get("mode", "")).strip(),
        trace_path=str(data.get("trace_path", "")).strip(),
        hooks=_normalize_hooks(data.get("hooks")),
        live_from_hook_index=live_from,
        fault=fault,
    )
    cfg.validate()
    return cfg


def load_trace_replay_config(path: str | Path) -> TraceReplayConfig:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Trace replay config not found: {path}")

    suffix = p.suffix.lower()
    if suffix in (".yaml", ".yml"):
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    elif suffix == ".json":
        raw = json.loads(p.read_text(encoding="utf-8"))
    else:
        raise ValueError("Trace replay config must be .yaml, .yml, or .json")

    if not isinstance(raw, dict):
        raise ValueError("Trace replay config root must be an object/dict")

    return trace_replay_config_from_dict(raw, config_dir=p.parent)


def enable_trace_replay(config: TraceReplayConfig | dict[str, Any] | str | Path) -> SequentialReplayProvider:
    """
    Enable deterministic A2A message replay from a baseline Jaeger trace.

    Does not enable fault injection. Call disable_trace_replay() to turn off.
    """
    global _ACTIVE_PROVIDER, _ENABLED

    if isinstance(config, (str, Path)):
        config = load_trace_replay_config(config)
    elif isinstance(config, dict):
        config = trace_replay_config_from_dict(config, config_dir=Path.cwd())
    elif not isinstance(config, TraceReplayConfig):
        raise TypeError("config must be TraceReplayConfig, dict, or path string")

    config.validate()
    provider = SequentialReplayProvider.from_jaeger_trace(
        config.trace_path,
        hooks=config.hooks,
        live_from_hook_index=config.live_from_hook_index,
        fault=config.fault,
    )
    _ACTIVE_PROVIDER = provider
    _ENABLED = True

    if config.fault is not None:
        inject_at = config.fault.inject_at_hook_index
        logger.info(
            "trace_replay enabled trace_path=%s baseline_hooks=%s fault_injection "
            "inject_at_hook_index=%s inject_at_hook_number=%s fault_type=%s "
            "(replay hooks 1..%s, inject at hook %s, live from hook %s)",
            config.trace_path,
            config.hooks,
            inject_at,
            inject_at + 1,
            config.fault.fault_type,
            inject_at if inject_at > 0 else "none",
            inject_at + 1,
            inject_at + 2,
        )
    elif config.live_from_hook_index is not None:
        logger.info(
            "trace_replay enabled trace_path=%s baseline_hooks=%s live_from_hook_index=%s "
            "(replay global indices 0..%s, live from %s)",
            config.trace_path,
            config.hooks,
            config.live_from_hook_index,
            config.live_from_hook_index - 1 if config.live_from_hook_index > 0 else "none",
            config.live_from_hook_index,
        )
    else:
        logger.info(
            "trace_replay enabled trace_path=%s baseline_hooks=%s (full replay)",
            config.trace_path,
            config.hooks,
        )

    return provider


def disable_trace_replay() -> None:
    global _ACTIVE_PROVIDER, _ENABLED
    _ACTIVE_PROVIDER = None
    _ENABLED = False


def is_trace_replay_enabled() -> bool:
    return _ENABLED


def get_replay_provider() -> Optional[SequentialReplayProvider]:
    return _ACTIVE_PROVIDER


def apply_trace_replay_to_message_body(
    hook_type: HookType,
    message_body: Optional[str],
    *,
    source_agent_id: Optional[str] = None,
    target_agent_id: Optional[str] = None,
    apply_mutation: Optional[Callable[[str], None]] = None,
) -> Optional[str]:
    """If trace replay is enabled, return the next recorded body for this hook (or unchanged)."""
    if not _ENABLED or _ACTIVE_PROVIDER is None:
        return message_body

    return _ACTIVE_PROVIDER.replay_message_body(
        hook_type,
        message_body,
        sender=source_agent_id,
        receiver=target_agent_id,
        apply_mutation=apply_mutation,
    )


def apply_trace_replay_to_llm_messages(
    messages: list[dict[str, str]],
) -> list[dict[str, str]]:
    """
    After an A2A fault inject, truncate the full task duplicated in system prompts
    for the next N LLM calls (ChatDev puts {task} on every agent system message).
    """
    if not _ENABLED or _ACTIVE_PROVIDER is None:
        return messages
    return _ACTIVE_PROVIDER.apply_llm_messages(messages)
