"""Tests for the pure, deterministic Swamp-first tool-call policy."""

from __future__ import annotations

import pytest

from swamp_first_hermes.policy import (
    PUBLIC_STRICT_SCHEDULED_AGENT_TOOLSET_ERROR,
    PUBLIC_STRICT_SCHEDULER_BYPASS_ERROR,
    PolicyAction,
    PolicyClassification,
    PolicyDecision,
    PolicyMode,
    classify_tool_call,
    evaluate_tool_call,
)


@pytest.mark.parametrize(
    "arguments",
    (
        {"action": "create"},
        {"action": "update"},
        {"action": "create", "enabled_toolsets": "swamp_first"},
        {"action": "update", "enabled_toolsets": {"swamp_first": True}},
        {"action": "create", "enabled_toolsets": []},
        {"action": "update", "enabled_toolsets": ["other_toolset"]},
    ),
)
def test_classification_detects_hermes_scheduled_agent_jobs_without_swamp_toolset(
    arguments: dict[str, object],
) -> None:
    assert classify_tool_call("cronjob", arguments) is (
        PolicyClassification.SCHEDULED_AGENT_MISSING_SWAMP_TOOLSET
    )


def test_classification_allows_compliant_scheduled_agent_jobs() -> None:
    for action in ("create", "update"):
        assert classify_tool_call(
            "cronjob", {"action": action, "enabled_toolsets": ["other_toolset", "swamp_first"]}
        ) is PolicyClassification.SAFE


@pytest.mark.parametrize("action", ("list", "get", "delete", "run", None, 42, []))
def test_classification_keeps_cronjob_lifecycle_actions_safe(action: object) -> None:
    assert classify_tool_call("cronjob", {"action": action}) is PolicyClassification.SAFE


@pytest.mark.parametrize("action", ("create", "update"))
def test_classification_keeps_script_only_cronjob_jobs_safe(action: str) -> None:
    assert classify_tool_call("cronjob", {"action": action, "no_agent": True}) is (
        PolicyClassification.SAFE
    )


def test_classification_is_scoped_to_the_documented_cronjob_tool() -> None:
    assert classify_tool_call("other_tool", {"action": "create"}) is PolicyClassification.SAFE


def test_scheduled_agent_toolset_policy_modes_are_deterministic_and_public_safe() -> None:
    arguments = {"action": "create", "enabled_toolsets": []}

    assert evaluate_tool_call("off", "cronjob", arguments) == PolicyDecision(
        action=PolicyAction.ALLOW,
        mode=PolicyMode.OFF,
        classification=PolicyClassification.SCHEDULED_AGENT_MISSING_SWAMP_TOOLSET,
        reason=None,
    )
    assert evaluate_tool_call("audit", "cronjob", arguments) == PolicyDecision(
        action=PolicyAction.ALLOW,
        mode=PolicyMode.AUDIT,
        classification=PolicyClassification.SCHEDULED_AGENT_MISSING_SWAMP_TOOLSET,
        reason="Audit: scheduled agent job is missing the required Swamp-first toolset.",
    )
    decision = evaluate_tool_call("strict", "cronjob", arguments)
    assert decision == PolicyDecision(
        action=PolicyAction.BLOCK,
        mode=PolicyMode.STRICT,
        classification=PolicyClassification.SCHEDULED_AGENT_MISSING_SWAMP_TOOLSET,
        reason=PUBLIC_STRICT_SCHEDULED_AGENT_TOOLSET_ERROR,
    )
    assert decision.reason == (
        "Blocked by Swamp-first policy: scheduled agent jobs must explicitly enable "
        "the required Swamp-first toolset in strict mode."
    )
    for private_detail in ("cronjob", "task-1", "secret prompt", "/private/path"):
        assert private_detail not in decision.reason.casefold()


def test_classification_detects_direct_scheduler_bypass_from_generic_command() -> None:
    """A generic execution tool cannot directly invoke a scheduler in strict mode."""
    assert classify_tool_call("execute", {"command": "crontab -e"}) is (
        PolicyClassification.SCHEDULER_BYPASS
    )
    assert classify_tool_call("run", {"argv": ["at", "10:00"]}) is (
        PolicyClassification.SCHEDULER_BYPASS
    )


def test_classification_does_not_treat_scheduler_words_as_a_bypass() -> None:
    """Detection is exact enough not to block ordinary descriptive arguments."""
    assert classify_tool_call("search", {"query": "scheduler design"}) is (
        PolicyClassification.SAFE
    )
    assert classify_tool_call("execute", {"command": "echo crontab"}) is (
        PolicyClassification.SAFE
    )


@pytest.mark.parametrize(
    "arguments",
    (
        {"command": "crontab -u example-user -l"},
        {"argv": ["crontab", "-u", "example-user", "-l"]},
        {"command": "crontab --help"},
        {"command": "crontab -h"},
        {"command": "crontab --version"},
        {"command": "crontab -V"},
    ),
)
def test_classification_allows_read_only_crontab_inspection_help_and_version(
    arguments: dict[str, object],
) -> None:
    """Known non-mutating crontab forms must remain usable in strict mode."""
    assert classify_tool_call("execute", arguments) is PolicyClassification.SAFE
    assert evaluate_tool_call("strict", "execute", arguments).action is PolicyAction.ALLOW


@pytest.mark.parametrize(
    "command",
    (
        "crontab -e",
        "crontab -r",
        "crontab -u example-user -e",
        "crontab /tmp/new-crontab",
    ),
)
def test_classification_retains_blocking_for_mutating_crontab_forms(command: str) -> None:
    assert classify_tool_call("execute", {"command": command}) is (
        PolicyClassification.SCHEDULER_BYPASS
    )
    assert evaluate_tool_call("strict", "execute", {"command": command}).action is (
        PolicyAction.BLOCK
    )


def test_off_mode_passes_scheduler_bypasses_through_without_audit_reason() -> None:
    assert evaluate_tool_call("off", "execute", {"command": "crontab -e"}) == (
        PolicyDecision(
            action=PolicyAction.ALLOW,
            mode=PolicyMode.OFF,
            classification=PolicyClassification.SCHEDULER_BYPASS,
            reason=None,
        )
    )


def test_audit_mode_passes_scheduler_bypasses_through_with_a_public_reason() -> None:
    decision = evaluate_tool_call(PolicyMode.AUDIT, "execute", {"command": "crontab -e"})

    assert decision == PolicyDecision(
        action=PolicyAction.ALLOW,
        mode=PolicyMode.AUDIT,
        classification=PolicyClassification.SCHEDULER_BYPASS,
        reason="Audit: direct scheduler bypass detected.",
    )


def test_strict_mode_blocks_only_direct_scheduler_bypasses_with_public_safe_error() -> None:
    decision = evaluate_tool_call("strict", "execute", {"command": "crontab -e"})

    assert decision == PolicyDecision(
        action=PolicyAction.BLOCK,
        mode=PolicyMode.STRICT,
        classification=PolicyClassification.SCHEDULER_BYPASS,
        reason=PUBLIC_STRICT_SCHEDULER_BYPASS_ERROR,
    )
    assert decision.reason == (
        "Blocked by Swamp-first policy: direct scheduler bypasses are not allowed "
        "in strict mode."
    )
    assert "crontab" not in decision.reason


def test_safe_tool_calls_pass_through_in_every_mode() -> None:
    for mode in PolicyMode:
        assert evaluate_tool_call(mode, "search", {"query": "public evidence"}) == (
            PolicyDecision(
                action=PolicyAction.ALLOW,
                mode=mode,
                classification=PolicyClassification.SAFE,
                reason=None,
            )
        )
