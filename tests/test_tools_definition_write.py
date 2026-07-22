"""Tests for the Hermes tool handlers wrapping scoped definition writes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swamp_first_hermes.definition_write import DefinitionWriteResult
from swamp_first_hermes.tools import (
    swamp_definition_write,
    swamp_model_set_config,
    swamp_workflow_set_schedule,
)


class _FakeValidateResult:
    def __init__(
        self,
        ok: bool,
        data: object = None,
        error: str | None = None,
        diagnostics: str | None = None,
    ) -> None:
        self.ok = ok
        self.data = data
        self.error = error
        self.diagnostics = diagnostics


def _stub_validate_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "swamp_first_hermes.definition_write.run_swamp_command",
        lambda *a, **k: _FakeValidateResult(True, {"valid": True}, None),
    )


def _stub_validate_fail_with_diagnostics(
    monkeypatch: pytest.MonkeyPatch, diagnostics: str
) -> None:
    monkeypatch.setattr(
        "swamp_first_hermes.definition_write.run_swamp_command",
        lambda *a, **k: _FakeValidateResult(False, None, "process_failed", diagnostics),
    )


def test_definition_write_handler_succeeds_and_serializes_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _stub_validate_ok(monkeypatch)

    payload = json.loads(
        swamp_definition_write(
            {
                "repository_path": str(tmp_path),
                "relative_path": "models/thing.yaml",
                "content": "name: thing\n",
                "definition_name": "thing",
            }
        )
    )

    assert payload == {
        "ok": True,
        "validated": True,
        "reverted": False,
        "deleted": False,
        "data": {"valid": True},
        "error": None,
        "diagnostics": None,
    }
    assert (tmp_path / "models" / "thing.yaml").read_text() == "name: thing\n"


def test_definition_write_handler_rejects_path_traversal(tmp_path: Path) -> None:
    payload = json.loads(
        swamp_definition_write(
            {
                "repository_path": str(tmp_path),
                "relative_path": "../../etc/passwd",
                "content": "x",
            }
        )
    )
    assert payload["ok"] is False
    assert payload["error"] == "path_not_allowed"


def test_definition_write_handler_rejects_a_live_schedule(tmp_path: Path) -> None:
    payload = json.loads(
        swamp_definition_write(
            {
                "repository_path": str(tmp_path),
                "relative_path": "workflows/nightly.yaml",
                "content": 'trigger:\n  schedule: "0 5 * * *"\n',
                "definition_name": "nightly",
            }
        )
    )
    assert payload == {
        "ok": False,
        "validated": False,
        "reverted": False,
        "deleted": False,
        "data": None,
        "error": "live_schedule_rejected",
        "diagnostics": None,
    }
    assert not (tmp_path / "workflows" / "nightly.yaml").exists()


def test_definition_write_handler_normalizes_an_unexpected_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raiser(*_args: object, **_kwargs: object):
        raise RuntimeError("private detail")

    monkeypatch.setattr("swamp_first_hermes.tools.write_definition", raiser)

    payload = json.loads(
        swamp_definition_write(
            {"repository_path": "/tmp", "relative_path": "models/x.yaml", "content": "x"}
        )
    )

    assert payload["ok"] is False
    assert payload["error"] == "execution_error"
    assert payload["diagnostics"] is None


def test_definition_write_handler_surfaces_scrubbed_diagnostics_on_revert(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The scrubbed diagnostics from the reverting validate call reach the
    JSON payload a caller actually sees, not just the internal result."""
    target = tmp_path / "models" / "thing.yaml"
    target.parent.mkdir(parents=True)
    target.write_text("name: original\n")
    _stub_validate_fail_with_diagnostics(monkeypatch, "thing.yaml:3:5 error: bad type")

    payload = json.loads(
        swamp_definition_write(
            {
                "repository_path": str(tmp_path),
                "relative_path": "models/thing.yaml",
                "content": "name: broken\n",
                "definition_name": "thing",
            }
        )
    )

    assert payload["ok"] is False
    assert payload["reverted"] is True
    assert payload["diagnostics"] == "thing.yaml:3:5 error: bad type"


# --- swamp_model_set_config ---------------------------------------------------


_MODEL_SET_CONFIG_PAYLOAD_KEYS = {
    "ok",
    "validated",
    "reverted",
    "deleted",
    "data",
    "error",
    "diagnostics",
    "relative_path",
}


def test_model_set_config_handler_succeeds_and_serializes_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canned = DefinitionWriteResult(True, True, False, False, {"valid": True}, None)
    monkeypatch.setattr(
        "swamp_first_hermes.tools.set_model_config",
        lambda *a, **k: (canned, "models/command/shell/809adf4b.yaml"),
    )

    payload = json.loads(
        swamp_model_set_config(
            {
                "repository_path": "/tmp/whatever",
                "name": "edittest",
                "config": {"globalArguments": {"a": "b"}},
            }
        )
    )

    assert payload == {
        "ok": True,
        "validated": True,
        "reverted": False,
        "deleted": False,
        "data": {"valid": True},
        "error": None,
        "diagnostics": None,
        "relative_path": "models/command/shell/809adf4b.yaml",
    }


def test_model_set_config_handler_surfaces_scrubbed_diagnostics_on_revert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canned = DefinitionWriteResult(
        False, True, True, False, None, "process_failed", "thing.yaml:3:5 error: bad type"
    )
    monkeypatch.setattr(
        "swamp_first_hermes.tools.set_model_config",
        lambda *a, **k: (canned, "models/command/shell/809adf4b.yaml"),
    )

    payload = json.loads(
        swamp_model_set_config(
            {"repository_path": "/tmp", "name": "edittest", "config": {"tags": {"a": "b"}}}
        )
    )

    assert payload["ok"] is False
    assert payload["reverted"] is True
    assert payload["diagnostics"] == "thing.yaml:3:5 error: bad type"
    assert payload["relative_path"] == "models/command/shell/809adf4b.yaml"


def test_model_set_config_handler_normalizes_an_unexpected_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raiser(*_args: object, **_kwargs: object):
        raise RuntimeError("private detail")

    monkeypatch.setattr("swamp_first_hermes.tools.set_model_config", raiser)

    payload = json.loads(
        swamp_model_set_config(
            {"repository_path": "/tmp", "name": "edittest", "config": {"tags": {"a": "b"}}}
        )
    )

    assert payload == {
        "ok": False,
        "validated": False,
        "reverted": False,
        "deleted": False,
        "data": None,
        "error": "execution_error",
        "diagnostics": None,
        "relative_path": None,
    }


def test_model_set_config_handler_payload_keys_stable_across_success_and_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The JSON payload shape must not change between the success path and
    the ``except Exception`` fallback — every key present in both."""
    canned = DefinitionWriteResult(True, True, False, False, {"valid": True}, None)
    monkeypatch.setattr(
        "swamp_first_hermes.tools.set_model_config",
        lambda *a, **k: (canned, "models/command/shell/809adf4b.yaml"),
    )
    success_payload = json.loads(
        swamp_model_set_config({"name": "edittest", "config": {"tags": {}}})
    )
    assert set(success_payload.keys()) == _MODEL_SET_CONFIG_PAYLOAD_KEYS

    def raiser(*_args: object, **_kwargs: object):
        raise RuntimeError("boom")

    monkeypatch.setattr("swamp_first_hermes.tools.set_model_config", raiser)
    exception_payload = json.loads(
        swamp_model_set_config({"name": "edittest", "config": {"tags": {}}})
    )
    assert set(exception_payload.keys()) == _MODEL_SET_CONFIG_PAYLOAD_KEYS


def test_set_schedule_handler_requires_confirmation(tmp_path: Path) -> None:
    payload = json.loads(
        swamp_workflow_set_schedule(
            {
                "repository_path": str(tmp_path),
                "relative_path": "workflows/nightly.yaml",
                "definition_name": "nightly",
                "cron_expression": "0 5 * * *",
            }
        )
    )
    assert payload == {
        "ok": False,
        "validated": False,
        "reverted": False,
        "deleted": False,
        "data": None,
        "error": "confirmation_required",
        "diagnostics": None,
    }


@pytest.mark.parametrize("confirmed", (False, "true", 1, None))
def test_set_schedule_handler_rejects_non_boolean_true_confirmation(
    tmp_path: Path, confirmed: object
) -> None:
    payload = json.loads(
        swamp_workflow_set_schedule(
            {
                "repository_path": str(tmp_path),
                "relative_path": "workflows/nightly.yaml",
                "definition_name": "nightly",
                "cron_expression": "0 5 * * *",
                "confirmed": confirmed,
            }
        )
    )
    assert payload["error"] == "confirmation_required"


def test_set_schedule_handler_proceeds_once_confirmed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "workflows" / "nightly.yaml"
    target.parent.mkdir(parents=True)
    target.write_text("name: nightly\n")
    _stub_validate_ok(monkeypatch)

    payload = json.loads(
        swamp_workflow_set_schedule(
            {
                "repository_path": str(tmp_path),
                "relative_path": "workflows/nightly.yaml",
                "definition_name": "nightly",
                "cron_expression": "0 5 * * *",
                "confirmed": True,
            }
        )
    )

    assert payload["ok"] is True
    assert payload["diagnostics"] is None
    assert '"0 5 * * *"' in target.read_text()


def test_set_schedule_handler_surfaces_scrubbed_diagnostics_on_revert(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "workflows" / "nightly.yaml"
    target.parent.mkdir(parents=True)
    target.write_text("name: nightly\n")
    _stub_validate_fail_with_diagnostics(monkeypatch, "nightly.yaml:1:1 error: bad schema")

    payload = json.loads(
        swamp_workflow_set_schedule(
            {
                "repository_path": str(tmp_path),
                "relative_path": "workflows/nightly.yaml",
                "definition_name": "nightly",
                "cron_expression": "0 5 * * *",
                "confirmed": True,
            }
        )
    )

    assert payload["ok"] is False
    assert payload["reverted"] is True
    assert payload["diagnostics"] == "nightly.yaml:1:1 error: bad schema"


def test_set_schedule_handler_normalizes_an_unexpected_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raiser(*_args: object, **_kwargs: object):
        raise RuntimeError("private detail")

    monkeypatch.setattr("swamp_first_hermes.tools.set_workflow_schedule", raiser)

    payload = json.loads(
        swamp_workflow_set_schedule(
            {
                "repository_path": "/tmp",
                "relative_path": "workflows/x.yaml",
                "definition_name": "x",
                "cron_expression": "0 5 * * *",
                "confirmed": True,
            }
        )
    )

    assert payload["ok"] is False
    assert payload["error"] == "execution_error"
    assert payload["diagnostics"] is None
