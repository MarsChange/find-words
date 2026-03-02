"""SQLite + FTS5 full-text search engine for classical text content."""

import re
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from app.config import settings

_local = threading.local()


def _get_connection() -> sqlite3.Connection:
    """Return a thread-local SQLite connection."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        db_path = Path(settings.db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return conn


@contextmanager
def get_db() -> Generator[sqlite3.Connection, None, None]:
    """Context manager that yields a thread-local connection."""
    conn = _get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_db() -> None:
    """Create tables and FTS5 virtual table if they don't exist."""
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS files (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                filename   TEXT    NOT NULL,
                filepath   TEXT    NOT NULL,
                dynasty    TEXT    DEFAULT '',
                author     TEXT    DEFAULT '',
                page_count INTEGER DEFAULT 0,
                status     TEXT    DEFAULT 'pending'
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS content_fts USING fts5(
                file_id,
                page_num,
                content,
                tokenize='unicode61'
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                keyword    TEXT    NOT NULL DEFAULT '',
                created_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M', 'now', 'localtime')),
                updated_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M', 'now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS messages (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                role       TEXT    NOT NULL CHECK(role IN ('user', 'assistant')),
                content    TEXT    NOT NULL,
                created_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime'))
            );
            """
        )


# ── File CRUD ────────────────────────────────────────────────────────────────

def insert_file(filename: str, filepath: str, dynasty: str = "",
                author: str = "") -> int:
    """Insert a new file record and return its id."""
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO files (filename, filepath, dynasty, author) "
            "VALUES (?, ?, ?, ?)",
            (filename, filepath, dynasty, author),
        )
        return cur.lastrowid


def update_file_status(file_id: int, status: str,
                       page_count: int | None = None) -> None:
    """Update a file's processing status and optionally its page count."""
    with get_db() as conn:
        if page_count is not None:
            conn.execute(
                "UPDATE files SET status=?, page_count=? WHERE id=?",
                (status, page_count, file_id),
            )
        else:
            conn.execute(
                "UPDATE files SET status=? WHERE id=?",
                (status, file_id),
            )


def update_file_metadata(file_id: int, dynasty: str | None = None,
                         author: str | None = None) -> None:
    """Update optional metadata fields on a file record."""
    with get_db() as conn:
        if dynasty is not None:
            conn.execute(
                "UPDATE files SET dynasty=? WHERE id=?", (dynasty, file_id)
            )
        if author is not None:
            conn.execute(
                "UPDATE files SET author=? WHERE id=?", (author, file_id)
            )


def get_file(file_id: int) -> dict | None:
    """Return a file record as dict, or None."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM files WHERE id=?", (file_id,)
        ).fetchone()
        return dict(row) if row else None


def list_files() -> list[dict]:
    """Return all file records."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM files ORDER BY id DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def delete_file(file_id: int) -> None:
    """Delete a file record and its indexed content."""
    with get_db() as conn:
        conn.execute(
            "DELETE FROM content_fts WHERE file_id=?",
            (str(file_id),),
        )
        conn.execute("DELETE FROM files WHERE id=?", (file_id,))


# ── Content indexing ─────────────────────────────────────────────────────────

def index_page(file_id: int, page_num: int, content: str) -> None:
    """Insert a single page's text into the FTS5 index."""
    with get_db() as conn:
        conn.execute(
            "INSERT INTO content_fts (file_id, page_num, content) "
            "VALUES (?, ?, ?)",
            (str(file_id), str(page_num), content),
        )


def index_pages_batch(rows: list[tuple[int, int, str]]) -> None:
    """Batch-insert multiple (file_id, page_num, content) rows."""
    with get_db() as conn:
        conn.executemany(
            "INSERT INTO content_fts (file_id, page_num, content) "
            "VALUES (?, ?, ?)",
            [(str(fid), str(pn), c) for fid, pn, c in rows],
        )


# ── FTS5 search ──────────────────────────────────────────────────────────────

# Characters that have special meaning in FTS5 MATCH expressions
_FTS5_SPECIAL = re.compile(r'["\*\(\)\+\-\^:{}]')


def _sanitize_fts5_query(raw: str) -> str:
    """Escape special FTS5 MATCH characters to prevent query injection.

    Wraps the sanitized query in double-quotes so it is treated as a
    literal phrase by the FTS5 engine.
    """
    cleaned = _FTS5_SPECIAL.sub(" ", raw).strip()
    if not cleaned:
        return '""'
    # Wrap in quotes so FTS5 treats it as a phrase / literal string
    escaped = cleaned.replace('"', ' ')
    return f'"{escaped}"'


def search_content(query: str, limit: int = 100) -> list[dict]:
    """
    Run an FTS5 MATCH query and return results with contextual snippets.

    The query is sanitized to prevent FTS5 syntax injection.

    Each result dict contains: file_id, page_num, snippet, filename,
    dynasty, author.
    """
    safe_query = _sanitize_fts5_query(query)
    ctx = settings.snippet_context_chars
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT
                c.file_id,
                c.page_num,
                snippet(content_fts, 2, '【', '】', '…', 30) AS snippet,
                f.filename,
                f.dynasty,
                f.author
            FROM content_fts c
            JOIN files f ON f.id = CAST(c.file_id AS INTEGER)
            WHERE content_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (safe_query, limit),
        ).fetchall()
        return [dict(r) for r in rows]


# ── Session CRUD ─────────────────────────────────────────────────────────────

def create_session(keyword: str) -> dict:
    """Create a new chat session and return it as dict."""
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO sessions (keyword) VALUES (?)",
            (keyword,),
        )
        row = conn.execute(
            "SELECT * FROM sessions WHERE id=?", (cur.lastrowid,)
        ).fetchone()
        return dict(row)


def get_sessions() -> list[dict]:
    """Return all sessions ordered by most recent first, with message counts."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT s.*,
                   COUNT(m.id) AS message_count
            FROM sessions s
            LEFT JOIN messages m ON m.session_id = s.id
            GROUP BY s.id
            ORDER BY s.updated_at DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]


def get_session_by_id(session_id: int) -> dict | None:
    """Return a single session with its message count, or None."""
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT s.*,
                   COUNT(m.id) AS message_count
            FROM sessions s
            LEFT JOIN messages m ON m.session_id = s.id
            WHERE s.id = ?
            GROUP BY s.id
            """,
            (session_id,),
        ).fetchone()
        return dict(row) if row else None


def get_messages_by_session(session_id: int) -> list[dict]:
    """Return all messages in a session ordered chronologically."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM messages WHERE session_id=? ORDER BY id ASC",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def add_message(session_id: int, role: str, content: str) -> dict:
    """Insert a message into a session and update session timestamp."""
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
            (session_id, role, content),
        )
        conn.execute(
            "UPDATE sessions SET updated_at = strftime('%Y-%m-%d %H:%M', 'now', 'localtime') "
            "WHERE id = ?",
            (session_id,),
        )
        row = conn.execute(
            "SELECT * FROM messages WHERE id=?", (cur.lastrowid,)
        ).fetchone()
        return dict(row)


def delete_session(session_id: int) -> None:
    """Delete a session and all its messages (CASCADE)."""
    with get_db() as conn:
        conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
