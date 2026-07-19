"""A minimal, read-only adapter for the locally installed Swamp CLI."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
import subprocess
from typing import Any


# Each public command maps to fixed CLI arguments. Do not accept caller-supplied
# arguments: keeping this mapping closed prevents command injection and limits
# this adapter to read-only operations.
_COMMAND_ARGUMENTS: dict[str, tuple[str, ...]] = {
    "model_search": ("model", "search"),
    "workflow_search": ("workflow", "search"),
}
ALLOWED_COMMANDS = frozenset(_COMMAND_ARGUMENTS)
DEFAULT_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True, slots=True)
class SwampCliResult:
    """The normalized result of a Swamp CLI invocation.

    ``error`` is one of ``None``, ``command_not_allowed``,
    ``invalid_repository_path``, ``invalid_timeout``, ``process_error``,
    ``malformed_json``, ``executable_not_found``, ``execution_error``, or
    ``timeout``. Error details and process output are intentionally omitted so
    local environment values cannot escape through this boundary.
    """

    ok: bool
    data: Any | None
    error: str | None


def build_command(command: str) -> tuple[str, ...]:
    """Build the fixed JSON-output argument vector for an allowed command."""
    try:
        command_arguments = _COMMAND_ARGUMENTS[command]
    except (KeyError, TypeError) as error:
        raise ValueError("Swamp command is not allowed") from error
    return ("swamp", *command_arguments, "--json")


def run_swamp_command(
    command: str,
    *,
    repository_path: str | os.PathLike[str] | None = None,
    timeout: int | float = DEFAULT_TIMEOUT_SECONDS,
) -> SwampCliResult:
    """Run an allowed read-only command and return its parsed JSON result.

    When ``repository_path`` is omitted, the subprocess inherits the current
    working directory. The repository path is passed only as ``cwd``; it is
    never interpolated into a command string. An explicitly supplied path must
    name an existing directory, and timeout must be a positive non-boolean
    ``int`` or ``float``.
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

    try:
        arguments = build_command(command)
    except ValueError:
        return SwampCliResult(ok=False, data=None, error="command_not_allowed")

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
