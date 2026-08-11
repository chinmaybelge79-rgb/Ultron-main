"""Tests for the Day 4 Action Layer: permission gate, audit log, kill switch."""

from __future__ import annotations

import logging

import pytest

from ultron.action import (
    AuditLog,
    KillSwitch,
    PermissionDenied,
    PermissionGate,
    PermissionTier,
)
from ultron.tools.base import Tool, ToolCall, ToolResult
from ultron.tools.registry import ToolRegistry


class _EchoTool(Tool):
    """Minimal tool whose run records its argument call."""

    name = "echo_read"
    tier = PermissionTier.READ

    def __init__(self, calls=None):
        self.calls = calls if calls is not None else []

    def run(self, arg: str) -> ToolResult:
        self.calls.append(arg)
        return ToolResult(True, f"ok:{arg}")


class _WriteTool(Tool):
    name = "write_file"
    tier = PermissionTier.WRITE
    destructive = False

    def run(self, arg: str) -> ToolResult:
        return ToolResult(True, "wrote")


class _DeleteTool(Tool):
    name = "delete_file"
    tier = PermissionTier.EXECUTE
    destructive = True

    def __init__(self, touched=None):
        self.touched = touched if touched is not None else []

    def run(self, arg: str) -> ToolResult:
        self.touched.append(arg)
        return ToolResult(True, "deleted")


def _make_gate(tmp_path, allowed=None, confirm=lambda text: True):
    audit = AuditLog.at_path(tmp_path / "audit.db")
    kill = KillSwitch(tmp_path / "DISABLED")
    gate = PermissionGate(audit, kill, confirm, allowed_tiers=allowed)
    return audit, kill, gate


def test_all_default_tools_have_tier_and_destructive(config, silent_logging):
    registry = ToolRegistry.build_default(config, None, logging.getLogger("ultron.t"))
    tools = list(registry._tools.values())
    assert tools
    missing = [
        tool.name
        for tool in tools
        if tool.tier is None or tool.destructive is None
    ]
    assert missing == [], f"Tools missing tier/destructive: {missing}"
    # Every tool must be present in the explicit permissions mapping so no
    # tool silently falls back to the safe READ/False default.
    from ultron.tools.registry import _TOOL_PERMISSIONS

    untagged = [name for name in registry.list_tools() if name not in _TOOL_PERMISSIONS]
    assert untagged == [], f"Tools not declared in _TOOL_PERMISSIONS: {untagged}"


def test_read_allowed_execute_blocked(tmp_path):
    audit, kill, gate = _make_gate(tmp_path, allowed={PermissionTier.READ})
    tool = _EchoTool()
    result = gate.invoke(tool, {"arg": "hello"}, source="voice")
    assert result.success is True
    assert result.output == "ok:hello"

    writer = _WriteTool()  # WRITE tier
    with pytest.raises(PermissionDenied) as exc:
        gate.invoke(writer, {"arg": "x"}, source="voice")
    assert "not permitted" in str(exc.value)
    rows = audit.recent()
    assert any("BLOCKED_TIER" in row[4] and row[1] == "write_file" for row in rows)


def test_destructive_requires_confirmation(tmp_path):
    touched = []
    audit, kill, gate = _make_gate(
        tmp_path,
        allowed={PermissionTier.READ, PermissionTier.WRITE, PermissionTier.EXECUTE},
        confirm=lambda text: False,
    )
    tool = _DeleteTool(touched)
    with pytest.raises(PermissionDenied) as exc:
        gate.invoke(tool, {"arg": "/tmp/f"}, source="voice")
    assert "declined" in str(exc.value)
    assert touched == []  # file untouched
    rows = audit.recent()
    assert any("DENIED_BY_USER" in row[4] and row[1] == "delete_file" for row in rows)
def test_destructive_confirmed_executes(tmp_path):
    touched = []
    audit, kill, gate = _make_gate(
        tmp_path,
        allowed={PermissionTier.READ, PermissionTier.WRITE, PermissionTier.EXECUTE},
        confirm=lambda text: True,
    )
    tool = _DeleteTool(touched)
    result = gate.invoke(tool, {"arg": "/tmp/f"}, source="coding_agent")
    assert result.success is True
    assert touched == ["/tmp/f"]
    rows = audit.recent()
    assert any("SUCCESS" in row[4] and row[3] == "coding_agent" for row in rows)


def test_kill_switch_blocks_everything(tmp_path):
    audit, kill, gate = _make_gate(tmp_path)
    kill.engage()
    tool = _EchoTool()
    with pytest.raises(PermissionDenied) as exc:
        gate.invoke(tool, {"arg": "x"}, source="voice")
    assert "Kill switch" in str(exc.value)
    rows = audit.recent()
    assert any("BLOCKED_KILL_SWITCH" in row[4] for row in rows)
    kill.release()
    assert not kill.is_active()


def test_kill_switch_is_active_check(tmp_path):
    kill = KillSwitch(tmp_path / "data" / "DISABLED")
    assert not kill.is_active()
    kill.engage()
    assert kill.is_active()
    kill.release()
    assert not kill.is_active()


def test_audit_records_allowed_and_blocked_once(tmp_path):
    audit, kill, gate = _make_gate(tmp_path, allowed={PermissionTier.READ})
    gate.invoke(_EchoTool(), {"arg": "a"}, source="voice")
    with pytest.raises(PermissionDenied):
        gate.invoke(_WriteTool(), {"arg": "b"}, source="autonomy_loop")
    rows = audit.recent()
    kinds = [row[4] for row in rows]
    assert kinds.count("SUCCESS") == 1
    assert kinds.count("BLOCKED_TIER") == 1
    sources = {row[3] for row in rows}
    assert sources == {"voice", "autonomy_loop"}


def test_registry_routes_through_gate(tmp_path, config, silent_logging):
    audit, kill, gate = _make_gate(tmp_path, allowed={PermissionTier.READ})
    registry = ToolRegistry.build_default(config, None, logging.getLogger("ultron.r"))
    registry.set_permission_gate(gate)

    read_call = _EchoTool()
    registry._tools["echo_read"] = read_call
    ok = registry.execute(ToolCall("echo_read", "hi"), source="voice")
    assert ok.success is True

    # A WRITE-tier tool call should be blocked by the gate and surface as a
    # failed ToolResult (PermissionDenied swallowed by the registry).
    writer = _WriteTool()
    registry._tools["write_file"] = writer
    blocked = registry.execute(ToolCall("write_file", "x"), source="voice")
    assert blocked.success is False
    assert "not permitted" in blocked.output

