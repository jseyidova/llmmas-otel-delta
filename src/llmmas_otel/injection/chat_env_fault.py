"""Optional ChatDev (or other) chat_env corruption during trace-replay fault injection."""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

logger = logging.getLogger("llmmas.chat_env_fault")

_chat_env_getter: Optional[Callable[[], Any]] = None


def register_chat_env(getter: Callable[[], Any]) -> None:
    """Register a zero-arg callable returning an object with ``env_dict`` (e.g. ChatEnv)."""
    global _chat_env_getter
    _chat_env_getter = getter


def clear_chat_env_registration() -> None:
    global _chat_env_getter
    _chat_env_getter = None


def apply_task_prompt_corruption(truncated_task: str) -> bool:
    """
    Overwrite ``env_dict['task_prompt']`` on the registered chat environment.

    Returns True if a task was written, False if no target was registered.
    """
    getter = _chat_env_getter
    if getter is None:
        logger.warning(
            "corrupt_chat_env=true but no chat_env registered "
            "(call register_chat_env from the ChatDev runner)"
        )
        return False

    try:
        target = getter()
    except Exception:
        logger.exception("corrupt_chat_env getter failed")
        return False

    if target is None:
        logger.warning("corrupt_chat_env getter returned None")
        return False

    env_dict = getattr(target, "env_dict", None)
    if not isinstance(env_dict, dict):
        logger.warning("corrupt_chat_env target has no env_dict: %s", type(target))
        return False

    previous = env_dict.get("task_prompt", "")
    env_dict["task_prompt"] = truncated_task
    logger.info(
        "corrupt_chat_env applied task_prompt len %s -> %s preview=%s",
        len(str(previous)),
        len(truncated_task),
        truncated_task[:120] + ("..." if len(truncated_task) > 120 else ""),
    )
    return True
