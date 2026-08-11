"""Assistant tests: tool-call parsing, online/offline handling, history."""

from __future__ import annotations

import logging

from ultron.core.assistant import Assistant
from ultron.tools.base import Tool, ToolCall, ToolResult
from ultron.tools.registry import ToolRegistry
from ultron.utils import LLMError


class StubLLM:
    def __init__(self, replies, configured=True):
        self._replies = list(replies)
        self.calls = 0
        self._configured = configured

    @property
    def configured(self):
        return self._configured

    def chat(self, messages):
        self.calls += 1
        if not self._replies:
            raise LLMError("no more replies")
        return self._replies.pop(0)


class StubFinalTool(Tool):
    name = "stub_final"
    description = "A deterministic final tool."
    result_is_final = True

    def run(self, arg):
        return ToolResult(True, f"ran {arg}")


class StubNonFinalTool(Tool):
    name = "stub_nonfinal"
    description = "A tool needing follow-up phrasing."

    def run(self, arg):
        return ToolResult(True, "long output " + "x" * 500)


class StubOpenTool(Tool):
    name = "open_application"
    result_is_final = True

    def run(self, arg):
        return ToolResult(True, f"opened {arg}")


class StubRememberTool(Tool):
    name = "remember"
    result_is_final = True

    def __init__(self, memory):
        self._memory = memory

    def run(self, arg):
        self._memory.remember_fact(arg)
        return ToolResult(True, "Remembered.")


def _registry():
    return ToolRegistry(
        [StubFinalTool(), StubNonFinalTool()],
        logging.getLogger("ultron.tools.test"),
    )


def _assistant(config, memory, llm=None, registry=None):
    logger = logging.getLogger("ultron.assistant.test")
    logger.disabled = True
    return Assistant(
        config,
        memory,
        llm or StubLLM([]),
        registry or _registry(),
        logger,
    )


# ---------------------------------------------------------------------------
# _parse_tool_call
# ---------------------------------------------------------------------------


def test_parse_bare_json():
    call = Assistant._parse_tool_call('{"tool": "open_application", "arg": "Safari"}')
    assert call == ToolCall("open_application", "Safari")


def test_parse_json_with_whitespace():
    call = Assistant._parse_tool_call('  \n {"tool": "run_command", "arg": "ls"}  ')
    assert call == ToolCall("run_command", "ls")


def test_parse_embedded_in_text():
    reply = 'Sure! Here you go: {"tool": "search_google", "arg": "coffee"} Enjoy!'
    call = Assistant._parse_tool_call(reply)
    assert call == ToolCall("search_google", "coffee")


def test_parse_scanner_handles_nested_object():
    reply = 'text {"tool": "run_command", "arg": {"x": 1}} tail'
    call = Assistant._parse_tool_call(reply)
    assert call is not None
    assert call.name == "run_command"


def test_parse_nested_braces_in_arg():
    reply = '{"tool": "run_command", "arg": "echo \'{\'"}'
    call = Assistant._parse_tool_call(reply)
    assert call is not None
    assert call.name == "run_command"


def test_parse_escaped_quotes():
    reply = '{"tool": "write_file", "arg": "a.txt :: he said \\"hi\\""}'
    call = Assistant._parse_tool_call(reply)
    assert call is not None
    assert 'he said "hi"' in call.arg


def test_parse_no_tool_key():
    assert Assistant._parse_tool_call('{"name": "x", "value": 1}') is None


def test_parse_not_json():
    assert Assistant._parse_tool_call("just plain text") is None


def test_parse_empty():
    assert Assistant._parse_tool_call("") is None
    assert Assistant._parse_tool_call(None) is None


def test_parse_tool_call_numeric_arg():
    call = Assistant._parse_tool_call('{"tool": "x", "arg": 42}')
    assert call == ToolCall("x", "42")


def test_parse_embedded_json_missing_tool():
    assert Assistant._parse_tool_call("text {'not': 'a tool'} more text") is None


# ---------------------------------------------------------------------------
# _handle_offline
# ---------------------------------------------------------------------------


def test_handle_offline_routes_and_executes(config, memory):
    llm = StubLLM([])
    registry = ToolRegistry(
        [StubRememberTool(memory)], logging.getLogger("ultron.tools.test")
    )
    assistant = _assistant(config, memory, llm, registry)
    reply = assistant._handle_offline("remember that my dog is named Rex")
    assert "Done, sir" in reply
    assert memory.search_facts("Rex") == ["that my dog is named Rex"]


def test_handle_offline_no_route(config, memory):
    assistant = _assistant(config, memory, StubLLM([]))
    reply = assistant._handle_offline("tell me a story")
    assert "offline" in reply.lower()


# ---------------------------------------------------------------------------
# _handle_online
# ---------------------------------------------------------------------------


def test_handle_online_plain_reply(config, memory):
    llm = StubLLM(["The sky is blue, sir."])
    assistant = _assistant(config, memory, llm)
    reply = assistant._handle_online("what color is the sky")
    assert reply == "The sky is blue, sir."
    assert llm.calls == 1


def test_handle_online_final_tool_no_followup(config, memory):
    llm = StubLLM(['{"tool": "stub_final", "arg": "hello"}'])
    assistant = _assistant(config, memory, llm)
    reply = assistant._handle_online("do the thing")
    assert llm.calls == 1
    assert "Done, sir." in reply
    assert "ran hello" in reply


def test_handle_online_final_tool_output_truncated(config, memory):
    class LongFinalTool(Tool):
        name = "long_final"
        result_is_final = True

        def run(self, arg):
            return ToolResult(True, "y" * 1000)

    registry = ToolRegistry([LongFinalTool()], logging.getLogger("ultron.tools.test"))
    llm = StubLLM(['{"tool": "long_final", "arg": ""}'])
    logger = logging.getLogger("ultron.assistant.test")
    logger.disabled = True
    assistant = Assistant(config, memory, llm, registry, logger)
    reply = assistant._handle_online("go")
    assert len(reply) <= 131


def test_handle_online_nonfinal_tool_followup(config, memory):
    llm = StubLLM(
        ['{"tool": "stub_nonfinal", "arg": "x"}', "It did a lot of work, sir."]
    )
    assistant = _assistant(config, memory, llm)
    reply = assistant._handle_online("do it")
    assert llm.calls == 2
    assert reply == "It did a lot of work, sir."


def test_handle_online_tool_failure(config, memory):
    class FailingTool(Tool):
        name = "failing_tool"

        def run(self, arg):
            return ToolResult(False, "permission denied")

    registry = ToolRegistry([FailingTool()], logging.getLogger("ultron.tools.test"))
    llm = StubLLM(['{"tool": "failing_tool", "arg": "x"}'])
    logger = logging.getLogger("ultron.assistant.test")
    logger.disabled = True
    assistant = Assistant(config, memory, llm, registry, logger)
    reply = assistant._handle_online("do it")
    assert "didn't work" in reply
    assert llm.calls == 1


def test_handle_online_llm_error_message(config, memory):
    class BrokenLLM(StubLLM):
        def chat(self, messages):
            raise LLMError("server down")

    assistant = _assistant(config, memory, BrokenLLM([]))
    reply = assistant._handle_online("hello")
    assert "trouble" in reply


# ---------------------------------------------------------------------------
# handle_command (full path, offline mode)
# ---------------------------------------------------------------------------


def test_handle_command_offline_without_llm(config, memory, monkeypatch):
    monkeypatch.setattr("ultron.core.assistant.is_online", lambda timeout=2.0: False)
    registry = ToolRegistry([StubOpenTool()], logging.getLogger("ultron.tools.test"))
    assistant = _assistant(config, memory, StubLLM([]), registry)
    reply = assistant.handle_command("open Safari")
    assert "Done, sir" in reply
    assert "opened Safari" in reply


def test_handle_command_records_exchange(config, memory, monkeypatch):
    monkeypatch.setattr("ultron.core.assistant.is_online", lambda timeout=2.0: False)
    assistant = _assistant(config, memory, StubLLM([]))
    assistant.handle_command("remember that cats are awesome")
    assert len(assistant._history) == 2
    assert memory.recent_summaries()


# ---------------------------------------------------------------------------
# history hygiene (C13)
# ---------------------------------------------------------------------------


def test_history_never_contains_raw_json(config, memory, monkeypatch):
    monkeypatch.setattr("ultron.core.assistant.is_online", lambda timeout=2.0: True)
    llm = StubLLM(['{"tool": "stub_final", "arg": "x"}'])
    assistant = _assistant(config, memory, llm)
    assistant.handle_command("do it")
    for message in assistant._history:
        content = message["content"]
        assert '{"tool"' not in content


def test_history_keeps_plain_replies(config, memory, monkeypatch):
    monkeypatch.setattr("ultron.core.assistant.is_online", lambda timeout=2.0: True)
    llm = StubLLM(["All done, sir."])
    assistant = _assistant(config, memory, llm)
    assistant.handle_command("hello")
    assert assistant._history[-1]["content"] == "All done, sir."


def test_history_capped(config, memory, monkeypatch):
    monkeypatch.setattr("ultron.core.assistant.is_online", lambda timeout=2.0: True)
    llm = StubLLM(["ok"] * 50)
    assistant = _assistant(config, memory, llm)
    for _ in range(25):
        assistant.handle_command("ping")
    assert len(assistant._history) <= 40


# ---------------------------------------------------------------------------
# offline mode gate (handle_command path selection)
# ---------------------------------------------------------------------------


def test_handle_command_uses_offline_when_no_llm_key(config, memory, monkeypatch):
    monkeypatch.setattr("ultron.core.assistant.is_online", lambda timeout=2.0: True)
    llm = StubLLM(["should never be used"], configured=False)
    assistant = _assistant(config, memory, llm)
    reply = assistant.handle_command("tell me a joke")
    assert "offline" in reply.lower()
    assert llm.calls == 0


def test_handle_command_uses_local_llm_when_offline(config, memory, monkeypatch):
    monkeypatch.setattr("ultron.core.assistant.is_online", lambda timeout=2.0: False)

    class LocalLLM(StubLLM):
        local_available = True

    llm = LocalLLM(["Replied via local brain."])
    assistant = _assistant(config, memory, llm)
    reply = assistant.handle_command("hello")
    assert reply == "Replied via local brain."
    assert llm.calls == 1
