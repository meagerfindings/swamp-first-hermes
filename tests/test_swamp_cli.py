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
    assert ALLOWED_COMMANDS == frozenset({"model_search", "workflow_search"})
    assert build_command("model_search") == ("swamp", "model", "search", "--json")
    assert build_command("workflow_search") == (
        "swamp",
        "workflow",
        "search",
        "--json",
    )


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
