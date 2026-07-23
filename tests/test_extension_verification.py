from __future__ import annotations

import json
from pathlib import Path
import subprocess
from unittest.mock import Mock

import pytest

from swamp_first_hermes.extension_verification import (
    prepare_extension_review,
    run_extension_verification,
)


def _package(root: Path) -> None:
    (root / "model.ts").write_text("export const x = 1", encoding="utf-8")
    (root / "model_test.ts").write_text("Deno.test('x', () => {})", encoding="utf-8")
    (root / "manifest.yaml").write_text(
        "name: '@example/x'\nversion: '1'\nmodels: [model.ts]\nadditionalFiles: [model_test.ts]\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize("manifest", ("../manifest.yaml", "/tmp/manifest.yaml", "a/./manifest.yaml", "--bad.yaml"))
def test_verification_rejects_manifest_traversal(tmp_path: Path, manifest: str) -> None:
    assert run_extension_verification(
        {"repository_path": str(tmp_path), "manifest_path": manifest}, tests=False
    )["error"] == "path_not_allowed"


def test_check_uses_discrete_bundled_deno_argv_and_scrubs_diagnostics(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _package(tmp_path)
    deno = tmp_path / "deno"
    deno.write_text("", encoding="utf-8")
    deno.chmod(0o700)
    runner = Mock(return_value=subprocess.CompletedProcess([], 1, "", f"{tmp_path}/model.ts:1 bad"))
    monkeypatch.setattr("swamp_first_hermes.extension_verification._deno", lambda: deno)
    monkeypatch.setattr("swamp_first_hermes.extension_verification.subprocess.run", runner)
    result = run_extension_verification(
        {"repository_path": str(tmp_path), "manifest_path": "manifest.yaml"}, tests=False
    )
    assert runner.call_args.args[0] == [str(deno), "check", str(tmp_path / "model.ts"), str(tmp_path / "model_test.ts")]
    assert result["diagnostics"] == "model.ts:1 bad"


def test_test_permission_is_package_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _package(tmp_path)
    deno = tmp_path / "deno"; deno.write_text(""); deno.chmod(0o700)
    runner = Mock(return_value=subprocess.CompletedProcess([], 0, "", ""))
    monkeypatch.setattr("swamp_first_hermes.extension_verification._deno", lambda: deno)
    monkeypatch.setattr("swamp_first_hermes.extension_verification.subprocess.run", runner)
    run_extension_verification({"repository_path": str(tmp_path), "manifest_path": "manifest.yaml"}, tests=True)
    assert runner.call_args.args[0] == [str(deno), "test", f"--allow-read={tmp_path}", str(tmp_path / "model_test.ts")]


def test_manifest_declared_symlink_escape_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.ts"; outside.write_text("")
    (tmp_path / "escape.ts").symlink_to(outside)
    (tmp_path / "manifest.yaml").write_text("models: [escape.ts]\n")
    assert run_extension_verification(
        {"repository_path": str(tmp_path), "manifest_path": "manifest.yaml"}, tests=False
    )["error"] == "manifest_path_not_allowed"


def _output(review_dir: Path, dimensions: list[str], *, warning: bool = True,
            path: Path | None = None, final: bool = True) -> str:
    skeleton = {"extension": "@example/x", "version": "1",
                "dimensions": [{"id": value, "verdict": "pending", "note": ""} for value in dimensions]}
    documents: list[object] = [{"name": "@example/x", "version": "1"}]
    if warning:
        documents.append({"reviewRuleWarnings": [{
            "ruleId": "adversarial-review-report",
            "file": str(path or review_dir / ("_example_x-" + "a" * 64 + ".json")),
            "skeleton": json.dumps(skeleton), "severity": "medium"}]})
    if final:
        documents.append({"status": "dry_run"})
    return "\n".join(json.dumps(document) for document in documents)


def _review(dimensions: list[str]) -> dict[str, object]:
    return {"reviewed_at": "2026-07-23T12:00:00Z",
            "dimensions": [{"id": value, "verdict": "pass",
                            "note": "Reviewed carefully and passes."} for value in dimensions]}


def test_successful_two_pass_uses_dynamic_dimensions_and_never_publishes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _package(tmp_path)
    review_dir = tmp_path / "reviews"
    dimensions = ["model-contract", "vault-secrets", "driver-lifecycle"]
    first = _output(review_dir, dimensions)
    second = _output(review_dir, dimensions, warning=False)
    runner = Mock(side_effect=[subprocess.CompletedProcess([], 0, first, ""),
                               subprocess.CompletedProcess([], 0, second, "")])
    monkeypatch.setattr("swamp_first_hermes.extension_verification._REVIEW_DIRECTORY", review_dir)
    monkeypatch.setattr("swamp_first_hermes.extension_verification.subprocess.run", runner)
    result = prepare_extension_review({"repository_path": str(tmp_path),
                                       "manifest_path": "manifest.yaml",
                                       "review": _review(dimensions)})
    assert result["ok"] is True
    report = json.loads((review_dir / ("_example_x-" + "a" * 64 + ".json")).read_text())
    assert [entry["id"] for entry in report["dimensions"]] == dimensions
    assert all("--dry-run" in call.args[0] and "--yes" not in call.args[0]
               for call in runner.call_args_list)


@pytest.mark.parametrize("nested,rule_id,filename", [
    (True, "adversarial-review-report", "_example_x-" + "a" * 64 + ".json"),
    (False, "lookalike-adversarial-review-report", "_example_x-" + "a" * 64 + ".json"),
    (False, "adversarial-review-report", "_example_x-" + "A" * 64 + ".json"),
    (False, "adversarial-review-report", "example-x-" + "a" * 64 + ".json"),
])
def test_contract_rejects_lookalikes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                    nested: bool, rule_id: str, filename: str) -> None:
    _package(tmp_path)
    review_dir = tmp_path / "reviews"
    skeleton = {"extension": "@example/x", "version": "1", "dimensions": []}
    warning = {"ruleId": rule_id, "file": str(review_dir / filename),
               "skeleton": json.dumps(skeleton)}
    middle = {"wrapper": {"reviewRuleWarnings": [warning]}} if nested else {"reviewRuleWarnings": [warning]}
    output = "\n".join(map(json.dumps, [middle, {"status": "dry_run"}]))
    monkeypatch.setattr("swamp_first_hermes.extension_verification._REVIEW_DIRECTORY", review_dir)
    monkeypatch.setattr("swamp_first_hermes.extension_verification.subprocess.run",
                        Mock(return_value=subprocess.CompletedProcess([], 0, output, "")))
    assert prepare_extension_review({"repository_path": str(tmp_path), "manifest_path": "manifest.yaml",
                                     "review": _review([])})["error"] == "review_path_not_found"


@pytest.mark.parametrize("returncode,final,error", [(2, True, "process_failed"), (0, False, "incomplete_dry_run")])
def test_nonzero_or_incomplete_never_succeeds(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                              returncode: int, final: bool, error: str) -> None:
    _package(tmp_path)
    review_dir = tmp_path / "reviews"
    output = _output(review_dir, ["one"], final=final)
    monkeypatch.setattr("swamp_first_hermes.extension_verification._REVIEW_DIRECTORY", review_dir)
    monkeypatch.setattr("swamp_first_hermes.extension_verification.subprocess.run",
                        Mock(return_value=subprocess.CompletedProcess([], returncode, output, "")))
    assert prepare_extension_review({"repository_path": str(tmp_path), "manifest_path": "manifest.yaml",
                                     "review": _review(["one"])}) == {"ok": False, "data": None, "error": error}


@pytest.mark.parametrize("same,expected", [(True, "review_rejected"), (False, "stale_review")])
def test_second_pass_adversarial_warning_is_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                                     same: bool, expected: str) -> None:
    _package(tmp_path)
    review_dir = tmp_path / "reviews"; dimensions = ["one"]
    first_path = review_dir / ("_example_x-" + "a" * 64 + ".json")
    second_path = first_path if same else review_dir / ("_example_x-" + "b" * 64 + ".json")
    runner = Mock(side_effect=[subprocess.CompletedProcess([], 0, _output(review_dir, dimensions), ""),
                               subprocess.CompletedProcess([], 0, _output(review_dir, dimensions, path=second_path), "")])
    monkeypatch.setattr("swamp_first_hermes.extension_verification._REVIEW_DIRECTORY", review_dir)
    monkeypatch.setattr("swamp_first_hermes.extension_verification.subprocess.run", runner)
    result = prepare_extension_review({"repository_path": str(tmp_path), "manifest_path": "manifest.yaml",
                                       "review": _review(dimensions)})
    assert result["ok"] is False and result["error"] == expected


def test_comma_in_package_path_is_deno_escaped(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    package = tmp_path / "comma,path"; package.mkdir(); _package(package)
    deno = tmp_path / "deno"; deno.write_text(""); deno.chmod(0o700)
    runner = Mock(return_value=subprocess.CompletedProcess([], 0, "", ""))
    monkeypatch.setattr("swamp_first_hermes.extension_verification._deno", lambda: deno)
    monkeypatch.setattr("swamp_first_hermes.extension_verification.subprocess.run", runner)
    run_extension_verification({"repository_path": str(tmp_path),
                                "manifest_path": "comma,path/manifest.yaml"}, tests=True)
    assert runner.call_args.args[0][2] == f"--allow-read={str(package).replace(',', ',,')}"


def test_insecure_review_directory_is_refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _package(tmp_path)
    review_dir = tmp_path / "reviews"; review_dir.mkdir(mode=0o777); review_dir.chmod(0o777)
    dimensions = ["one"]
    monkeypatch.setattr("swamp_first_hermes.extension_verification._REVIEW_DIRECTORY", review_dir)
    monkeypatch.setattr("swamp_first_hermes.extension_verification.subprocess.run",
                        Mock(return_value=subprocess.CompletedProcess([], 0, _output(review_dir, dimensions), "")))
    result = prepare_extension_review({"repository_path": str(tmp_path), "manifest_path": "manifest.yaml",
                                       "review": _review(dimensions)})
    assert result["error"] == "review_path_not_allowed"


def test_symlink_review_directory_is_refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _package(tmp_path)
    target = tmp_path / "target"; target.mkdir(mode=0o700)
    review_dir = tmp_path / "reviews"; review_dir.symlink_to(target, target_is_directory=True)
    dimensions = ["one"]
    monkeypatch.setattr("swamp_first_hermes.extension_verification._REVIEW_DIRECTORY", review_dir)
    monkeypatch.setattr("swamp_first_hermes.extension_verification.subprocess.run",
                        Mock(return_value=subprocess.CompletedProcess([], 0, _output(review_dir, dimensions), "")))
    result = prepare_extension_review({"repository_path": str(tmp_path), "manifest_path": "manifest.yaml",
                                       "review": _review(dimensions)})
    assert result["error"] == "review_path_not_allowed"
