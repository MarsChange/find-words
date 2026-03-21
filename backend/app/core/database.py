"""SQLite + FTS5 full-text search engine for classical text content."""

import json
import logging
import re
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from app.config import settings

_local = threading.local()
logger = logging.getLogger(__name__)

# CJK Unicode ranges — used to insert spaces so each character becomes
# an individual FTS5 token, enabling substring matching on Chinese text.
_CJK_RE = re.compile(
    r'([\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff'
    r'\u2f00-\u2fdf\u2e80-\u2eff])'
)


def _tokenize_cjk(text: str) -> str:
    """Insert spaces around CJK characters for character-level FTS5 tokenization."""
    return _CJK_RE.sub(r' \1 ', text)


# Regex to collapse spaces between adjacent CJK characters (reverse of _tokenize_cjk)
_CJK_SPACE_RE = re.compile(
    r'(?<=[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff'
    r'\u2f00-\u2fdf\u2e80-\u2eff])'
    r'\s+'
    r'(?=[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff'
    r'\u2f00-\u2fdf\u2e80-\u2eff])'
)


def _clean_snippet(raw: str) -> str:
    """Remove FTS5 highlight markers and CJK tokenization spaces from snippets."""
    cleaned = raw.replace("\u3010", "").replace("\u3011", "")
    cleaned = _CJK_SPACE_RE.sub("", cleaned)
    return cleaned.strip()


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


def _get_fts_table_sql(conn: sqlite3.Connection) -> str | None:
    """Return CREATE SQL of content_fts table if exists."""
    try:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='content_fts'"
        ).fetchone()
        if row and row["sql"]:
            return str(row["sql"])
    except Exception:
        pass
    return None


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
                category   TEXT    DEFAULT '',
                author     TEXT    DEFAULT '',
                page_count INTEGER DEFAULT 0,
                status     TEXT    DEFAULT 'pending'
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                keyword              TEXT    NOT NULL DEFAULT '',
                traditional_keyword  TEXT    NOT NULL DEFAULT '',
                synthesis            TEXT    NOT NULL DEFAULT '',
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

            CREATE TABLE IF NOT EXISTS search_results (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                source     TEXT    NOT NULL DEFAULT 'local',
                file_id    INTEGER,
                filename   TEXT    DEFAULT '',
                page_num   INTEGER,
                snippet    TEXT    DEFAULT '',
                keyword_sentence TEXT DEFAULT '',
                is_original_text INTEGER DEFAULT 0,
                content_label TEXT DEFAULT '',
                dynasty    TEXT    DEFAULT '',
                category   TEXT    DEFAULT '',
                author     TEXT    DEFAULT '',
                sutra_id   TEXT,
                title      TEXT,
                created_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            INSERT OR IGNORE INTO settings (key, value) VALUES ('cbeta_max_results', '20');
            INSERT OR IGNORE INTO settings (key, value) VALUES ('enable_thinking', 'false');
            INSERT OR IGNORE INTO settings (key, value) VALUES ('ocr_model', 'qwen3.5-plus');
            INSERT OR IGNORE INTO settings (key, value) VALUES ('include_commentary_in_synthesis_prompt', 'false');
            INSERT OR IGNORE INTO settings (key, value) VALUES ('synthesis_user_prompt', '请从汉语词汇史的角度，结合汉译佛典和本土文献语料，梳理并分析用户所检索词语的中土化路径。');
            """
        )

        # Keep a single content field per page.
        # If old schema has content_type, recreate and merge rows by page.
        fts_sql = _get_fts_table_sql(conn)
        if fts_sql is None:
            conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS content_fts USING fts5("
                "file_id, page_num, content, tokenize='unicode61')"
            )
        elif "content_type" in fts_sql:
            conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS content_fts_new USING fts5("
                "file_id, page_num, content, tokenize='unicode61')"
            )
            conn.execute(
                "INSERT INTO content_fts_new (file_id, page_num, content) "
                "SELECT file_id, page_num, group_concat(content, ' ') "
                "FROM content_fts GROUP BY file_id, page_num"
            )
            conn.execute("DROP TABLE content_fts")
            conn.execute("ALTER TABLE content_fts_new RENAME TO content_fts")

        # Migrate existing databases: add traditional_keyword column if missing
        try:
            conn.execute(
                "ALTER TABLE sessions ADD COLUMN traditional_keyword TEXT NOT NULL DEFAULT ''"
            )
        except sqlite3.OperationalError:
            pass  # Column already exists
        # Migrate existing databases: add synthesis column if missing
        try:
            conn.execute(
                "ALTER TABLE sessions ADD COLUMN synthesis TEXT NOT NULL DEFAULT ''"
            )
        except sqlite3.OperationalError:
            pass  # Column already exists
        # Migrate existing databases: add category column to files if missing
        try:
            conn.execute(
                "ALTER TABLE files ADD COLUMN category TEXT DEFAULT ''"
            )
        except sqlite3.OperationalError:
            pass  # Column already exists
        # Migrate existing databases: add category column to search_results if missing
        try:
            conn.execute(
                "ALTER TABLE search_results ADD COLUMN category TEXT DEFAULT ''"
            )
        except sqlite3.OperationalError:
            pass  # Column already exists
        # Migrate existing databases: add keyword_sentence column if missing
        try:
            conn.execute(
                "ALTER TABLE search_results ADD COLUMN keyword_sentence TEXT DEFAULT ''"
            )
        except sqlite3.OperationalError:
            pass  # Column already exists
        # Migrate existing databases: add is_original_text column if missing
        try:
            conn.execute(
                "ALTER TABLE search_results ADD COLUMN is_original_text INTEGER DEFAULT 0"
            )
        except sqlite3.OperationalError:
            pass  # Column already exists
        # Migrate existing databases: add content_label column if missing
        try:
            conn.execute(
                "ALTER TABLE search_results ADD COLUMN content_label TEXT DEFAULT ''"
            )
        except sqlite3.OperationalError:
            pass  # Column already exists


def recover_stuck_files() -> list[dict]:
    """Reset files stuck at 'processing' (from previous crash) back to 'pending'.

    Returns the list of recovered file records so the caller can re-trigger
    background processing for them.
    """
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM files WHERE status = 'processing'"
        ).fetchall()
        if rows:
            conn.execute(
                "UPDATE files SET status = 'pending', page_count = 0 "
                "WHERE status = 'processing'"
            )
            # Also clear any partial FTS content for these files
            for row in rows:
                conn.execute(
                    "DELETE FROM content_fts WHERE file_id = ?",
                    (str(row["id"]),),
                )
        return [dict(r) for r in rows]


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
                         category: str | None = None,
                         author: str | None = None) -> None:
    """Update optional metadata fields on a file record."""
    updates: list[str] = []
    params: list = []
    if dynasty is not None:
        updates.append("dynasty=?")
        params.append(dynasty)
    if category is not None:
        updates.append("category=?")
        params.append(category)
    if author is not None:
        updates.append("author=?")
        params.append(author)
    if not updates:
        return
    params.append(file_id)
    with get_db() as conn:
        conn.execute(
            f"UPDATE files SET {', '.join(updates)} WHERE id=?",
            params,
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


def clear_file_content(file_id: int) -> None:
    """Remove all indexed content for a file (for re-indexing)."""
    with get_db() as conn:
        conn.execute(
            "DELETE FROM content_fts WHERE file_id=?",
            (str(file_id),),
        )


# ── Content indexing ─────────────────────────────────────────────────────────

def index_page(file_id: int, page_num: int, content: str) -> None:
    """Insert a single page's text into the FTS5 index."""
    with get_db() as conn:
        conn.execute(
            "INSERT INTO content_fts (file_id, page_num, content) "
            "VALUES (?, ?, ?)",
            (str(file_id), str(page_num), _tokenize_cjk(content)),
        )


def index_pages_batch(rows: list[tuple[int, int, str]]) -> None:
    """Batch-insert multiple (file_id, page_num, content) rows."""
    with get_db() as conn:
        conn.executemany(
            "INSERT INTO content_fts (file_id, page_num, content) "
            "VALUES (?, ?, ?)",
            [(str(fid), str(pn), _tokenize_cjk(c)) for fid, pn, c in rows],
        )


# ── FTS5 search ──────────────────────────────────────────────────────────────

# Characters that have special meaning in FTS5 MATCH expressions
_FTS5_SPECIAL = re.compile(r'["\*\(\)\+\-\^:{}]')


def _sanitize_fts5_query(raw: str) -> str:
    """Escape special FTS5 MATCH characters and tokenize CJK for matching.

    CJK characters are spaced out so the query matches the character-level
    tokens stored in the index.  The result is wrapped in double-quotes
    so FTS5 treats it as a literal phrase.
    """
    cleaned = _FTS5_SPECIAL.sub(" ", raw).strip()
    if not cleaned:
        return '""'
    # Tokenize CJK characters to match the indexed format
    cleaned = _tokenize_cjk(cleaned)
    escaped = cleaned.replace('"', ' ')
    return f'"{escaped}"'


def _extract_snippets(content: str, keyword: str, ctx: int = 40) -> list[str]:
    """Extract all occurrences of *keyword* from *content* with context.

    *content* is the raw CJK-tokenized text stored in FTS5.  We first
    collapse the tokenization spaces so the search works on natural text,
    then create one snippet per occurrence with *ctx* characters of
    surrounding context.
    """
    clean = _CJK_SPACE_RE.sub("", content)
    target = _CJK_SPACE_RE.sub("", keyword)
    if not target:
        return []
    snippets: list[str] = []
    start = 0
    while True:
        idx = clean.find(target, start)
        if idx == -1:
            break
        lo = max(0, idx - ctx)
        hi = min(len(clean), idx + len(target) + ctx)
        prefix = "…" if lo > 0 else ""
        suffix = "…" if hi < len(clean) else ""
        snippets.append(prefix + clean[lo:hi] + suffix)
        start = idx + 1  # advance past this occurrence
    return snippets


def _extract_sentence_for_keyword(content: str, keyword: str) -> str:
    """Extract the sentence containing the first keyword occurrence."""
    clean = _CJK_SPACE_RE.sub("", content)
    target = _CJK_SPACE_RE.sub("", keyword)
    if not target:
        return ""

    idx = clean.find(target)
    if idx == -1:
        return ""

    boundaries = "。！？；\n"
    start = idx
    while start > 0 and clean[start - 1] not in boundaries:
        start -= 1

    end = idx + len(target)
    while end < len(clean) and clean[end] not in boundaries:
        end += 1
    if end < len(clean):
        end += 1

    return clean[start:end].strip()


def _extract_occurrence_items(
    content: str,
    keyword: str,
    ctx: int = 40,
) -> list[tuple[str, str]]:
    """Extract (snippet, sentence) for every keyword occurrence in content."""
    clean = _CJK_SPACE_RE.sub("", content)
    target = _CJK_SPACE_RE.sub("", keyword)
    if not target:
        return []

    boundaries = "。！？；\n"
    items: list[tuple[str, str]] = []
    start = 0
    while True:
        idx = clean.find(target, start)
        if idx == -1:
            break

        lo = max(0, idx - ctx)
        hi = min(len(clean), idx + len(target) + ctx)
        prefix = "…" if lo > 0 else ""
        suffix = "…" if hi < len(clean) else ""
        snippet = prefix + clean[lo:hi] + suffix

        sent_start = idx
        while sent_start > 0 and clean[sent_start - 1] not in boundaries:
            sent_start -= 1

        sent_end = idx + len(target)
        while sent_end < len(clean) and clean[sent_end] not in boundaries:
            sent_end += 1
        if sent_end < len(clean):
            sent_end += 1

        sentence = clean[sent_start:sent_end].strip()
        items.append((snippet, sentence))
        start = idx + 1

    return items


def search_content(query: str, limit: int = 200) -> list[dict]:
    """
    Run an FTS5 MATCH query and return results with contextual snippets.

    The query is sanitized to prevent FTS5 syntax injection.

    Each result dict contains: file_id, page_num, snippet,
    snippets, filename, dynasty, category, author.
    """
    safe_query = _sanitize_fts5_query(query)
    # Strip FTS5 special chars to get the raw keyword for in-text search
    raw_keyword = _FTS5_SPECIAL.sub(" ", query).strip()

    with get_db() as conn:
        rows = conn.execute(
            f"""
            SELECT
                c.file_id,
                c.page_num,
                c.content,
                snippet(content_fts, 2, '【', '】', '…', 30) AS snippet,
                f.filename,
                f.dynasty,
                f.category,
                f.author
            FROM content_fts c
            JOIN files f ON f.id = CAST(c.file_id AS INTEGER)
            WHERE content_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (safe_query, limit),
        ).fetchall()
        results: list[dict] = []
        for r in rows:
            d = dict(r)
            content = d.pop("content", "")
            db_snippet = _clean_snippet(d.get("snippet", ""))
            occurrences = _extract_occurrence_items(content, raw_keyword)

            # Split local hits by occurrence so multiple matches on the same page
            # become multiple entries.
            if occurrences:
                for snippet, sentence in occurrences:
                    row_item = dict(d)
                    row_item["snippet"] = snippet
                    row_item["snippets"] = [snippet]
                    row_item["keyword_sentence"] = sentence
                    results.append(row_item)
            else:
                d["snippet"] = db_snippet
                d["snippets"] = [db_snippet] if db_snippet else []
                d["keyword_sentence"] = (
                    _extract_sentence_for_keyword(content, raw_keyword) or db_snippet
                )
                results.append(d)
        return results


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
    """Delete a session and all its messages and search results (CASCADE)."""
    with get_db() as conn:
        conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))


def update_session_traditional_keyword(session_id: int,
                                       traditional_keyword: str) -> None:
    """Store the traditional Chinese keyword on a session."""
    with get_db() as conn:
        conn.execute(
            "UPDATE sessions SET traditional_keyword=? WHERE id=?",
            (traditional_keyword, session_id),
        )


def update_session_synthesis(session_id: int, synthesis: str) -> None:
    """Store the AI synthesis text on a session."""
    with get_db() as conn:
        conn.execute(
            "UPDATE sessions SET synthesis=? WHERE id=?",
            (synthesis, session_id),
        )


# ── Search Results CRUD ──────────────────────────────────────────────────────

def insert_search_results(session_id: int, hits: list[dict]) -> None:
    """Batch-insert search result hits for a session.

    The ``snippets`` list (if present) is JSON-serialised into the
    ``snippet`` column so that no schema migration is needed.  For
    local results that only carry a single ``snippet`` string, the
    value is stored as-is.
    """
    if not hits:
        return
    with get_db() as conn:
        # Session may be deleted while an async search task is still running.
        session_exists = conn.execute(
            "SELECT 1 FROM sessions WHERE id=? LIMIT 1",
            (session_id,),
        ).fetchone()
        if not session_exists:
            logger.warning(
                "Skip insert_search_results: session %s does not exist",
                session_id,
            )
            return

        try:
            conn.executemany(
                """INSERT INTO search_results
                   (session_id, source, file_id, filename, page_num,
                    snippet, keyword_sentence, is_original_text,
                    content_label,
                    dynasty, category, author, sutra_id, title)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        session_id,
                        h.get("source", "local"),
                        int(h["file_id"]) if h.get("file_id") else None,
                        h.get("filename", ""),
                        int(h["page_num"]) if h.get("page_num") else None,
                        json.dumps(h["snippets"], ensure_ascii=False)
                        if h.get("snippets")
                        else h.get("snippet", ""),
                        h.get("keyword_sentence", ""),
                        1 if h.get("is_original_text", False) else 0,
                        h.get("content_label", ""),
                        h.get("dynasty", ""),
                        h.get("category", ""),
                        h.get("author", ""),
                        h.get("sutra_id"),
                        h.get("title"),
                    )
                    for h in hits
                ],
            )
        except sqlite3.IntegrityError:
            logger.warning(
                "Skip insert_search_results due FK constraint. session_id=%s, hits=%d",
                session_id,
                len(hits),
                exc_info=True,
            )


def get_search_results_by_session(session_id: int) -> list[dict]:
    """Return all search results for a session ordered by id.

    If the ``snippet`` column contains a JSON array string, it is
    parsed back into a ``snippets`` list on the returned dict.
    """
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM search_results WHERE session_id=? ORDER BY id ASC",
            (session_id,),
        ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["is_original_text"] = bool(d.get("is_original_text"))
            snippet_val = d.get("snippet", "")
            if snippet_val.startswith("["):
                try:
                    d["snippets"] = json.loads(snippet_val)
                    d["snippet"] = d["snippets"][0] if d["snippets"] else ""
                except (json.JSONDecodeError, TypeError):
                    d["snippets"] = [snippet_val] if snippet_val else []
            else:
                d["snippets"] = [snippet_val] if snippet_val else []
            results.append(d)
        return results


# ── Settings CRUD ────────────────────────────────────────────────────────────

def get_setting(key: str) -> str | None:
    """Return a setting value by key, or None if not found."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key=?", (key,)
        ).fetchone()
        return row["value"] if row else None


def set_setting(key: str, value: str) -> None:
    """Insert or update a setting."""
    with get_db() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


def get_all_settings() -> dict[str, str]:
    """Return all settings as a dict."""
    with get_db() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        return {r["key"]: r["value"] for r in rows}
