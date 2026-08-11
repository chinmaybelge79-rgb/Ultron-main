"""Day 7 tests: deployment hardening, packaging, and scripts."""

from __future__ import annotations

import os
import plistlib
from pathlib import Path

import pytest

from ultron.action.permissions import PermissionTier
from ultron.action.gate import PermissionGate, KillSwitch, PermissionDenied
from ultron.action.audit import AuditLog
from ultron.security import (
    ScopeViolation,
    allowed_fs_roots,
    allowed_network_domains,
    validate_fs_path,
    validate_network_domain,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Filesystem scope hardening
# ---------------------------------------------------------------------------

class TestFilesystemScope:
    def test_home_dir_allowed(self, tmp_path):
        inside = Path.home() / "some-file.txt"
        assert validate_fs_path(inside) == inside.resolve()

    def test_etc_blocked(self):
        with pytest.raises(ScopeViolation):
            validate_fs_path("/etc/passwd")

    def test_system_blocked(self):
        with pytest.raises(ScopeViolation):
            validate_fs_path("/System/Library/CoreServices")

    def test_other_users_dir_blocked(self):
        with pytest.raises(ScopeViolation):
            validate_fs_path("/Users/someone_else/secret.txt")

    def test_root_blocked(self):
        with pytest.raises(ScopeViolation):
            validate_fs_path("/var/root/data")

    def test_relative_path_under_home_allowed(self):
        # A ~-path expands under home, which is on the default allowlist.
        resolved = validate_fs_path("~/Documents/notes.txt")
        assert str(resolved).startswith(str(Path.home()))

    def test_env_extra_root(self, tmp_path, monkeypatch):
        outside = Path("/tmp/ultron_extra_root/file.txt")
        monkeypatch.setenv("ULTRON_FS_ALLOW_ROOTS", "/tmp/ultron_extra_root")
        assert validate_fs_path(outside) == outside.resolve()

    def test_explicit_extra_root(self, tmp_path):
        target = tmp_path / "allowed" / "thing.txt"
        assert validate_fs_path(target, extra_roots=(tmp_path,)) == target.resolve()


# ---------------------------------------------------------------------------
# Network egress allowlist
# ---------------------------------------------------------------------------

class TestNetworkAllowlist:
    def test_localhost_allowed(self):
        assert validate_network_domain("http://localhost:11434/api/chat") == "localhost"
        assert validate_network_domain("127.0.0.1") == "127.0.0.1"

    def test_unauthorized_host_blocked(self):
        with pytest.raises(ScopeViolation):
            validate_network_domain("https://evil.example.com/exfiltrate")

    def test_allowed_domain_via_env(self, monkeypatch):
        monkeypatch.setenv("ULTRON_NET_ALLOW_DOMAINS", "openrouter.ai")
        assert (
            validate_network_domain("https://openrouter.ai/api/v1/chat/completions")
            == "openrouter.ai"
        )

    def test_subdomain_of_allowed_domain(self, monkeypatch):
        monkeypatch.setenv("ULTRON_NET_ALLOW_DOMAINS", "openrouter.ai")
        assert validate_network_domain("https://api.openrouter.ai/v1") == "api.openrouter.ai"

    def test_bare_host_without_scheme(self, monkeypatch):
        monkeypatch.setenv("ULTRON_NET_ALLOW_DOMAINS", "example.com")
        assert validate_network_domain("example.com") == "example.com"

    def test_default_allowlist_is_local_only(self, monkeypatch):
        monkeypatch.delenv("ULTRON_NET_ALLOW_DOMAINS", raising=False)
        assert "openrouter.ai" not in allowed_network_domains()
        assert "localhost" in allowed_network_domains()


# ---------------------------------------------------------------------------
# Packaging: launchd plist
# ---------------------------------------------------------------------------

class TestPlist:
    def _load(self):
        path = PROJECT_ROOT / "packaging" / "com.ultron.agent.plist"
        with path.open("rb") as fh:
            return plistlib.load(fh)

    def test_plist_is_valid(self):
        plist = self._load()
        assert plist["Label"] == "com.ultron.agent"

    def test_runs_daemon_module(self):
        plist = self._load()
        args = plist["ProgramArguments"]
        assert args[0].endswith("/.venv/bin/python")
        assert args[-2:] == ["-m", "ultron.daemon"]

    def test_keepalive_and_runatload(self):
        plist = self._load()
        assert plist["RunAtLoad"] is True
        assert plist["KeepAlive"] is True

    def test_local_only_routing_pinned(self):
        plist = self._load()
        env = plist["EnvironmentVariables"]
        assert env["ULTRON_ROUTING_POLICY"] == "local_only", (
            "launchd daemon must never fall back to cloud providers"
        )
        assert "ULTRON_PROJECT_DIR" in env

    def test_project_dir_placeholder_present(self):
        # bootstrap.sh substitutes __PROJECT_DIR__ with the real path via sed.
        raw = (PROJECT_ROOT / "packaging" / "com.ultron.agent.plist").read_text()
        assert "__PROJECT_DIR__" in raw

    def test_sed_substitution_renders_valid_plist(self, tmp_path):
        """Simulate bootstrap.sh's sed replacement -> still a valid plist."""
        raw = (PROJECT_ROOT / "packaging" / "com.ultron.agent.plist").read_text()
        rendered = raw.replace("__PROJECT_DIR__", str(PROJECT_ROOT))
        out = tmp_path / "rendered.plist"
        out.write_text(rendered)
        with out.open("rb") as fh:
            plist = plistlib.load(fh)
        assert plist["ProgramArguments"][0] == str(
            PROJECT_ROOT / ".venv" / "bin" / "python"
        )
        assert plist["EnvironmentVariables"]["ULTRON_PROJECT_DIR"] == str(PROJECT_ROOT)


# ---------------------------------------------------------------------------
# Scripts: bootstrap / kill / enable / rollback
# ---------------------------------------------------------------------------

class TestScripts:
    def _read(self, name: str) -> str:
        path = PROJECT_ROOT / "scripts" / name
        assert path.exists(), f"scripts/{name} missing"
        return path.read_text()

    @pytest.mark.parametrize(
        "name",
        ["bootstrap.sh", "kill_ultron.sh", "enable_ultron.sh", "rollback.sh"],
    )
    def test_script_is_executable(self, name):
        assert os.access(PROJECT_ROOT / "scripts" / name, os.X_OK)

    def test_bootstrap_checks_ollama(self):
        body = self._read("bootstrap.sh")
        assert "ollama" in body
        assert "set -e" in body  # fail-fast

    def test_bootstrap_runs_tests_before_install(self):
        body = self._read("bootstrap.sh")
        # pytest must run before the plist install step.
        assert body.index("pytest") < body.index("LaunchAgents")

    def test_bootstrap_installs_launchd_plist(self):
        body = self._read("bootstrap.sh")
        assert "com.ultron.agent.plist" in body
        assert "LaunchAgents" in body
        assert "launchctl load" in body

    def test_bootstrap_substitutes_project_dir(self):
        body = self._read("bootstrap.sh")
        assert "__PROJECT_DIR__" in body and "sed" in body

    def test_kill_script_engages_sentinel_and_unloads(self):
        body = self._read("kill_ultron.sh")
        assert "DISABLED" in body
        assert "launchctl unload" in body

    def test_enable_script_releases_sentinel_and_loads(self):
        body = self._read("enable_ultron.sh")
        assert "DISABLED" in body and ("rm" in body or "rm -f" in body)
        assert "launchctl load" in body

    def test_rollback_script_unloads_resets_reloads(self):
        body = self._read("rollback.sh")
        assert "launchctl unload" in body
        assert "reset --hard" in body
        assert "launchctl load" in body


# ---------------------------------------------------------------------------
# Default tier policy (least privilege on first install)
# ---------------------------------------------------------------------------

class TestDefaultTiers:
    def test_gate_defaults_to_read_write(self, tmp_path):
        import sqlite3

        audit = AuditLog(sqlite3.connect(":memory:"))
        kill = KillSwitch(tmp_path / "DISABLED")
        gate = PermissionGate(audit, kill, confirm_fn=lambda m: True)
        tiers = gate.allowed_tiers()
        assert tiers == {PermissionTier.READ, PermissionTier.WRITE}

    def test_execute_blocked_by_default(self, tmp_path):
        import sqlite3

        audit = AuditLog(sqlite3.connect(":memory:"))
        kill = KillSwitch(tmp_path / "DISABLED")
        gate = PermissionGate(audit, kill, confirm_fn=lambda m: True)

        class _T:
            name = "run_command"
            tier = PermissionTier.EXECUTE
            destructive = True

            def fn(self):
                return "ran"

        with pytest.raises(PermissionDenied):
            gate.invoke(_T(), {}, source="autonomy_loop")


# ---------------------------------------------------------------------------
# Bootstrap simulation (no actual launchd install in tests)
# ---------------------------------------------------------------------------

class TestBootstrapSimulation:
    def test_prerequisites_present(self):
        """bootstrap.sh's documented prerequisites exist in this environment."""
        import shutil

        assert shutil.which("python3") is not None
        # The project venv bootstrap targets exists (Day 7 setup already ran).
        assert (PROJECT_ROOT / ".venv" / "bin" / "python").exists()

    def test_rendered_plist_points_at_real_python(self):
        python_path = PROJECT_ROOT / ".venv" / "bin" / "python"
        assert python_path.exists(), "plist's interpreter must exist post-bootstrap"


# ---------------------------------------------------------------------------
# Scope enforcement is load-bearing inside a real tool (end-to-end)
# ---------------------------------------------------------------------------

class TestScopeEnforcementLoadBearing:
    def _run_tool(self, tool, arg):
        from ultron.tools.filesystem import enable_scope_enforcement
        import ultron.tools.filesystem as fsmod
        from ultron.tools.base import ToolCall
        from ultron.tools.registry import ToolRegistry
        import logging

        enable_scope_enforcement()
        try:
            registry = ToolRegistry([tool], logging.getLogger("t"))
            return registry.execute(ToolCall(name=tool.name, arg=arg), source="voice")
        finally:
            # Scope enforcement is process-global; reset for other tests.
            fsmod._SCOPE_ENFORCED = False
            fsmod._EXTRA_ROOTS = ()

    def test_write_file_blocked_outside_scope(self):
        from ultron.tools.filesystem import WriteFileTool

        result = self._run_tool(WriteFileTool(), "/etc/ultron_escape.txt :: x")
        assert result.success is False
        assert "outside the allowed filesystem scope" in result.output

    def test_read_file_blocked_outside_scope(self):
        from ultron.tools.filesystem import ReadFileTool

        result = self._run_tool(ReadFileTool(), "/etc/passwd")
        assert result.success is False
        assert "outside the allowed filesystem scope" in result.output
