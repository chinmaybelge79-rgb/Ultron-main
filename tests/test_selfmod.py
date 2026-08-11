"""Tests for the Day 6 self-modification safety machinery."""

from __future__ import annotations

import logging

import pytest

from ultron.action.permissions import PermissionTier
from ultron.selfmod.edit_lock import EditLock
from ultron.selfmod.git_guard import GitGuard
from ultron.selfmod.self_modify import SelfModifyTool, _in_scope


def _git_repo(tmp_path):
    """Create a repo with a tracked file, returning (repo, file)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    from ultron.selfmod.git_guard import subprocess

    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "ultron@test"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Ultron Test"],
        cwd=repo,
        check=True,
    )
    return repo


def _fake_tests(passed=True, tail="ok"):
    def run(repo, logger):
        return passed, tail

    return run


# ---------------------------------------------------------------------------
# Scope allowlist
# ---------------------------------------------------------------------------


def test_in_scope_accepts_allowed_files():
    assert _in_scope("ultron/persona/style_rules.py")
    assert _in_scope("ultron/config.py")
    assert _in_scope("ultron/probes/system_probe.py")
    assert _in_scope("ultron/memory/store.py")


def test_in_scope_rejects_protected_files():
    assert not _in_scope("ultron/action/gate.py")
    assert not _in_scope("ultron/action/permissions.py")
    assert not _in_scope("ultron/selfmod/self_modify.py")
    assert not _in_scope("tests/test_selfmod.py")
    assert not _in_scope(".env")
    assert not _in_scope("packaging/com.ultron.agent.plist")
    assert not _in_scope("ultron/core/assistant.py")


# ---------------------------------------------------------------------------
# EditLock
# ---------------------------------------------------------------------------


def test_edit_lock_refuses_when_coding_agent_active(tmp_path):
    lock = EditLock(tmp_path)
    lock.coding_agent_lock_path.touch()
    with pytest.raises(RuntimeError):
        with lock.ultron_editing():
            pass
    assert not lock.ultron_lock_path.exists()


def test_edit_lock_releases_after_editing(tmp_path):
    lock = EditLock(tmp_path)
    with lock.ultron_editing():
        assert lock.ultron_lock_path.exists()
    assert not lock.ultron_lock_path.exists()


# ---------------------------------------------------------------------------
# GitGuard
# ---------------------------------------------------------------------------


def test_git_guard_snapshot_then_rollback(tmp_path):
    repo = _git_repo(tmp_path)
    target = repo / "ultron" / "persona" / "style_rules.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("OLD")

    guard = GitGuard(repo)
    pre_sha = guard.snapshot("before edit")
    target.write_text("NEW CONTENT")
    guard.rollback_to(pre_sha)
    assert target.read_text() == "OLD"


# ---------------------------------------------------------------------------
# SelfModifyTool
# ---------------------------------------------------------------------------


def _tool(tmp_path, passed=True, tail="ok", repo=None):
    repo = repo or _git_repo(tmp_path)
    for rel in ("ultron/persona/style_rules.py",):
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text("OLD")
    tool = SelfModifyTool(
        repo,
        git_guard=GitGuard(repo),
        edit_lock=EditLock(repo),
        run_tests=_fake_tests(passed=passed, tail=tail),
        logger=logging.getLogger("ultron.selfmod.test"),
    )
    return repo, tool


def test_self_edit_format_error(tmp_path):
    repo, tool = _tool(tmp_path)
    result = tool.run("only_a_path")
    assert not result.success


def test_self_edit_out_of_scope_refused(tmp_path):
    repo = _git_repo(tmp_path)
    tool = SelfModifyTool(
        repo,
        git_guard=GitGuard(repo),
        edit_lock=EditLock(repo),
        run_tests=_fake_tests(),
    )
    result = tool.run("ultron/action/gate.py :: reason :: print('hax')")
    assert not result.success
    assert "outside" in result.output
    assert not (repo / "ultron" / "action" / "gate.py").exists()


def test_self_edit_escape_refused(tmp_path):
    repo, tool = _tool(tmp_path)
    result = tool.run("../outside.txt :: reason :: x")
    assert not result.success
    assert "escapes" in result.output


def test_self_edit_successful_write(tmp_path):
    repo, tool = _tool(tmp_path)
    target = repo / "ultron" / "persona" / "style_rules.py"
    result = tool.run(
        f"{target.relative_to(repo)} :: tune dry wit :: NEW PERSONA"
    )
    assert result.success
    assert target.read_text() == "NEW PERSONA"
    assert not (repo / ".ultron-selfedit-lock").exists()


def test_self_edit_rolls_back_on_failed_tests(tmp_path):
    repo, tool = _tool(tmp_path, passed=False, tail="FAILED TEST")
    target = repo / "ultron" / "persona" / "style_rules.py"
    result = tool.run(
        f"{target.relative_to(repo)} :: risky change :: BROKEN"
    )
    assert not result.success
    assert "rolled back" in result.output
    assert target.read_text() == "OLD"


def test_self_edit_refused_when_coding_agent_holds_lock(tmp_path):
    repo = _git_repo(tmp_path)
    (repo / ".coding-agent-lock").touch()
    tool = SelfModifyTool(
        repo,
        git_guard=GitGuard(repo),
        edit_lock=EditLock(repo),
        run_tests=_fake_tests(),
    )
    result = tool.run("ultron/config.py :: reason :: x = 1")
    assert not result.success
    assert "Coding agent lock" in result.output


# ---------------------------------------------------------------------------
# Registry tagging
# ---------------------------------------------------------------------------


def test_self_modify_tool_tagged_system_destructive(tmp_path, config):
    from ultron.tools.registry import ToolRegistry

    registry = ToolRegistry.build_default(config, object(), logging.getLogger("t"))
    tool = registry.get_tool("self_modify_code")
    assert tool is not None
    assert tool.tier is PermissionTier.SYSTEM
    assert tool.destructive is True
