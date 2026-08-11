"""Audit log stored in the existing ``ultron_memory.db`` (a new ``audit_log``
table), so there is one database and one backup story. Every tool invocation
that reaches the PermissionGate is recorded here with its source and outcome.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL,
    tool_name TEXT,
    args_json TEXT,
    source TEXT,
    result TEXT,
    duration_ms REAL
)
"""


class AuditLog:
    """Thread-safe writer/reader for the ``audit_log`` table.

    Args:
        db_connection: An open ``sqlite3.Connection`` to ``ultron_memory.db``.
    """

    def __init__(self, db_connection: sqlite3.Connection) -> None:
        self._db = db_connection
        self._lock = threading.RLock()
        with self._lock:
            self._db.execute(_SCHEMA)
            self._db.commit()

    @classmethod
    def at_path(cls, path: Path | str) -> AuditLog:
        """Open an AuditLog against the SQLite file at ``path``."""
        return cls(sqlite3.connect(str(path)))

    def record(
        self,
        tool_name: str,
        args: dict,
        source: str,
        result: str,
        duration: float = 0.0,
    ) -> None:
        """Append one audit row for a tool invocation attempt."""
        with self._lock:
            self._db.execute(
                "INSERT INTO audit_log "
                "(timestamp, tool_name, args_json, source, result, duration_ms) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    time.time(),
                    tool_name,
                    json.dumps(args, sort_keys=True),
                    source,
                    result,
                    duration * 1000,
                ),
            )
            self._db.commit()

    def recent(self, limit: int = 20) -> list[tuple]:
        """Return the most recent audit rows, newest first."""
        with self._lock:
            cursor = self._db.execute(
                "SELECT timestamp, tool_name, args_json, source, result "
                "FROM audit_log ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            )
            return list(cursor.fetchall())

    def close(self) -> None:
        """Best-effort close of the wrapped connection."""
        try:
            self._db.close()
        except Exception:  # noqa: BLE001
            pass
