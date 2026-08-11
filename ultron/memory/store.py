"""SQLite-backed memory store for Ultron.

Persists conversation summaries, preferences, and facts, and retrieves
memories relevant to the current query. Thread-safe (a single RLock
guards every statement) and dependency-injected.

Enhanced with embedding support for semantic search.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from ultron.utils import MemoryStoreError, normalize, truncate

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    summary TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS preferences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fact TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'user',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    memory_type TEXT NOT NULL DEFAULT 'long_term',
    source TEXT NOT NULL DEFAULT 'user',
    importance REAL NOT NULL DEFAULT 0.5,
    vector BLOB,
    created_at TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    priority INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id INTEGER,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY (goal_id) REFERENCES goals(id)
);

CREATE TABLE IF NOT EXISTS reasoning_traces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_description TEXT NOT NULL,
    trace_json TEXT NOT NULL,
    outcome TEXT NOT NULL DEFAULT 'unknown',
    created_at TEXT NOT NULL
);
"""

_REMEMBER_THAT_PATTERN = re.compile(r"\bremember that (.+?)(?:\.|,|$)", re.IGNORECASE)
_REMEMBER_PATTERN = re.compile(r"\bremember (.+?)(?:\.|,|$)", re.IGNORECASE)
_LIKE_PATTERN = re.compile(
    r"\bi (?:really )?(?:like|love) (.+?)(?:\.|,|$)", re.IGNORECASE
)
_DONT_LIKE_PATTERN = re.compile(r"\bi don'?t like (.+?)(?:\.|,|$)", re.IGNORECASE)

_FACT_PATTERNS = (
    _REMEMBER_THAT_PATTERN,
    _REMEMBER_PATTERN,
    _LIKE_PATTERN,
    _DONT_LIKE_PATTERN,
)

_I_AM_PATTERN = re.compile(r"\bi (?:am|'m) (.+?)(?:\.|,|$)", re.IGNORECASE)

_NAME_PATTERN = re.compile(r"\bmy name is ([a-z]+)\b", re.IGNORECASE)
_PREFERENCE_PATTERNS = (
    re.compile(r"\bi prefer (.+?)(?:\.|,|$)", re.IGNORECASE),
    re.compile(r"\bi'd rather (.+?)(?:\.|,|$)", re.IGNORECASE),
)

_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "you",
        "your",
        "have",
        "what",
        "when",
        "where",
        "which",
        "will",
        "would",
        "could",
        "should",
        "about",
        "from",
        "they",
        "them",
        "their",
        "there",
        "here",
        "than",
    }
)


class MemoryStore:
    """Persistent, retrievable memory backed by SQLite.

    Args:
        db_path: Path to the SQLite database file.
        logger: Logger instance for this store.
    """

    def __init__(self, db_path: Path, logger: logging.Logger) -> None:
        self._db_path = Path(db_path)
        self._log = logger
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._log.info("Memory store ready at %s", self._db_path)

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        with self._lock:
            try:
                self._conn.close()
            except sqlite3.Error as exc:
                self._log.warning("Error closing memory store: %s", exc)
        self._log.info("Memory store closed.")

    def __enter__(self) -> MemoryStore:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def add_conversation_summary(self, summary: str) -> None:
        """Persist a one-line summary of an exchange.

        Args:
            summary: Compact summary text.

        Raises:
            MemoryStoreError: On SQLite failure.
        """
        summary = truncate(summary.strip(), limit=1000)
        if not summary:
            return
        try:
            with self._lock:
                self._conn.execute(
                    "INSERT INTO conversations (created_at, summary) VALUES (?, ?)",
                    (self._now(), summary),
                )
                self._conn.commit()
        except sqlite3.Error as exc:
            raise MemoryStoreError(f"Failed to store conversation: {exc}") from exc

    def set_preference(self, key: str, value: str) -> None:
        """Upsert a preference (e.g. ``name``, ``wake_volume``).

        Args:
            key: Preference key.
            value: Preference value.

        Raises:
            MemoryStoreError: On SQLite failure.
        """
        key = key.strip().lower()
        value = truncate(value.strip(), limit=500)
        if not key or not value:
            return
        try:
            with self._lock:
                self._conn.execute(
                    "INSERT INTO preferences (key, value, updated_at) VALUES (?, ?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
                    "updated_at=excluded.updated_at",
                    (key, value, self._now()),
                )
                self._conn.commit()
        except sqlite3.Error as exc:
            raise MemoryStoreError(f"Failed to store preference: {exc}") from exc

    def remember_fact(self, fact: str) -> None:
        """Persist a remembered fact.

        Args:
            fact: The fact to remember.

        Raises:
            MemoryStoreError: On SQLite failure.
        """
        fact = truncate(fact.strip(), limit=500)
        if not fact:
            return
        try:
            with self._lock:
                self._conn.execute(
                    "INSERT INTO facts (fact, source, created_at) "
                    "VALUES (?, 'user', ?)",
                    (fact, self._now()),
                )
                self._conn.commit()
            self._log.info("Remembered fact: %s", fact)
        except sqlite3.Error as exc:
            raise MemoryStoreError(f"Failed to store fact: {exc}") from exc

    def store_embedding(
        self,
        content: str,
        vector: bytes | None = None,
        memory_type: str = "long_term",
        source: str = "user",
        importance: float = 0.5,
        tags: str = "",
    ) -> int:
        """Store a memory entry with an optional embedding vector.

        Args:
            content: Text content to store.
            vector: Serialized embedding vector (numpy .tobytes()).
            memory_type: Classification of the memory.
            source: Origin of the memory.
            importance: Importance score 0.0–1.0.
            tags: Comma-separated tag string.

        Returns:
            The row ID of the inserted entry.

        Raises:
            MemoryStoreError: On SQLite failure.
        """
        try:
            with self._lock:
                cursor = self._conn.execute(
                    "INSERT INTO embeddings (content, memory_type, source, "
                    "importance, vector, created_at, tags) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        content,
                        memory_type,
                        source,
                        importance,
                        vector,
                        self._now(),
                        tags,
                    ),
                )
                self._conn.commit()
                return cursor.lastrowid  # type: ignore[return-value]
        except sqlite3.Error as exc:
            raise MemoryStoreError(f"Failed to store embedding: {exc}") from exc

    def add_goal(self, title: str, description: str = "", priority: int = 0) -> int:
        """Create a new goal.

        Args:
            title: Goal title.
            description: Detailed description.
            priority: Priority level (higher = more important).

        Returns:
            The row ID of the new goal.
        """
        now = self._now()
        try:
            with self._lock:
                cursor = self._conn.execute(
                    "INSERT INTO goals (title, description, priority, created_at, "
                    "updated_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (title, description, priority, now, now),
                )
                self._conn.commit()
                return cursor.lastrowid  # type: ignore[return-value]
        except sqlite3.Error as exc:
            raise MemoryStoreError(f"Failed to create goal: {exc}") from exc

    def add_task(
        self, title: str, description: str = "", goal_id: int | None = None
    ) -> int:
        """Create a new task, optionally linked to a goal.

        Args:
            title: Task title.
            description: Detailed description.
            goal_id: Optional parent goal ID.

        Returns:
            The row ID of the new task.
        """
        try:
            with self._lock:
                cursor = self._conn.execute(
                    "INSERT INTO tasks (goal_id, title, description, status, "
                    "created_at) "
                    "VALUES (?, ?, ?, 'pending', ?)",
                    (goal_id, title, description, self._now()),
                )
                self._conn.commit()
                return cursor.lastrowid  # type: ignore[return-value]
        except sqlite3.Error as exc:
            raise MemoryStoreError(f"Failed to create task: {exc}") from exc

    def store_reasoning_trace(
        self, task_description: str, trace_json: str, outcome: str = "unknown"
    ) -> None:
        """Persist a reasoning trace for future self-improvement.

        Args:
            task_description: What the task was about.
            trace_json: JSON-serialized reasoning trace.
            outcome: success / failure / partial.
        """
        try:
            with self._lock:
                self._conn.execute(
                    "INSERT INTO reasoning_traces "
                    "(task_description, trace_json, outcome, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (task_description, trace_json, outcome, self._now()),
                )
                self._conn.commit()
        except sqlite3.Error as exc:
            self._log.warning("Failed to store reasoning trace: %s", exc)

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_reasoning_traces(
        self, limit: int = 10, outcome: str | None = None
    ) -> list[tuple[int, str, str, str]]:
        """Return persisted reasoning traces for inspection and self-improvement.

        Args:
            limit: Maximum number of traces, most recent first.
            outcome: Optional filter (success / failure / info / unknown).

        Returns:
            List of (id, task_description, outcome, created_at) tuples.
        """
        try:
            with self._lock:
                if outcome:
                    cursor = self._conn.execute(
                        "SELECT id, task_description, outcome, created_at "
                        "FROM reasoning_traces WHERE outcome = ? "
                        "ORDER BY id DESC LIMIT ?",
                        (outcome, limit),
                    )
                else:
                    cursor = self._conn.execute(
                        "SELECT id, task_description, outcome, created_at "
                        "FROM reasoning_traces ORDER BY id DESC LIMIT ?",
                        (limit,),
                    )
                return [tuple(row) for row in cursor.fetchall()]  # type: ignore[return-value]
        except sqlite3.Error as exc:
            raise MemoryStoreError(f"Failed to read reasoning traces: {exc}") from exc

    def get_preference(self, key: str, default: str | None = None) -> str | None:
        """Read a preference value.

        Args:
            key: Preference key.
            default: Value returned when the key is absent.

        Returns:
            The stored value or ``default``.

        Raises:
            MemoryStoreError: On SQLite failure.
        """
        try:
            with self._lock:
                cursor = self._conn.execute(
                    "SELECT value FROM preferences WHERE key = ?",
                    (key.strip().lower(),),
                )
                row = cursor.fetchone()
                return row[0] if row else default
        except sqlite3.Error as exc:
            raise MemoryStoreError(f"Failed to read preference: {exc}") from exc

    def recent_summaries(self, limit: int = 5) -> list[str]:
        """Return the most recent conversation summaries.

        Args:
            limit: Maximum number of summaries.

        Returns:
            List of summary strings, most recent first.
        """
        try:
            with self._lock:
                cursor = self._conn.execute(
                    "SELECT summary FROM conversations ORDER BY id DESC LIMIT ?",
                    (limit,),
                )
                return [row[0] for row in cursor.fetchall()]
        except sqlite3.Error as exc:
            raise MemoryStoreError(f"Failed to read summaries: {exc}") from exc

    def search_facts(self, query: str, limit: int = 5) -> list[str]:
        """Find facts whose text overlaps with the query's keywords.

        Args:
            query: Natural-language query.
            limit: Maximum number of facts.

        Returns:
            List of matching fact strings, best matches first.
        """
        keywords = self._keywords(query)
        if not keywords:
            return []
        where = " OR ".join("fact LIKE ?" for _ in keywords)
        params = [f"%{kw}%" for kw in keywords]
        try:
            with self._lock:
                cursor = self._conn.execute(
                    f"SELECT fact FROM facts WHERE {where} ORDER BY id DESC LIMIT ?",
                    (*params, max(limit * 3, 20)),
                )
                candidates = [row[0] for row in cursor.fetchall()]
        except sqlite3.Error as exc:
            raise MemoryStoreError(f"Failed to search facts: {exc}") from exc

        scored: list[tuple[int, str]] = []
        for fact in candidates:
            score = sum(kw in normalize(fact) for kw in keywords)
            if score > 0:
                scored.append((score, fact))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [fact for _, fact in scored[:limit]]

    def get_all_embeddings(self) -> list[tuple[int, str, bytes | None]]:
        """Fetch all embeddings for vector search.

        Returns:
            List of (id, content, vector_bytes) tuples.
        """
        try:
            with self._lock:
                cursor = self._conn.execute(
                    "SELECT id, content, vector FROM embeddings ORDER BY id DESC"
                )
                return [(row[0], row[1], row[2]) for row in cursor.fetchall()]
        except sqlite3.Error as exc:
            raise MemoryStoreError(f"Failed to read embeddings: {exc}") from exc

    def get_active_goals(self) -> list[tuple[int, str, str, int]]:
        """Fetch all active goals.

        Returns:
            List of (id, title, description, priority) tuples.
        """
        try:
            with self._lock:
                cursor = self._conn.execute(
                    "SELECT id, title, description, priority FROM goals "
                    "WHERE status = 'active' ORDER BY priority DESC"
                )
                return [(row[0], row[1], row[2], row[3]) for row in cursor.fetchall()]
        except sqlite3.Error as exc:
            raise MemoryStoreError(f"Failed to read goals: {exc}") from exc

    def get_pending_tasks(
        self, goal_id: int | None = None
    ) -> list[tuple[int, str, str]]:
        """Fetch pending tasks, optionally filtered by goal.

        Args:
            goal_id: Optional goal ID to filter by.

        Returns:
            List of (id, title, description) tuples.
        """
        try:
            with self._lock:
                if goal_id is not None:
                    cursor = self._conn.execute(
                        "SELECT id, title, description FROM tasks "
                        "WHERE status = 'pending' AND goal_id = ? ORDER BY id",
                        (goal_id,),
                    )
                else:
                    cursor = self._conn.execute(
                        "SELECT id, title, description FROM tasks "
                        "WHERE status = 'pending' ORDER BY id"
                    )
                return [(row[0], row[1], row[2]) for row in cursor.fetchall()]
        except sqlite3.Error as exc:
            raise MemoryStoreError(f"Failed to read tasks: {exc}") from exc

    def build_context(self, query: str, max_lines: int = 8) -> str:
        """Assemble a compact memory context for the LLM prompt.

        Includes remembered facts relevant to the query, preferences, and
        recent conversation summaries.

        Args:
            query: Current user request.
            max_lines: Maximum number of context lines.

        Returns:
            A formatted memory block, or an empty string when empty.
        """
        lines: list[str] = []
        for fact in self.search_facts(query, limit=4):
            lines.append(f"- {fact}")
        try:
            with self._lock:
                cursor = self._conn.execute(
                    "SELECT key, value FROM preferences "
                    "ORDER BY updated_at DESC LIMIT 5"
                )
                for key, value in cursor.fetchall():
                    lines.append(f"- Preference: {key} = {value}")
        except sqlite3.Error as exc:
            self._log.warning("Could not load preferences: %s", exc)
        for summary in self.recent_summaries(limit=4):
            lines.append(f"- Previous: {summary}")
        return "\n".join(lines[:max_lines])

    # ------------------------------------------------------------------
    # Memory extraction
    # ------------------------------------------------------------------

    def extract_and_store(self, user_text: str) -> list[str]:
        """Extract facts/preferences from user speech and store them.

        Rules are deliberately simple: recognized patterns (remember,
        like, prefer, my name is ...) are persisted; the rest is ignored.

        Args:
            user_text: Raw user command.

        Returns:
            List of stored memory strings (empty when nothing matched).
        """
        stored: list[str] = []
        has_intent = any(
            marker in user_text.lower()
            for marker in (
                "remember",
                "call me",
                "my name",
                "i like",
                "i love",
                "i prefer",
                "i'd rather",
                "i don't like",
            )
        )
        for pattern in _FACT_PATTERNS:
            if pattern is _REMEMBER_PATTERN and _REMEMBER_THAT_PATTERN.search(
                user_text
            ):
                continue
            match = pattern.search(user_text)
            if match:
                fact = match.group(1).strip().rstrip(".,")
                if len(fact) >= 3:
                    self.remember_fact(fact)
                    stored.append(fact)
        if has_intent:
            match = _I_AM_PATTERN.search(user_text)
            if match:
                fact = match.group(1).strip().rstrip(".,")
                if len(fact) >= 3:
                    self.remember_fact(fact)
                    stored.append(fact)
        for pattern in _PREFERENCE_PATTERNS:
            match = pattern.search(user_text)
            if match:
                preference = match.group(1).strip().rstrip(".,")
                if len(preference) >= 2:
                    key = preference.split(" ", 1)[0].lower()
                    self.set_preference(key, preference)
                    stored.append(f"preference {key}")
        name_match = _NAME_PATTERN.search(user_text)
        if name_match:
            name = name_match.group(1)
            self.set_preference("name", name)
            self.remember_fact(f"User's name is {name}")
            stored.append(f"name {name}")
        return stored

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _now() -> str:
        """Return the current UTC timestamp as an ISO string."""
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def _keywords(query: str, min_len: int = 3) -> list[str]:
        """Split a query into meaningful keywords for LIKE matching."""
        words = [w for w in normalize(query).split() if len(w) >= min_len]
        return [w for w in words if w not in _STOPWORDS]
