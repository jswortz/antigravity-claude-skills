#!/usr/bin/env python3
"""
Test Suite for Skill Manager (Package Version)
==============================================
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from antigravity_skills.cli import main as cli_main
from unittest.mock import patch

# Setup paths
PROJECT_ROOT = Path(".").resolve()
TEST_ENV_DIR = PROJECT_ROOT / ".agent" / "test_env"


def run_manager(args, cwd=PROJECT_ROOT, expect_error=False):
    """Runs the skill manager via the installed package command."""
    # Since we are installed in the venv, we can run 'antigravity-skills'
    # But for tests within this environment, calling the python module is safer/easier to mock env vars

    # We will invoke the cli.py directly via subprocess using sys.executable to mock env vars
    # effectively `python -m antigravity_skills.cli ...`

    cmd = [sys.executable, "-m", "antigravity_skills.cli"] + args
    result = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "HOME": str(TEST_ENV_DIR / "home"),
            "PYTHONPATH": str(
                PROJECT_ROOT / "src"
            ),  # Ensure src is in path if not fully installed in test env context
        },
    )

    if expect_error and result.returncode == 0:
        print(f"FAIL: Expected error but got success for {' '.join(args)}")
        print(result.stdout)
        return False
    elif not expect_error and result.returncode != 0:
        print(f"FAIL: Expected success but got error for {' '.join(args)}")
        print(result.stderr)
        return False

    return result


def setup():
    """Prepares the test environment."""
    if TEST_ENV_DIR.exists():
        shutil.rmtree(TEST_ENV_DIR)

    TEST_ENV_DIR.mkdir(parents=True)
    (TEST_ENV_DIR / "home").mkdir()
    (
        TEST_ENV_DIR / "home" / ".gemini"
    ).mkdir()  # Ensure .gemini exists for global rules


def test_source_management():
    """Tests adding and listing skill sources."""
    print("TEST: Source Management")

    # 1. Add Source
    res = run_manager(
        ["add-source", "https://github.com/anthropics/skills", "test-source"]
    )
    if res.returncode != 0:
        return False

    # 2. List Sources
    res = run_manager(["list-sources"])
    if "test-source" not in res.stdout:
        print("FAIL: 'test-source' not found in list-sources output")
        return False

    print("PASS: Source Management")
    return True


def test_workflow_ingestion():
    """Tests ingesting a skill as a workflow."""
    print("TEST: Workflow Ingestion")

    res = run_manager(
        ["ingest", "webapp-testing", "--as", "workflow", "--source", "test-source"]
    )
    if res.returncode != 0:
        return False

    expected_file = PROJECT_ROOT / ".agent" / "workflows" / "webapp-testing.md"
    if not expected_file.exists():
        print(f"FAIL: Workflow file not created at {expected_file}")
        return False

    content = expected_file.read_text()
    if "---" not in content or "description" not in content:
        print("FAIL: Workflow content seems invalid (missing frontmatter)")
        return False

    print("PASS: Workflow Ingestion")
    return True


def test_rule_ingestion_workspace_activation():
    """Tests ingesting a workspace rule with activation metadata."""
    print("TEST: Rule Ingestion (Workspace + Activation)")

    res = run_manager(
        [
            "ingest",
            "webapp-testing",
            "--as",
            "rule",
            "--scope",
            "workspace",
            "--source",
            "test-source",
            "--activation",
            "glob",
            "--glob",
            "**/*.test.js",
        ]
    )
    if res.returncode != 0:
        return False

    expected_file = PROJECT_ROOT / ".agent" / "rules" / "webapp-testing.md"
    if not expected_file.exists():
        print(f"FAIL: Workspace rule file not created at {expected_file}")
        return False

    content = expected_file.read_text()
    if "activation:" not in content or "glob: **/*.test.js" not in content:
        print(
            f"FAIL: Activation metadata missing in {expected_file}. Content:\n{content[:200]}"
        )
        return False

    print("PASS: Rule Ingestion (Workspace + Activation)")
    return True


def test_rule_ingestion_global_idempotency():
    """Tests that global rules updates are idempotent (no duplicates)."""
    print("TEST: Rule Ingestion (Global Idempotency)")

    # Run 1
    res = run_manager(
        [
            "ingest",
            "webapp-testing",
            "--as",
            "rule",
            "--scope",
            "global",
            "--source",
            "test-source",
        ]
    )
    if res.returncode != 0:
        return False

    expected_file = TEST_ENV_DIR / "home" / ".gemini" / "GEMINI.md"
    if not expected_file.exists():
        print(f"FAIL: Global rule file not created at {expected_file}")
        return False

    content_v1 = expected_file.read_text()
    if "<!-- ANTHROPIC_SKILL_START: webapp-testing -->" not in content_v1:
        print("FAIL: Global rule markers missing")
        return False

    # Run 2 (Should update/replace, not append duplicate)
    res = run_manager(
        [
            "ingest",
            "webapp-testing",
            "--as",
            "rule",
            "--scope",
            "global",
            "--source",
            "test-source",
        ]
    )
    if res.returncode != 0:
        return False

    content_v2 = expected_file.read_text()

    # Count occurrences of the marker
    marker_count = content_v2.count("<!-- ANTHROPIC_SKILL_START: webapp-testing -->")
    if marker_count != 1:
        print(f"FAIL: Expected 1 occurrence of marker, found {marker_count}")
        return False
    print("PASS: Rule Ingestion (Global Idempotency)")
    return True


def test_crud_operations():
    """Tests list and remove commands."""
    print("TEST: CRUD Operations (List/Remove)")

    # Setup: Ensure we have artifacts to list/remove
    # We rely on previous tests having created:
    # - .agent/workflows/webapp-testing.md
    # - .agent/rules/webapp-testing.md
    # - Global rule in mocked GEMINI.md

    # 1. LIST
    res = run_manager(["list"])
    if res.returncode != 0:
        return False

    # Check output for known artifacts
    stdout = res.stdout
    if "webapp-testing" not in stdout:
        print(f"FAIL: 'webapp-testing' not found in list output. Output:\n{stdout}")
        return False

    if "INSTALLED GLOBAL RULES" not in stdout:
        print("FAIL: List output format incorrect (missing Global section)")
        return False

    # 2. REMOVE WORKFLOW
    res = run_manager(["remove", "webapp-testing", "--type", "workflow"])
    if res.returncode != 0:
        return False

    if (PROJECT_ROOT / ".agent" / "workflows" / "webapp-testing.md").exists():
        print("FAIL: Workflow file NOT deleted after remove command")
        return False

    # 3. REMOVE WORKSPACE RULE
    res = run_manager(
        ["remove", "webapp-testing", "--type", "rule", "--scope", "workspace"]
    )
    if res.returncode != 0:
        return False

    if (PROJECT_ROOT / ".agent" / "rules" / "webapp-testing.md").exists():
        print("FAIL: Workspace rule file NOT deleted after remove command")
        return False

    # 4. REMOVE GLOBAL RULE
    res = run_manager(
        ["remove", "webapp-testing", "--type", "rule", "--scope", "global"]
    )
    if res.returncode != 0:
        return False

    gemini_file = TEST_ENV_DIR / "home" / ".gemini" / "GEMINI.md"
    content = gemini_file.read_text()
    if "<!-- ANTHROPIC_SKILL_START: webapp-testing -->" in content:
        print("FAIL: Global rule block NOT removed from GEMINI.md")
        return False

    print("PASS: CRUD Operations")
    return True


def main():
    setup()

    tests = [
        test_source_management,
        test_workflow_ingestion,
        test_rule_ingestion_workspace_activation,
        test_rule_ingestion_global_idempotency,
        test_crud_operations,
    ]

    passed = 0
    for t in tests:
        if t():
            passed += 1
        else:
            print("Tests aborted due to failure.")
            break

    print(f"\nSummary: {passed}/{len(tests)} tests passed.")

    # Cleanup (Optional, maybe keep for inspection)
    # shutil.rmtree(TEST_ENV_DIR)


if __name__ == "__main__":
    main()
