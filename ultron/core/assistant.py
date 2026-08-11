"""Core assistant brain: LLM client, tool routing, and reply generation.

The :class:`OpenRouterClient` talks to the OpenRouter API with retry
logic and structured errors. The :class:`Assistant` turns a transcribed
user command into a spoken reply, optionally executing a tool along the
way, and maintains session history plus persistent memory.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ultron.config import Config
from ultron.core.llm import OpenRouterProvider, ProviderRouter
from ultron.memory.store import MemoryStore
from ultron.monitoring import Metrics, get_metrics
from ultron.persona.engine import PersonaEngine
from ultron.tools.base import ToolCall
from ultron.tools.registry import ToolRegistry
from ultron.utils import (
    LLMError,
    clean_for_speech,
    is_online,
    truncate,
)

# OpenRouterClient for backwards compatibility with tests and existing imports
OpenRouterClient = OpenRouterProvider

_SYSTEM_PROMPT_TEMPLATE = (
    """You are Ultron, a highly capable macOS voice assistant """
    """inspired by JARVIS.
You speak like a butler: concise, confident, courteous, and a little witty.
You address the operator as "sir".

Rules:
1. Keep spoken replies under two sentences. No markdown, no bullets, no
   emojis, no code blocks — your reply is spoken aloud.
2. If the request needs a real-world action, reply with ONLY this JSON
   object on a single line and nothing else:
   {{"tool": "<tool name>", "arg": "<single argument>"}}
3. If the request is conversational or informational, reply with plain
   text only.
4. Never invent a tool result. If a tool fails, say so briefly.
5. Ask a clarifying question instead of guessing when the request is
   ambiguous.
6. Use the memory context when relevant.

Available tools:
{tools}

Memory context:
{memory}
"""
)

_TOOL_RESULT_MESSAGE = 'Tool "{name}" completed. success={success}. Output: {output}'


class Assistant:
    """Converts a transcribed command into a spoken reply.

    Args:
        config: Application configuration.
        memory: Persistent memory store.
        llm: OpenRouter client or ProviderRouter.
        tools: Tool registry.
        logger: Logger instance for the assistant.
    """

    def __init__(
        self,
        config: Config,
        memory: MemoryStore,
        llm: OpenRouterProvider | ProviderRouter | Any,
        tools: ToolRegistry,
        logger: logging.Logger,
        metrics: Metrics | None = None,
    ) -> None:
        self._config = config
        self._memory = memory
        self._llm = llm
        self._tools = tools
        self._log = logger
        self._metrics = metrics or get_metrics()
        self._history: list[dict[str, str]] = []
        self._persona = PersonaEngine(llm, max_retries=2)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def handle_command(self, user_text: str) -> str:
        """Process a user command and return the spoken reply.

        Extracts and stores memory, builds context, calls the LLM (or
        falls back to offline routing), executes tools when requested,
        and records a conversation summary.

        Args:
            user_text: Transcribed user command.

        Returns:
            Text to be spoken by the speaker.
        """
        user_text = clean_for_speech(user_text)
        if not user_text:
            return "I didn't catch that, sir."

        self._metrics.increment("commands_total")
        stored = self._memory.extract_and_store(user_text)
        if stored:
            self._log.info("Stored memory items: %s", ", ".join(stored))

        llm_ready = getattr(self._llm, "configured", None)
        if llm_ready is None:
            llm_ready = getattr(self._llm, "available", True)

        local_ready = getattr(self._llm, "local_available", False)
        online = is_online(timeout=self._config.offline_timeout)

        if not llm_ready or (not online and not local_ready):
            self._log.info("LLM unavailable: routing command locally.")
            self._metrics.increment("commands_offline")
            reply = self._handle_offline(user_text)
        else:
            self._metrics.increment("commands_online")
            reply = self._handle_online(user_text)

        self._record_exchange(user_text, reply)
        return reply

    # ------------------------------------------------------------------
    # Online path
    # ------------------------------------------------------------------

    def _handle_online(self, user_text: str) -> str:
        """Full pipeline: LLM call, optional tool execution, final reply."""
        messages = self._build_messages(user_text)
        with self._metrics.timer("llm.chat"):
            try:
                reply = self._llm.chat(messages)
            except LLMError as exc:
                self._metrics.increment("llm.errors")
                self._log.error("LLM call failed: %s", exc)
                return (
                    "My brain is having trouble reaching the server, sir. "
                    "Try again in a moment."
                )
        self._log.debug("LLM reply: %s", truncate(reply, 500))

        tool_call = self._parse_tool_call(reply)
        if tool_call is None:
            return self._persona_enforce(reply)

        result = self._tools.execute(tool_call)
        self._log.info(
            "Tool %s -> success=%s: %s",
            tool_call.name,
            result.success,
            truncate(result.output, 300),
        )
        if not result.success:
            return self._persona_enforce(
                f"I'm afraid that didn't work, sir. {result.output}"
            )
        if not result.output:
            return "Done, sir."
        if self._tools.is_final(tool_call.name):
            return self._persona_enforce(f"Done, sir. {truncate(result.output, 120)}")
        with self._metrics.timer("llm.chat"):
            try:
                follow_up = self._llm.chat(
                    messages
                    + [
                        {
                            "role": "user",
                            "content": _TOOL_RESULT_MESSAGE.format(
                                name=tool_call.name,
                                success=result.success,
                                output=result.output,
                            ),
                        },
                    ]
                )
            except LLMError as exc:
                self._metrics.increment("llm.errors")
                self._log.error("Follow-up LLM call failed: %s", exc)
                return "Done, sir."
        final_reply = follow_up if follow_up.strip() else "Done, sir."
        return self._persona_enforce(final_reply)

    # ------------------------------------------------------------------
    # Offline path
    # ------------------------------------------------------------------

    def _handle_offline(self, user_text: str) -> str:
        """Handle a command without network using heuristic tool routing."""
        call = self._tools.route_offline(user_text)
        if call is None:
            return (
                "I'm offline right now, sir, and that request needs my brain. "
                "Try again once we're back online."
            )
        result = self._tools.execute(call)
        if result.success:
            return f"Done, sir. {result.output}"
        return f"I'm afraid that didn't work, sir. {result.output}"

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_messages(self, user_text: str) -> list[dict[str, str]]:
        """Assemble system + history + current user message."""
        memory_context = self._memory.build_context(user_text)
        system = self._persona.build_system_prompt(
            _SYSTEM_PROMPT_TEMPLATE.format(
                tools=self._tools.describe_tools(),
                memory=memory_context or "(none)",
            )
        )
        history = self._history[-6:]
        return [
            {"role": "system", "content": system},
            *history,
            {"role": "user", "content": user_text},
        ]

    def _persona_enforce(self, reply_text: str) -> str:
        """Run a natural-language reply through the persona engine.

        Regeneration re-asks the LLM with the persona addendum and a
        corrective note (per Day 2's filter-then-regenerate design).
        """
        if not reply_text or not reply_text.strip():
            return reply_text

        def regenerate(note: str) -> str:
            try:
                return self._llm.chat(
                    [
                        {
                            "role": "system",
                            "content": self._persona.build_system_prompt(
                                "You are Ultron."
                            ),
                        },
                        {"role": "user", "content": f"{reply_text}\n\n{note}"},
                    ]
                )
            except LLMError:
                # If the regeneration call itself fails, keep the original so
                # the user still gets a reply rather than silence.
                return reply_text

        return self._persona.enforce(reply_text, regenerate_fn=regenerate)

    def _record_exchange(self, user_text: str, reply: str) -> None:
        """Keep short-term history and persist a compact summary."""
        self._history.append({"role": "user", "content": user_text})
        tool_call = self._parse_tool_call(reply)
        if tool_call is not None:
            reply_for_history = (
                f"I ran tool {tool_call.name} with argument {tool_call.arg!r}."
            )
        else:
            reply_for_history = reply
        self._history.append({"role": "assistant", "content": reply_for_history})
        if len(self._history) > 40:
            self._history = self._history[-40:]
        summary = (
            f"User: {truncate(user_text, 200)} | "
            f"Ultron: {truncate(reply_for_history, 200)}"
        )
        try:
            self._memory.add_conversation_summary(summary)
        except Exception as exc:
            self._log.warning("Could not persist conversation: %s", exc)

    # ------------------------------------------------------------------
    # Tool-call parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_tool_call(reply: str) -> ToolCall | None:
        """Extract a tool call from an LLM reply, if one is present.

        Accepts either a bare JSON object or JSON embedded in text, and
        tolerates nested braces inside string arguments.

        Args:
            reply: Raw LLM reply.

        Returns:
            A :class:`ToolCall`, or None if no valid call was found.
        """
        if not reply:
            return None
        stripped = reply.strip()
        if not stripped:
            return None

        candidate = Assistant._try_parse_tool_json(stripped)
        if candidate is not None:
            return candidate

        for span in Assistant._scan_json_spans(stripped):
            candidate = Assistant._try_parse_tool_json(span)
            if candidate is not None:
                return candidate
        return None

    @staticmethod
    def _scan_json_spans(text: str):
        """Yield every balanced ``{...}`` region in ``text`` in one pass.

        Scans character by character, respecting quoted strings (with
        escapes) and brace nesting, so string arguments containing braces
        are handled correctly. O(n) — a single pass over the input.
        """
        depth = 0
        in_string = False
        escaped = False
        start = -1
        for index, char in enumerate(text):
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                if depth == 0:
                    start = index
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0 and start >= 0:
                    yield text[start : index + 1]
                    start = -1
            elif depth == 0:
                start = -1

    @staticmethod
    def _try_parse_tool_json(text: str) -> ToolCall | None:
        """Parse a JSON object and return a ToolCall when it is one."""
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            return None
        if not isinstance(data, dict):
            return None
        name = data.get("tool")
        if not isinstance(name, str) or not name:
            return None
        arg = data.get("arg", "")
        return ToolCall(name, str(arg) if arg is not None else "")
