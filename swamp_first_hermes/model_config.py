"""Set configuration fields on an existing Swamp model instance, by name.

Today Hermes can only edit a model instance's raw file with
``swamp_definition_write`` if it already knows the instance's on-disk
``models/<type-path>/<uuid>.yaml`` filename — a UUID the caller has no
reason to already know. This module closes that gap: it locates the single
instance file whose parsed top-level ``name`` matches the caller-supplied
name, deep-merges caller-supplied configuration fields into the parsed
instance, and delegates the actual write to ``write_definition``. That
delegation is deliberate — it means this module gets path containment,
immediate ``swamp model validate <name>``, revert-on-failure (or
delete-on-failure for a brand-new file, though that path is unreachable
here since the instance must already exist to be found by name), and
already-scrubbed diagnostics for free, without reimplementing any of it.

Identity fields (``id``, ``type``, ``typeVersion``, ``name``, ``version``)
are refused outright: this is a configuration-setting tool, never an
identity-rewriting one. Letting ``name`` change out from under a
by-name lookup, or letting ``type``/``typeVersion`` drift from the schema
the instance was created against, would corrupt the instance in ways
``model validate`` may not catch symmetrically on both the old and new
identity.
"""

from __future__ import annotations

from collections.abc import Mapping
import os
from typing import Any

import yaml

from .definition_write import DefinitionWriteResult, write_definition
from .swamp_cli import DEFAULT_TIMEOUT_SECONDS, default_repository_path

_IMMUTABLE_FIELDS = frozenset({"id", "type", "typeVersion", "name", "version"})
_MODELS_DIRECTORY_NAME = "models"
_INSTANCE_FILE_EXTENSIONS = (".yaml", ".yml")


def _resolve_repository_directory(repository_path: object) -> str | None:
    """Return an existing repository directory, or ``None``.

    An explicitly supplied ``repository_path`` must itself name an existing
    directory — it is never silently swapped for the deployment default.
    Only an omitted (``None``) ``repository_path`` falls back to
    ``default_repository_path()``.
    """
    if repository_path is not None:
        try:
            candidate = os.fspath(repository_path)  # type: ignore[arg-type]
        except (OSError, TypeError, ValueError):
            return None
        if isinstance(candidate, str) and os.path.isdir(candidate):
            return candidate
        return None
    return default_repository_path()


def _iter_yaml_files(models_directory: str):
    """Yield every ``*.yaml``/``*.yml`` file under ``models_directory``."""
    for root, _directories, files in os.walk(models_directory):
        for filename in files:
            if filename.endswith(_INSTANCE_FILE_EXTENSIONS):
                yield os.path.join(root, filename)


_AMBIGUOUS = object()


def _find_instance_by_name(
    repository_directory: str, name: str
) -> tuple[str, dict[str, Any]] | None | object:
    """Locate the single model instance file whose parsed ``name`` matches.

    Returns ``(full_path, parsed_dict)`` on exactly one match, ``None`` on
    zero matches, or the sentinel ``_AMBIGUOUS`` on two or more. Each
    candidate file is parsed independently inside its own try/except: a
    sibling instance file that fails to read or does not parse as a YAML
    mapping is skipped rather than raised, so one malformed file elsewhere
    in the repository can never crash a lookup for an unrelated instance.
    """
    models_directory = os.path.join(repository_directory, _MODELS_DIRECTORY_NAME)
    if not os.path.isdir(models_directory):
        return None

    matches: list[tuple[str, dict[str, Any]]] = []
    for full_path in _iter_yaml_files(models_directory):
        try:
            with open(full_path, "r", encoding="utf-8") as handle:
                parsed = yaml.safe_load(handle)
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(parsed, dict):
            continue
        if parsed.get("name") == name:
            matches.append((full_path, parsed))

    if not matches:
        return None
    if len(matches) > 1:
        return _AMBIGUOUS
    return matches[0]


def _deep_merge(base: Mapping[str, Any], incoming: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively merge ``incoming`` into ``base``, returning a new dict.

    When both the existing and incoming values at a key are dicts, their
    keys are merged recursively; otherwise the incoming value replaces the
    existing one outright. There is no key-deletion syntax — a value can
    only be set or replaced, never removed. Neither ``base`` nor
    ``incoming`` is mutated.
    """
    merged = dict(base)
    for key, value in incoming.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(existing, value)
        else:
            merged[key] = value
    return merged


def set_model_config(
    repository_path: object,
    name: object,
    config: object,
    *,
    timeout: int | float = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[DefinitionWriteResult, str | None]:
    """Deep-merge ``config`` into the raw instance file named ``name``.

    Returns ``(DefinitionWriteResult, relative_path)``. ``relative_path`` is
    the repository-relative path of the located instance file (POSIX
    separators) when a single match was found and handed to
    ``write_definition``, and ``None`` on any earlier failure (bad
    argument, repository not found, no match, or an ambiguous match).

    ``error`` on the returned ``DefinitionWriteResult`` is one of ``None``,
    ``invalid_argument`` (``config`` is not a non-empty mapping, or ``name``
    is not a non-empty string), ``immutable_field`` (``config`` sets one of
    ``id``/``type``/``typeVersion``/``name``/``version``),
    ``invalid_repository_path``, ``model_not_found`` (no instance file has a
    matching ``name``), ``ambiguous_model`` (more than one instance file has
    a matching ``name``), or any error ``write_definition`` itself can
    return (path/validation/revert errors).
    """
    if not isinstance(config, Mapping) or len(config) == 0:
        return (
            DefinitionWriteResult(False, False, False, False, None, "invalid_argument"),
            None,
        )

    if not isinstance(name, str) or name == "":
        return (
            DefinitionWriteResult(False, False, False, False, None, "invalid_argument"),
            None,
        )

    if _IMMUTABLE_FIELDS.intersection(config):
        return (
            DefinitionWriteResult(False, False, False, False, None, "immutable_field"),
            None,
        )

    repository_directory = _resolve_repository_directory(repository_path)
    if repository_directory is None:
        return (
            DefinitionWriteResult(
                False, False, False, False, None, "invalid_repository_path"
            ),
            None,
        )

    located = _find_instance_by_name(repository_directory, name)
    if located is None:
        return (
            DefinitionWriteResult(False, False, False, False, None, "model_not_found"),
            None,
        )
    if located is _AMBIGUOUS:
        return (
            DefinitionWriteResult(False, False, False, False, None, "ambiguous_model"),
            None,
        )

    full_path, parsed_instance = located
    relative_path = os.path.relpath(full_path, repository_directory).replace(os.sep, "/")

    merged = _deep_merge(parsed_instance, config)
    serialized = yaml.safe_dump(
        merged, sort_keys=False, default_flow_style=False, allow_unicode=True
    )

    result = write_definition(
        repository_directory,
        relative_path,
        serialized,
        definition_name=name,
        timeout=timeout,
    )
    return (result, relative_path)
