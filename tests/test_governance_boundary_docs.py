"""Regression checks for the public Swamp-first governance contract."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GOVERNANCE = ROOT / "docs" / "governance-boundary.md"
README = ROOT / "README.md"


def test_governance_boundary_is_public_and_honest_about_current_scope() -> None:
    governance = GOVERNANCE.read_text(encoding="utf-8")
    readme = README.read_text(encoding="utf-8")
    public_text = governance + readme
    normalized_governance = " ".join(governance.casefold().split())

    for required_statement in (
        "bounded",
        "not comprehensive",
        "does not comprehensively enforce",
        "caller input and agent-generated intent",
        "tool selection and routing",
        "free-form command or process execution",
        "filesystem and repository selection",
        "scheduler and job control",
        "network or remote-service access",
        "plugin lifecycle and configuration",
        "off",
        "audit",
        "enforce",
        "future core routing",
        "provenance",
        "not present today",
        "every tool invocation",
        "acceptance criteria",
    ):
        assert required_statement in normalized_governance

    assert "docs/governance-boundary.md" in readme

    # The governance contract is public documentation, not an operational record.
    for forbidden_marker in (
        "/" + "home/",
        "C:\\" + "Users\\",
        chr(64),
        "http" + "://",
        "https" + "://",
        "tok" + "en=",
    ):
        assert forbidden_marker not in public_text
