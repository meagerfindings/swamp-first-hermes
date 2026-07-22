"""Static checks for the public, private-install documentation."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLATION = ROOT / "docs" / "installation.md"
README = ROOT / "README.md"


def test_private_installation_documentation_is_complete_and_public() -> None:
    installation = INSTALLATION.read_text(encoding="utf-8")
    readme = README.read_text(encoding="utf-8")

    for required_statement in (
        "$HERMES_HOME/plugins/swamp_first_hermes",
        "plugin.yaml",
        "__init__.py",
        "hermes plugins enable swamp_first_hermes",
        "hermes plugins list",
        "swamp_model_search",
        "swamp_workflow_search",
        "repository_path",
        "SWAMP_FIRST_POLICY_MODE",
        "direct scheduler bypasses",
        "scheduled agent jobs",
        "`cronjob`",
        "`create` or `update`",
        "`enabled_toolsets`",
        "`swamp_first`",
        "`no_agent`",
        "comprehensively enforce all Swamp-first routing",
        "local observation only",
        "not immutable provenance",
        "not a comprehensive audit",
        "swamp_definition_write",
        "swamp_workflow_set_schedule",
        "confirmed",
    ):
        assert required_statement in installation

    assert "docs/installation.md" in readme
    assert "deployment, scheduler, or delivery" in readme
    for required_statement in (
        "scheduled agent jobs",
        "`cronjob`",
        "`create` or `update`",
        "`enabled_toolsets`",
        "`swamp_first`",
        "`no_agent`",
        "does not prove that an agent uses Swamp",
        "does not parse shell text",
        "swamp_definition_write",
        "swamp_workflow_set_schedule",
        "confirmed",
    ):
        assert required_statement in readme

    # Public examples must use a variable or a relative path, never a personal
    # home path, host, token, or a literal infrastructure URL.
    public_text = installation + readme
    # Keep these privacy-negative fixtures dynamic so credential scanners do not
    # mistake the test data for a published assignment.  Each expression still
    # evaluates to the exact marker the audit must reject.
    for forbidden_example in (
        "/" + "home/",
        "C:\\" + "Users\\",
        chr(64),
        "http" + "://",
        "https" + "://",
        "tok" + "en=",
    ):
        assert forbidden_example not in public_text
