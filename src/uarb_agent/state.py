"""SQLite state: which emails were handled (no double replies, crash recovery) and rate-limit counters.

Only the worker thread touches the database.
"""

import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    message_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,          -- 'claimed' while in progress, then 'done' or 'ignored'
    attempts INTEGER NOT NULL DEFAULT 0,
    detail TEXT,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS served (
    sender TEXT NOT NULL,
    at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS served_at ON served(at);
"""

MAX_ATTEMPTS = 2  # a message that crashed the agent twice is not retried a third time


class State:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        # Created on the main thread, then used only by the worker thread.
        self.db = sqlite3.connect(path, isolation_level=None, check_same_thread=False)  # autocommit
        self.db.executescript(SCHEMA)

    def is_empty(self) -> bool:
        return self.db.execute("SELECT 1 FROM messages LIMIT 1").fetchone() is None

    def baseline(self, message_ids: list[str]) -> None:
        """On the very first start, mark emails already in the inbox as handled so they get no reply."""
        self.db.executemany(
            "INSERT OR IGNORE INTO messages (message_id, status, detail, updated_at) "
            "VALUES (?, 'ignored', 'before first start', ?)",
            [(m, time.time()) for m in message_ids],
        )

    def claim(self, message_id: str) -> bool:
        """True if this message should be processed now (new, or interrupted and under the retry cap)."""
        row = self.db.execute("SELECT status, attempts FROM messages WHERE message_id = ?", (message_id,)).fetchone()
        if row and (row[0] != "claimed" or row[1] >= MAX_ATTEMPTS):
            return False
        self.db.execute(
            "INSERT INTO messages (message_id, status, attempts, updated_at) VALUES (?, 'claimed', 1, ?) "
            "ON CONFLICT(message_id) DO UPDATE SET attempts = attempts + 1, updated_at = excluded.updated_at",
            (message_id, time.time()),
        )
        return True

    def finish(self, message_id: str, status: str, detail: str = "") -> None:
        self.db.execute(
            "UPDATE messages SET status = ?, detail = ?, updated_at = ? WHERE message_id = ?",
            (status, detail, time.time(), message_id),
        )

    def seen(self, message_id: str) -> bool:
        return self.db.execute("SELECT 1 FROM messages WHERE message_id = ?", (message_id,)).fetchone() is not None

    def record_served(self, sender: str) -> None:
        self.db.execute("INSERT INTO served (sender, at) VALUES (?, ?)", (sender, time.time()))

    def served_count(self, since_seconds: float, sender: str | None = None) -> int:
        since = time.time() - since_seconds
        if sender is None:
            return self.db.execute("SELECT COUNT(*) FROM served WHERE at > ?", (since,)).fetchone()[0]
        return self.db.execute(
            "SELECT COUNT(*) FROM served WHERE at > ? AND sender = ?", (since, sender)
        ).fetchone()[0]
