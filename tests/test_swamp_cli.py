"""Tests for the deterministic, read-only Swamp CLI adapter."""

from __future__ import annotations

from pathlib import Path
import subprocess
from unittest.mock import Mock

import pytest

from swamp_first_hermes.swamp_cli import (
    ALLOWED_COMMANDS,
    SwampCliResult,
    build_command,
    run_swamp_command,
)


def test_allowlist_maps_read_only_commands_to_fixed_json_arguments() -> None:
    """The adapter maps each public command to fixed ``--json`` arguments."""
    assert ALLOWED_COMMANDS == frozenset(
        {
            "model_search",
            "workflow_search",
            "model_create",
            "model_validate",
            "model_method_run",
            "workflow_create",
            "workflow_validate",
            "workflow_run",
            "extension_search",
            "extension_pull",
            "extension_quality",
            "extension_push",
        }
    )
    assert build_command("model_search") == ("swamp", "model", "search", "--json")
    assert build_command("workflow_search") == (
        "swamp",
        "workflow",
        "search",
        "--json",
    )


@pytest.mark.parametrize(
    ("command", "positional_arguments", "expected_suffix"),
    (
        ("model_create", ("aws-ec2", "my-server"), ("model", "create", "aws-ec2", "my-server")),
        ("model_validate", (), ("model", "validate")),
        ("model_validate", ("my-server",), ("model", "validate", "my-server")),
        (
            "model_method_run",
            ("my-server", "start"),
            ("model", "method", "run", "my-server", "start"),
        ),
        ("workflow_create", ("nightly-check",), ("workflow", "create", "nightly-check")),
        ("workflow_validate", (), ("workflow", "validate")),
        (
            "workflow_validate",
            ("nightly-check",),
            ("workflow", "validate", "nightly-check"),
        ),
        ("workflow_run", ("nightly-check",), ("workflow", "run", "nightly-check")),
        ("extension_search", (), ("extension", "search")),
        ("extension_search", ("llm",), ("extension", "search", "llm")),
        (
            "extension_pull",
            ("@keeb/ollama",),
            ("extension", "pull", "@keeb/ollama"),
        ),
        (
            "extension_quality",
            ("manifest.yaml",),
            ("extension", "quality", "manifest.yaml"),
        ),
        (
            "extension_push",
            ("manifest.yaml",),
            ("extension", "push", "manifest.yaml"),
        ),
    ),
)
def test_build_command_assembles_positional_arguments_for_new_commands(
    command: str,
    positional_arguments: tuple[str, ...],
    expected_suffix: tuple[str, ...],
) -> None:
    """New commands accept caller-supplied positional arguments as discrete argv."""
    assert build_command(command, *positional_arguments) == (
        "swamp",
        *expected_suffix,
        "--json",
    )


@pytest.mark.parametrize(
    ("command", "positional_arguments"),
    (
        ("model_create", ()),
        ("model_create", ("only-one",)),
        ("model_create", ("type", "name", "extra")),
        ("workflow_run", ()),
        ("workflow_run", ("a", "b")),
        ("extension_search", ("a", "b")),
    ),
)
def test_build_command_rejects_the_wrong_number_of_positional_arguments(
    command: str,
    positional_arguments: tuple[str, ...],
) -> None:
    with pytest.raises(ValueError, match="wrong number of arguments"):
        build_command(command, *positional_arguments)


@pytest.mark.parametrize(
    "positional_arguments",
    (
        ("-rf",),
        ("",),
        ("bad\x00name",),
    ),
)
def test_build_command_rejects_unsafe_positional_arguments(
    positional_arguments: tuple[str, ...],
) -> None:
    with pytest.raises(ValueError, match="invalid argument"):
        build_command("extension_pull", *positional_arguments)


def test_run_swamp_command_passes_positional_arguments_to_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = Mock(
        return_value=subprocess.CompletedProcess(
            args=[], returncode=0, stdout='{"created": true}', stderr=""
        )
    )
    monkeypatch.setattr("swamp_first_hermes.swamp_cli.subprocess.run", runner)

    result = run_swamp_command("model_create", "aws-ec2", "my-server")

    assert result == SwampCliResult(ok=True, data={"created": True}, error=None)
    runner.assert_called_once_with(
        ["swamp", "model", "create", "aws-ec2", "my-server", "--json"],
        cwd=None,
        capture_output=True,
        check=False,
        text=True,
        timeout=10.0,
    )


def test_run_swamp_command_rejects_invalid_positional_arguments_without_running_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = Mock()
    monkeypatch.setattr("swamp_first_hermes.swamp_cli.subprocess.run", runner)

    result = run_swamp_command("model_create", "-rf", "name")

    assert result == SwampCliResult(ok=False, data=None, error="invalid_argument")
    runner.assert_not_called()


def test_success_parses_json_and_uses_the_supplied_repository_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner = Mock(
        return_value=subprocess.CompletedProcess(
            args=[], returncode=0, stdout='{"state": "ready"}', stderr=""
        )
    )
    monkeypatch.setattr("swamp_first_hermes.swamp_cli.subprocess.run", runner)

    result = run_swamp_command("model_search", repository_path=tmp_path)

    assert result == SwampCliResult(ok=True, data={"state": "ready"}, error=None)
    runner.assert_called_once_with(
        ["swamp", "model", "search", "--json"],
        cwd=str(tmp_path),
        capture_output=True,
        check=False,
        text=True,
        timeout=10.0,
    )


def test_success_uses_current_working_directory_when_no_path_is_supplied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = Mock(
        return_value=subprocess.CompletedProcess(
            args=[], returncode=0, stdout="[]", stderr=""
        )
    )
    monkeypatch.setattr("swamp_first_hermes.swamp_cli.subprocess.run", runner)

    result = run_swamp_command("workflow_search")

    assert result == SwampCliResult(ok=True, data=[], error=None)
    assert runner.call_args.kwargs["cwd"] is None


@pytest.mark.parametrize(
    "repository_path",
    ["bad\x00path", "missing", "not-a-directory"],
)
def test_invalid_repository_paths_are_rejected_without_running_subprocess(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    repository_path: str,
) -> None:
    runner = Mock()
    monkeypatch.setattr("swamp_first_hermes.swamp_cli.subprocess.run", runner)
    if repository_path == "missing":
        repository_path = str(tmp_path / repository_path)
    elif repository_path == "not-a-directory":
        path = tmp_path / repository_path
        path.write_text("not a directory")
        repository_path = str(path)

    result = run_swamp_command("model_search", repository_path=repository_path)

    assert result == SwampCliResult(
        ok=False, data=None, error="invalid_repository_path"
    )
    runner.assert_not_called()


@pytest.mark.parametrize(
    "timeout", ["10", None, True, 0, -1, float("nan"), float("inf")]
)
def test_invalid_timeouts_are_rejected_without_running_subprocess(
    monkeypatch: pytest.MonkeyPatch,
    timeout: object,
) -> None:
    runner = Mock()
    monkeypatch.setattr("swamp_first_hermes.swamp_cli.subprocess.run", runner)

    result = run_swamp_command("model_search", timeout=timeout)  # type: ignore[arg-type]

    assert result == SwampCliResult(ok=False, data=None, error="invalid_timeout")
    runner.assert_not_called()


def test_repository_path_is_normalized_once_before_subprocess(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class StatefulPath:
        def __init__(self, safe_path: Path) -> None:
            self.safe_path = safe_path
            self.calls = 0

        def __fspath__(self) -> str:
            self.calls += 1
            return str(self.safe_path) if self.calls == 1 else "bad\x00path"

    repository_path = StatefulPath(tmp_path)
    runner = Mock(
        return_value=subprocess.CompletedProcess(
            args=[], returncode=0, stdout="[]", stderr=""
        )
    )
    monkeypatch.setattr("swamp_first_hermes.swamp_cli.subprocess.run", runner)

    result = run_swamp_command("model_search", repository_path=repository_path)

    assert result == SwampCliResult(ok=True, data=[], error=None)
    assert repository_path.calls == 1
    assert runner.call_args.kwargs["cwd"] == str(tmp_path)


def test_nonzero_exit_is_normalized_without_stderr_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = Mock(
        return_value=subprocess.CompletedProcess(
            args=[], returncode=7, stdout="", stderr="private diagnostic"
        )
    )
    monkeypatch.setattr("swamp_first_hermes.swamp_cli.subprocess.run", runner)

    result = run_swamp_command("model_search")

    assert result == SwampCliResult(ok=False, data=None, error="process_error")
    assert "private diagnostic" not in repr(result)


def test_malformed_json_is_normalized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = Mock(
        return_value=subprocess.CompletedProcess(
            args=[], returncode=0, stdout="not-json", stderr=""
        )
    )
    monkeypatch.setattr("swamp_first_hermes.swamp_cli.subprocess.run", runner)

    assert run_swamp_command("model_search") == SwampCliResult(
        ok=False, data=None, error="malformed_json"
    )


def test_missing_executable_is_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = Mock(side_effect=FileNotFoundError("private executable path"))
    monkeypatch.setattr("swamp_first_hermes.swamp_cli.subprocess.run", runner)

    assert run_swamp_command("model_search") == SwampCliResult(
        ok=False, data=None, error="executable_not_found"
    )


def test_os_errors_are_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = Mock(side_effect=OSError("private operating system error"))
    monkeypatch.setattr("swamp_first_hermes.swamp_cli.subprocess.run", runner)

    assert run_swamp_command("model_search") == SwampCliResult(
        ok=False, data=None, error="execution_error"
    )


def test_timeout_is_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = Mock(side_effect=subprocess.TimeoutExpired("swamp", 10.0, output="private"))
    monkeypatch.setattr("swamp_first_hermes.swamp_cli.subprocess.run", runner)

    assert run_swamp_command("model_search") == SwampCliResult(
        ok=False, data=None, error="timeout"
    )


def test_non_allowlisted_commands_are_rejected_without_running_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = Mock()
    monkeypatch.setattr("swamp_first_hermes.swamp_cli.subprocess.run", runner)

    result = run_swamp_command("delete --all")

    assert result == SwampCliResult(ok=False, data=None, error="command_not_allowed")
    runner.assert_not_called()


def test_build_command_rejects_non_allowlisted_commands() -> None:
    with pytest.raises(ValueError, match="not allowed"):
        build_command("delete")
