"""Memory store tests: schema, prefs, facts, context, extraction."""

from __future__ import annotations

import sqlite3


def _tables(db_path):
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    conn.close()
    return {row[0] for row in rows}


def test_schema_created(memory, config):
    tables = _tables(config.db_path)
    assert {"conversations", "preferences", "facts"} <= tables


def test_set_and_get_preference(memory):
    memory.set_preference("name", "Tony")
    assert memory.get_preference("name") == "Tony"


def test_get_preference_missing_default(memory):
    assert memory.get_preference("nope") is None
    assert memory.get_preference("nope", "fallback") == "fallback"


def test_preference_upsert(memory):
    memory.set_preference("city", "NYC")
    memory.set_preference("city", "LA")
    assert memory.get_preference("city") == "LA"


def test_preference_key_normalized(memory):
    memory.set_preference("  Wake Volume ", "high")
    assert memory.get_preference("wake volume") == "high"


def test_remember_fact(memory):
    memory.remember_fact("dog is named Rex")
    assert memory.search_facts("dog") == ["dog is named Rex"]


def test_remember_fact_blank_ignored(memory):
    memory.remember_fact("   ")
    assert memory.search_facts("anything") == []


def test_search_facts_ranking(memory):
    memory.remember_fact("user likes espresso")
    memory.remember_fact("user likes espresso in the morning")
    results = memory.search_facts("espresso")
    assert results[0] == "user likes espresso in the morning"


def test_search_facts_no_keywords(memory):
    memory.remember_fact("anything at all")
    assert memory.search_facts("a") == []


def test_recent_summaries_order(memory):
    memory.add_conversation_summary("first")
    memory.add_conversation_summary("second")
    memory.add_conversation_summary("third")
    recent = memory.recent_summaries(limit=2)
    assert recent == ["third", "second"]


def test_add_conversation_blank_ignored(memory):
    memory.add_conversation_summary("  ")
    assert memory.recent_summaries() == []


def test_build_context_includes_facts_and_prefs(memory):
    memory.remember_fact("user's dog is named Rex")
    memory.set_preference("name", "Tony")
    memory.add_conversation_summary("chat about music")
    context = memory.build_context("dog")
    assert "Rex" in context
    assert "name" in context
    assert "chat about music" in context


def test_build_context_respects_max_lines(memory):
    for i in range(10):
        memory.remember_fact(f"fact number {i}")
        memory.add_conversation_summary(f"summary {i}")
    context = memory.build_context("fact", max_lines=3)
    assert len(context.splitlines()) <= 3


def test_build_context_empty(memory):
    assert memory.build_context("nothing here") == ""


def test_extract_remember_that(memory):
    stored = memory.extract_and_store("remember that my dog is named Rex")
    assert stored == ["my dog is named Rex"]
    assert memory.search_facts("Rex") == ["my dog is named Rex"]


def test_extract_i_like(memory):
    stored = memory.extract_and_store("I really like espresso")
    assert "espresso" in stored


def test_extract_i_dont_like(memory):
    stored = memory.extract_and_store("I don't like mornings")
    assert stored == ["mornings"]


def test_extract_i_prefer(memory):
    stored = memory.extract_and_store("I prefer dark mode")
    assert stored == ["preference dark"]


def test_extract_name(memory):
    stored = memory.extract_and_store("my name is Bob")
    assert "name Bob" in stored
    assert memory.get_preference("name") == "Bob"
    assert memory.search_facts("Bob") == ["User's name is Bob"]


def test_extract_junk_i_am_stores_nothing(memory):
    stored = memory.extract_and_store("I am going to open Safari")
    assert stored == []
    assert memory.search_facts("Safari") == []


def test_extract_i_am_with_intent_stores(memory):
    stored = memory.extract_and_store("Remember, I am allergic to peanuts")
    assert stored == ["allergic to peanuts"]


def test_extract_no_match_returns_empty(memory):
    assert memory.extract_and_store("open safari please") == []


def test_close_then_fact_fails(memory, config):
    memory.close()
    try:
        memory.remember_fact("after close")
    except Exception:
        pass
    else:
        raise AssertionError("expected error after close")


def test_wal_mode_enabled(memory, config):
    conn = sqlite3.connect(str(config.db_path))
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    conn.close()
    assert mode == "wal"


def test_store_is_reusable(memory):
    memory.set_preference("a", "1")
    memory.add_conversation_summary("x")
    memory.remember_fact("dog is loyal")
    assert memory.get_preference("a") == "1"
    assert memory.recent_summaries() == ["x"]
    assert memory.search_facts("loyal") == ["dog is loyal"]


def test_truncate_long_fact(memory):
    long_text = "z" * 2000
    memory.remember_fact(long_text)
    results = memory.search_facts("z" * 10)
    assert results and len(results[0]) <= 500


def test_conversation_summary_truncated(memory):
    memory.add_conversation_summary("q" * 5000)
    assert len(memory.recent_summaries()[0]) <= 1000


def test_preference_value_truncated(memory):
    memory.set_preference("key", "v" * 2000)
    assert len(memory.get_preference("key")) <= 500
