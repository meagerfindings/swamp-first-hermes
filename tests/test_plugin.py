"""Tests for the documented Hermes directory-plugin registration glue."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest

from swamp_first_hermes import POLICY_MODE_ENV_VAR, pre_tool_call_policy, register
from swamp_first_hermes.policy import PUBLIC_STRICT_SCHEDULER_BYPASS_ERROR
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
