from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any, Optional

from . import message_store


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class LlmCallStoreConfig:
    path: str


_config: Optional[LlmCallStoreConfig] = None


def enable_llm_call_store(path: str, *, append: bool = False) -> None:
    """
    Append one JSON object per LLM call (full input/output text) for offline analysis.

    Example:
      enable_llm_call_store("out/llm-calls.jsonl")
    """
    global _config
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if not append:
        open(path, "w", encoding="utf-8").close()
    _config = LlmCallStoreConfig(path=path)


def disable_llm_call_store() -> None:
    global _config
    _config = None


def is_enabled() -> bool:
    return _config is not None


def write_call(
    *,
    hook_index: int,
    hook_type_index: int,
    provider_name: str,
    model: str,
    operation_name: str,
    request_id: str,
    input_text: str,
    output_text: str,
    agent_id: Optional[str] = None,
    replay_used: bool = False,
    response: Optional[Any] = None,
) -> None:
    if _config is None:
        return

    record: dict[str, Any] = {
        "kind": "llm_call",
        "session_id": message_store.current_session_id(),
        "segment": message_store.current_segment(),
        "hook_index": hook_index,
        "hook_type_index": hook_type_index,
        "agent_id": agent_id,
        "provider": provider_name,
        "model": model,
        "operation": operation_name,
        "request_id": request_id,
        "input": input_text,
        "input_sha256": _sha256_hex(input_text),
        "output": output_text,
        "output_sha256": _sha256_hex(output_text),
        "replay_used": replay_used,
    }
    if response is not None:
        record["response"] = response

    with open(_config.path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
