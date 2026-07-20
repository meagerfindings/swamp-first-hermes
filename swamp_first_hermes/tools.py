"""Swamp discovery, authoring, and evidence tool handlers for Hermes."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .definition_write import set_workflow_schedule, write_definition
from .swamp_cli import DEFAULT_TIMEOUT_SECONDS, run_swamp_command


_COMMON_PARAMETERS = {
    "type": "object",
    "properties": {
        "repository_path": {
            "type": "string",
            "description": (
                "Optional repository directory for the read-only Swamp query. "
                "When omitted, use the current working directory."
            ),
        },
        "timeout": {
            "type": "number",
            "description": "Optional positive timeout in seconds (default: 10).",
            "exclusiveMinimum": 0,
        },
    },
    "additionalProperties": False,
}

_REPOSITORY_PATH_PROPERTY = {
    "type": "string",
    "description": (
        "Optional repository directory for the Swamp command. When omitted, "
        "use the current working directory."
    ),
}
_TIMEOUT_PROPERTY = {
    "type": "number",
    "description": "Optional positive timeout in seconds (default: 10).",
    "exclusiveMinimum": 0,
}


def _parameters(
    properties: dict[str, object], required: tuple[str, ...]
) -> dict[str, object]:
    """Build a tool parameters schema with the common repository_path/timeout."""
    return {
        "type": "object",
        "properties": {
            **properties,
            "repository_path": _REPOSITORY_PATH_PROPERTY,
            "timeout": _TIMEOUT_PROPERTY,
        },
        "required": list(required),
        "additionalProperties": False,
    }


SWAMP_MODEL_SEARCH_SCHEMA = {
    "name": "swamp_model_search",
    "description": "Read-only Swamp discovery: list searchable models as JSON.",
    "parameters": _COMMON_PARAMETERS,
}

SWAMP_WORKFLOW_SEARCH_SCHEMA = {
    "name": "swamp_workflow_search",
    "description": "Read-only Swamp evidence discovery: list searchable workflows as JSON.",
    "parameters": _COMMON_PARAMETERS,
}

SWAMP_MODEL_CREATE_SCHEMA = {
    "name": "swamp_model_create",
    "description": (
        "Create a new Swamp model definition of the given type with the "
        "given instance name. Scaffolds a definition file; it does not "
        "customize its content — use swamp_definition_write for that."
    ),
    "parameters": _parameters(
        {
            "model_type": {
                "type": "string",
                "description": (
                    "The Swamp model type to instantiate (e.g. "
                    "'@scope/package-name')."
                ),
            },
            "name": {
                "type": "string",
                "description": "The new model instance's name.",
            },
        },
        required=("model_type", "name"),
    ),
}

SWAMP_MODEL_VALIDATE_SCHEMA = {
    "name": "swamp_model_validate",
    "description": (
        "Validate a Swamp model definition against its schema. Validates "
        "every model when name is omitted."
    ),
    "parameters": _parameters(
        {
            "name": {
                "type": "string",
                "description": "Optional model instance name to validate.",
            }
        },
        required=(),
    ),
}

SWAMP_MODEL_METHOD_RUN_SCHEMA = {
    "name": "swamp_model_method_run",
    "description": "Execute a method on an existing Swamp model instance.",
    "parameters": _parameters(
        {
            "model": {"type": "string", "description": "The model instance name."},
            "method": {"type": "string", "description": "The method name to execute."},
            "inputs": {
                "type": "object",
                "description": (
                    "The method's own arguments, as name/value pairs — the "
                    "equivalent of --input name=value. Check the method's "
                    "declared arguments; many require values here. Put them "
                    "in this object, never in the method name."
                ),
                "additionalProperties": {"type": "string"},
            },
        },
        required=("model", "method"),
    ),
}

SWAMP_WORKFLOW_CREATE_SCHEMA = {
    "name": "swamp_workflow_create",
    "description": (
        "Create a new Swamp workflow definition with the given name. "
        "Scaffolds a definition file; it does not customize its content — "
        "use swamp_definition_write for that."
    ),
    "parameters": _parameters(
        {"name": {"type": "string", "description": "The new workflow's name."}},
        required=("name",),
    ),
}

SWAMP_WORKFLOW_VALIDATE_SCHEMA = {
    "name": "swamp_workflow_validate",
    "description": (
        "Validate a Swamp workflow definition against its schema. Validates "
        "every workflow when name is omitted."
    ),
    "parameters": _parameters(
        {
            "name": {
                "type": "string",
                "description": "Optional workflow name to validate.",
            }
        },
        required=(),
    ),
}

SWAMP_WORKFLOW_RUN_SCHEMA = {
    "name": "swamp_workflow_run",
    "description": "Execute an existing Swamp workflow by name.",
    "parameters": _parameters(
        {
            "name": {"type": "string", "description": "The workflow name to run."},
            "inputs": {
                "type": "object",
                "description": (
                    "The workflow's own arguments, as name/value pairs — the "
                    "equivalent of --input name=value."
                ),
                "additionalProperties": {"type": "string"},
            },
        },
        required=("name",),
    ),
}

SWAMP_EXTENSION_SEARCH_SCHEMA = {
    "name": "swamp_extension_search",
    "description": (
        "Search the Swamp extension registry. Lists all extensions when "
        "query is omitted."
    ),
    "parameters": _parameters(
        {"query": {"type": "string", "description": "Optional search query."}},
        required=(),
    ),
}

SWAMP_EXTENSION_PULL_SCHEMA = {
    "name": "swamp_extension_pull",
    "description": (
        "Pull (install) an extension from the Swamp registry, e.g. "
        "'@keeb/ollama'."
    ),
    "parameters": _parameters(
        {
            "extension": {
                "type": "string",
                "description": "The extension identifier to pull.",
            }
        },
        required=("extension",),
    ),
}

SWAMP_EXTENSION_QUALITY_SCHEMA = {
    "name": "swamp_extension_quality",
    "description": (
        "Score an extension against the Swamp Club quality rubric from its "
        "manifest path, and cache the packaged tarball for reuse by publish."
    ),
    "parameters": _parameters(
        {
            "manifest_path": {
                "type": "string",
                "description": "Path to the extension manifest to score.",
            }
        },
        required=("manifest_path",),
    ),
}

SWAMP_EXTENSION_PUSH_SCHEMA = {
    "name": "swamp_extension_push",
    "description": (
        "Publish a Swamp extension to the public registry from its manifest "
        "path. This is a public, hard-to-reverse action: once published it "
        "is visible to the registry and this plugin cannot retract it. "
        "Requires 'confirmed': true — set this only after the human has "
        "explicitly confirmed they want to publish."
    ),
    "parameters": _parameters(
        {
            "manifest_path": {
                "type": "string",
                "description": "Path to the extension manifest to publish.",
            },
            "confirmed": {
                "type": "boolean",
                "description": (
                    "Must be true. Set only after explicit human "
                    "confirmation to publish."
                ),
            },
        },
        required=("manifest_path", "confirmed"),
    ),
}

SWAMP_DEFINITION_WRITE_SCHEMA = {
    "name": "swamp_definition_write",
    "description": (
        "Write content to a Swamp model, workflow, report, or extension "
        "definition file. The path must resolve inside repository_path and "
        "match a known Swamp definition convention (models/, "
        "extensions/models/, workflows/, reports/, or a root-level "
        "model.ts / *_report.ts / manifest.yaml). Every write is "
        "immediately validated (model/workflow validate, or extension "
        "quality); a failed validation reverts the previous content, or "
        "deletes the file if it did not exist before. A workflow write that "
        "sets a live trigger.schedule value is rejected outright — use "
        "swamp_workflow_set_schedule for that, which requires separate "
        "human confirmation."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "repository_path": {
                "type": "string",
                "description": "Repository directory the write must stay inside.",
            },
            "relative_path": {
                "type": "string",
                "description": "Path to the definition file, relative to repository_path.",
            },
            "content": {
                "type": "string",
                "description": "The full new content of the file.",
            },
            "definition_name": {
                "type": "string",
                "description": (
                    "For a models/ or workflows/ path, the instance name to "
                    "validate afterward (required). For an extension path "
                    "under extensions/, omit this: the manifest governing the "
                    "written file is found automatically. If given for an "
                    "extension it must be a manifest path relative to "
                    "repository_path, not an instance name; a value that "
                    "names no existing file is ignored in favour of the "
                    "discovered manifest."
                ),
            },
            "timeout": _TIMEOUT_PROPERTY,
        },
        "required": ["repository_path", "relative_path", "content"],
        "additionalProperties": False,
    },
}

SWAMP_WORKFLOW_SET_SCHEDULE_SCHEMA = {
    "name": "swamp_workflow_set_schedule",
    "description": (
        "Set an existing workflow's live schedule (cron expression), making "
        "it run automatically and unattended via Swamp's own scheduler. "
        "This is the only tool that can activate a workflow's schedule — "
        "authoring a workflow with swamp_definition_write never does this "
        "by itself. Requires 'confirmed': true — set this only after the "
        "human has explicitly agreed the workflow should start running on "
        "this schedule."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "repository_path": {
                "type": "string",
                "description": "Repository directory containing the workflow.",
            },
            "relative_path": {
                "type": "string",
                "description": "Path to the workflow file, relative to repository_path.",
            },
            "definition_name": {
                "type": "string",
                "description": (
                    "The workflow instance name, used to validate after the "
                    "change."
                ),
            },
            "cron_expression": {
                "type": "string",
                "description": (
                    "The cron expression to set as the workflow's "
                    "trigger.schedule."
                ),
            },
            "confirmed": {
                "type": "boolean",
                "description": (
                    "Must be true. Set only after explicit human "
                    "confirmation to activate this schedule."
                ),
            },
            "timeout": _TIMEOUT_PROPERTY,
        },
        "required": [
            "repository_path",
            "relative_path",
            "definition_name",
            "cron_expression",
            "confirmed",
        ],
        "additionalProperties": False,
    },
}


def swamp_model_search(args: dict[str, object], **kwargs: Any) -> str:
    """Return normalized JSON from the fixed read-only ``swamp model search`` call."""
    del kwargs
    return _run_read_only_search("model_search", args)


def swamp_workflow_search(args: dict[str, object], **kwargs: Any) -> str:
    """Return normalized JSON from the fixed read-only ``swamp workflow search`` call."""
    del kwargs
    return _run_read_only_search("workflow_search", args)


def _run_read_only_search(command: str, args: object) -> str:
    """Call only the closed adapter mapping and return Hermes handler JSON."""
    arguments = args if isinstance(args, Mapping) else {}
    repository_path = arguments.get("repository_path")
    timeout = arguments.get("timeout", DEFAULT_TIMEOUT_SECONDS)
    try:
        result = run_swamp_command(
            command,
            repository_path=repository_path,
            timeout=timeout,
        )
        payload = {"ok": result.ok, "data": result.data, "error": result.error}
    except Exception:
        # Preserve the public boundary: no process, path, or environment detail.
        payload = {"ok": False, "data": None, "error": "execution_error"}
    return json.dumps(payload, ensure_ascii=False)


def _call_swamp_command(
    command: str,
    args: object,
    *,
    required_argument_names: tuple[str, ...] = (),
    optional_argument_names: tuple[str, ...] = (),
) -> str:
    """Call an allowlisted Swamp command and return normalized Hermes JSON.

    Required arguments are read from ``args`` in order and must each be a
    non-empty string; a missing or invalid one short-circuits with
    ``missing_argument`` before the Swamp CLI adapter is touched. Optional
    arguments are appended only when present and non-null.
    """
    arguments = args if isinstance(args, Mapping) else {}
    positional: list[str] = []
    for name in required_argument_names:
        value = arguments.get(name)
        if not isinstance(value, str) or value == "":
            return json.dumps(
                {"ok": False, "data": None, "error": "missing_argument"},
                ensure_ascii=False,
            )
        positional.append(value)
    for name in optional_argument_names:
        value = arguments.get(name)
        if value is None:
            continue
        if not isinstance(value, str) or value == "":
            return json.dumps(
                {"ok": False, "data": None, "error": "missing_argument"},
                ensure_ascii=False,
            )
        positional.append(value)

    inputs = arguments.get("inputs")
    if inputs is not None and not isinstance(inputs, Mapping):
        return json.dumps(
            {"ok": False, "data": None, "error": "invalid_argument"},
            ensure_ascii=False,
        )

    repository_path = arguments.get("repository_path")
    # Omitting timeout lets the adapter apply its per-command budget; passing a
    # fixed default here would silently cap long commands like extension_push.
    timeout_arguments = (
        {"timeout": arguments["timeout"]} if arguments.get("timeout") is not None else {}
    )
    try:
        result = run_swamp_command(
            command,
            *positional,
            repository_path=repository_path,
            inputs=inputs,
            **timeout_arguments,
        )
        payload = {"ok": result.ok, "data": result.data, "error": result.error}
    except Exception:
        payload = {"ok": False, "data": None, "error": "execution_error"}
    return json.dumps(payload, ensure_ascii=False)


def swamp_model_create(args: dict[str, object], **kwargs: Any) -> str:
    del kwargs
    return _call_swamp_command(
        "model_create", args, required_argument_names=("model_type", "name")
    )


def swamp_model_validate(args: dict[str, object], **kwargs: Any) -> str:
    del kwargs
    return _call_swamp_command(
        "model_validate", args, optional_argument_names=("name",)
    )


def swamp_model_method_run(args: dict[str, object], **kwargs: Any) -> str:
    del kwargs
    return _call_swamp_command(
        "model_method_run", args, required_argument_names=("model", "method")
    )


def swamp_workflow_create(args: dict[str, object], **kwargs: Any) -> str:
    del kwargs
    return _call_swamp_command(
        "workflow_create", args, required_argument_names=("name",)
    )


def swamp_workflow_validate(args: dict[str, object], **kwargs: Any) -> str:
    del kwargs
    return _call_swamp_command(
        "workflow_validate", args, optional_argument_names=("name",)
    )


def swamp_workflow_run(args: dict[str, object], **kwargs: Any) -> str:
    del kwargs
    return _call_swamp_command("workflow_run", args, required_argument_names=("name",))


def swamp_extension_search(args: dict[str, object], **kwargs: Any) -> str:
    del kwargs
    return _call_swamp_command(
        "extension_search", args, optional_argument_names=("query",)
    )


def swamp_extension_pull(args: dict[str, object], **kwargs: Any) -> str:
    del kwargs
    return _call_swamp_command(
        "extension_pull", args, required_argument_names=("extension",)
    )


def swamp_extension_quality(args: dict[str, object], **kwargs: Any) -> str:
    del kwargs
    return _call_swamp_command(
        "extension_quality", args, required_argument_names=("manifest_path",)
    )


def swamp_extension_push(args: dict[str, object], **kwargs: Any) -> str:
    """Publish an extension only when the caller has set ``confirmed: true``.

    Publishing to the registry is public and cannot be undone by this
    plugin, so it never proceeds silently.
    """
    del kwargs
    arguments = args if isinstance(args, Mapping) else {}
    if arguments.get("confirmed") is not True:
        return json.dumps(
            {"ok": False, "data": None, "error": "confirmation_required"},
            ensure_ascii=False,
        )
    return _call_swamp_command(
        "extension_push", args, required_argument_names=("manifest_path",)
    )


def swamp_definition_write(args: dict[str, object], **kwargs: Any) -> str:
    """Write and validate a Swamp definition file; revert or delete on failure."""
    del kwargs
    arguments = args if isinstance(args, Mapping) else {}
    try:
        result = write_definition(
            arguments.get("repository_path"),
            arguments.get("relative_path"),
            arguments.get("content"),
            definition_name=arguments.get("definition_name"),
            timeout=arguments.get("timeout", DEFAULT_TIMEOUT_SECONDS),
        )
        payload = {
            "ok": result.ok,
            "validated": result.validated,
            "reverted": result.reverted,
            "deleted": result.deleted,
            "data": result.validation_data,
            "error": result.error,
        }
    except Exception:
        payload = {
            "ok": False,
            "validated": False,
            "reverted": False,
            "deleted": False,
            "data": None,
            "error": "execution_error",
        }
    return json.dumps(payload, ensure_ascii=False)


def swamp_workflow_set_schedule(args: dict[str, object], **kwargs: Any) -> str:
    """Activate a workflow's live schedule only when ``confirmed: true`` is set."""
    del kwargs
    arguments = args if isinstance(args, Mapping) else {}
    if arguments.get("confirmed") is not True:
        return json.dumps(
            {
                "ok": False,
                "validated": False,
                "reverted": False,
                "deleted": False,
                "data": None,
                "error": "confirmation_required",
            },
            ensure_ascii=False,
        )
    try:
        result = set_workflow_schedule(
            arguments.get("repository_path"),
            arguments.get("relative_path"),
            arguments.get("cron_expression"),
            definition_name=arguments.get("definition_name"),
            timeout=arguments.get("timeout", DEFAULT_TIMEOUT_SECONDS),
        )
        payload = {
            "ok": result.ok,
            "validated": result.validated,
            "reverted": result.reverted,
            "deleted": result.deleted,
            "data": result.validation_data,
            "error": result.error,
        }
    except Exception:
        payload = {
            "ok": False,
            "validated": False,
            "reverted": False,
            "deleted": False,
            "data": None,
            "error": "execution_error",
        }
    return json.dumps(payload, ensure_ascii=False)
