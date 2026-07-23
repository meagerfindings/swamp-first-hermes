"""Bounded local verification and adversarial-review preparation for extensions."""
from __future__ import annotations

from collections.abc import Mapping
import json
import math
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
from typing import Any

import yaml

from .swamp_cli import _scrub_diagnostics, default_repository_path

_SOURCE_KEYS = ("models", "reports", "vaults", "drivers", "datastores")
_MAX_DIAGNOSTICS = 16_384
_REVIEW_DIRECTORY = Path("/tmp/swamp-extension-review")
_VERDICTS = frozenset({"pass", "issue", "na", "pending"})


def _timeout(value: object) -> float | None:
    if value is None:
        return 120.0
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if value > 0 and math.isfinite(value) else None


def _repository(value: object) -> Path | None:
    raw = default_repository_path() if value is None else value
    if raw is None:
        raw = os.getcwd()
    try:
        path = Path(os.fspath(raw)).resolve(strict=True)
    except (OSError, TypeError, ValueError):
        return None
    return path if path.is_dir() else None


def _relative(value: object) -> str | None:
    if (not isinstance(value, str) or not value or "\x00" in value or
            os.path.isabs(value)):
        return None
    normalized = value.replace("\\", "/")
    if normalized.startswith("-") or any(part in ("", ".", "..") for part in normalized.split("/")):
        return None
    return normalized


def _contained(root: Path, relative: str, *, file: bool = True) -> Path | None:
    try:
        candidate = (root / relative).resolve(strict=True)
        candidate.relative_to(root)
    except (OSError, ValueError):
        return None
    if candidate == root or (file and not candidate.is_file()):
        return None
    return candidate


def _package(args: Mapping[str, object]) -> tuple[Path, Path, dict[str, Any]] | str:
    repo = _repository(args.get("repository_path"))
    if repo is None:
        return "invalid_repository_path"
    relative = _relative(args.get("manifest_path"))
    if relative is None:
        return "path_not_allowed"
    manifest = _contained(repo, relative)
    if manifest is None:
        return "path_escapes_repository"
    try:
        parsed = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        return "invalid_manifest"
    if not isinstance(parsed, dict):
        return "invalid_manifest"
    return repo, manifest.parent, parsed


def _declared_ts(package: Path, manifest: Mapping[str, Any]) -> tuple[list[Path], str | None]:
    names: list[str] = []
    for key in (*_SOURCE_KEYS, "additionalFiles"):
        values = manifest.get(key, [])
        if values is None:
            continue
        if not isinstance(values, list) or any(not isinstance(v, str) for v in values):
            return [], "invalid_manifest"
        names.extend(v for v in values if v.endswith((".ts", ".tsx")))
    paths: list[Path] = []
    for name in dict.fromkeys(names):
        relative = _relative(name)
        path = _contained(package, relative) if relative else None
        if path is None:
            return [], "manifest_path_not_allowed"
        paths.append(path)
    return paths, None


def _deno() -> Path | None:
    candidate = Path.home() / ".swamp" / "deno" / "deno"
    return candidate if candidate.is_file() and os.access(candidate, os.X_OK) else None


def run_extension_verification(args: Mapping[str, object], *, tests: bool) -> dict[str, Any]:
    timeout = _timeout(args.get("timeout"))
    if timeout is None:
        return {"ok": False, "data": None, "error": "invalid_timeout", "diagnostics": None}
    loaded = _package(args)
    if isinstance(loaded, str):
        return {"ok": False, "data": None, "error": loaded, "diagnostics": None}
    repo, package, manifest = loaded
    files, error = _declared_ts(package, manifest)
    if error:
        return {"ok": False, "data": None, "error": error, "diagnostics": None}
    if tests:
        source_dirs = {p.parent for p in files if not p.name.endswith("_test.ts")}
        files = [p for p in files if p.name.endswith("_test.ts") and p.parent in source_dirs]
    deno = _deno()
    if deno is None:
        return {"ok": False, "data": None, "error": "executable_not_found", "diagnostics": None}
    if not files:
        return {"ok": True, "data": {"files": [], "file_count": 0}, "error": None, "diagnostics": None}
    allowed = str(package).replace(",", ",,")
    argv = [str(deno), "test", f"--allow-read={allowed}"] if tests else [str(deno), "check"]
    argv.extend(str(path) for path in files)
    try:
        completed = subprocess.run(argv, cwd=str(package), capture_output=True, check=False,
                                   text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "data": None, "error": "timeout", "diagnostics": None}
    except OSError:
        return {"ok": False, "data": None, "error": "execution_error", "diagnostics": None}
    diagnostics = _scrub_diagnostics((completed.stderr or completed.stdout)[-_MAX_DIAGNOSTICS:], str(repo)) or None
    return {"ok": completed.returncode == 0,
            "data": {"files": [str(p.relative_to(repo)) for p in files], "file_count": len(files)},
            "error": None if completed.returncode == 0 else "verification_failed",
            "diagnostics": diagnostics}


def _scrub_value(value: object, repository: Path) -> object:
    if isinstance(value, str):
        return _scrub_diagnostics(value, str(repository))[:_MAX_DIAGNOSTICS]
    if isinstance(value, Mapping):
        return {str(key): _scrub_value(child, repository) for key, child in value.items()}
    if isinstance(value, list):
        return [_scrub_value(child, repository) for child in value]
    return value


def _dry_run(repo: Path, manifest_relative: str, timeout: float) -> tuple[list[object] | None, int | None, str | None]:
    try:
        completed = subprocess.run(
            ["swamp", "extension", "push", manifest_relative, "--dry-run", "--json"],
            cwd=str(repo), capture_output=True, check=False, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, None, "timeout"
    except OSError:
        return None, None, "execution_error"
    decoder, documents, output, index = json.JSONDecoder(), [], completed.stdout or "", 0
    try:
        while index < len(output):
            while index < len(output) and output[index].isspace():
                index += 1
            if index < len(output):
                document, index = decoder.raw_decode(output, index)
                documents.append(document)
    except ValueError:
        return None, completed.returncode, "malformed_json"
    if not documents:
        return None, completed.returncode, "process_failed" if completed.returncode else "malformed_json"
    if not isinstance(documents[-1], Mapping) or documents[-1].get("status") != "dry_run":
        return documents, completed.returncode, "incomplete_dry_run"
    if completed.returncode:
        return documents, completed.returncode, "process_failed"
    return documents, completed.returncode, None


def _sanitize_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]", "_", name)


def _review_warnings(documents: list[object]) -> list[Mapping[str, object]]:
    warnings: list[Mapping[str, object]] = []
    for document in documents:
        if isinstance(document, Mapping) and isinstance(document.get("reviewRuleWarnings"), list):
            warnings.extend(entry for entry in document["reviewRuleWarnings"] if isinstance(entry, Mapping))
    return warnings


def _review_material(body: list[object], manifest: Mapping[str, Any]) -> tuple[Path, dict[str, Any]] | None:
    name, version = manifest.get("name"), manifest.get("version")
    if not isinstance(name, str) or not isinstance(version, str):
        return None
    expected = re.compile(rf"{re.escape(_sanitize_name(name))}-[0-9a-f]{{64}}\.json")
    for warning in _review_warnings(body):
        if warning.get("ruleId") != "adversarial-review-report":
            continue
        file_value, skeleton_value = warning.get("file"), warning.get("skeleton")
        if not isinstance(file_value, str) or not isinstance(skeleton_value, str):
            continue
        path = Path(file_value)
        if path.parent != _REVIEW_DIRECTORY or not expected.fullmatch(path.name):
            continue
        try:
            parsed = json.loads(skeleton_value)
        except ValueError:
            continue
        if (isinstance(parsed, dict) and parsed.get("extension") == name and
                parsed.get("version") == version):
            return path, parsed
    return None


def _secure_review_dir() -> int:
    try:
        _REVIEW_DIRECTORY.mkdir(mode=0o700)
    except FileExistsError:
        pass
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(_REVIEW_DIRECTORY, flags)
    info = os.fstat(fd)
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or
            info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
        os.close(fd)
        raise OSError("insecure review directory")
    return fd


def _write_review(path: Path, report: Mapping[str, object]) -> None:
    directory_fd = _secure_review_dir()
    temporary, fd = f".review-{secrets.token_hex(16)}", None
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600,
                     dir_fd=directory_fd)
        remaining = memoryview((json.dumps(report, indent=2) + "\n").encode())
        while remaining:
            remaining = remaining[os.write(fd, remaining):]
        os.fsync(fd)
        os.close(fd)
        fd = None
        os.rename(temporary, path.name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        os.fsync(directory_fd)
    finally:
        if fd is not None:
            os.close(fd)
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except FileNotFoundError:
            pass
        os.close(directory_fd)


def prepare_extension_review(args: Mapping[str, object]) -> dict[str, Any]:
    timeout = _timeout(args.get("timeout"))
    if timeout is None:
        return {"ok": False, "data": None, "error": "invalid_timeout"}
    loaded = _package(args)
    if isinstance(loaded, str):
        return {"ok": False, "data": None, "error": loaded}
    repo, _package_dir, manifest = loaded
    manifest_relative = _relative(args.get("manifest_path"))
    assert manifest_relative is not None
    body, _returncode, error = _dry_run(repo, manifest_relative, timeout)
    if error:
        return {"ok": False, "data": None, "error": error}
    assert body is not None
    material = _review_material(body, manifest)
    if material is None:
        return {"ok": False, "data": None, "error": "review_path_not_found"}
    review_path, skeleton = material
    review, skeleton_dimensions = args.get("review"), skeleton.get("dimensions")
    if not isinstance(review, Mapping) or not isinstance(skeleton_dimensions, list):
        return {"ok": False, "data": {"template": skeleton}, "error": "invalid_review"}
    required_ids: list[str] = []
    for entry in skeleton_dimensions:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("id"), str):
            return {"ok": False, "data": {"template": skeleton}, "error": "invalid_review"}
        required_ids.append(entry["id"])
    dimensions = review.get("dimensions")
    if len(required_ids) != len(set(required_ids)) or not isinstance(dimensions, list):
        return {"ok": False, "data": {"template": skeleton}, "error": "invalid_review"}
    normalized_by_id: dict[str, dict[str, str]] = {}
    for entry in dimensions:
        if not isinstance(entry, Mapping):
            return {"ok": False, "data": None, "error": "invalid_review"}
        identifier, verdict, note = entry.get("id"), entry.get("verdict"), entry.get("note")
        if (not isinstance(identifier, str) or verdict not in _VERDICTS or
                not isinstance(note, str) or len(note.strip()) < 12 or identifier in normalized_by_id):
            return {"ok": False, "data": None, "error": "invalid_review"}
        normalized_by_id[identifier] = {"id": identifier, "verdict": verdict, "note": note.strip()}
    if set(normalized_by_id) != set(required_ids):
        return {"ok": False, "data": None, "error": "invalid_review"}
    reviewed_at = review.get("reviewed_at")
    if not isinstance(reviewed_at, str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT.+", reviewed_at):
        return {"ok": False, "data": None, "error": "invalid_review"}
    report = {"extension": skeleton["extension"], "version": skeleton["version"],
              "reviewedAt": reviewed_at,
              "dimensions": [normalized_by_id[identifier] for identifier in required_ids]}
    try:
        _write_review(review_path, report)
    except OSError:
        return {"ok": False, "data": None, "error": "review_path_not_allowed"}
    rerun, returncode, error = _dry_run(repo, manifest_relative, timeout)
    if error:
        return {"ok": False, "data": None, "error": error}
    assert rerun is not None and returncode == 0
    warnings = _review_warnings(rerun)
    adversarial = [warning for warning in warnings if warning.get("ruleId") == "adversarial-review-report"]
    if adversarial:
        same_path = any(warning.get("file") == str(review_path) for warning in adversarial)
        return {"ok": False, "data": None,
                "error": "review_rejected" if same_path else "stale_review"}
    return {"ok": True,
            "data": {"review_file": review_path.name,
                     "remaining_warnings": _scrub_value(warnings[:100], repo)},
            "error": None}
