"""Tests for the closed-argument authoring/publish tool handlers."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import Mock

import pytest

from swamp_first_hermes.tools import (
    swamp_extension_pull,
    swamp_extension_push,
    swamp_extension_quality,
    swamp_extension_search,
    swamp_model_create,
    swamp_model_method_run,
    swamp_model_validate,
    swamp_workflow_create,
    swamp_workflow_run,
    swamp_workflow_validate,
)


class _FakeResult:
    def __init__(self, ok: bool, data: object, error: str | None) -> None:
        self.ok = ok
        self.data = data
        self.error = error


@pytest.mark.parametrize(
    ("handler", "args", "expected_command", "expected_positional"),
    (
        (
            swamp_model_create,
            {"model_type": "aws-ec2", "name": "my-server"},
            "model_create",
            ("aws-ec2", "my-server"),
        ),
        (swamp_model_validate, {}, "model_validate", ()),
        (
            swamp_model_validate,
            {"name": "my-server"},
            "model_validate",
            ("my-server",),
        ),
        (
            swamp_model_method_run,
            {"model": "my-server", "method": "start"},
            "model_method_run",
            ("my-server", "start"),
        ),
        (
            swamp_workflow_create,
            {"name": "nightly-check"},
            "workflow_create",
            ("nightly-check",),
        ),
        (swamp_workflow_validate, {}, "workflow_validate", ()),
        (
            swamp_workflow_run,
            {"name": "nightly-check"},
            "workflow_run",
            ("nightly-check",),
        ),
        (swamp_extension_search, {}, "extension_search", ()),
        (
            swamp_extension_search,
            {"query": "llm"},
            "extension_search",
            ("llm",),
        ),
        (
            swamp_extension_pull,
            {"extension": "@keeb/ollama"},
            "extension_pull",
            ("@keeb/ollama",),
        ),
        (
            swamp_extension_quality,
            {"manifest_path": "manifest.yaml"},
            "extension_quality",
            ("manifest.yaml",),
        ),
    ),
)
def test_wrapper_calls_the_matching_allowlisted_command(
    monkeypatch: pytest.MonkeyPatch,
    handler: Any,
    args: dict[str, object],
    expected_command: str,
    expected_positional: tuple[str, ...],
) -> None:
    captured: dict[str, object] = {}

    def fake_runner(command: str, *positional: str, **kwargs: object):
        captured["command"] = command
        captured["positional"] = positional
        captured["kwargs"] = kwargs
        return _FakeResult(True, {"ok": True}, None)

    monkeypatch.setattr("swamp_first_hermes.tools.run_swamp_command", fake_runner)

    payload = json.loads(handler(args))

    assert captured["command"] == expected_command
    assert captured["positional"] == expected_positional
    assert payload == {"ok": True, "data": {"ok": True}, "error": None}


@pytest.mark.parametrize(
    ("handler", "args"),
    (
        (swamp_model_create, {"name": "only-one"}),
        (swamp_model_create, {"model_type": "aws-ec2"}),
        (swamp_model_method_run, {"model": "my-server"}),
        (swamp_workflow_create, {}),
        (swamp_workflow_run, {}),
        (swamp_extension_pull, {}),
        (swamp_extension_quality, {}),
    ),
)
def test_wrapper_rejects_missing_required_arguments_without_calling_swamp(
    monkeypatch: pytest.MonkeyPatch,
    handler: Any,
    args: dict[str, object],
) -> None:
    runner = Mock()
    monkeypatch.setattr("swamp_first_hermes.tools.run_swamp_command", runner)

    payload = json.loads(handler(args))

    assert payload == {"ok": False, "data": None, "error": "missing_argument"}
    runner.assert_not_called()


def test_extension_push_requires_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = Mock()
    monkeypatch.setattr("swamp_first_hermes.tools.run_swamp_command", runner)

    payload = json.loads(
        swamp_extension_push({"manifest_path": "manifest.yaml"})
    )

    assert payload == {"ok": False, "data": None, "error": "confirmation_required"}
    runner.assert_not_called()


@pytest.mark.parametrize("confirmed", (False, "true", 1, None))
def test_extension_push_rejects_non_boolean_true_confirmation(
    monkeypatch: pytest.MonkeyPatch, confirmed: object
) -> None:
    runner = Mock()
    monkeypatch.setattr("swamp_first_hermes.tools.run_swamp_command", runner)

    payload = json.loads(
        swamp_extension_push({"manifest_path": "manifest.yaml", "confirmed": confirmed})
    )

    assert payload == {"ok": False, "data": None, "error": "confirmation_required"}
    runner.assert_not_called()


def test_extension_push_proceeds_once_explicitly_confirmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_runner(command: str, *positional: str, **kwargs: object):
        captured["command"] = command
        captured["positional"] = positional
        return _FakeResult(True, {"published": True}, None)

    monkeypatch.setattr("swamp_first_hermes.tools.run_swamp_command", fake_runner)

    payload = json.loads(
        swamp_extension_push({"manifest_path": "manifest.yaml", "confirmed": True})
    )

    assert captured["command"] == "extension_push"
    assert captured["positional"] == ("manifest.yaml",)
    assert payload == {"ok": True, "data": {"published": True}, "error": None}


def test_wrapper_normalizes_an_unexpected_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raiser(*_args: object, **_kwargs: object):
        raise RuntimeError("private detail")

    monkeypatch.setattr("swamp_first_hermes.tools.run_swamp_command", raiser)

    payload = json.loads(swamp_model_validate({}))

    assert payload == {"ok": False, "data": None, "error": "execution_error"}


def test_model_method_run_forwards_inputs_to_the_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The tool must pass method arguments through, not drop them."""
    captured: dict[str, object] = {}

    def fake_runner(command: str, *positional: str, **kwargs: object):
        captured["command"] = command
        captured["positional"] = positional
        captured["inputs"] = kwargs.get("inputs")
        return _FakeResult(True, {"ok": 1}, None)

    monkeypatch.setattr("swamp_first_hermes.tools.run_swamp_command", fake_runner)

    swamp_model_method_run(
        {
            "model": "unifi-release-safety-repo",
            "method": "status",
            "inputs": {"project": "owner/repo", "localPath": "/opt/data/repo"},
        }
    )

    assert captured["positional"] == ("unifi-release-safety-repo", "status")
    assert captured["inputs"] == {
        "project": "owner/repo",
        "localPath": "/opt/data/repo",
    }


def test_model_method_run_rejects_non_mapping_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "swamp_first_hermes.tools.run_swamp_command",
        lambda *a, **k: _FakeResult(True, {}, None),
    )
    payload = json.loads(
        swamp_model_method_run({"model": "m", "method": "x", "inputs": "project=a"})
    )
    assert payload["error"] == "invalid_argument"


def test_command_timeout_is_not_capped_by_the_tool_layer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fixed default here would silently cap long commands like push."""
    captured: dict[str, object] = {}

    def fake_runner(command: str, *positional: str, **kwargs: object):
        captured["timeout_passed"] = "timeout" in kwargs
        return _FakeResult(True, {}, None)

    monkeypatch.setattr("swamp_first_hermes.tools.run_swamp_command", fake_runner)
    swamp_model_method_run({"model": "m", "method": "x"})
    assert captured["timeout_passed"] is False
