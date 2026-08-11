"""PersonaEngine — enforce the register, don't just detect it.

A filter that only *flags* violations still lets bad output reach the speaker.
This engine regenerates offending replies up to ``max_retries`` times, then
falls back to mechanically stripping any remaining banned phrases so nothing
generic is ever spoken or logged.
"""

from __future__ import annotations

from collections.abc import Callable

from ultron.persona.banned_phrases import contains_banned_phrase, strip_banned_phrases
from ultron.persona.style_rules import SYSTEM_PROMPT_ADDENDUM


class PersonaEngine:
    """Wraps every outbound reply before it reaches ``voice/speaker.py``.

    Args:
        llm_provider: Object with a ``chat(messages, **kwargs)`` method used
            to regenerate offending replies (e.g. an LLMProvider or router).
        max_retries: How many regeneration attempts before mechanical strip.
    """

    def __init__(self, llm_provider, max_retries: int = 2) -> None:
        self._llm = llm_provider
        self._max_retries = max_retries

    def build_system_prompt(self, base_prompt: str) -> str:
        """Append the persona addendum to an existing system prompt."""
        return f"{base_prompt}\n\n{SYSTEM_PROMPT_ADDENDUM}"

    def enforce(self, reply_text: str, regenerate_fn: Callable[[str], str]) -> str:
        """Return ``reply_text`` in Ultron's register.

        Args:
            reply_text: The raw LLM reply.
            regenerate_fn: Callable that re-asks the LLM with a corrective
                note and returns the fresh reply.
        """
        attempt = reply_text
        for _ in range(self._max_retries):
            violations = contains_banned_phrase(attempt)
            if not violations:
                return attempt
            attempt = regenerate_fn(
                f"Rewrite without these phrases: {violations}. "
                "Same meaning, Ultron's register, no generic AI phrasing."
            )
        # Final fallback: strip mechanically rather than ship a violation.
        return strip_banned_phrases(attempt)
