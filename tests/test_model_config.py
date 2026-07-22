"""Tests for locating and deep-merging config into an existing model instance
by name, without the caller needing to know its on-disk UUID filename.

``set_model_config`` delegates the actual write to ``write_definition``, so
these tests monkeypatch ``write_definition`` in this module's own namespace
and assert on what it was called with (relative_path, definition_name,
merged serialized YAML) rather than re-testing containment/validation/revert
behaviour already covered by ``tests/test_definition_write.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from swamp_first_hermes.definition_write import DefinitionWriteResult
from swamp_first_hermes.model_config import set_model_config

_INSTANCE_CONTENT = """\
type: command/shell
typeVersion: 2026.02.09.1
id: 809adf4b-2d84-4805-b993-6f379065c375
name: edittest
version: 1
tags: {}
globalArguments:
  existing_key: existing_value
methods: {}
"""


def _write_instance(
    tmp_path: Path,
    relative_path: str = "models/command/shell/809adf4b-2d84-4805-b993-6f379065c375.yaml",
    content: str = _INSTANCE_CONTENT,
) -> Path:
    target = tmp_path / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return target


def _fail_if_called(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("write_definition should not have been called")


# --- config argument validation ----------------------------------------------


def test_rejects_non_mapping_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("swamp_first_hermes.model_config.write_definition", _fail_if_called)

    result, relative_path = set_model_config(str(tmp_path), "edittest", ["not", "a", "mapping"])

    assert result == DefinitionWriteResult(False, False, False, False, None, "invalid_argument")
    assert relative_path is None


def test_rejects_empty_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("swamp_first_hermes.model_config.write_definition", _fail_if_called)

    result, relative_path = set_model_config(str(tmp_path), "edittest", {})

    assert result.error == "invalid_argument"
    assert relative_path is None


def test_rejects_non_string_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("swamp_first_hermes.model_config.write_definition", _fail_if_called)

    result, relative_path = set_model_config(str(tmp_path), None, {"tags": {}})

    assert result.error == "invalid_argument"
    assert relative_path is None


# --- identity-field rejection --------------------------------------------------


@pytest.mark.parametrize("field", ("id", "type", "typeVersion", "name", "version"))
def test_rejects_identity_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    _write_instance(tmp_path)
    monkeypatch.setattr("swamp_first_hermes.model_config.write_definition", _fail_if_called)

    result, relative_path = set_model_config(
        str(tmp_path), "edittest", {field: "new-value", "tags": {}}
    )

    assert result == DefinitionWriteResult(False, False, False, False, None, "immutable_field")
    assert relative_path is None


# --- repository path resolution ------------------------------------------------


def test_rejects_invalid_repository_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("swamp_first_hermes.model_config.write_definition", _fail_if_called)

    result, relative_path = set_model_config(
        str(tmp_path / "does-not-exist"), "edittest", {"tags": {}}
    )

    assert result.error == "invalid_repository_path"
    assert relative_path is None


def test_falls_back_to_default_repository_path_when_omitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_instance(tmp_path)
    monkeypatch.setattr(
        "swamp_first_hermes.model_config.default_repository_path", lambda: str(tmp_path)
    )
    captured: dict[str, object] = {}

    def fake_write_definition(repository_path, relative_path, content, **kwargs):
        captured["repository_path"] = repository_path
        captured["relative_path"] = relative_path
        return DefinitionWriteResult(True, True, False, False, {"valid": True}, None)

    monkeypatch.setattr(
        "swamp_first_hermes.model_config.write_definition", fake_write_definition
    )

    result, relative_path = set_model_config(None, "edittest", {"tags": {}})

    assert result.ok is True
    assert captured["repository_path"] == str(tmp_path)
    assert relative_path == "models/command/shell/809adf4b-2d84-4805-b993-6f379065c375.yaml"


# --- instance lookup by name ---------------------------------------------------


def test_model_not_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_instance(tmp_path)
    monkeypatch.setattr("swamp_first_hermes.model_config.write_definition", _fail_if_called)

    result, relative_path = set_model_config(str(tmp_path), "does-not-exist", {"tags": {}})

    assert result == DefinitionWriteResult(False, False, False, False, None, "model_not_found")
    assert relative_path is None


def test_no_models_directory_is_model_not_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("swamp_first_hermes.model_config.write_definition", _fail_if_called)

    result, relative_path = set_model_config(str(tmp_path), "edittest", {"tags": {}})

    assert result.error == "model_not_found"
    assert relative_path is None


def test_ambiguous_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_instance(
        tmp_path,
        relative_path="models/command/shell/first-uuid.yaml",
    )
    _write_instance(
        tmp_path,
        relative_path="models/command/shell/second-uuid.yaml",
        content=_INSTANCE_CONTENT.replace(
            "809adf4b-2d84-4805-b993-6f379065c375", "a1a1a1a1-0000-0000-0000-000000000000"
        ),
    )
    monkeypatch.setattr("swamp_first_hermes.model_config.write_definition", _fail_if_called)

    result, relative_path = set_model_config(str(tmp_path), "edittest", {"tags": {}})

    assert result == DefinitionWriteResult(False, False, False, False, None, "ambiguous_model")
    assert relative_path is None


def test_malformed_sibling_yaml_is_skipped_not_fatal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_instance(tmp_path)
    bad = tmp_path / "models" / "command" / "shell" / "broken.yaml"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("not: [valid yaml: :::\n")
    non_mapping = tmp_path / "models" / "command" / "shell" / "list.yaml"
    non_mapping.write_text("- just\n- a\n- list\n")

    captured: dict[str, object] = {}

    def fake_write_definition(repository_path, relative_path, content, **kwargs):
        captured["relative_path"] = relative_path
        return DefinitionWriteResult(True, True, False, False, {"valid": True}, None)

    monkeypatch.setattr(
        "swamp_first_hermes.model_config.write_definition", fake_write_definition
    )

    result, relative_path = set_model_config(str(tmp_path), "edittest", {"tags": {}})

    assert result.ok is True
    assert relative_path == "models/command/shell/809adf4b-2d84-4805-b993-6f379065c375.yaml"
    assert captured["relative_path"] == relative_path


# --- deep merge + delegation to write_definition -------------------------------


def test_deep_merge_preserves_sibling_keys_under_global_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_instance(tmp_path)
    caller_config = {"globalArguments": {"new_key": "new_value"}}
    original_caller_config = {"globalArguments": {"new_key": "new_value"}}
    captured: dict[str, object] = {}

    def fake_write_definition(repository_path, relative_path, content, *, definition_name=None, timeout=None):
        captured["repository_path"] = repository_path
        captured["relative_path"] = relative_path
        captured["content"] = content
        captured["definition_name"] = definition_name
        return DefinitionWriteResult(True, True, False, False, {"valid": True}, None)

    monkeypatch.setattr(
        "swamp_first_hermes.model_config.write_definition", fake_write_definition
    )

    result, relative_path = set_model_config(str(tmp_path), "edittest", caller_config)

    assert result.ok is True
    assert relative_path == "models/command/shell/809adf4b-2d84-4805-b993-6f379065c375.yaml"
    assert captured["repository_path"] == str(tmp_path)
    assert captured["relative_path"] == relative_path
    assert captured["definition_name"] == "edittest"

    merged = yaml.safe_load(captured["content"])
    assert merged["globalArguments"] == {
        "existing_key": "existing_value",
        "new_key": "new_value",
    }
    # unrelated top-level fields survive untouched
    assert merged["tags"] == {}
    assert merged["id"] == "809adf4b-2d84-4805-b993-6f379065c375"
    assert merged["name"] == "edittest"

    # the caller's config dict must never be mutated
    assert caller_config == original_caller_config


def test_replaces_non_dict_values_outright(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the existing or incoming value at a key is not a dict on both
    sides, the incoming value replaces it wholesale rather than merging."""
    _write_instance(tmp_path)
    captured: dict[str, object] = {}

    def fake_write_definition(repository_path, relative_path, content, **kwargs):
        captured["content"] = content
        return DefinitionWriteResult(True, True, False, False, {"valid": True}, None)

    monkeypatch.setattr(
        "swamp_first_hermes.model_config.write_definition", fake_write_definition
    )

    result, _relative_path = set_model_config(
        str(tmp_path),
        "edittest",
        # existing "tags" is a dict ({}); incoming value here is a plain
        # string, so it must replace "tags" outright, not attempt a merge.
        {"tags": "override-scalar"},
    )

    assert result.ok is True
    merged = yaml.safe_load(captured["content"])
    assert merged["tags"] == "override-scalar"


def test_diagnostics_passthrough_on_reverted_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``diagnostics`` from a reverting write_definition call must pass
    through unchanged — never re-derived from anything unscrubbed."""
    _write_instance(tmp_path)
    canned = DefinitionWriteResult(
        False, True, True, False, None, "process_failed", "thing.yaml:3:5 error: bad type"
    )
    monkeypatch.setattr(
        "swamp_first_hermes.model_config.write_definition", lambda *a, **k: canned
    )

    result, relative_path = set_model_config(str(tmp_path), "edittest", {"tags": {"env": "prod"}})

    assert result is canned
    assert result.diagnostics == "thing.yaml:3:5 error: bad type"
    assert relative_path == "models/command/shell/809adf4b-2d84-4805-b993-6f379065c375.yaml"
