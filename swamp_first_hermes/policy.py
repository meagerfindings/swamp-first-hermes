"""Pure, deterministic policy decisions for generic tool calls.

This module intentionally has no Hermes runtime dependency.  It accepts a tool
name and JSON-like argument mapping so a caller can apply the returned decision
at its own integration boundary.

The first strict-mode release is deliberately narrow: it blocks only direct,
clearly mutating scheduler invocations expressed through conventional
``command`` or ``argv`` arguments.  It does not infer intent from a tool name,
free-form text, shell pipelines, or environment-specific metadata.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from os.path import basename
import shlex



class PolicyMode(StrEnum):
    """Operating modes for the policy engine."""

    OFF = "off"
    AUDIT = "audit"
    STRICT = "strict"


class PolicyAction(StrEnum):
    """Actions an integration should take for a policy decision."""

    ALLOW = "allow"
    BLOCK = "block"


class PolicyClassification(StrEnum):
    """The limited, public set of classifications produced by this release."""

    SAFE = "safe"
    SCHEDULER_BYPASS = "scheduler_bypass"


PUBLIC_STRICT_SCHEDULER_BYPASS_ERROR = (
    "Blocked by Swamp-first policy: direct scheduler bypasses are not allowed "
    "in strict mode."
)
_AUDIT_SCHEDULER_BYPASS_REASON = "Audit: direct scheduler bypass detected."
_COMMAND_ARGUMENT_KEYS = ("command", "argv")


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """A public, serializable-by-fields result for a generic tool call.

    ``reason`` is either ``None`` or fixed public policy text.  It never
    contains a tool name, supplied arguments, paths, or runtime diagnostics.
    """

    action: PolicyAction
    mode: PolicyMode
    classification: PolicyClassification
    reason: str | None


def classify_tool_call(
    tool_name: str,
    arguments: Mapping[str, object],
) -> PolicyClassification:
    """Classify a generic call without relying on a Hermes tool registry.

    ``tool_name`` is deliberately not interpreted: integrations use many names
    for command execution.  Detection is limited to direct command vectors in
    the conventional ``command`` and ``argv`` argument fields, avoiding broad
    matches against descriptive values such as search queries.
    """
    del tool_name
    for key in _COMMAND_ARGUMENT_KEYS:
        command = _command_vector(arguments.get(key))
        if command is not None and _is_direct_scheduler_bypass(command):
            return PolicyClassification.SCHEDULER_BYPASS
    return PolicyClassification.SAFE


def evaluate_tool_call(
    mode: PolicyMode | str,
    tool_name: str,
    arguments: Mapping[str, object],
) -> PolicyDecision:
    """Return the deterministic policy decision for one generic tool call.

    ``off`` permits all calls silently.  ``audit`` permits all calls but records
    the fixed public reason for detected bypasses.  ``strict`` blocks detected
    direct scheduler bypasses and permits every other call in this first
    release.
    """
    normalized_mode = _normalize_mode(mode)
    classification = classify_tool_call(tool_name, arguments)

    if classification is PolicyClassification.SCHEDULER_BYPASS:
        if normalized_mode is PolicyMode.STRICT:
            return PolicyDecision(
                action=PolicyAction.BLOCK,
                mode=normalized_mode,
                classification=classification,
                reason=PUBLIC_STRICT_SCHEDULER_BYPASS_ERROR,
            )
        if normalized_mode is PolicyMode.AUDIT:
            return PolicyDecision(
                action=PolicyAction.ALLOW,
                mode=normalized_mode,
                classification=classification,
                reason=_AUDIT_SCHEDULER_BYPASS_REASON,
            )

    return PolicyDecision(
        action=PolicyAction.ALLOW,
        mode=normalized_mode,
        classification=classification,
        reason=None,
    )


def _normalize_mode(mode: PolicyMode | str) -> PolicyMode:
    try:
        return PolicyMode(mode)
    except (TypeError, ValueError) as error:
        raise ValueError("Policy mode must be off, audit, or strict") from error


def _command_vector(value: object) -> tuple[str, ...] | None:
    if isinstance(value, str):
        try:
            parsed = shlex.split(value)
        except ValueError:
            return None
        return tuple(parsed) or None
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if all(isinstance(item, str) for item in value) and value:
            return tuple(value)
    return None


def _is_direct_scheduler_bypass(command: tuple[str, ...]) -> bool:
    executable = basename(command[0])
    arguments = command[1:]

    if executable == "crontab":
        return not _is_read_only_crontab_command(arguments)
    if executable in {"at", "batch"}:
        return True
    if executable == "schtasks":
        return any(
            argument.casefold() in {"/create", "/change", "/run", "/end", "/delete"}
            for argument in arguments
        )
    return False


def _is_read_only_crontab_command(arguments: tuple[str, ...]) -> bool:
    """Allowlist the crontab invocations that cannot alter a crontab.

    Options are intentionally not parsed generically.  Accepting only these
    complete vectors prevents an informational flag from masking a mutating
    action while supporting ordinary inspection, help, and version requests.
    """
    if arguments in {
        ("-l",),
        ("-h",),
        ("--help",),
        ("-V",),
        ("--version",),
    }:
        return True

    return (
        len(arguments) == 3
        and arguments[0] == "-u"
        and bool(arguments[1])
        and not arguments[1].startswith("-")
        and arguments[2] == "-l"
    )
