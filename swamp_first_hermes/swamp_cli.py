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

# Commands that reach the network or run user code need far longer than the
# default. A publish observed at ~9s against a 10s budget would time out after
# the registry had already been written, so these are sized well above the
# observed durations rather than just above them.
_COMMAND_TIMEOUT_SECONDS: dict[str, float] = {
    "extension_push": 180.0,
    "extension_pull": 120.0,
    "extension_quality": 120.0,
    "extension_search": 60.0,
    "model_method_run": 300.0,
    "workflow_run": 600.0,
    "model_validate": 60.0,
    "workflow_validate": 60.0,
}

# Optional deployment default for the Swamp repository the CLI runs against,
# read at call time. Hermes' own working directory is never a Swamp repository,
# so without this every tool call would require the caller to supply
# ``repository_path`` explicitly.
REPOSITORY_PATH_ENV_VAR = "SWAMP_FIRST_REPO_PATH"

# Distinguishes "caller said nothing about timeout" from an explicit ``None``,
# which remains an invalid value rather than a request for the default.
_UNSET_TIMEOUT: Any = object()


def default_repository_path() -> str | None:
    """Return the configured default repository path, if one is usable."""
    configured = os.environ.get(REPOSITORY_PATH_ENV_VAR, "").strip()
    if configured and os.path.isdir(configured):
        return configured
    return None


def _parse_json_documents(text: str) -> Any | None:
    """Return the last JSON document in ``text``, or ``None`` if there is none.

    Some Swamp commands write more than one pretty-printed JSON document to
    stdout for a single invocation — ``extension push`` emits a package summary
    followed by the actual result. A plain ``json.loads`` over the whole buffer
    raises ``Extra data`` on exactly the successful runs, so decode
    document-by-document and treat the final one as authoritative.
    """
    if not isinstance(text, str):
        return None
    decoder = json.JSONDecoder()
    documents: list[Any] = []
    index = 0
    length = len(text)
    while index < length:
        while index < length and text[index].isspace():
            index += 1
        if index >= length:
            break
        try:
            document, index = decoder.raw_decode(text, index)
        except ValueError:
            return None
        documents.append(document)
    return documents[-1] if documents else None


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
    timeout: int | float | None = _UNSET_TIMEOUT,
) -> SwampCliResult:
    """Run an allowed command and return its parsed JSON result.

    When ``repository_path`` is omitted, the deployment default from
    ``SWAMP_FIRST_REPO_PATH`` is used; if that is unset or not a directory, the
    subprocess inherits the current working directory. The repository path is
    passed only as ``cwd``; it is never interpolated into a command string. An
    explicitly supplied path must name an existing directory, and timeout must
    be a positive non-boolean ``int`` or ``float``. ``positional_arguments``
    are validated by ``build_command`` before any subprocess is started.

    When the CLI exits non-zero but still writes a JSON body, that body is
    returned as ``data`` alongside ``error="process_error"``. Swamp reports
    real, actionable rejections this way (an unknown model name, a duplicate
    version); discarding them makes a correctly refused operation and a broken
    environment indistinguishable to the caller.
    """
    if timeout is _UNSET_TIMEOUT:
        timeout = _COMMAND_TIMEOUT_SECONDS.get(command, DEFAULT_TIMEOUT_SECONDS)

    repository_directory: str | None = None
    if repository_path is None:
        repository_directory = default_repository_path()
    else:
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
        return SwampCliResult(
            ok=False,
            data=_parse_json_documents(completed.stdout or ""),
            error="process_error",
        )

    data = _parse_json_documents(completed.stdout or "")
    if data is None:
        return SwampCliResult(ok=False, data=None, error="malformed_json")

    return SwampCliResult(ok=True, data=data, error=None)
