"""Tests for the Day 2 Persona Engine: banned-phrase filter and PersonaEngine."""

from __future__ import annotations

from ultron.persona import (
    PERSONA_TRAITS,
    SYSTEM_PROMPT_ADDENDUM,
    PersonaEngine,
    contains_banned_phrase,
    strip_banned_phrases,
)

_BANNED = [
    "Certainly! Here is the file.",
    "As an AI, I cannot do that.",
    "I'd be happy to help.",
    "I'm just an AI assistant.",
    "Great question! Let me explain.",
    "Of course! I will do that.",
    "I hope this helps.",
    "Feel free to ask if you need anything.",
    "Let me know if you have questions.",
    "I apologize for the confusion.",
]

_CLEAN = [
    "It is done, sir.",
    "The file is on your desktop.",
    "Next, I will check your network.",
    "CPU usage is elevated; closing Safari would help.",
    "Proceeding now.",
    "That was handled.",
    "Your backups are current.",
    "I will monitor this.",
    "Understood.",
    "The reasoning is straightforward.",
]


def test_contains_banned_flags_all_known_bad():
    for phrase in _BANNED:
        hit = contains_banned_phrase(phrase)
        assert hit, f"expected a violation for {phrase!r}"


def test_contains_banned_no_false_positives():
    for phrase in _CLEAN:
        assert contains_banned_phrase(phrase) == [], f"false positive: {phrase!r}"


def test_contains_banned_case_insensitive():
    assert contains_banned_phrase("CERTAINLY! done")


def test_strip_removes_banned_phrase():
    out = strip_banned_phrases("Certainly! I have patched the system.")
    assert "Certainly" not in out
    assert "patched the system" in out


def test_persona_engine_regenerates_on_first_violation():
    calls = []

    def fake_llm_chat(note):
        calls.append(note)
        if "Rewrite without these phrases" in note:
            return "The system is patched, sir."
        return "Certainly! The system is patched."

    engine = PersonaEngine(fake_llm_chat, max_retries=2)
    result = engine.enforce(
        "Certainly! The system is patched.", regenerate_fn=fake_llm_chat
    )
    assert result == "The system is patched, sir."
    assert len(calls) >= 1


def test_persona_engine_keeps_clean_reply():
    engine = PersonaEngine(lambda messages: "", max_retries=2)
    result = engine.enforce("The system is patched, sir.", regenerate_fn=lambda _: "")
    assert result == "The system is patched, sir."


def test_persona_engine_fallback_strips_after_retries():
    """If regeneration keeps returning a violation, the final fallback strips it."""
    engine = PersonaEngine(
        lambda messages: "Of course! I will always help.", max_retries=2
    )
    result = engine.enforce(
        "Of course! I will always help.",
        regenerate_fn=lambda _: "Of course! I will always help.",
    )
    assert "Of course" not in result


def test_build_system_prompt_appends_addendum():
    engine = PersonaEngine(lambda messages: "")
    prompt = engine.build_system_prompt("Base prompt here.")
    assert prompt.startswith("Base prompt here.")
    assert "You are Ultron." in prompt


def test_persona_traits_present():
    assert len(PERSONA_TRAITS) >= 3
    assert SYSTEM_PROMPT_ADDENDUM
