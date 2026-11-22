"""SQLite storage. One file, WAL mode, schema migrations via PRAGMA user_version."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS learner (
    language        TEXT PRIMARY KEY,
    current_unit_id TEXT,
    started_at      TEXT,
    notes           TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS unit_progress (
    language        TEXT NOT NULL,
    unit_id         TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'active',   -- active | completed
    mastery         REAL NOT NULL DEFAULT 0,
    sessions        INTEGER NOT NULL DEFAULT 0,
    last_session_at TEXT,
    notes           TEXT DEFAULT '',
    PRIMARY KEY (language, unit_id)
);

CREATE TABLE IF NOT EXISTS sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    language    TEXT NOT NULL,
    mode        TEXT NOT NULL,
    unit_id     TEXT,
    scenario    TEXT DEFAULT '',
    focus       TEXT DEFAULT '',
    title       TEXT DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'active',   -- active | completed
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    ended_at    TEXT,
    summary     TEXT DEFAULT '',
    analysis    TEXT,                              -- JSON
    model       TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_sessions_lang ON sessions(language, created_at);

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role        TEXT NOT NULL,                     -- user | assistant
    content     TEXT NOT NULL,
    hidden      INTEGER NOT NULL DEFAULT 0,        -- instructions not shown in the UI
    created_at  TEXT NOT NULL,
    meta        TEXT                               -- JSON
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);

CREATE TABLE IF NOT EXISTS vocab (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    language            TEXT NOT NULL,
    lemma               TEXT NOT NULL,
    lemma_norm          TEXT NOT NULL,
    forms               TEXT DEFAULT '',
    gender              TEXT DEFAULT '',
    pos                 TEXT DEFAULT '',
    translation         TEXT DEFAULT '',
    example             TEXT DEFAULT '',
    example_translation TEXT DEFAULT '',
    notes               TEXT DEFAULT '',
    unit_id             TEXT DEFAULT '',
    session_id          INTEGER,
    status              TEXT NOT NULL DEFAULT 'candidate', -- candidate | learning | known | ignored
    source              TEXT DEFAULT 'extracted',          -- extracted | manual
    reason              TEXT DEFAULT '',
    freq                REAL DEFAULT 0,
    anki_note_id        INTEGER,
    anki_interval       INTEGER,
    anki_lapses         INTEGER,
    anki_reps           INTEGER,
    anki_synced_at      TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    UNIQUE (language, lemma_norm)
);

CREATE TABLE IF NOT EXISTS errors (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    language      TEXT NOT NULL,
    category      TEXT DEFAULT 'grammar',
    pattern       TEXT NOT NULL,
    pattern_norm  TEXT NOT NULL,
    example_wrong TEXT DEFAULT '',
    example_right TEXT DEFAULT '',
    explanation   TEXT DEFAULT '',
    count         INTEGER NOT NULL DEFAULT 1,
    first_seen    TEXT NOT NULL,
    last_seen     TEXT NOT NULL,
    last_session  INTEGER,
    resolved      INTEGER NOT NULL DEFAULT 0,
    UNIQUE (language, pattern_norm)
);

CREATE TABLE IF NOT EXISTS memories (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    language          TEXT,                          -- NULL = applies to all languages
    category          TEXT DEFAULT 'personal',       -- personal | preference | goal | other
    content           TEXT NOT NULL,
    source_session_id INTEGER,
    pinned            INTEGER NOT NULL DEFAULT 0,
    active            INTEGER NOT NULL DEFAULT 1,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS exam_scores (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    language    TEXT NOT NULL,
    level       TEXT NOT NULL,
    session_id  INTEGER,
    score       REAL NOT NULL,
    max_score   REAL NOT NULL,
    breakdown   TEXT DEFAULT '',
    created_at  TEXT NOT NULL
);
"""

MIGRATIONS = [SCHEMA_V1]


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def norm(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


class DB:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA foreign_keys=ON")
            self._migrate()

    def _migrate(self) -> None:
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        for i, script in enumerate(MIGRATIONS[version:], start=version + 1):
            self.conn.executescript(script)
            self.conn.execute(f"PRAGMA user_version={i}")

    # -- generic helpers -------------------------------------------------
    def all(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, tuple(params)).fetchall()]

    def one(self, sql: str, params: Iterable[Any] = ()) -> dict | None:
        with self.lock:
            r = self.conn.execute(sql, tuple(params)).fetchone()
            return dict(r) if r else None

    def scalar(self, sql: str, params: Iterable[Any] = ()) -> Any:
        with self.lock:
            r = self.conn.execute(sql, tuple(params)).fetchone()
            return r[0] if r else None

    def execute(self, sql: str, params: Iterable[Any] = ()) -> int:
        """Execute and return lastrowid."""
        with self.lock:
            cur = self.conn.execute(sql, tuple(params))
            return cur.lastrowid

    def insert(self, table: str, row: dict) -> int:
        cols = ", ".join(row)
        qs = ", ".join("?" for _ in row)
        return self.execute(f"INSERT INTO {table} ({cols}) VALUES ({qs})", row.values())

    def update(self, table: str, row_id: Any, patch: dict, key: str = "id") -> None:
        if not patch:
            return
        sets = ", ".join(f"{k}=?" for k in patch)
        self.execute(f"UPDATE {table} SET {sets} WHERE {key}=?", [*patch.values(), row_id])

    def backup_to(self, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with self.lock:
            target = sqlite3.connect(dest)
            try:
                self.conn.backup(target)
            finally:
                target.close()

    def close(self) -> None:
        with self.lock:
            self.conn.close()

    # -- learner / progress ---------------------------------------------
    def learner(self, language: str) -> dict | None:
        return self.one("SELECT * FROM learner WHERE language=?", [language])

    def ensure_learner(self, language: str, first_unit_id: str) -> dict:
        row = self.learner(language)
        if not row:
            self.insert("learner", {"language": language, "current_unit_id": first_unit_id,
                                    "started_at": now(), "notes": ""})
            self.ensure_unit(language, first_unit_id)
            row = self.learner(language)
        return row

    def ensure_unit(self, language: str, unit_id: str) -> dict:
        row = self.one("SELECT * FROM unit_progress WHERE language=? AND unit_id=?", [language, unit_id])
        if not row:
            self.execute("INSERT INTO unit_progress (language, unit_id, status) VALUES (?, ?, 'active')",
                         [language, unit_id])
            row = self.one("SELECT * FROM unit_progress WHERE language=? AND unit_id=?", [language, unit_id])
        return row

    def unit_progress_map(self, language: str) -> dict[str, dict]:
        return {r["unit_id"]: r for r in self.all("SELECT * FROM unit_progress WHERE language=?", [language])}

    # -- sessions / messages -------------------------------------------
    def session(self, sid: int) -> dict | None:
        s = self.one("SELECT * FROM sessions WHERE id=?", [sid])
        if s and s.get("analysis"):
            try:
                s["analysis"] = json.loads(s["analysis"])
            except json.JSONDecodeError:
                s["analysis"] = None
        return s

    def messages(self, sid: int, include_hidden: bool = True) -> list[dict]:
        sql = "SELECT * FROM messages WHERE session_id=?"
        if not include_hidden:
            sql += " AND hidden=0"
        rows = self.all(sql + " ORDER BY id", [sid])
        for r in rows:
            r["meta"] = json.loads(r["meta"]) if r.get("meta") else {}
        return rows

    def add_message(self, sid: int, role: str, content: str, hidden: bool = False,
                    meta: dict | None = None) -> int:
        ts = now()
        mid = self.insert("messages", {"session_id": sid, "role": role, "content": content,
                                       "hidden": 1 if hidden else 0, "created_at": ts,
                                       "meta": json.dumps(meta) if meta else None})
        self.execute("UPDATE sessions SET updated_at=? WHERE id=?", [ts, sid])
        return mid
