"""Regression checks for the public Hermes-core routing/effect-policy proposal."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RFC = ROOT / "docs" / "hermes-core-routing-policy-rfc.md"
PLAN = ROOT / "docs" / "hermes-core-routing-policy-plan.md"


def test_rfc_defines_a_generic_complete_and_bounded_core_contract() -> None:
    rfc = RFC.read_text(encoding="utf-8")
    normalized = " ".join(rfc.casefold().split())

    for required_statement in (
        "status: proposal",
        "generic hermes-core",
        "allow",
        "block",
        "redirect",
        "host-owned audit events",
        "turn requirements",
        "evidence completion",
        "deterministic ordering",
        "redirect loop",
        "policy exception",
        "fail-open",
        "fail-closed",
        "no-policy behavior",
        "public plugin compatibility",
        "scheduler job mutation and run",
        "dashboard/api",
        "plugin direct dispatch",
        "agent-local tools",
        "no-agent scripts",
        "delegation",
        "core changes",
        "current plugin can do",
        "conceptual areas",
        "not present today",
    ):
        assert required_statement in normalized

    # This proposal is deliberately generic; it is not a claim of existing,
    # comprehensive enforcement by this plugin repository.
    assert "swamp-first api" not in normalized
    assert "comprehensively enforce" not in normalized


def test_plan_is_phased_and_has_a_conformance_matrix() -> None:
    plan = PLAN.read_text(encoding="utf-8")
    normalized = " ".join(plan.casefold().split())

    for required_statement in (
        "status: implementation plan",
        "phase 0",
        "phase 1",
        "phase 2",
        "phase 3",
        "phase 4",
        "conformance matrix",
        "unit",
        "integration",
        "compatibility",
        "failure-mode",
        "all relevant ingress and effect boundaries",
        "scheduler job mutation and run",
        "dashboard/api",
        "plugin direct dispatch",
        "agent-local tools",
        "no-agent scripts",
        "delegation",
        "exit criteria",
    ):
        assert required_statement in normalized


def test_proposal_documents_are_public_safe() -> None:
    public_text = RFC.read_text(encoding="utf-8") + PLAN.read_text(encoding="utf-8")

    for forbidden_marker in (
        "/" + "opt/",
        "/" + "home/",
        "c:\\" + "users\\",
        chr(64),
        "http" + "://",
        "https" + "://",
        "tok" + "en=",
        "api" + "_key",
        "password",
        "credential",
    ):
        assert forbidden_marker not in public_text.casefold()
