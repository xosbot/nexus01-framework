"""Tests for shell exec security — command injection payloads."""

import pytest

from tools.shell_exec import _is_safe_command, run_command


class TestCommandInjection:
    def test_semicolon_injection_rejected(self):
        safe, reason = _is_safe_command("echo hi; rm -rf /tmp/x")
        assert not safe
        assert "metacharacters" in reason.lower()

    def test_pipe_injection_rejected(self):
        safe, reason = _is_safe_command("echo hi | cat /etc/passwd")
        assert not safe
        assert "metacharacters" in reason.lower()

    def test_backtick_injection_rejected(self):
        safe, reason = _is_safe_command("echo `whoami`")
        assert not safe
        assert "metacharacters" in reason.lower()

    def test_dollar_paren_injection_rejected(self):
        safe, reason = _is_safe_command("echo $(whoami)")
        assert not safe
        assert "metacharacters" in reason.lower()

    def test_and_and_injection_rejected(self):
        safe, reason = _is_safe_command("echo hi && rm -rf /tmp/x")
        assert not safe
        assert "metacharacters" in reason.lower()

    def test_or_or_injection_rejected(self):
        safe, reason = _is_safe_command("echo hi || rm -rf /tmp/x")
        assert not safe
        assert "metacharacters" in reason.lower()

    def test_ampersand_background_rejected(self):
        safe, reason = _is_safe_command("echo hi & rm -rf /tmp/x")
        assert not safe
        assert "metacharacters" in reason.lower()

    def test_redirect_rejected(self):
        safe, reason = _is_safe_command("echo hi > /tmp/x")
        assert not safe
        assert "metacharacters" in reason.lower()

    def test_semicolon_only_payload_rejected(self):
        safe, reason = _is_safe_command("; rm -rf /")
        assert not safe

    def test_subshell_injection_rejected(self):
        safe, reason = _is_safe_command("$(rm -rf /)")
        assert not safe


class TestAllowedCommands:
    def test_simple_echo_allowed(self):
        safe, _ = _is_safe_command("echo hello")
        assert safe

    def test_simple_ls_allowed(self):
        safe, _ = _is_safe_command("ls -la")
        assert safe

    def test_unknown_command_rejected(self):
        safe, reason = _is_safe_command("nmap -sV target")
        assert not safe
        assert "not in allowlist" in reason

    def test_empty_command_rejected(self):
        safe, reason = _is_safe_command("")
        assert not safe
        assert "empty" in reason.lower()

    def test_dangerous_path_rejected(self):
        safe, reason = _is_safe_command("cat /etc/passwd")
        assert not safe
        assert "restricted" in reason

    @pytest.mark.asyncio
    async def test_injection_payload_not_executed(self):
        result = await run_command("echo hi; rm -rf /tmp/nonexistent_test_dir_xyz", timeout=5)
        assert result.get("exit_code") == -1
        assert "error" in result
