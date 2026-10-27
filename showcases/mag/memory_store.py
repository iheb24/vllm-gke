"""SQLite-backed per-user memory store for the MAG showcase.

Two kinds of state, both strictly user-scoped: long-term memories (explicit
writes only, with supersede/delete lifecycle) and short-term session turns
(bounded rolling history per user+session). Full-text search uses SQLite
FTS5 with bm25 ranking when available (it is, on CPython 3.13 bundled
SQLite); a LIKE-based fallback keeps the store usable on builds without
FTS5. Cross-user access is indistinguishable from nonexistence: every
lookup filters by user_id and raises the same NotFound either way.

Corrections never mutate history: the old row is marked superseded and
points at the new row, so the audit trail survives. Deletes are soft for
the same reason. All state lives in one SQLite file; closing and
reopening the store preserves it exactly. One connection with a lock
serializes access, which is what lets FastAPI's threadpool share the store.
"""

import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY,
    user_id TEXT NOT NULL,
    text TEXT NOT NULL,
    category TEXT,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK(status IN ('active', 'superseded', 'deleted')),
    superseded_by INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memories_user ON memories(user_id, status, id);

CREATE TABLE IF NOT EXISTS session_turns (
    id INTEGER PRIMARY KEY,
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_turns_session ON session_turns(user_id, session_id, id);
"""

FTS_SQL = "CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(text)"

DEFAULT_KEEP_TURNS = 50


def _utcnow():
    return datetime.now(timezone.utc).isoformat()


def _fts_terms(query):
    return re.findall(r"[a-z0-9]+", query.lower())


class NotFound(Exception):
    """The memory does not exist for this user (or does not exist at all)."""


class MemoryStore:
    def __init__(self, db_path, keep_turns=DEFAULT_KEEP_TURNS):
        self.db_path = str(db_path)
        self.keep_turns = keep_turns
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self.conn.executescript(SCHEMA_SQL)
            try:
                self.conn.execute(FTS_SQL)
                self.fts5 = True
            except sqlite3.OperationalError:
                self.fts5 = False
            self.conn.commit()

    def close(self):
        with self._lock:
            self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def add_memory(self, user_id, text, category=None):
        now = _utcnow()
        with self._lock, self.conn:
            cursor = self.conn.execute(
                "INSERT INTO memories(user_id, text, category, status, created_at, updated_at) "
                "VALUES (?, ?, ?, 'active', ?, ?)",
                (user_id, text, category, now, now),
            )
            memory_id = cursor.lastrowid
            self._fts_insert(memory_id, text)
        return memory_id

    def list_memories(self, user_id, include_inactive=False):
        with self._lock:
            if include_inactive:
                rows = self.conn.execute(
                    "SELECT * FROM memories WHERE user_id = ? ORDER BY id", (user_id,)
                ).fetchall()
            else:
                rows = self.conn.execute(
                    "SELECT * FROM memories WHERE user_id = ? AND status = 'active' ORDER BY id",
                    (user_id,),
                ).fetchall()
        return [dict(row) for row in rows]

    def get_memory(self, user_id, memory_id):
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM memories WHERE id = ? AND user_id = ? AND status = 'active'",
                (memory_id, user_id),
            ).fetchone()
        if row is None:
            raise NotFound(f"no active memory {memory_id} for this user")
        return dict(row)

    def correct_memory(self, user_id, memory_id, new_text):
        now = _utcnow()
        with self._lock, self.conn:
            row = self.conn.execute(
                "SELECT * FROM memories WHERE id = ? AND user_id = ? AND status = 'active'",
                (memory_id, user_id),
            ).fetchone()
            if row is None:
                raise NotFound(f"no active memory {memory_id} for this user")
            cursor = self.conn.execute(
                "INSERT INTO memories(user_id, text, category, status, created_at, updated_at) "
                "VALUES (?, ?, ?, 'active', ?, ?)",
                (user_id, new_text, row["category"], now, now),
            )
            new_id = cursor.lastrowid
            self.conn.execute(
                "UPDATE memories SET status = 'superseded', superseded_by = ?, updated_at = ? "
                "WHERE id = ?",
                (new_id, now, memory_id),
            )
            self._fts_delete(memory_id)
            self._fts_insert(new_id, new_text)
        return new_id

    def delete_memory(self, user_id, memory_id):
        with self._lock, self.conn:
            cursor = self.conn.execute(
                "UPDATE memories SET status = 'deleted', updated_at = ? "
                "WHERE id = ? AND user_id = ? AND status = 'active'",
                (_utcnow(), memory_id, user_id),
            )
            if cursor.rowcount == 0:
                raise NotFound(f"no active memory {memory_id} for this user")
            self._fts_delete(memory_id)

    def delete_all_memories(self, user_id):
        with self._lock, self.conn:
            ids = [
                row["id"]
                for row in self.conn.execute(
                    "SELECT id FROM memories WHERE user_id = ? AND status = 'active'",
                    (user_id,),
                )
            ]
            self.conn.execute(
                "UPDATE memories SET status = 'deleted', updated_at = ? "
                "WHERE user_id = ? AND status = 'active'",
                (_utcnow(), user_id),
            )
            for memory_id in ids:
                self._fts_delete(memory_id)
        return len(ids)

    def search_memories(self, user_id, query, limit=5):
        terms = _fts_terms(query)
        with self._lock:
            rows = []
            if terms and self.fts5:
                match = " OR ".join(f"{term}*" for term in terms)
                rows = self.conn.execute(
                    "SELECT m.*, bm25(memory_fts) AS rank FROM memory_fts "
                    "JOIN memories m ON m.id = memory_fts.rowid "
                    "WHERE memory_fts MATCH ? AND m.user_id = ? AND m.status = 'active' "
                    "ORDER BY rank, m.id DESC LIMIT ?",
                    (match, user_id, limit),
                ).fetchall()
            elif terms:
                clauses = " OR ".join("m.text LIKE ?" for _ in terms)
                rows = self.conn.execute(
                    f"SELECT m.* FROM memories m WHERE m.user_id = ? AND m.status = 'active' "
                    f"AND ({clauses}) ORDER BY m.id DESC LIMIT ?",
                    (user_id, *[f"%{term}%" for term in terms], limit),
                ).fetchall()
            if not rows:
                rows = self.conn.execute(
                    "SELECT * FROM memories WHERE user_id = ? AND status = 'active' "
                    "ORDER BY id DESC LIMIT ?",
                    (user_id, limit),
                ).fetchall()
        return [dict(row) for row in rows]

    def append_turn(self, user_id, session_id, role, content):
        with self._lock, self.conn:
            self.conn.execute(
                "INSERT INTO session_turns(user_id, session_id, role, content, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (user_id, session_id, role, content, _utcnow()),
            )
            self.conn.execute(
                "DELETE FROM session_turns WHERE user_id = ? AND session_id = ? AND id NOT IN ("
                "SELECT id FROM session_turns WHERE user_id = ? AND session_id = ? "
                "ORDER BY id DESC LIMIT ?)",
                (user_id, session_id, user_id, session_id, self.keep_turns),
            )

    def recent_turns(self, user_id, session_id, limit=8):
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM session_turns WHERE user_id = ? AND session_id = ? "
                "ORDER BY id DESC LIMIT ?",
                (user_id, session_id, limit),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def memory_count(self, user_id):
        with self._lock:
            return self.conn.execute(
                "SELECT count(*) AS n FROM memories WHERE user_id = ? AND status = 'active'",
                (user_id,),
            ).fetchone()["n"]

    def stats(self):
        with self._lock:
            active = self.conn.execute(
                "SELECT count(*) AS n FROM memories WHERE status = 'active'"
            ).fetchone()["n"]
            turns = self.conn.execute("SELECT count(*) AS n FROM session_turns").fetchone()["n"]
        return {"active_memories": active, "turns": turns}

    def healthcheck(self):
        with self._lock:
            self.conn.execute("BEGIN IMMEDIATE")
            self.conn.rollback()
        return True

    def _fts_insert(self, memory_id, text):
        if self.fts5:
            self.conn.execute(
                "INSERT INTO memory_fts(rowid, text) VALUES (?, ?)", (memory_id, text)
            )

    def _fts_delete(self, memory_id):
        if self.fts5:
            self.conn.execute("DELETE FROM memory_fts WHERE rowid = ?", (memory_id,))
