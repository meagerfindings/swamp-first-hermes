"""A minimal, read-only adapter for the locally installed Swamp CLI."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
import math
import os
import re
import subprocess
from typing import Any


# Each public command maps to a fixed CLI prefix plus a declared arity of
# caller-supplied positional arguments. Positional arguments are validated and
# passed as discrete argv elements — never interpolated into a command
# string — so the closed mapping still prevents command injection even for
# commands that accept caller-supplied values.
_COMMAND_ARGUMENTS: dict[str, tuple[str, ...]] = {
    "model_search": ("model", "search"),
    "model_type_search": ("model", "type", "search"),
    "model_type_describe": ("model", "type", "describe"),
    "workflow_search": ("workflow", "search"),
    "model_create": ("model", "create"),
    "model_validate": ("model", "validate"),
    "model_method_run": ("model", "method", "run"),
    "workflow_create": ("workflow", "create"),
    "workflow_validate": ("workflow", "validate"),
    "workflow_run": ("workflow", "run"),
    "extension_search": ("extension", "search"),
    "extension_info": ("extension", "info"),
    "extension_pull": ("extension", "pull"),
    "extension_quality": ("extension", "quality"),
    "extension_fmt": ("extension", "fmt"),
    "extension_push": ("extension", "push"),
}
ALLOWED_COMMANDS = frozenset(_COMMAND_ARGUMENTS)

# (minimum, maximum) count of caller-supplied positional arguments each
# command accepts, appended after its fixed prefix and before ``--json``.
_COMMAND_POSITIONAL_ARITY: dict[str, tuple[int, int]] = {
    "model_search": (0, 0),
    "model_type_search": (0, 1),
    "model_type_describe": (1, 1),
    "workflow_search": (0, 0),
    "model_create": (2, 2),
    "model_validate": (0, 1),
    "model_method_run": (2, 2),
    "workflow_create": (1, 1),
    "workflow_validate": (0, 1),
    "workflow_run": (1, 1),
    "extension_search": (0, 1),
    "extension_info": (1, 1),
    "extension_pull": (1, 1),
    "extension_quality": (1, 1),
    "extension_fmt": (1, 1),
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
    "extension_fmt": 60.0,
    "extension_search": 60.0,
    "extension_info": 60.0,
    "model_type_search": 60.0,
    "model_type_describe": 60.0,
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
    ``process_failed``, ``malformed_json``, ``executable_not_found``,
    ``execution_error``, or ``timeout``. A non-zero exit that still wrote an
    actionable JSON result body is ``process_error`` (the body is in ``data``);
    a non-zero exit with no result body — the swamp process itself failing, e.g.
    a broken extension bundle or environment — is ``process_failed`` (``data``
    is ``None``). Error details and raw process output are intentionally omitted
    so local environment values cannot escape through this boundary; only the
    failure class is surfaced, never stderr text — with one narrow, explicit
    exception: ``diagnostics``.

    ``diagnostics`` is ``None`` for every command except the small allowlist in
    ``_DIAGNOSTIC_COMMANDS`` (the authoring/validate/quality/fmt commands), and
    even there it is populated only on the ``process_failed`` path (a non-zero
    exit with no JSON body). When set, it is stderr with every absolute
    filesystem path scrubbed — see ``_scrub_diagnostics`` — so a lint rule,
    file:line, and fix hint stay actionable without ever surfacing where the
    repository lives on disk. Every other command, and every other failure
    path, keeps stderr fully withheld exactly as before.
    """

    ok: bool
    data: Any | None
    error: str | None
    diagnostics: str | None = None


# The narrow, explicit allowlist of authoring/diagnostic commands for which
# ``run_swamp_command`` will surface a scrubbed ``diagnostics`` string on the
# ``process_failed`` path. These are exactly the commands whose whole purpose
# is to report actionable problems in caller-authored source (a formatting
# diff, a lint rule with file:line, a quality-rubric failure) — and whose own
# error text can tell the agent to run a sibling command it then has no way to
# act on if stderr stays withheld. No other command is affected: every command
# not in this set keeps the original, unconditional stderr withholding.
_DIAGNOSTIC_COMMANDS = frozenset(
    {
        "model_validate",
        "workflow_validate",
        "extension_quality",
        "extension_fmt",
        # Execution commands: a failed run's stderr carries the actionable cause
        # (a missing/misplaced input, a schema violation, a model-code exception)
        # that the agent needs to fix its own definition — scrubbed of paths just
        # like the authoring commands.
        "model_method_run",
        "workflow_run",
    }
)

# Matches an absolute filesystem path token: a ``/`` not preceded by a word
# character, ``.``, or another ``/`` (so it only matches where a path token
# actually starts — the start of the string, after whitespace, or after
# punctuation like ``(`` or ``:`` — never mid-way through an already-relative
# path such as ``models/thing.ts``), followed by a run of non-whitespace.
_ABSOLUTE_PATH_TOKEN_PATTERN = re.compile(r"(?<![\w./])/\S+")
_ABSOLUTE_PATH_PLACEHOLDER = "<path>"
_REPOSITORY_ROOT_PLACEHOLDER = "<repo>"


def _repository_root_candidates(repository_directory: str | None) -> tuple[str, ...]:
    """Return the absolute forms of the repository root to relativize against.

    Includes the exact directory Swamp's subprocess ran in, plus its
    ``abspath`` and ``realpath`` forms, since a diagnostic tool may print any
    of them depending on how it resolved the path internally (for example
    through a symlink). Only absolute forms are returned — a caller-supplied
    ``repository_directory`` that was itself relative (e.g. ``"."``) is not
    used verbatim, since a short relative string is far more likely to
    coincidentally reappear elsewhere in diagnostic text than a real absolute
    path is. Ordered longest-first so the most specific form is substituted
    before a shorter one could partially match.
    """
    if not repository_directory:
        return ()
    candidates: list[str] = []
    for candidate in (
        repository_directory,
        os.path.abspath(repository_directory),
        os.path.realpath(repository_directory),
    ):
        if not os.path.isabs(candidate):
            continue
        stripped = candidate.rstrip("/")
        if stripped and stripped not in candidates:
            candidates.append(stripped)
    return tuple(sorted(candidates, key=len, reverse=True))


# A repository-root match must not be followed by another path/identifier
# character (letter, digit, ``_``, or ``-``) — otherwise ``/Users/x/y`` would
# wrongly match as a prefix of an unrelated sibling path like
# ``/Users/x/yz/secret/file`` (leaking ``secret``) rather than leaving it to
# the wholesale catch-all below. A literal ``/`` immediately after the root
# already satisfies this (``/`` is not in the excluded class), so the same
# boundary works for both "root continues as a relative path" and "root is a
# bare mention" without needing two different lookaheads.
_ROOT_BOUNDARY = r"(?![\w\-])"


def _scrub_diagnostics(stderr_text: str, repository_directory: str | None) -> str:
    """Return ``stderr_text`` with local filesystem paths scrubbed.

    Only ever reached for the narrow ``_DIAGNOSTIC_COMMANDS`` allowlist, and
    only on the no-JSON-body failure path. Two passes:

    1. Every known absolute form of the repository root Swamp actually ran in
       is relativized in place: ``<root>/relative/file.ts:42:3`` becomes
       ``relative/file.ts:42:3`` (a bare mention of the root with no
       trailing path becomes the placeholder ``<repo>``). This is the
       useful, intended case — a lint diagnostic's file:line, rule name, and
       fix hint survive untouched. Each substitution is boundary-checked (see
       ``_ROOT_BOUNDARY``) so the root can only match a complete path
       component, never a prefix of an unrelated longer one.
    2. Any absolute path that survives that pass — a different sensitive
       location entirely (a bundle cache path, a temp directory, a symlinked
       ancestor the first pass did not anticipate, or an unrelated sibling
       path the boundary check in step 1 correctly declined to touch), or any
       path at all when no repository root is known — is replaced wholesale
       with an opaque ``<path>`` placeholder. It is never partially
       relativized, because there is no way to tell safe relative structure
       from a sensitive identifier inside a path this function does not
       recognize as the repository root.
    """
    if not isinstance(stderr_text, str) or stderr_text == "":
        return ""

    scrubbed = stderr_text
    for root in _repository_root_candidates(repository_directory):
        escaped_root = re.escape(root)
        scrubbed = re.sub(escaped_root + r"/", "", scrubbed)
        scrubbed = re.sub(escaped_root + _ROOT_BOUNDARY, _REPOSITORY_ROOT_PLACEHOLDER, scrubbed)

    return _ABSOLUTE_PATH_TOKEN_PATTERN.sub(_ABSOLUTE_PATH_PLACEHOLDER, scrubbed)


# Commands that accept caller-supplied ``--input name=value`` pairs. Model
# methods and workflows declare their own argument schemas, so the values are
# opaque here; each pair becomes one discrete argv element and is never
# concatenated into a shell string.
_COMMANDS_ACCEPTING_INPUTS = frozenset({"model_method_run", "workflow_run"})

# An input name is restricted to the shape Swamp's own argument names take.
# The value is left unconstrained apart from rejecting NUL, since it may
# legitimately contain paths, URLs, JSON, or spaces.
_INPUT_NAME_PATTERN = re.compile(r"\A[A-Za-z_][A-Za-z0-9_.\-]*\Z")


def _build_input_arguments(
    inputs: Mapping[str, object] | None,
) -> tuple[str, ...]:
    """Return validated ``--input name=value`` argv elements."""
    if not inputs:
        return ()
    if not isinstance(inputs, Mapping):
        raise ValueError("Swamp inputs must be a mapping")
    arguments: list[str] = []
    for name, value in inputs.items():
        if not isinstance(name, str) or not _INPUT_NAME_PATTERN.match(name):
            raise ValueError("Swamp input name is invalid")
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        elif isinstance(value, (int, float)):
            rendered = str(value)
        elif isinstance(value, str):
            rendered = value
        else:
            raise ValueError("Swamp input value is invalid")
        if "\x00" in rendered:
            raise ValueError("Swamp input value is invalid")
        arguments.extend(("--input", f"{name}={rendered}"))
    return tuple(arguments)


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


def build_command(
    command: str,
    *positional_arguments: str,
    inputs: Mapping[str, object] | None = None,
) -> tuple[str, ...]:
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
    if inputs and command not in _COMMANDS_ACCEPTING_INPUTS:
        raise ValueError("Swamp command does not accept inputs")
    input_arguments = _build_input_arguments(inputs)
    return (
        "swamp",
        *command_arguments,
        *positional_arguments,
        *input_arguments,
        "--json",
    )


def run_swamp_command(
    command: str,
    *positional_arguments: str,
    repository_path: str | os.PathLike[str] | None = None,
    timeout: int | float | None = _UNSET_TIMEOUT,
    inputs: Mapping[str, object] | None = None,
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
    environment indistinguishable to the caller. When the CLI exits non-zero
    with no JSON body — it crashed or fatally errored (a broken extension
    bundle, a missing export, an unusable environment) and wrote only a
    stderr diagnostic — the result is ``error="process_failed"`` with
    ``data=None``. That diagnostic is not surfaced for most commands (it can
    carry absolute local paths and private identifiers), but the distinct code
    lets the caller tell an environment/tooling failure apart from a plain
    rejection instead of seeing an opaque ``process_error`` for both.

    For the narrow allowlist in ``_DIAGNOSTIC_COMMANDS`` — ``model_validate``,
    ``workflow_validate``, ``extension_quality``, and ``extension_fmt`` — this
    same ``process_failed`` path additionally populates ``diagnostics`` with
    stderr run through ``_scrub_diagnostics``, so the file:line, lint rule, and
    fix hint an agent needs to self-correct its own authoring loop are
    visible, with every absolute filesystem path scrubbed to a repository-
    relative path or an opaque placeholder. Every command outside that
    allowlist leaves ``diagnostics`` as ``None`` and keeps stderr fully
    withheld, exactly as before.
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
        arguments = build_command(command, *positional_arguments, inputs=inputs)
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
        body = _parse_json_documents(completed.stdout or "")
        # A non-zero exit with an actionable JSON body is a real rejection
        # (unknown model, duplicate version) — surface the body. A non-zero
        # exit with no body is the swamp process itself failing (a crash, a
        # broken bundle); mark it distinctly so it is not mistaken for a
        # rejection. stderr stays withheld either way (boundary) — except for
        # the narrow diagnostic-command allowlist, where a scrubbed version of
        # it is surfaced in ``diagnostics`` so the caller can self-correct.
        if body is None:
            diagnostics = None
            if command in _DIAGNOSTIC_COMMANDS and completed.stderr:
                diagnostics = _scrub_diagnostics(completed.stderr, repository_directory) or None
            return SwampCliResult(
                ok=False, data=None, error="process_failed", diagnostics=diagnostics
            )
        return SwampCliResult(ok=False, data=body, error="process_error")

    data = _parse_json_documents(completed.stdout or "")
    if data is None:
        return SwampCliResult(ok=False, data=None, error="malformed_json")

    return SwampCliResult(ok=True, data=data, error=None)
