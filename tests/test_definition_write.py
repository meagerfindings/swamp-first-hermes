"""Tests for the scoped, path-restricted Swamp definition writer.

These cover the two safety properties this module exists for: the write
cannot escape the repository (traversal/symlink), and a workflow write can
never carry a live ``trigger.schedule`` value — checked structurally, since
a live ``swamp serve`` process hot-reloads local workflow files with no
grace period, making this the only safety boundary, not defense-in-depth.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from swamp_first_hermes.definition_write import (
    DefinitionWriteResult,
    _classify_relative_path,
    _content_sets_live_schedule,
    _WorkflowContentError,
    set_workflow_schedule,
    write_definition,
)


class _FakeResult:
    def __init__(
        self,
        ok: bool,
        data: object = None,
        error: str | None = None,
        diagnostics: str | None = None,
    ) -> None:
        self.ok = ok
        self.data = data
        self.error = error
        self.diagnostics = diagnostics


def _stub_validate_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "swamp_first_hermes.definition_write.run_swamp_command",
        lambda *a, **k: _FakeResult(True, {"valid": True}, None),
    )


def _stub_validate_fail(monkeypatch: pytest.MonkeyPatch, error: str = "process_error") -> None:
    monkeypatch.setattr(
        "swamp_first_hermes.definition_write.run_swamp_command",
        lambda *a, **k: _FakeResult(False, None, error),
    )


# --- path traversal / escape -------------------------------------------------


def test_rejects_parent_traversal(tmp_path: Path) -> None:
    result = write_definition(tmp_path, "models/../../etc/passwd", "x", definition_name="n")
    assert result.error == "path_not_allowed"
    assert result.ok is False


def test_rejects_absolute_relative_path(tmp_path: Path) -> None:
    result = write_definition(tmp_path, "/etc/passwd", "x", definition_name="n")
    assert result.error == "path_not_allowed"


def test_rejects_embedded_null_byte(tmp_path: Path) -> None:
    result = write_definition(tmp_path, "models/bad\x00name.yaml", "x", definition_name="n")
    assert result.error == "path_not_allowed"


def test_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-target"
    outside.mkdir(exist_ok=True)
    repo = tmp_path / "repo"
    (repo / "models").mkdir(parents=True)
    (repo / "models" / "escape").symlink_to(outside)

    result = write_definition(
        repo, "models/escape/evil.yaml", "x", definition_name="n"
    )

    assert result.error == "path_escapes_repository"
    assert not (outside / "evil.yaml").exists()


def test_invalid_repository_path_is_rejected(tmp_path: Path) -> None:
    result = write_definition(
        tmp_path / "does-not-exist", "models/x.yaml", "x", definition_name="n"
    )
    assert result.error == "invalid_repository_path"


# --- path classification / allowlist -----------------------------------------


def test_models_and_workflows_prefixes_are_always_allowed(tmp_path: Path) -> None:
    assert _classify_relative_path("models/anything/here.yaml", str(tmp_path)) == "model"
    assert _classify_relative_path("workflows/anything.yaml", str(tmp_path)) == "workflow"


def test_manifest_yaml_itself_is_always_allowed(tmp_path: Path) -> None:
    assert _classify_relative_path("manifest.yaml", str(tmp_path)) == "extension"


def test_extensions_models_prefix_is_always_allowed(tmp_path: Path) -> None:
    assert _classify_relative_path("extensions/models/thing.ts", str(tmp_path)) == "extension"


def test_unrelated_path_is_rejected_with_no_manifest(tmp_path: Path) -> None:
    assert _classify_relative_path("model.ts", str(tmp_path)) is None
    assert _classify_relative_path("scripts/evil.sh", str(tmp_path)) is None


def test_manifest_declared_root_level_paths_are_allowed(tmp_path: Path) -> None:
    (tmp_path / "manifest.yaml").write_text(
        "models:\n  - model.ts\nreports:\n  - review_report.ts\n"
    )

    assert _classify_relative_path("model.ts", str(tmp_path)) == "extension"
    assert _classify_relative_path("review_report.ts", str(tmp_path)) == "extension"
    assert _classify_relative_path("not_declared.ts", str(tmp_path)) is None


def test_manifest_declared_workflow_path_is_classified_as_workflow_instance(
    tmp_path: Path,
) -> None:
    """A manifest-declared workflows: entry is a workflow instance, not
    extension source — it must stay subject to the live-schedule guard even
    though its path doesn't start with workflows/."""
    (tmp_path / "manifest.yaml").write_text("workflows:\n  - custom/my-flow.yaml\n")

    assert _classify_relative_path("custom/my-flow.yaml", str(tmp_path)) == "workflow"


def test_malformed_manifest_declares_nothing_extra(tmp_path: Path) -> None:
    (tmp_path / "manifest.yaml").write_text("not: [valid yaml: :::\n")

    assert _classify_relative_path("model.ts", str(tmp_path)) is None


def test_non_mapping_manifest_declares_nothing_extra(tmp_path: Path) -> None:
    (tmp_path / "manifest.yaml").write_text("- just\n- a\n- list\n")

    assert _classify_relative_path("model.ts", str(tmp_path)) is None


# --- structural schedule detection -------------------------------------------


@pytest.mark.parametrize(
    "content",
    (
        'trigger:\n  schedule: "0 5 * * *"\n',
        "trigger:\n  schedule: '0 5 * * *'\n",
        "trigger:\n  schedule: 0 5 * * *\n",
        # reformatted / different key order still detected structurally
        "name: x\ntrigger:\n  other: 1\n  schedule: '0 5 * * *'\n",
    ),
)
def test_detects_a_live_schedule_regardless_of_formatting(content: str) -> None:
    assert _content_sets_live_schedule(content) is True


@pytest.mark.parametrize(
    "content",
    (
        "name: nightly-check\n",
        "trigger: {}\n",
        "trigger:\n  schedule: null\n",
        "trigger:\n  schedule: ~\n",
        'trigger:\n  schedule: ""\n',
        "trigger:\n  schedule:   \n",
        "",
    ),
)
def test_does_not_flag_absent_or_explicitly_empty_schedule(content: str) -> None:
    assert _content_sets_live_schedule(content) is False


@pytest.mark.parametrize(
    "content",
    (
        "trigger:\n  - a\n  - b\n",  # trigger present but not a mapping
        "trigger:\n  schedule:\n    nested: true\n",  # schedule not a string
        "trigger:\n  schedule: 12345\n",
    ),
)
def test_fails_closed_on_unrecognized_trigger_or_schedule_shape(content: str) -> None:
    assert _content_sets_live_schedule(content) is True


def test_raises_on_unparseable_yaml() -> None:
    with pytest.raises(_WorkflowContentError):
        _content_sets_live_schedule("not: [valid yaml: :::")


def test_raises_when_document_is_not_a_mapping() -> None:
    with pytest.raises(_WorkflowContentError):
        _content_sets_live_schedule("- just\n- a\n- list\n")


# --- write_definition: schedule rejection ------------------------------------


def test_write_definition_rejects_workflow_content_with_a_live_schedule(
    tmp_path: Path,
) -> None:
    result = write_definition(
        tmp_path,
        "workflows/nightly.yaml",
        'trigger:\n  schedule: "0 5 * * *"\n',
        definition_name="nightly",
    )

    assert result == DefinitionWriteResult(False, False, False, False, None, "live_schedule_rejected")
    assert not (tmp_path / "workflows" / "nightly.yaml").exists()


def test_write_definition_rejects_unparseable_workflow_content(tmp_path: Path) -> None:
    result = write_definition(
        tmp_path,
        "workflows/nightly.yaml",
        "not: [valid yaml: :::",
        definition_name="nightly",
    )

    assert result.error == "unparseable_workflow_content"
    assert not (tmp_path / "workflows" / "nightly.yaml").exists()


def test_write_definition_allows_workflow_content_without_a_schedule(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _stub_validate_ok(monkeypatch)

    result = write_definition(
        tmp_path, "workflows/nightly.yaml", "name: nightly\n", definition_name="nightly"
    )

    assert result.ok is True
    assert (tmp_path / "workflows" / "nightly.yaml").read_text() == "name: nightly\n"


def test_write_definition_rejects_schedule_smuggled_via_manifest_declared_workflow_path(
    tmp_path: Path,
) -> None:
    """A manifest can declare a workflow instance at a path that doesn't
    start with workflows/ — Swamp doesn't enforce that prefix. The
    live-schedule guard must still apply there, exactly as it does for
    workflows/**, or a written file could reach a live scheduler unchecked."""
    (tmp_path / "manifest.yaml").write_text("workflows:\n  - custom/my-flow.yaml\n")

    result = write_definition(
        tmp_path,
        "custom/my-flow.yaml",
        'trigger:\n  schedule: "0 5 * * *"\n',
        definition_name="my-flow",
    )

    assert result == DefinitionWriteResult(False, False, False, False, None, "live_schedule_rejected")
    assert not (tmp_path / "custom" / "my-flow.yaml").exists()


def test_write_definition_allows_manifest_declared_workflow_path_without_schedule(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The same path is writable when it carries no live schedule, and is
    validated via workflow_validate (instance kind), not extension_quality."""
    captured: dict[str, object] = {}

    def fake_runner(command: str, *positional: str, **kwargs: object):
        captured["command"] = command
        captured["positional"] = positional
        return _FakeResult(True, {"valid": True}, None)

    monkeypatch.setattr(
        "swamp_first_hermes.definition_write.run_swamp_command", fake_runner
    )
    (tmp_path / "manifest.yaml").write_text("workflows:\n  - custom/my-flow.yaml\n")

    result = write_definition(
        tmp_path, "custom/my-flow.yaml", "name: my-flow\n", definition_name="my-flow"
    )

    assert result.ok is True
    assert captured["command"] == "workflow_validate"
    assert captured["positional"] == ("my-flow",)


def test_manifest_declared_models_and_reports_entries_stay_extension_kind(
    tmp_path: Path,
) -> None:
    """Only workflows: entries get workflow-instance treatment — models:/
    reports: entries remain extension source, validated via quality."""
    (tmp_path / "manifest.yaml").write_text(
        "models:\n  - model.ts\nreports:\n  - review_report.ts\n"
    )

    assert _classify_relative_path("model.ts", str(tmp_path)) == "extension"
    assert _classify_relative_path("review_report.ts", str(tmp_path)) == "extension"


# --- write / validate / revert or delete -------------------------------------


def test_new_file_is_deleted_after_failed_validation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _stub_validate_fail(monkeypatch, error="process_error")

    result = write_definition(
        tmp_path, "models/thing.yaml", "bad: content\n", definition_name="thing"
    )

    assert result == DefinitionWriteResult(False, True, False, True, None, "process_error")
    assert not (tmp_path / "models" / "thing.yaml").exists()


def test_existing_file_is_reverted_after_failed_validation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "models" / "thing.yaml"
    target.parent.mkdir(parents=True)
    target.write_text("original: content\n")
    _stub_validate_fail(monkeypatch, error="process_error")

    result = write_definition(
        tmp_path, "models/thing.yaml", "bad: content\n", definition_name="thing"
    )

    assert result == DefinitionWriteResult(False, True, True, False, None, "process_error")
    assert target.read_text() == "original: content\n"


def test_successful_write_and_validate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _stub_validate_ok(monkeypatch)

    result = write_definition(
        tmp_path, "models/thing.yaml", "good: content\n", definition_name="thing"
    )

    assert result == DefinitionWriteResult(True, True, False, False, {"valid": True}, None)
    assert (tmp_path / "models" / "thing.yaml").read_text() == "good: content\n"


def test_model_and_workflow_paths_require_definition_name(tmp_path: Path) -> None:
    assert write_definition(tmp_path, "models/thing.yaml", "x").error == (
        "definition_name_required"
    )
    assert write_definition(tmp_path, "workflows/thing.yaml", "x").error == (
        "definition_name_required"
    )


def test_extension_path_defaults_definition_name_to_manifest_yaml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    def fake_runner(command: str, *positional: str, **kwargs: object):
        captured["command"] = command
        captured["positional"] = positional
        return _FakeResult(True, {}, None)

    monkeypatch.setattr(
        "swamp_first_hermes.definition_write.run_swamp_command", fake_runner
    )

    result = write_definition(tmp_path, "extensions/models/thing.ts", "export const x = 1;\n")

    assert result.ok is True
    assert captured["command"] == "extension_quality"
    assert captured["positional"] == ("manifest.yaml",)


def test_extension_path_scores_the_nearest_manifest_not_the_repository_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A repository of many extensions has no root manifest to fall back on.

    Defaulting to the repository root made every extension write fail
    validation and revert, which reads as a broken tool rather than a missing
    argument.
    """
    extension = tmp_path / "extensions" / "models" / "owner" / "thing"
    extension.mkdir(parents=True)
    (extension / "manifest.yaml").write_text("name: thing\n")
    captured: dict[str, object] = {}

    def fake_runner(command: str, *positional: str, **kwargs: object):
        captured["positional"] = positional
        return _FakeResult(True, {}, None)

    monkeypatch.setattr(
        "swamp_first_hermes.definition_write.run_swamp_command", fake_runner
    )

    result = write_definition(
        tmp_path,
        "extensions/models/owner/thing/model.ts",
        "export const x = 1;\n",
    )

    assert result.ok is True
    assert captured["positional"] == (
        "extensions/models/owner/thing/manifest.yaml",
    )


def test_explicit_definition_name_still_wins_when_it_resolves(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    extension = tmp_path / "extensions" / "models" / "owner" / "thing"
    extension.mkdir(parents=True)
    (extension / "manifest.yaml").write_text("name: thing\n")
    chosen = tmp_path / "chosen"
    chosen.mkdir()
    (chosen / "manifest.yaml").write_text("name: chosen\n")
    captured: dict[str, object] = {}

    def fake_runner(command: str, *positional: str, **kwargs: object):
        captured["positional"] = positional
        return _FakeResult(True, {}, None)

    monkeypatch.setattr(
        "swamp_first_hermes.definition_write.run_swamp_command", fake_runner
    )

    result = write_definition(
        tmp_path,
        "extensions/models/owner/thing/model.ts",
        "export const x = 1;\n",
        definition_name="chosen/manifest.yaml",
    )

    assert result.ok is True
    assert captured["positional"] == ("chosen/manifest.yaml",)


def test_extension_instance_name_falls_back_to_manifest_discovery(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``definition_name`` is an instance name for models but a path here.

    A caller following the documented "instance name" meaning names no
    manifest at all, which previously failed the write outright. Honour the
    argument only when it resolves to a real file.
    """
    extension = tmp_path / "extensions" / "models" / "owner" / "thing"
    extension.mkdir(parents=True)
    (extension / "manifest.yaml").write_text("name: thing\n")
    captured: dict[str, object] = {}

    def fake_runner(command: str, *positional: str, **kwargs: object):
        captured["positional"] = positional
        return _FakeResult(True, {}, None)

    monkeypatch.setattr(
        "swamp_first_hermes.definition_write.run_swamp_command", fake_runner
    )

    result = write_definition(
        tmp_path,
        "extensions/models/owner/thing/model.ts",
        "export const x = 1;\n",
        definition_name="thing",
    )

    assert result.ok is True
    assert captured["positional"] == (
        "extensions/models/owner/thing/manifest.yaml",
    )


# --- set_workflow_schedule ----------------------------------------------------


def test_set_workflow_schedule_requires_an_existing_file(tmp_path: Path) -> None:
    result = set_workflow_schedule(
        tmp_path, "workflows/nightly.yaml", "0 5 * * *", definition_name="nightly"
    )
    assert result.error == "path_not_allowed"


def test_set_workflow_schedule_inserts_a_schedule_and_validates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "workflows" / "nightly.yaml"
    target.parent.mkdir(parents=True)
    target.write_text("name: nightly\n")
    _stub_validate_ok(monkeypatch)

    result = set_workflow_schedule(
        tmp_path, "workflows/nightly.yaml", "0 5 * * *", definition_name="nightly"
    )

    assert result.ok is True
    written = target.read_text()
    assert "trigger:" in written
    assert '"0 5 * * *"' in written
    assert _content_sets_live_schedule(written) is True


def test_set_workflow_schedule_updates_an_existing_schedule_in_place(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "workflows" / "nightly.yaml"
    target.parent.mkdir(parents=True)
    target.write_text('name: nightly\ntrigger:\n  schedule: "0 3 * * *"\n')
    _stub_validate_ok(monkeypatch)

    result = set_workflow_schedule(
        tmp_path, "workflows/nightly.yaml", "0 9 * * *", definition_name="nightly"
    )

    assert result.ok is True
    written = target.read_text()
    assert '"0 9 * * *"' in written
    assert "0 3 * * *" not in written
    assert written.count("trigger:") == 1


def test_set_workflow_schedule_reverts_on_failed_validation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "workflows" / "nightly.yaml"
    target.parent.mkdir(parents=True)
    original = "name: nightly\n"
    target.write_text(original)
    _stub_validate_fail(monkeypatch)

    result = set_workflow_schedule(
        tmp_path, "workflows/nightly.yaml", "0 5 * * *", definition_name="nightly"
    )

    assert result.ok is False
    assert result.reverted is True
    assert target.read_text() == original


def test_set_workflow_schedule_cron_expression_cannot_break_out_of_the_scalar(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A hostile cron_expression is always emitted as one safe YAML string."""
    target = tmp_path / "workflows" / "nightly.yaml"
    target.parent.mkdir(parents=True)
    target.write_text("name: nightly\n")
    _stub_validate_ok(monkeypatch)
    hostile = '0 5 * * *"\nsome_other_key: injected\n#'

    result = set_workflow_schedule(
        tmp_path, "workflows/nightly.yaml", hostile, definition_name="nightly"
    )

    assert result.ok is True
    import yaml

    parsed = yaml.safe_load(target.read_text())
    assert parsed["trigger"]["schedule"] == hostile
    assert "some_other_key" not in parsed


def test_set_workflow_schedule_requires_definition_name(tmp_path: Path) -> None:
    target = tmp_path / "workflows" / "nightly.yaml"
    target.parent.mkdir(parents=True)
    target.write_text("name: nightly\n")

    result = set_workflow_schedule(tmp_path, "workflows/nightly.yaml", "0 5 * * *")

    assert result.error == "definition_name_required"


def test_set_workflow_schedule_rejects_non_workflow_paths(tmp_path: Path) -> None:
    target = tmp_path / "models" / "thing.yaml"
    target.parent.mkdir(parents=True)
    target.write_text("name: thing\n")

    result = set_workflow_schedule(
        tmp_path, "models/thing.yaml", "0 5 * * *", definition_name="thing"
    )

    assert result.error == "path_not_allowed"


def test_extension_write_is_kept_when_the_quality_rubric_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Quality scores publishability; it does not decide validity.

    Reverting on it makes a multi-file extension change impossible to build up
    incrementally: the README written to fix "rich-readme" is deleted for not
    having fixed it yet.
    """
    extension = tmp_path / "extensions" / "models" / "owner" / "thing"
    extension.mkdir(parents=True)
    (extension / "manifest.yaml").write_text("name: thing\n")
    target = extension / "README.md"
    target.write_text("old\n")

    monkeypatch.setattr(
        "swamp_first_hermes.definition_write.run_swamp_command",
        lambda *a, **k: _FakeResult(
            False, {"status": "failed", "missing": ["rich-readme"]}, "process_error"
        ),
    )

    result = write_definition(
        tmp_path, "extensions/models/owner/thing/README.md", "# much better\n"
    )

    assert result.ok is True
    assert result.validated is False
    assert result.reverted is False
    assert result.deleted is False
    assert result.validation_data == {"status": "failed", "missing": ["rich-readme"]}
    assert target.read_text() == "# much better\n"


def test_model_write_still_reverts_when_validation_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Schema validation stays fail-closed for models and workflows."""
    target = tmp_path / "models" / "thing.yaml"
    target.parent.mkdir(parents=True)
    target.write_text("name: original\n")

    monkeypatch.setattr(
        "swamp_first_hermes.definition_write.run_swamp_command",
        lambda *a, **k: _FakeResult(False, {"error": "bad schema"}, "process_error"),
    )

    result = write_definition(
        tmp_path, "models/thing.yaml", "name: broken\n", definition_name="thing"
    )

    assert result.ok is False
    assert result.reverted is True
    assert target.read_text() == "name: original\n"


def test_workflow_write_still_reverts_when_validation_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "workflows" / "nightly.yaml"
    target.parent.mkdir(parents=True)
    target.write_text("name: original\n")

    monkeypatch.setattr(
        "swamp_first_hermes.definition_write.run_swamp_command",
        lambda *a, **k: _FakeResult(False, {"error": "bad schema"}, "process_error"),
    )

    result = write_definition(
        tmp_path, "workflows/nightly.yaml", "name: broken\n", definition_name="nightly"
    )

    assert result.ok is False
    assert result.reverted is True
    assert target.read_text() == "name: original\n"


# --- rollback diagnostics -----------------------------------------------------


def test_reverted_model_write_surfaces_scrubbed_diagnostics(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A caller learns *why* a write was reverted via the already-scrubbed
    ``diagnostics`` string, not just the opaque error code."""
    target = tmp_path / "models" / "thing.yaml"
    target.parent.mkdir(parents=True)
    target.write_text("name: original\n")

    monkeypatch.setattr(
        "swamp_first_hermes.definition_write.run_swamp_command",
        lambda *a, **k: _FakeResult(
            False, None, "process_failed", "thing.yaml:3:5 error: bad type"
        ),
    )

    result = write_definition(
        tmp_path, "models/thing.yaml", "name: broken\n", definition_name="thing"
    )

    assert result.ok is False
    assert result.reverted is True
    assert result.diagnostics == "thing.yaml:3:5 error: bad type"


def test_deleted_new_workflow_write_surfaces_scrubbed_diagnostics(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "swamp_first_hermes.definition_write.run_swamp_command",
        lambda *a, **k: _FakeResult(
            False, None, "process_failed", "nightly.yaml:1:1 error: bad schema"
        ),
    )

    result = write_definition(
        tmp_path, "workflows/nightly.yaml", "name: broken\n", definition_name="nightly"
    )

    assert result.ok is False
    assert result.deleted is True
    assert result.diagnostics == "nightly.yaml:1:1 error: bad schema"


def test_successful_write_has_no_diagnostics(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _stub_validate_ok(monkeypatch)

    result = write_definition(
        tmp_path, "models/thing.yaml", "good: content\n", definition_name="thing"
    )

    assert result.ok is True
    assert result.diagnostics is None


def test_reverted_write_with_no_diagnostics_available_stays_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A validation failure outside the diagnostics allowlist (or one that
    produced no stderr) reverts exactly as before, with diagnostics unset."""
    target = tmp_path / "models" / "thing.yaml"
    target.parent.mkdir(parents=True)
    target.write_text("name: original\n")
    _stub_validate_fail(monkeypatch, error="process_error")

    result = write_definition(
        tmp_path, "models/thing.yaml", "name: broken\n", definition_name="thing"
    )

    assert result.ok is False
    assert result.reverted is True
    assert result.diagnostics is None
