"""A minimal, read-only adapter for the locally installed Swamp CLI."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
import subprocess
from typing import Any


# Each public command maps to a fixed CLI prefix plus a declared arity of
# caller-supplied positional arguments. Positional arguments are validated and
# passed as discrete argv elements — never interpolated into a command
# string — so the closed mapping still prevents command injection even for
# commands that accept caller-supplied values.
_COMMAND_ARGUMENTS: dict[str, tuple[str, ...]] = {
    "model_search": ("model", "search"),
    "workflow_search": ("workflow", "search"),
    "model_create": ("model", "create"),
    "model_validate": ("model", "validate"),
    "model_method_run": ("model", "method", "run"),
    "workflow_create": ("workflow", "create"),
    "workflow_validate": ("workflow", "validate"),
    "workflow_run": ("workflow", "run"),
    "extension_search": ("extension", "search"),
    "extension_pull": ("extension", "pull"),
    "extension_quality": ("extension", "quality"),
    "extension_push": ("extension", "push"),
}
ALLOWED_COMMANDS = frozenset(_COMMAND_ARGUMENTS)

# (minimum, maximum) count of caller-supplied positional arguments each
# command accepts, appended after its fixed prefix and before ``--json``.
_COMMAND_POSITIONAL_ARITY: dict[str, tuple[int, int]] = {
    "model_search": (0, 0),
    "workflow_search": (0, 0),
    "model_create": (2, 2),
    "model_validate": (0, 1),
    "model_method_run": (2, 2),
    "workflow_create": (1, 1),
    "workflow_validate": (0, 1),
    "workflow_run": (1, 1),
    "extension_search": (0, 1),
    "extension_pull": (1, 1),
    "extension_quality": (1, 1),
    "extension_push": (1, 1),
}
DEFAULT_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True, slots=True)
class SwampCliResult:
    """The normalized result of a Swamp CLI invocation.

    ``error`` is one of ``None``, ``command_not_allowed``, ``invalid_argument``,
    ``invalid_repository_path``, ``invalid_timeout``, ``process_error``,
    ``malformed_json``, ``executable_not_found``, ``execution_error``, or
    ``timeout``. Error details and process output are intentionally omitted so
    local environment values cannot escape through this boundary.
    """

    ok: bool
    data: Any | None
    error: str | None


def _is_safe_positional_argument(value: object) -> bool:
    """A caller-supplied positional argument safe to pass straight to argv.

    Rejects anything that is not a non-empty string, contains an embedded NUL
    byte, or begins with ``-`` (which would let a value be misread as a flag
    by the wrapped Swamp CLI rather than a positional argument).
    """
    return (
        isinstance(value, str)
        and value != ""
        and "\x00" not in value
        and not value.startswith("-")
    )


def build_command(command: str, *positional_arguments: str) -> tuple[str, ...]:
    """Build the fixed JSON-output argument vector for an allowed command.

    ``positional_arguments`` are caller-supplied values appended after the
    command's fixed prefix. Each command declares exactly how many it accepts
    in ``_COMMAND_POSITIONAL_ARITY``. No value is ever concatenated into a
    shell string; every element becomes one discrete argv entry passed
    directly to ``subprocess.run``.
    """
    try:
        command_arguments = _COMMAND_ARGUMENTS[command]
        minimum_arity, maximum_arity = _COMMAND_POSITIONAL_ARITY[command]
    except (KeyError, TypeError) as error:
        raise ValueError("Swamp command is not allowed") from error
    if not (minimum_arity <= len(positional_arguments) <= maximum_arity):
        raise ValueError("Swamp command received the wrong number of arguments")
    if not all(_is_safe_positional_argument(value) for value in positional_arguments):
        raise ValueError("Swamp command received an invalid argument")
    return ("swamp", *command_arguments, *positional_arguments, "--json")


def run_swamp_command(
    command: str,
    *positional_arguments: str,
    repository_path: str | os.PathLike[str] | None = None,
    timeout: int | float = DEFAULT_TIMEOUT_SECONDS,
) -> SwampCliResult:
    """Run an allowed command and return its parsed JSON result.

    When ``repository_path`` is omitted, the subprocess inherits the current
    working directory. The repository path is passed only as ``cwd``; it is
    never interpolated into a command string. An explicitly supplied path must
    name an existing directory, and timeout must be a positive non-boolean
    ``int`` or ``float``. ``positional_arguments`` are validated by
    ``build_command`` before any subprocess is started.
    """
    repository_directory: str | None = None
    if repository_path is not None:
        try:
            repository_directory = os.fspath(repository_path)
            is_repository_directory = isinstance(
                repository_directory, str
            ) and os.path.isdir(repository_directory)
        except (OSError, TypeError, ValueError):
            is_repository_directory = False
        if not is_repository_directory:
            return SwampCliResult(
                ok=False, data=None, error="invalid_repository_path"
            )

    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or timeout <= 0
        or not math.isfinite(timeout)
    ):
        return SwampCliResult(ok=False, data=None, error="invalid_timeout")

    if command not in ALLOWED_COMMANDS:
        return SwampCliResult(ok=False, data=None, error="command_not_allowed")

    try:
        arguments = build_command(command, *positional_arguments)
    except ValueError:
        return SwampCliResult(ok=False, data=None, error="invalid_argument")

    try:
        completed = subprocess.run(
            list(arguments),
            cwd=repository_directory,
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return SwampCliResult(ok=False, data=None, error="timeout")
    except FileNotFoundError:
        return SwampCliResult(ok=False, data=None, error="executable_not_found")
    except OSError:
        return SwampCliResult(ok=False, data=None, error="execution_error")

    if completed.returncode != 0:
        return SwampCliResult(ok=False, data=None, error="process_error")

    try:
        data = json.loads(completed.stdout)
    except (TypeError, json.JSONDecodeError):
        return SwampCliResult(ok=False, data=None, error="malformed_json")

    return SwampCliResult(ok=True, data=data, error=None)
