"""Read-only Swamp discovery and evidence tool handlers for Hermes."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

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
