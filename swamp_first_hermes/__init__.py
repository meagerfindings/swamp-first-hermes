"""Hermes directory-plugin registration for safe Swamp-first capabilities."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from .policy import PolicyAction, PolicyMode, evaluate_tool_call
from .tools import (
    SWAMP_MODEL_SEARCH_SCHEMA,
    SWAMP_WORKFLOW_SEARCH_SCHEMA,
    swamp_model_search,
    swamp_workflow_search,
)

POLICY_MODE_ENV_VAR = "SWAMP_FIRST_POLICY_MODE"
_TOOLSET = "swamp_first"


def _policy_mode() -> PolicyMode:
    """Read the public opt-in policy mode, defaulting safely to ``off``."""
    value = os.getenv(POLICY_MODE_ENV_VAR, PolicyMode.OFF).strip().casefold()
    try:
        return PolicyMode(value)
    except ValueError:
        return PolicyMode.OFF


def pre_tool_call_policy(
    tool_name: str,
    args: dict[str, object],
    task_id: str,
    **kwargs: Any,
) -> dict[str, str] | None:
    """Return Hermes's documented block directive only for a blocking decision."""
    del task_id, kwargs
    arguments: Mapping[str, object] = args if isinstance(args, Mapping) else {}
    decision = evaluate_tool_call(_policy_mode(), tool_name, arguments)
    if decision.action is PolicyAction.BLOCK:
        return {"action": "block", "message": decision.reason or ""}
    return None


def register(ctx: Any) -> None:
    """Register the read-only Swamp tools and documented pre-tool-call hook."""
    ctx.register_tool(
        name="swamp_model_search",
        toolset=_TOOLSET,
        schema=SWAMP_MODEL_SEARCH_SCHEMA,
        handler=swamp_model_search,
    )
    ctx.register_tool(
        name="swamp_workflow_search",
        toolset=_TOOLSET,
        schema=SWAMP_WORKFLOW_SEARCH_SCHEMA,
        handler=swamp_workflow_search,
    )
    ctx.register_hook("pre_tool_call", pre_tool_call_policy)
