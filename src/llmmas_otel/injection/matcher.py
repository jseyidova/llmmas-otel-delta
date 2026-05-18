from __future__ import annotations

from .spec import FaultSelector
from .types import HookContext


def _eq_or_wildcard(expected, actual) -> bool:
    return expected is None or expected == actual


def _after_or_wildcard(expected, actual) -> bool:
    return expected is None or (actual is not None and actual > expected)


def _extras_match(expected: dict, actual: dict) -> bool:
    return all(actual.get(k) == v for k, v in expected.items())


def selector_matches(selector: FaultSelector, ctx: HookContext) -> bool:
    """
    Return True if selector matches the runtime HookContext.
    Any selector field that is None is treated as a wildcard ("don't care").
    """
    return (
        _eq_or_wildcard(selector.phase_name, ctx.phase_name)
        and _eq_or_wildcard(selector.phase_order, ctx.phase_order)
        and _eq_or_wildcard(selector.agent_id, ctx.agent_id)
        and _eq_or_wildcard(selector.step_index, ctx.step_index)
        and _eq_or_wildcard(selector.source_agent_id, ctx.source_agent_id)
        and _eq_or_wildcard(selector.target_agent_id, ctx.target_agent_id)
        and _eq_or_wildcard(selector.edge_id, ctx.edge_id)
        and _eq_or_wildcard(selector.message_id, ctx.message_id)
        and _eq_or_wildcard(selector.channel, ctx.channel)
        and _eq_or_wildcard(selector.tool_name, ctx.tool_name)
        and _eq_or_wildcard(selector.tool_type, ctx.tool_type)
        and _eq_or_wildcard(selector.tool_call_id, ctx.tool_call_id)
        and _eq_or_wildcard(selector.hook_index, ctx.hook_index)
        and _eq_or_wildcard(selector.hook_type_index, ctx.hook_type_index)
        and _after_or_wildcard(selector.after_hook_index, ctx.hook_index)
        and _after_or_wildcard(selector.after_hook_type_index, ctx.hook_type_index)
        and _extras_match(selector.extras, ctx.extras)
    )
