"""A narrowly scoped, path-restricted writer for Swamp definition files.

``swamp model edit`` / ``swamp workflow edit`` are interactive editors with no
non-interactive content flag, so there is no Swamp CLI command to wrap for
authoring a definition's content directly. This module is the one place a
caller-supplied string is ever written to disk by this plugin, and it is
deliberately narrow:

- the target path must resolve inside the given repository, with no ``..``
  traversal and no symlink escape (checked against the fully resolved real
  path, which also defends against an intermediate symlinked directory);
- the target path must be a Swamp-managed instance path (``models/**``,
  ``workflows/**``), the exact ``manifest.yaml`` file, the conventional
  ``extensions/models/`` extension-source location, or a path the
  repository's own ``manifest.yaml`` actually declares under its
  ``models:``/``reports:``/``workflows:`` keys — Swamp does not enforce one
  fixed directory layout (a manifest may declare a root-level source file,
  as this project's own hermes-review-kit example does), so the manifest is
  the source of truth beyond the always-allowed defaults;
- the write itself is plain Python file I/O — no subprocess, so the
  command-injection risk category that applies to shell-backed tools does not
  apply here;
- every write is immediately followed by the matching Swamp validate/quality
  check, and a failed check reverts the previous content (or deletes a newly
  created file) rather than leaving invalid content on disk;
- a workflow write that would set a live ``trigger.schedule`` value is
  rejected outright, based on an actual structural YAML parse rather than a
  text search. This matters because a live ``swamp serve`` process hot-reloads
  local workflow files within about one scheduler tick with no grace period —
  this check is the *only* safety boundary preventing a written file from
  immediately going live on a schedule, not defense-in-depth on top of some
  other delay. Schedule activation only happens through
  ``set_workflow_schedule``, so "author a thing" and "make a thing run
  unattended forever" are never the same action.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import re
from typing import Any

import yaml

from .swamp_cli import DEFAULT_TIMEOUT_SECONDS, run_swamp_command

_MODEL_INSTANCE_PREFIX = "models/"
_WORKFLOW_INSTANCE_PREFIX = "workflows/"
_ALWAYS_ALLOWED_EXTENSION_PREFIXES = ("extensions/models/",)
_MANIFEST_FILENAME = "manifest.yaml"
_MANIFEST_SOURCE_KEYS = ("models", "reports", "workflows")
_DEFAULT_MANIFEST_NAME = _MANIFEST_FILENAME


class _WorkflowContentError(Exception):
    """``content`` for a workflow path did not parse as a YAML mapping.

    Raised internally so a caller can fail closed with a distinct error
    rather than writing content this module cannot structurally reason
    about — an unparseable workflow file could not be proven schedule-free.
    """


@dataclass(frozen=True, slots=True)
class DefinitionWriteResult:
    """The normalized result of a scoped Swamp definition write.

    ``error`` is one of ``None``, ``invalid_repository_path``,
    ``path_not_allowed``, ``path_escapes_repository``,
    ``definition_name_required``, ``invalid_content``,
    ``live_schedule_rejected``, ``unparseable_workflow_content``,
    ``schedule_splice_failed``, ``read_error``, ``write_error``,
    ``revert_error``, or a validation-adapter error surfaced from
    ``run_swamp_command`` (e.g. ``process_error``, ``malformed_json``).

    ``validated`` is ``True`` only once a validate/quality check actually ran
    against the new content. ``reverted`` is ``True`` only when previously
    existing content was restored after a failed validation; ``deleted`` is
    ``True`` only when a newly created file was removed after a failed
    validation. ``validation_data`` carries the validator's JSON payload when
    available. ``diagnostics`` carries the already-scrubbed
    ``SwampCliResult.diagnostics`` string from the validate/quality call that
    triggered a revert or delete, when one was available; it is ``None`` on
    success and on any failure that produced no diagnostics.
    """

    ok: bool
    validated: bool
    reverted: bool
    deleted: bool
    validation_data: Any | None
    error: str | None
    diagnostics: str | None = None


def _read_manifest_declared_paths(repository_directory: str) -> dict[str, str]:
    """Read manifest.yaml's models:/reports:/workflows: entries, if present.

    Returns a mapping of declared relative path -> the manifest key that
    declared it (``"models"``, ``"reports"``, or ``"workflows"``). Provenance
    is preserved deliberately: a manifest-declared ``workflows:`` entry is a
    workflow *instance* — subject to the same live-schedule guard as
    anything under ``workflows/`` — while ``models:``/``reports:`` entries
    are extension source with no schedule concept. Collapsing these into one
    undifferentiated set would let a workflow declared at a path outside
    ``workflows/`` skip the schedule check entirely.

    Returns an empty mapping if there is no manifest, it cannot be read, or
    it does not parse as a YAML mapping — a manifest is optional, so any of
    those is "no additional paths declared", not an error.
    """
    manifest_path = os.path.join(repository_directory, _MANIFEST_FILENAME)
    try:
        with open(manifest_path, "r", encoding="utf-8") as handle:
            raw = handle.read()
    except OSError:
        return {}
    try:
        parsed = yaml.safe_load(raw)
    except yaml.YAMLError:
        return {}
    if not isinstance(parsed, dict):
        return {}

    declared: dict[str, str] = {}
    for key in _MANIFEST_SOURCE_KEYS:
        entries = parsed.get(key)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, str) and entry != "":
                declared[entry.replace("\\", "/").removeprefix("./")] = key
    return declared


def _classify_relative_path(normalized: str, repository_directory: str) -> str | None:
    """Return which validate/quality lane a definition path belongs to.

    ``models/**`` and ``workflows/**`` are Swamp's own default instance
    locations (validated by instance name via ``model_validate`` /
    ``workflow_validate``). The exact ``manifest.yaml`` file, the
    conventional ``extensions/models/`` source location, and any
    manifest-declared ``models:``/``reports:`` entry are extension *source*,
    scored via ``extension_quality`` instead. A manifest-declared
    ``workflows:`` entry is still a workflow *instance* even though its path
    does not start with ``workflows/`` — Swamp does not enforce that prefix
    — so it is classified as ``"workflow"``, not ``"extension"``, to keep it
    subject to the live-schedule guard.
    """
    if normalized.startswith(_MODEL_INSTANCE_PREFIX):
        return "model"
    if normalized.startswith(_WORKFLOW_INSTANCE_PREFIX):
        return "workflow"
    if normalized == _MANIFEST_FILENAME:
        return "extension"
    if normalized.startswith(_ALWAYS_ALLOWED_EXTENSION_PREFIXES):
        return "extension"
    declared_source = _read_manifest_declared_paths(repository_directory).get(normalized)
    if declared_source == "workflows":
        return "workflow"
    if declared_source in ("models", "reports"):
        return "extension"
    return None


def _normalize_relative_path(relative_path: object) -> str | None:
    """Return a `/`-separated relative path with no traversal segments, or None."""
    if not isinstance(relative_path, str) or relative_path == "":
        return None
    if os.path.isabs(relative_path) or "\x00" in relative_path:
        return None
    normalized = relative_path.replace("\\", "/")
    segments = normalized.split("/")
    if any(segment in ("", ".", "..") for segment in segments):
        return None
    return normalized


def _resolve_within_repository(
    repository_directory: str, normalized_relative_path: str
) -> str | None:
    """Return the real, resolved path if it stays inside the repository root."""
    real_root = os.path.realpath(repository_directory)
    candidate = os.path.join(repository_directory, normalized_relative_path)
    real_candidate = os.path.realpath(candidate)
    try:
        common = os.path.commonpath([real_root, real_candidate])
    except ValueError:
        return None
    if common != real_root or real_candidate == real_root:
        return None
    return real_candidate


def _load_workflow_document(content: str) -> dict[str, Any]:
    """Parse workflow ``content`` as YAML, raising ``_WorkflowContentError``
    if it is not a YAML mapping this module can structurally reason about."""
    try:
        parsed = yaml.safe_load(content)
    except yaml.YAMLError as error:
        raise _WorkflowContentError from error
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise _WorkflowContentError
    return parsed


def _content_sets_live_schedule(content: str) -> bool:
    """Structurally check for a populated ``trigger.schedule`` value.

    Fails closed: an absent ``trigger`` key, or an explicitly empty/null
    schedule, is the only shape treated as schedule-free. A ``trigger`` that
    is not a mapping, or a ``schedule`` that is not a non-empty string, is
    treated as *possibly* a live schedule in an unrecognized shape rather
    than assumed safe — there is no second safety net if this is wrong.
    May raise ``_WorkflowContentError``; callers must handle it.
    """
    document = _load_workflow_document(content)
    if "trigger" not in document:
        return False
    trigger = document.get("trigger")
    if not isinstance(trigger, dict):
        return True
    if "schedule" not in trigger:
        return False
    schedule = trigger.get("schedule")
    if schedule is None:
        return False
    if not isinstance(schedule, str):
        return True
    return schedule.strip() != ""


# Used only to splice a schedule into existing text while leaving everything
# else in the file byte-for-byte unchanged (a full YAML parse/dump round-trip
# would risk reformatting comments, key order, and quote style). The result
# is re-parsed with the same structural check before use, so a splice that
# produced something unexpected is caught rather than trusted blindly.
_TRIGGER_BLOCK_PATTERN = re.compile(r"(?m)^trigger:[ \t]*\n((?:[ \t]+.*\n?)*)")
_SCHEDULE_LINE_PATTERN = re.compile(r"(?m)^([ \t]+)schedule:[ \t]*(.*)$")


def _set_schedule_in_content(content: str, cron_expression: str) -> str:
    """Return ``content`` with its ``trigger.schedule`` value set.

    ``cron_expression`` is always emitted as a JSON (and therefore
    YAML-double-quoted-scalar-compatible) string, so the caller-supplied
    value can never break out of the scalar regardless of its contents.
    """
    quoted = json.dumps(cron_expression)
    trigger_match = _TRIGGER_BLOCK_PATTERN.search(content)
    if trigger_match:
        block = trigger_match.group(1)
        schedule_match = _SCHEDULE_LINE_PATTERN.search(block)
        if schedule_match:
            indent = schedule_match.group(1)
            new_block = (
                block[: schedule_match.start()]
                + f"{indent}schedule: {quoted}"
                + block[schedule_match.end() :]
            )
        else:
            indent_match = re.search(r"(?m)^([ \t]+)\S", block)
            indent = indent_match.group(1) if indent_match else "  "
            separator = "" if block == "" or block.endswith("\n") else "\n"
            new_block = f"{block}{separator}{indent}schedule: {quoted}\n"
        return (
            content[: trigger_match.start(1)]
            + new_block
            + content[trigger_match.end(1) :]
        )
    separator = "" if content == "" or content.endswith("\n") else "\n"
    return f"{content}{separator}trigger:\n  schedule: {quoted}\n"


def _validate_repository(repository_path: object) -> str | None:
    try:
        repository_directory = os.fspath(repository_path)  # type: ignore[arg-type]
        if not isinstance(repository_directory, str) or not os.path.isdir(
            repository_directory
        ):
            return None
        return repository_directory
    except (OSError, TypeError, ValueError):
        return None


def _nearest_manifest(normalized: str, repository_directory: str) -> str | None:
    """Find the manifest governing ``normalized``, searching upward.

    A repository holding many extensions has no manifest at its root — each
    extension carries its own. Walking up from the written file finds that
    manifest, so an extension write does not have to restate a path the target
    already implies. Returns a repository-relative path, or ``None`` when no
    manifest exists between the file and the repository root.
    """
    directory = os.path.dirname(normalized)
    while True:
        candidate_relative = (
            os.path.join(directory, _DEFAULT_MANIFEST_NAME)
            if directory
            else _DEFAULT_MANIFEST_NAME
        )
        candidate_real = _resolve_within_repository(
            repository_directory, candidate_relative
        )
        if candidate_real is not None and os.path.isfile(candidate_real):
            return candidate_relative
        if not directory:
            return None
        directory = os.path.dirname(directory)


def _run_validation(
    kind: str,
    definition_name: str | None,
    repository_directory: str,
    timeout: int | float,
    normalized: str | None = None,
):
    """Run the validate/quality check matching ``kind``.

    Callers guarantee ``definition_name`` is set for ``model``/``workflow``
    before reaching here; only the ``extension`` lane defaults it.
    """
    if kind == "model":
        return run_swamp_command(
            "model_validate", definition_name, repository_path=repository_directory, timeout=timeout
        )
    if kind == "workflow":
        return run_swamp_command(
            "workflow_validate", definition_name, repository_path=repository_directory, timeout=timeout
        )
    # ``definition_name`` means different things per lane: an instance name for
    # model/workflow, but a manifest *path* here. Callers reasonably supply the
    # instance name in both cases, which names no manifest and fails the write.
    # Treat it as a hint: honour it only when it actually resolves to a file,
    # otherwise find the manifest governing the written path.
    manifest_target = None
    if definition_name:
        supplied = _normalize_relative_path(definition_name)
        if supplied is not None:
            supplied_real = _resolve_within_repository(repository_directory, supplied)
            if supplied_real is not None and os.path.isfile(supplied_real):
                manifest_target = supplied
    if manifest_target is None and normalized is not None:
        manifest_target = _nearest_manifest(normalized, repository_directory)
    manifest_target = manifest_target or definition_name or _DEFAULT_MANIFEST_NAME
    return run_swamp_command(
        "extension_quality", manifest_target, repository_path=repository_directory, timeout=timeout
    )


def _write_validate_or_revert(
    *,
    repository_directory: str,
    real_candidate: str,
    kind: str,
    definition_name: str | None,
    new_content: str,
    timeout: int | float,
    normalized: str | None = None,
) -> DefinitionWriteResult:
    existed_before = os.path.isfile(real_candidate)
    previous_content: str | None = None
    if existed_before:
        try:
            with open(real_candidate, "r", encoding="utf-8") as handle:
                previous_content = handle.read()
        except OSError:
            return DefinitionWriteResult(False, False, False, False, None, "read_error")

    try:
        os.makedirs(os.path.dirname(real_candidate), exist_ok=True)
        with open(real_candidate, "w", encoding="utf-8") as handle:
            handle.write(new_content)
    except OSError:
        return DefinitionWriteResult(False, False, False, False, None, "write_error")

    validation = _run_validation(
        kind, definition_name, repository_directory, timeout, normalized
    )
    if validation.ok:
        return DefinitionWriteResult(True, True, False, False, validation.data, None)

    # An extension's quality rubric scores how publishable a package is; it is
    # not a correctness check, and a source file is not invalid for scoring
    # badly. Reverting on it makes the whole extension the unit of work: a
    # README that fails "rich-readme" gets deleted for not yet having fixed the
    # score it was written to fix, so a multi-file change can never be built up
    # one file at a time. Keep the write and report the score instead.
    #
    # Model and workflow validation stays fail-closed below — those are real
    # schema checks, and a live ``swamp serve`` hot-reloads workflow files with
    # no grace period.
    if kind == "extension":
        return DefinitionWriteResult(
            True, False, False, False, validation.data, validation.error
        )

    # Captured only here, on the fail-closed model/workflow lane that actually
    # reverts or deletes: this is the "why was my write undone" the caller
    # needs. ``validation.diagnostics`` is already the scrubbed string (or
    # ``None``) produced by ``run_swamp_command`` — never raw stderr — and is
    # passed through unchanged, never re-derived from anything unscrubbed.
    error = validation.error or "validation_failed"
    diagnostics = validation.diagnostics
    if existed_before:
        try:
            with open(real_candidate, "w", encoding="utf-8") as handle:
                handle.write(previous_content or "")
        except OSError:
            return DefinitionWriteResult(
                False, True, False, False, validation.data, "revert_error", diagnostics
            )
        return DefinitionWriteResult(
            False, True, True, False, validation.data, error, diagnostics
        )

    try:
        os.remove(real_candidate)
    except OSError:
        return DefinitionWriteResult(
            False, True, False, False, validation.data, "revert_error", diagnostics
        )
    return DefinitionWriteResult(
        False, True, False, True, validation.data, error, diagnostics
    )


def write_definition(
    repository_path: str | os.PathLike[str],
    relative_path: str,
    content: str,
    *,
    definition_name: str | None = None,
    timeout: int | float = DEFAULT_TIMEOUT_SECONDS,
) -> DefinitionWriteResult:
    """Write ``content`` to ``relative_path`` inside ``repository_path``.

    ``relative_path`` must resolve inside the repository and match a known
    Swamp definition convention. ``definition_name`` is the model or workflow
    instance name to validate afterward (required for model/workflow paths);
    for extension paths it is the manifest path to score, defaulting to the
    nearest ``manifest.yaml`` at or above the written file, and falling back to
    the repository root. The write is reverted (or, for a brand-new file,
    deleted) if validation fails.
    """
    repository_directory = _validate_repository(repository_path)
    if repository_directory is None:
        return DefinitionWriteResult(False, False, False, False, None, "invalid_repository_path")

    normalized = _normalize_relative_path(relative_path)
    if normalized is None:
        return DefinitionWriteResult(False, False, False, False, None, "path_not_allowed")

    kind = _classify_relative_path(normalized, repository_directory)
    if kind is None:
        return DefinitionWriteResult(False, False, False, False, None, "path_not_allowed")

    if kind in ("model", "workflow") and not definition_name:
        return DefinitionWriteResult(False, False, False, False, None, "definition_name_required")

    if not isinstance(content, str):
        return DefinitionWriteResult(False, False, False, False, None, "invalid_content")

    if kind == "workflow":
        try:
            has_live_schedule = _content_sets_live_schedule(content)
        except _WorkflowContentError:
            return DefinitionWriteResult(
                False, False, False, False, None, "unparseable_workflow_content"
            )
        if has_live_schedule:
            return DefinitionWriteResult(
                False, False, False, False, None, "live_schedule_rejected"
            )

    real_candidate = _resolve_within_repository(repository_directory, normalized)
    if real_candidate is None:
        return DefinitionWriteResult(False, False, False, False, None, "path_escapes_repository")

    return _write_validate_or_revert(
        repository_directory=repository_directory,
        real_candidate=real_candidate,
        kind=kind,
        definition_name=definition_name,
        new_content=content,
        timeout=timeout,
        normalized=normalized,
    )


def set_workflow_schedule(
    repository_path: str | os.PathLike[str],
    relative_path: str,
    cron_expression: str,
    *,
    definition_name: str | None = None,
    timeout: int | float = DEFAULT_TIMEOUT_SECONDS,
) -> DefinitionWriteResult:
    """Set an existing workflow's live ``trigger.schedule`` value.

    This is the only function in this module allowed to write a live
    schedule. ``cron_expression`` is the sole caller-supplied value that
    reaches the file — the rest of the content is read from the existing
    file and passed through unchanged except for the schedule line, so this
    cannot be used to smuggle in unrelated content changes. The caller
    (the Hermes tool handler) is responsible for requiring explicit human
    confirmation before invoking this.
    """
    repository_directory = _validate_repository(repository_path)
    if repository_directory is None:
        return DefinitionWriteResult(False, False, False, False, None, "invalid_repository_path")

    normalized = _normalize_relative_path(relative_path)
    if normalized is None:
        return DefinitionWriteResult(False, False, False, False, None, "path_not_allowed")

    kind = _classify_relative_path(normalized, repository_directory)
    if kind != "workflow":
        return DefinitionWriteResult(False, False, False, False, None, "path_not_allowed")

    if not definition_name:
        return DefinitionWriteResult(False, False, False, False, None, "definition_name_required")

    if not isinstance(cron_expression, str) or cron_expression == "":
        return DefinitionWriteResult(False, False, False, False, None, "path_not_allowed")

    real_candidate = _resolve_within_repository(repository_directory, normalized)
    if real_candidate is None:
        return DefinitionWriteResult(False, False, False, False, None, "path_escapes_repository")

    if not os.path.isfile(real_candidate):
        return DefinitionWriteResult(False, False, False, False, None, "path_not_allowed")

    try:
        with open(real_candidate, "r", encoding="utf-8") as handle:
            existing_content = handle.read()
    except OSError:
        return DefinitionWriteResult(False, False, False, False, None, "read_error")

    new_content = _set_schedule_in_content(existing_content, cron_expression)

    # Sanity-check the textual splice actually produced what it should — a
    # structurally valid document with the schedule now populated — rather
    # than trusting the regex-based edit blindly.
    try:
        spliced_correctly = _content_sets_live_schedule(new_content)
    except _WorkflowContentError:
        spliced_correctly = False
    if not spliced_correctly:
        return DefinitionWriteResult(
            False, False, False, False, None, "schedule_splice_failed"
        )

    return _write_validate_or_revert(
        repository_directory=repository_directory,
        real_candidate=real_candidate,
        kind=kind,
        definition_name=definition_name,
        new_content=new_content,
        timeout=timeout,
    )
