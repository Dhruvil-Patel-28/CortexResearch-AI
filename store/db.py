"""
SQLite storage layer.

Stdlib-only (sqlite3) with WAL mode. A fresh connection is opened per
operation so the store is safe to use from FastAPI threads, CLI runs and
background workers alike.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable

from utils.config import settings

if TYPE_CHECKING:
    from sources.base import FeedItem

_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id            TEXT PRIMARY KEY,
    source        TEXT NOT NULL,
    external_id   TEXT,
    title         TEXT NOT NULL,
    url           TEXT,
    author        TEXT,
    published_at  TEXT,
    raw_text      TEXT,
    metrics_json  TEXT,
    content_hash  TEXT,
    cluster_key   TEXT,
    first_seen_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_items_source ON items(source);
CREATE INDEX IF NOT EXISTS idx_items_published ON items(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_items_first_seen ON items(first_seen_at DESC);
CREATE INDEX IF NOT EXISTS idx_items_cluster ON items(cluster_key);

CREATE TABLE IF NOT EXISTS topics (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE,
    keywords_json TEXT,
    active        INTEGER DEFAULT 1,
    created_at    TEXT
);

CREATE TABLE IF NOT EXISTS scores (
    item_id         TEXT NOT NULL,
    topic_id        TEXT NOT NULL,
    relevance       REAL NOT NULL,
    rationale       TEXT,
    tags_json       TEXT,
    model           TEXT,
    profile_version TEXT,
    scored_at       TEXT NOT NULL,
    PRIMARY KEY (item_id, topic_id, profile_version)
);
CREATE INDEX IF NOT EXISTS idx_scores_item ON scores(item_id);

CREATE TABLE IF NOT EXISTS bookmarks (
    item_id    TEXT PRIMARY KEY,
    note       TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS briefs (
    id             TEXT PRIMARY KEY,
    item_id        TEXT,
    topic_id       TEXT,
    query          TEXT,
    status         TEXT NOT NULL,
    report_json    TEXT,
    citations_json TEXT,
    cost_usd       REAL,
    created_at     TEXT NOT NULL,
    finished_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_briefs_created ON briefs(created_at DESC);

CREATE TABLE IF NOT EXISTS jobs (
    id            TEXT PRIMARY KEY,
    kind          TEXT NOT NULL,
    status        TEXT NOT NULL,
    payload_json  TEXT,
    progress_json TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at DESC);

CREATE TABLE IF NOT EXISTS digests (
    id            TEXT PRIMARY KEY,
    created_at    TEXT NOT NULL,
    item_ids_json TEXT,
    rendered_md   TEXT,
    delivered_json TEXT
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve_path(path: str | None = None) -> str:
    return path or settings.db_path


def connect(path: str | None = None) -> sqlite3.Connection:
    """Open a fresh SQLite connection (WAL, row factory, busy timeout)."""
    p = resolve_path(path)
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p, timeout=30.0)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    return con


def init_db(path: str | None = None) -> None:
    """Create all tables if they do not exist yet, and apply light migrations."""
    with closing(connect(path)) as con, con:
        con.executescript(_SCHEMA)
        _migrate(con)


def _migrate(con: sqlite3.Connection) -> None:
    """Add columns introduced after the first schema version."""
    existing = {r["name"] for r in con.execute("PRAGMA table_info(items)").fetchall()}
    if "cluster_key" not in existing:
        con.execute("ALTER TABLE items ADD COLUMN cluster_key TEXT")
        con.execute("CREATE INDEX IF NOT EXISTS idx_items_cluster ON items(cluster_key)")


def _decode(r: sqlite3.Row | dict) -> dict[str, Any]:
    """Decode a stored item row into an API-friendly dict."""
    d = dict(r)
    d["metrics"] = json.loads(d.pop("metrics_json", None) or "{}")
    d["tags"] = json.loads(d.pop("tags_json", None) or "[]")
    if "bookmarked" in d:
        d["bookmarked"] = bool(d["bookmarked"])
    d.setdefault("cluster_size", 1)
    if not d.get("cluster_sources"):
        d["cluster_sources"] = d.get("source", "")
    return d


# ─── Items ───


def upsert_items(items: Iterable["FeedItem"], path: str | None = None) -> tuple[int, int]:
    """
    Insert items, ignoring duplicates (same source + external id/url).

    Returns:
        (new_count, duplicate_count)
    """
    now = _now()
    new = dup = 0
    with closing(connect(path)) as con, con:
        for it in items:
            cur = con.execute(
                """
                INSERT OR IGNORE INTO items
                    (id, source, external_id, title, url, author, published_at,
                     raw_text, metrics_json, content_hash, cluster_key, first_seen_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    it.id,
                    it.source,
                    it.external_id,
                    it.title,
                    it.url,
                    it.author,
                    it.published_at,
                    it.raw_text,
                    json.dumps(it.metrics, ensure_ascii=False),
                    it.content_hash,
                    getattr(it, "cluster_key", "") or "",
                    now,
                ),
            )
            if cur.rowcount:
                new += 1
            else:
                dup += 1
    return new, dup


def list_items(
    *,
    source: str | None = None,
    since: str | None = None,
    min_score: float | None = None,
    bookmarked: bool | None = None,
    cluster_key: str | None = None,
    q: str | None = None,
    limit: int = 100,
    offset: int = 0,
    order: str = "newest",
    collapse: bool = True,
    path: str | None = None,
) -> list[dict[str, Any]]:
    """
    Query stored items with optional filters, joined with latest score + bookmark state.

    collapse=True (default) returns one row per story cluster — the best-scoring,
    newest representative — with `cluster_size` and `cluster_sources` so the same
    news from HN + RSS + Reddit renders as a single card.
    """
    clauses: list[str] = []
    params: list[Any] = []

    if source:
        clauses.append("i.source = ?")
        params.append(source)
    if since:
        clauses.append("COALESCE(NULLIF(i.published_at, ''), i.first_seen_at) >= ?")
        params.append(since)
    if q:
        clauses.append("(i.title LIKE ? OR i.raw_text LIKE ?)")
        params += [f"%{q}%", f"%{q}%"]
    if min_score is not None:
        clauses.append("COALESCE(s.relevance, 0) >= ?")
        params.append(min_score)
    if bookmarked:
        clauses.append("b.item_id IS NOT NULL")
    if cluster_key:
        clauses.append("COALESCE(NULLIF(i.cluster_key, ''), i.id) = ?")
        params.append(cluster_key)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    order_sql = "ORDER BY relevance DESC, ts DESC" if order == "relevance" else "ORDER BY ts DESC"

    base = f"""
        SELECT i.*,
               COALESCE(NULLIF(i.cluster_key, ''), i.id) AS ckey,
               COALESCE(NULLIF(i.published_at, ''), i.first_seen_at) AS ts,
               s.relevance, s.rationale, s.tags_json, s.scored_at,
               CASE WHEN b.item_id IS NULL THEN 0 ELSE 1 END AS bookmarked
        FROM items i
        LEFT JOIN scores s
               ON s.item_id = i.id
              AND s.scored_at = (SELECT MAX(scored_at) FROM scores s2 WHERE s2.item_id = i.id)
        LEFT JOIN bookmarks b ON b.item_id = i.id
        {where}
    """

    if collapse:
        sql = f"""
            WITH base AS ({base}),
            ranked AS (
                SELECT *,
                       ROW_NUMBER() OVER (
                           PARTITION BY ckey
                           ORDER BY COALESCE(relevance, -1) DESC, ts DESC
                       ) AS rn,
                       COUNT(*) OVER (PARTITION BY ckey) AS cluster_size,
                       SUM(COALESCE(relevance, 0)) OVER (PARTITION BY ckey) AS cluster_score
                FROM base
            )
            SELECT ranked.*,
                   (SELECT GROUP_CONCAT(DISTINCT i2.source)
                      FROM items i2
                     WHERE COALESCE(NULLIF(i2.cluster_key, ''), i2.id) = ranked.ckey) AS cluster_sources
            FROM ranked
            WHERE rn = 1
            {order_sql}
            LIMIT ? OFFSET ?
        """
    else:
        sql = f"{base} {order_sql} LIMIT ? OFFSET ?"

    params += [limit, offset]

    with closing(connect(path)) as con:
        rows = con.execute(sql, params).fetchall()

    return [_decode(r) for r in rows]


def get_item(item_id: str, path: str | None = None) -> dict[str, Any] | None:
    """Fetch a single item with its score, bookmark state and cluster info."""
    with closing(connect(path)) as con:
        row = con.execute(
            """
            SELECT i.*,
                   COALESCE(NULLIF(i.cluster_key, ''), i.id) AS ckey,
                   CASE WHEN b.item_id IS NULL THEN 0 ELSE 1 END AS bookmarked,
                   (SELECT COUNT(*) FROM items i2
                     WHERE COALESCE(NULLIF(i2.cluster_key, ''), i2.id)
                         = COALESCE(NULLIF(i.cluster_key, ''), i.id)) AS cluster_size,
                   (SELECT GROUP_CONCAT(DISTINCT i2.source) FROM items i2
                     WHERE COALESCE(NULLIF(i2.cluster_key, ''), i2.id)
                         = COALESCE(NULLIF(i.cluster_key, ''), i.id)) AS cluster_sources
            FROM items i
            LEFT JOIN bookmarks b ON b.item_id = i.id
            WHERE i.id = ?
            """,
            (item_id,),
        ).fetchone()
        if not row:
            return None

        d = _decode(row)
        s = con.execute(
            "SELECT relevance, rationale, tags_json, scored_at FROM scores WHERE item_id = ? ORDER BY scored_at DESC LIMIT 1",
            (item_id,),
        ).fetchone()
        if s:
            d["relevance"] = s["relevance"]
            d["rationale"] = s["rationale"]
            d["tags"] = json.loads(s["tags_json"] or "[]")
        else:
            d["relevance"] = None
            d["rationale"] = ""
            d["tags"] = []
        return d


def get_cluster_items(cluster_key: str, path: str | None = None) -> list[dict[str, Any]]:
    """All items in a story cluster — powers the 'also covered by' list."""
    if not cluster_key:
        return []
    return list_items(cluster_key=cluster_key, collapse=False, limit=25, path=path)


def item_ids_with_content_hashes(path: str | None = None) -> dict[str, str]:
    """Map of item_id -> content_hash for prefilter cache checks."""
    with closing(connect(path)) as con:
        rows = con.execute("SELECT id, content_hash FROM items").fetchall()
    return {r["id"]: r["content_hash"] for r in rows}


# ─── Scores ───


def save_scores(scores: Iterable[dict[str, Any]], path: str | None = None) -> int:
    """Insert or replace score rows. Each dict: item_id, topic_id, relevance, rationale, tags, model, profile_version."""
    now = _now()
    n = 0
    with closing(connect(path)) as con, con:
        for s in scores:
            con.execute(
                """
                INSERT OR REPLACE INTO scores
                    (item_id, topic_id, relevance, rationale, tags_json, model, profile_version, scored_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    s["item_id"],
                    s.get("topic_id", "general"),
                    float(s["relevance"]),
                    s.get("rationale", ""),
                    json.dumps(s.get("tags", []), ensure_ascii=False),
                    s.get("model", ""),
                    s.get("profile_version", ""),
                    now,
                ),
            )
            n += 1
    return n


def scored_item_ids(profile_version: str, path: str | None = None) -> set[str]:
    """Item ids already scored under a given profile version (cache lookups)."""
    with closing(connect(path)) as con:
        rows = con.execute(
            "SELECT DISTINCT item_id FROM scores WHERE profile_version = ?", (profile_version,)
        ).fetchall()
    return {r["item_id"] for r in rows}


# ─── Bookmarks ───


def set_bookmark(item_id: str, note: str = "", path: str | None = None) -> None:
    with closing(connect(path)) as con, con:
        con.execute(
            "INSERT OR REPLACE INTO bookmarks (item_id, note, created_at) VALUES (?, ?, ?)",
            (item_id, note, _now()),
        )


def remove_bookmark(item_id: str, path: str | None = None) -> None:
    with closing(connect(path)) as con, con:
        con.execute("DELETE FROM bookmarks WHERE item_id = ?", (item_id,))


# ─── Jobs ───


def create_job(kind: str, payload: dict[str, Any] | None = None, path: str | None = None) -> str:
    job_id = uuid.uuid4().hex[:12]
    now = _now()
    with closing(connect(path)) as con, con:
        con.execute(
            "INSERT INTO jobs (id, kind, status, payload_json, progress_json, created_at, updated_at) VALUES (?, ?, 'pending', ?, '{}', ?, ?)",
            (job_id, kind, json.dumps(payload or {}), now, now),
        )
    return job_id


def update_job(
    job_id: str,
    *,
    status: str | None = None,
    progress: dict[str, Any] | None = None,
    path: str | None = None,
) -> None:
    sets = ["updated_at = ?"]
    params: list[Any] = [_now()]
    if status:
        sets.append("status = ?")
        params.append(status)
    if progress is not None:
        sets.append("progress_json = ?")
        params.append(json.dumps(progress, ensure_ascii=False))
    params.append(job_id)
    with closing(connect(path)) as con, con:
        con.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id = ?", params)


def get_job(job_id: str, path: str | None = None) -> dict[str, Any] | None:
    with closing(connect(path)) as con:
        row = con.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["payload"] = json.loads(d.pop("payload_json") or "{}")
    d["progress"] = json.loads(d.pop("progress_json") or "{}")
    return d


# ─── Meta ───


def set_meta(key: str, value: str, path: str | None = None) -> None:
    with closing(connect(path)) as con, con:
        con.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))


def get_meta(key: str, default: str | None = None, path: str | None = None) -> str | None:
    with closing(connect(path)) as con:
        row = con.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


# ─── Stats ───


def stats(path: str | None = None) -> dict[str, Any]:
    """Summary counts for the dashboard."""
    with closing(connect(path)) as con:
        total = con.execute("SELECT COUNT(*) AS c FROM items").fetchone()["c"]
        by_source = {
            r["source"]: r["c"]
            for r in con.execute("SELECT source, COUNT(*) AS c FROM items GROUP BY source").fetchall()
        }
        scored = con.execute("SELECT COUNT(DISTINCT item_id) AS c FROM scores").fetchone()["c"]
        bookmarks = con.execute("SELECT COUNT(*) AS c FROM bookmarks").fetchone()["c"]
        last_ingest = con.execute("SELECT value FROM meta WHERE key = 'last_ingest_at'").fetchone()
    return {
        "total_items": total,
        "by_source": by_source,
        "scored_items": scored,
        "bookmarks": bookmarks,
        "last_ingest_at": last_ingest["value"] if last_ingest else None,
    }
