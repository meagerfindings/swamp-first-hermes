"""Hermes directory-plugin registration for safe Swamp-first capabilities."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from typing import Any

from .policy import (
    PolicyAction,
    PolicyClassification,
    PolicyDecision,
    PolicyMode,
    evaluate_tool_call,
)
from .tools import (
    SWAMP_MODEL_SEARCH_SCHEMA,
    SWAMP_WORKFLOW_SEARCH_SCHEMA,
    swamp_model_search,
    swamp_workflow_search,
)

POLICY_MODE_ENV_VAR = "SWAMP_FIRST_POLICY_MODE"
_TOOLSET = "swamp_first"
_LOGGER = logging.getLogger(__name__)
_POLICY_DECISION_EVENT = "swamp_first_policy_decision"
_REASON_CODES = {
    PolicyClassification.SCHEDULER_BYPASS: "direct_scheduler_bypass",
    PolicyClassification.SCHEDULED_AGENT_MISSING_SWAMP_TOOLSET: (
        "scheduled_agent_requires_swamp_toolset"
    ),
}


def _log_relevant_policy_decision(decision: PolicyDecision) -> None:
    """Emit one fixed-field local observation for a relevant policy decision.

    This deliberately passes only enum-derived public values to standard Python
    logging. Tool names, arguments, task identifiers, and runtime details are
    excluded from the event.
    """
    reason_code = _REASON_CODES.get(decision.classification)
    if decision.mode is PolicyMode.OFF or reason_code is None:
        return
    _LOGGER.info(
        "%s mode=%s classification=%s action=%s reason_code=%s",
        _POLICY_DECISION_EVENT,
        decision.mode.value,
        decision.classification.value,
        decision.action.value,
        reason_code,
    )


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
    _log_relevant_policy_decision(decision)
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
