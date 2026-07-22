"""Tests for the deterministic, read-only Swamp CLI adapter."""

from __future__ import annotations

from pathlib import Path
import subprocess
from unittest.mock import Mock

import pytest

from swamp_first_hermes.swamp_cli import (
    ALLOWED_COMMANDS,
    SwampCliResult,
    _scrub_diagnostics,
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
            "extension_fmt",
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
            "extension_fmt",
            ("manifest.yaml",),
            ("extension", "fmt", "manifest.yaml"),
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
        ("extension_fmt", ()),
        ("extension_fmt", ("manifest.yaml", "extra")),
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


def test_nonzero_exit_without_body_is_process_failed_without_stderr_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = Mock(
        return_value=subprocess.CompletedProcess(
            args=[], returncode=7, stdout="", stderr="private diagnostic"
        )
    )
    monkeypatch.setattr("swamp_first_hermes.swamp_cli.subprocess.run", runner)

    result = run_swamp_command("model_search")

    # A non-zero exit with no JSON result body is the process itself failing,
    # not an actionable rejection — surfaced as ``process_failed`` so the
    # caller can tell the two apart, with stderr still withheld.
    assert result == SwampCliResult(ok=False, data=None, error="process_failed")
    assert "private diagnostic" not in repr(result)


def test_nonzero_exit_with_json_body_surfaces_the_body_as_process_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = Mock(
        return_value=subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout='{"status": "invalid", "reason": "unknown model"}',
            stderr="",
        )
    )
    monkeypatch.setattr("swamp_first_hermes.swamp_cli.subprocess.run", runner)

    result = run_swamp_command("model_validate", "some-model")

    # A non-zero exit that still wrote an actionable JSON body is a real
    # rejection: the body is surfaced in ``data`` under ``process_error``.
    assert result == SwampCliResult(
        ok=False,
        data={"status": "invalid", "reason": "unknown model"},
        error="process_error",
    )


def test_validate_fatal_bundle_error_surfaces_scrubbed_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Models a swamp ``model validate`` fatal: the CLI exits non-zero and writes
    # a ``[FTL]`` diagnostic — containing an absolute local path and a private
    # extension identifier — to stderr, with no JSON on stdout. ``model_validate``
    # is in the narrow diagnostic-command allowlist, so the adapter must report
    # a distinct ``process_failed`` (not an opaque ``process_error`` that looks
    # like a rejection) and surface a scrubbed version of the diagnostic — but
    # the absolute path and the private identifier embedded in it must never
    # appear in what is surfaced, since no repository root was supplied here to
    # relativize against and the path is not one the adapter can prove safe.
    fatal_stderr = (
        "[FTL] error: Error: Bundle has no extension export: "
        "/opt/data/swamp-hub/.swamp/bundles/e9c5c01e/@acme/private-writer/model.js"
    )
    runner = Mock(
        return_value=subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr=fatal_stderr
        )
    )
    monkeypatch.setattr("swamp_first_hermes.swamp_cli.subprocess.run", runner)

    result = run_swamp_command("model_validate", "some-model")

    assert result.ok is False
    assert result.data is None
    assert result.error == "process_failed"
    assert result.diagnostics is not None
    assert "Bundle has no extension export" in result.diagnostics
    assert "/opt/data" not in result.diagnostics
    assert "private-writer" not in result.diagnostics
    assert "/opt/data" not in repr(result)
    assert "private-writer" not in repr(result)


def test_non_diagnostic_command_still_withholds_stderr_entirely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Same fatal shape as above (no JSON body, an absolute path and a private
    # identifier on stderr), but for a command outside the narrow diagnostic
    # allowlist. The scoping must be strict: this must stay fully withheld,
    # exactly as before this feature existed.
    fatal_stderr = (
        "[FTL] error: Error: Bundle has no extension export: "
        "/opt/data/swamp-hub/.swamp/bundles/e9c5c01e/@acme/private-writer/model.js"
    )
    runner = Mock(
        return_value=subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr=fatal_stderr
        )
    )
    monkeypatch.setattr("swamp_first_hermes.swamp_cli.subprocess.run", runner)

    result = run_swamp_command("extension_pull", "@acme/private-writer")

    assert result == SwampCliResult(ok=False, data=None, error="process_failed")
    assert result.diagnostics is None
    assert "/opt/data" not in repr(result)
    assert "private-writer" not in repr(result)


def test_execution_command_surfaces_scrubbed_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A failed model_method_run: the actionable cause (a misplaced input) is on
    # stderr with an absolute path. The path must be scrubbed, the cause kept —
    # this is what lets the agent self-correct a run instead of asking a human.
    fatal_stderr = (
        "[FTL] error: unknown method input 'apiToken' for "
        "/opt/data/swamp-hub/extensions/models/trip-packing/trip-packing.ts:12 "
        "— apiToken is a global argument, not a per-method input"
    )
    runner = Mock(
        return_value=subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr=fatal_stderr
        )
    )
    monkeypatch.setattr("swamp_first_hermes.swamp_cli.subprocess.run", runner)

    result = run_swamp_command("model_method_run", "trip-packing-smoke", "preview")

    assert result.error == "process_failed"
    assert result.diagnostics is not None
    # the actionable cause survives so the agent can self-correct the run
    assert "apiToken is a global argument" in result.diagnostics
    # the absolute location does not
    assert "/opt/data" not in result.diagnostics
    assert "/opt/data" not in repr(result)


def test_diagnostic_command_relativizes_repository_root_and_hides_identifiers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # A realistic ``extension quality`` failure: a lint diagnostic with a
    # file:line, a rule name, and a fix hint, prefixed by the absolute
    # repository path (which itself embeds a private username and project
    # name). The surfaced diagnostics must keep the relative file:line and
    # rule name — that is the entire point — while the absolute prefix and
    # the private identifiers embedded in it must not appear anywhere in it.
    repository_directory = tmp_path / "mgreten" / "git" / "acme-secret-project"
    repository_directory.mkdir(parents=True)
    fatal_stderr = (
        f"{repository_directory}/extensions/models/thing-writer/model.ts:42:3 - "
        "error require-await: Async function 'writeThing' has no await "
        "expression. Run `swamp extension fmt` to fix.\n"
    )
    runner = Mock(
        return_value=subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr=fatal_stderr
        )
    )
    monkeypatch.setattr("swamp_first_hermes.swamp_cli.subprocess.run", runner)

    result = run_swamp_command(
        "extension_quality",
        "extensions/models/thing-writer/manifest.yaml",
        repository_path=str(repository_directory),
    )

    assert result.error == "process_failed"
    assert result.data is None
    assert result.diagnostics is not None
    assert (
        "extensions/models/thing-writer/model.ts:42:3" in result.diagnostics
    )
    assert "require-await" in result.diagnostics
    assert "swamp extension fmt" in result.diagnostics
    assert str(repository_directory) not in result.diagnostics
    assert "mgreten" not in result.diagnostics
    assert "acme-secret-project" not in result.diagnostics


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


# --- method/workflow inputs ---------------------------------------------------


def test_build_command_appends_input_pairs_as_discrete_argv_elements() -> None:
    """Each ``--input name=value`` pair is its own argv element.

    The git-workspace model takes its target repository as a method argument,
    so a tool that cannot pass inputs cannot drive it at all.
    """
    command = build_command(
        "model_method_run",
        "unifi-release-safety-repo",
        "status",
        inputs={"project": "owner/repo", "localPath": "/opt/data/repo"},
    )
    assert command[:4] == (
        "swamp",
        "model",
        "method",
        "run",
    )
    assert "--input" in command
    assert "project=owner/repo" in command
    assert "localPath=/opt/data/repo" in command
    assert command[-1] == "--json"


def test_input_values_containing_shell_metacharacters_stay_one_argv_element() -> None:
    command = build_command(
        "model_method_run",
        "model",
        "method",
        inputs={"message": "fix; rm -rf / && echo $(whoami)"},
    )
    assert "message=fix; rm -rf / && echo $(whoami)" in command


def test_build_command_rejects_inputs_for_commands_that_do_not_accept_them() -> None:
    with pytest.raises(ValueError):
        build_command("model_search", inputs={"project": "owner/repo"})


@pytest.mark.parametrize(
    "name",
    ["--flag", "has space", "", "1leading", "semi;colon", "new\nline"],
)
def test_build_command_rejects_invalid_input_names(name: str) -> None:
    with pytest.raises(ValueError):
        build_command("model_method_run", "m", "meth", inputs={name: "value"})


def test_build_command_rejects_input_values_containing_nul() -> None:
    with pytest.raises(ValueError):
        build_command("model_method_run", "m", "meth", inputs={"a": "b\x00c"})


def test_build_command_renders_scalar_input_values() -> None:
    command = build_command(
        "model_method_run", "m", "meth", inputs={"n": 3, "flag": True}
    )
    assert "n=3" in command
    assert "flag=true" in command


def test_build_command_omits_input_arguments_when_inputs_is_empty() -> None:
    assert build_command("model_method_run", "m", "meth", inputs={}) == (
        "swamp",
        "model",
        "method",
        "run",
        "m",
        "meth",
        "--json",
    )


# --- diagnostics scrubber -------------------------------------------------


def test_scrub_diagnostics_relativizes_the_repository_root(tmp_path: Path) -> None:
    repository_directory = tmp_path / "mgreten" / "acme-secret-project"
    text = (
        f"{repository_directory}/models/thing.yaml:5:1 - error: bad indent\n"
    )

    scrubbed = _scrub_diagnostics(text, str(repository_directory))

    assert scrubbed == "models/thing.yaml:5:1 - error: bad indent\n"
    assert "mgreten" not in scrubbed
    assert "acme-secret-project" not in scrubbed


def test_scrub_diagnostics_replaces_a_bare_repository_root_mention(
    tmp_path: Path,
) -> None:
    repository_directory = tmp_path / "mgreten" / "acme-secret-project"
    text = f"fatal: could not open repository at {repository_directory}"

    scrubbed = _scrub_diagnostics(text, str(repository_directory))

    assert scrubbed == "fatal: could not open repository at <repo>"


def test_scrub_diagnostics_redacts_unrelated_absolute_paths_wholesale(
    tmp_path: Path,
) -> None:
    repository_directory = tmp_path / "repo"
    repository_directory.mkdir()
    text = (
        "cache miss at /opt/data/swamp-hub/.swamp/bundles/e9c5/@acme/secret/model.js"
    )

    scrubbed = _scrub_diagnostics(text, str(repository_directory))

    assert scrubbed == "cache miss at <path>"
    assert "secret" not in scrubbed


def test_scrub_diagnostics_does_not_leak_a_sibling_path_sharing_the_root_as_a_prefix(
    tmp_path: Path,
) -> None:
    # A repository root is a literal string prefix of an unrelated sibling
    # directory's name (e.g. "acme" vs. "acme-secret-internal"). A naive
    # substring replace would strip only the "acme" portion and leave the
    # rest — "secret-internal" — exposed. The boundary check must decline to
    # touch this case at all, deferring to the wholesale absolute-path
    # catch-all instead.
    repository_directory = tmp_path / "acme"
    repository_directory.mkdir()
    sibling_path = tmp_path / "acme-secret-internal" / "file.txt"
    text = f"see also {sibling_path}"

    scrubbed = _scrub_diagnostics(text, str(repository_directory))

    assert scrubbed == "see also <path>"
    assert "secret" not in scrubbed
    assert str(repository_directory) not in scrubbed


def test_scrub_diagnostics_escapes_regex_metacharacters_in_the_repository_root(
    tmp_path: Path,
) -> None:
    # The repository root is substituted via a regex built from the path
    # string, not a plain substring replace, so a root containing a regex
    # metacharacter (a real, common case: "." in a directory name like
    # "my.repo") must be escaped rather than interpreted as a pattern.
    repository_directory = tmp_path / "my.repo"
    repository_directory.mkdir()
    text = f"{repository_directory}/models/thing.yaml:1:1 - error"

    scrubbed = _scrub_diagnostics(text, str(repository_directory))

    assert scrubbed == "models/thing.yaml:1:1 - error"
    assert "my.repo" not in scrubbed


def test_scrub_diagnostics_redacts_every_absolute_path_with_no_known_root() -> None:
    text = "error at /Users/mgreten/git/acme-secret-project/model.ts:1:1"

    scrubbed = _scrub_diagnostics(text, None)

    assert scrubbed == "error at <path>"


def test_scrub_diagnostics_does_not_disturb_relative_paths() -> None:
    text = "models/thing.yaml:5:1 - error: bad indent"

    assert _scrub_diagnostics(text, None) == text


def test_scrub_diagnostics_returns_empty_string_for_empty_or_non_string_input() -> None:
    assert _scrub_diagnostics("", "/some/repo") == ""
    assert _scrub_diagnostics(None, "/some/repo") == ""  # type: ignore[arg-type]
