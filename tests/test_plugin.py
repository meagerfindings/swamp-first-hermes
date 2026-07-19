"""Tests for the documented Hermes directory-plugin registration glue."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest

from swamp_first_hermes import POLICY_MODE_ENV_VAR, pre_tool_call_policy, register
from swamp_first_hermes.policy import (
    PUBLIC_STRICT_SCHEDULED_AGENT_TOOLSET_ERROR,
    PUBLIC_STRICT_SCHEDULER_BYPASS_ERROR,
)
from swamp_first_hermes.tools import swamp_model_search, swamp_workflow_search


class FakePluginContext:
    """Small stand-in for the documented PluginContext registration surface."""

    def __init__(self) -> None:
        self.tools: list[dict[str, Any]] = []
        self.hooks: list[tuple[str, Callable[..., object]]] = []

    def register_tool(
        self,
        *,
        name: str,
        toolset: str,
        schema: dict[str, object],
        handler: Callable[..., object],
    ) -> None:
        self.tools.append(
            {
                "name": name,
                "toolset": toolset,
                "schema": schema,
                "handler": handler,
            }
        )

    def register_hook(self, hook_name: str, callback: Callable[..., object]) -> None:
        self.hooks.append((hook_name, callback))


def test_registers_only_safe_swamp_discovery_and_evidence_tools_and_policy_hook() -> None:
    context = FakePluginContext()

    register(context)

    assert [(tool["name"], tool["toolset"], tool["handler"]) for tool in context.tools] == [
        ("swamp_model_search", "swamp_first", swamp_model_search),
        ("swamp_workflow_search", "swamp_first", swamp_workflow_search),
    ]
    assert [tool["schema"]["name"] for tool in context.tools] == [
        "swamp_model_search",
        "swamp_workflow_search",
    ]
    assert context.hooks == [("pre_tool_call", pre_tool_call_policy)]


def test_policy_hook_returns_only_the_documented_block_directive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(POLICY_MODE_ENV_VAR, "strict")

    blocked = pre_tool_call_policy("terminal", {"command": "crontab -e"}, "task-1")
    allowed = pre_tool_call_policy("terminal", {"command": "crontab -l"}, "task-1")

    assert blocked == {
        "action": "block",
        "message": PUBLIC_STRICT_SCHEDULER_BYPASS_ERROR,
    }
    assert allowed is None


def test_policy_hook_defaults_to_off_and_does_not_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(POLICY_MODE_ENV_VAR, raising=False)

    assert pre_tool_call_policy("terminal", {"command": "crontab -e"}, "task-1") is None


def test_policy_hook_logs_a_safe_structured_audit_event_for_detected_bypass(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv(POLICY_MODE_ENV_VAR, "audit")
    caplog.set_level("INFO", logger="swamp_first_hermes")

    assert pre_tool_call_policy("terminal", {"command": "crontab -e"}, "task-1") is None

    assert caplog.messages == [
        "swamp_first_policy_decision mode=audit classification=scheduler_bypass "
        "action=allow reason_code=direct_scheduler_bypass"
    ]


def test_policy_hook_logs_before_returning_a_strict_block(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv(POLICY_MODE_ENV_VAR, "strict")
    caplog.set_level("INFO", logger="swamp_first_hermes")

    assert pre_tool_call_policy("terminal", {"command": "crontab -e"}, "task-1") == {
        "action": "block",
        "message": PUBLIC_STRICT_SCHEDULER_BYPASS_ERROR,
    }

    assert caplog.messages == [
        "swamp_first_policy_decision mode=strict classification=scheduler_bypass "
        "action=block reason_code=direct_scheduler_bypass"
    ]


@pytest.mark.parametrize(
    ("mode", "arguments"),
    (
        ("audit", {"command": "echo harmless"}),
        ("strict", {"command": "echo harmless"}),
        ("off", {"command": "crontab -e"}),
    ),
)
def test_policy_hook_does_not_log_safe_or_off_mode_decisions(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    mode: str,
    arguments: dict[str, object],
) -> None:
    monkeypatch.setenv(POLICY_MODE_ENV_VAR, mode)
    caplog.set_level("INFO", logger="swamp_first_hermes")

    assert pre_tool_call_policy("terminal", arguments, "task-1") is None

    assert caplog.messages == []


def test_policy_hook_event_never_leaks_tool_arguments_or_task_identity(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv(POLICY_MODE_ENV_VAR, "audit")
    caplog.set_level("INFO", logger="swamp_first_hermes")
    secret_argument = "private-prompt-7f091"
    private_task_id = "private-user-4bd83"

    assert pre_tool_call_policy(
        "terminal",
        {"command": f"crontab -e --comment={secret_argument}", "prompt": secret_argument},
        private_task_id,
    ) is None

    assert len(caplog.messages) == 1
    for private_value in (secret_argument, private_task_id, "terminal", "command", "prompt"):
        assert private_value not in caplog.messages[0]


def test_policy_hook_blocks_noncompliant_scheduled_agent_jobs_in_strict_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(POLICY_MODE_ENV_VAR, "strict")

    assert pre_tool_call_policy("cronjob", {"action": "create"}, "task-1") == {
        "action": "block",
        "message": PUBLIC_STRICT_SCHEDULED_AGENT_TOOLSET_ERROR,
    }


def test_policy_hook_allows_compliant_and_script_only_scheduled_jobs_in_strict_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(POLICY_MODE_ENV_VAR, "strict")

    assert pre_tool_call_policy(
        "cronjob",
        {"action": "update", "enabled_toolsets": ["swamp_first"]},
        "task-1",
    ) is None
    assert pre_tool_call_policy(
        "cronjob", {"action": "create", "no_agent": True}, "task-1"
    ) is None


def test_discovery_and_evidence_wrappers_return_normalized_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_runner(command: str, **kwargs: object):
        assert kwargs == {"repository_path": "repository", "timeout": 2.5}
        return type("Result", (), {"ok": True, "data": {"command": command}, "error": None})()

    monkeypatch.setattr("swamp_first_hermes.tools.run_swamp_command", fake_runner)

    assert json.loads(swamp_model_search({"repository_path": "repository", "timeout": 2.5})) == {
        "ok": True,
        "data": {"command": "model_search"},
        "error": None,
    }
    assert json.loads(swamp_workflow_search({"repository_path": "repository", "timeout": 2.5})) == {
        "ok": True,
        "data": {"command": "workflow_search"},
        "error": None,
    }
