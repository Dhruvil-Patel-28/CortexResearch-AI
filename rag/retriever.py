"""
Hybrid retriever over the personal store — the RAG layer for v2.

Indexed content is *your* data, not stale PDFs: feed items (title + body)
and published research briefs. Retrieval is hybrid:

- **BM25 leg** — SQLite FTS5 full-text index over the same documents.
- **Dense leg** — sentence-transformers embeddings + a flat FAISS index.
- **Rerank** — optional cross-encoder over the fused candidates.

Fusion is reciprocal-rank fusion (RRF), which needs no score calibration
between the legs. The whole thing is content-addressed: a fingerprint of
(id, content_hash) for every indexed document is kept in the store's meta
table, so `ensure_index()` only rebuilds when the store actually changed —
ingest a new item and the index updates on the next query, with no manual
re-index step.

Both the embedder and the reranker are injectable callables so tests run
fully offline with deterministic fakes; in production they default to local
HuggingFace models (free, no API). Every failure path degrades gracefully:
if embeddings are unavailable the BM25 leg still works, and if retrieval is
unavailable the callers get [] instead of a crash.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from dataclasses import dataclass
from contextlib import closing
from pathlib import Path
from typing import Any, Callable

from store import db
from tools.store_search import tokens
from utils.config import settings

logger = logging.getLogger(__name__)

_SNIPPET_LEN = 600
_TEXT_CAP = 4000
_RRF_K = 60
_RERANK_CANDIDATES = 16

EmbedFn = Callable[[list[str]], "Any"]  # -> list of unit vectors
RerankFn = Callable[[str, list[str]], list[float]]


@dataclass
class Doc:
    ref_id: str
    kind: str  # "item" | "brief"
    title: str
    url: str
    text: str
    source: str = ""
    published_at: str = ""
    content_hash: str = ""


def _item_docs() -> list[Doc]:
    with closing(db.connect()) as con:
        rows = con.execute(
            "SELECT id, title, url, source, raw_text, published_at, content_hash FROM items"
        ).fetchall()
    docs = []
    for r in rows:
        body = (r["raw_text"] or "").strip()[:_TEXT_CAP]
        if not body and not r["title"]:
            continue
        docs.append(
            Doc(
                ref_id=r["id"],
                kind="item",
                title=r["title"] or r["url"] or r["id"],
                url=r["url"] or "",
                text=f"{r['title'] or ''}\n\n{body}".strip(),
                source=r["source"] or "",
                published_at=r["published_at"] or "",
                content_hash=r["content_hash"] or "",
            )
        )
    return docs


def _brief_text(report: dict[str, Any]) -> str:
    """Flatten a report v2 JSON into plain text for indexing."""
    parts: list[str] = []
    for key in ("title", "query", "executive_summary", "technical_explainer"):
        value = report.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    for bullet in report.get("tldr") or []:
        if isinstance(bullet, str):
            parts.append(bullet)
    for dev in report.get("key_developments") or []:
        if isinstance(dev, dict):
            if isinstance(dev.get("claim"), str):
                parts.append(dev["claim"])
            if isinstance(dev.get("evidence"), str):
                parts.append(dev["evidence"])
    for entry in report.get("implications") or []:
        if isinstance(entry, str):
            parts.append(entry)
        elif isinstance(entry, dict) and isinstance(entry.get("text"), str):
            parts.append(entry["text"])
    return "\n\n".join(parts)[:_TEXT_CAP]


def _brief_docs() -> list[Doc]:
    with closing(db.connect()) as con:
        rows = con.execute(
            "SELECT id, query, report_json, created_at FROM briefs WHERE status = 'done'"
        ).fetchall()
    docs = []
    for r in rows:
        try:
            report = json.loads(r["report_json"] or "{}")
        except (ValueError, TypeError):
            continue
        text = _brief_text(report)
        if not text:
            continue
        title = report.get("title") or r["query"] or r["id"]
        docs.append(
            Doc(
                ref_id=r["id"],
                kind="brief",
                title=title,
                url="",
                text=f"{title}\n\n{text}".strip(),
                source="report",
                published_at=r["created_at"] or "",
            )
        )
    return docs


def load_docs() -> list[Doc]:
    return _item_docs() + _brief_docs()


def fingerprint(docs: list[Doc]) -> str:
    h = hashlib.sha1()
    h.update(f"{len(docs)}\n".encode())
    for d in sorted(docs, key=lambda d: d.ref_id):
        digest = d.content_hash or hashlib.sha1(d.text.encode()).hexdigest()[:16]
        h.update(f"{d.ref_id}:{d.kind}:{digest}\n".encode())
    return h.hexdigest()


def _fts_query(query: str) -> str:
    kw = tokens(query, limit=12)
    if not kw:
        return ""
    return " OR ".join(f'"{t}"' for t in kw)


class Retriever:
    """Hybrid (BM25 + dense) retriever with optional cross-encoder rerank."""

    def __init__(
        self,
        *,
        embedder: EmbedFn | None = None,
        reranker: RerankFn | None = None,
    ) -> None:
        self._embedder = embedder
        self._reranker = reranker
        self._dense_failed = False
        self._vectors: Any = None  # numpy matrix of unit vectors (dense index)
        self._index_docs: list[Doc] = []
        self._fts_ready = False

    # ── component loading ────────────────────────────────────────────

    def _get_embedder(self) -> EmbedFn | None:
        if self._dense_failed:
            return None
        if self._embedder is None:
            try:
                from sentence_transformers import SentenceTransformer

                model = SentenceTransformer(settings.embedding_model)
                self._embedder = lambda texts: model.encode(
                    texts, normalize_embeddings=True, show_progress_bar=False
                )
                logger.info("Embedding model loaded: %s", settings.embedding_model)
            except Exception as e:  # noqa: BLE001 — offline / missing model
                logger.warning("Dense retrieval disabled (embedder unavailable): %s", e)
                self._dense_failed = True
                return None
        return self._embedder

    def _get_reranker(self) -> RerankFn | None:
        if self._reranker is None and not settings.rag_rerank:
            return None
        if self._reranker is None:
            try:
                from sentence_transformers import CrossEncoder

                model = CrossEncoder(settings.rag_rerank_model)
                self._reranker = lambda query, texts: [
                    float(s) for s in model.predict([(query, t) for t in texts])
                ]
                logger.info("Reranker loaded: %s", settings.rag_rerank_model)
            except Exception as e:  # noqa: BLE001 — optional component
                logger.warning("Reranking disabled (model unavailable): %s", e)
                self._reranker = lambda query, texts: []
                return None
        return self._reranker or None

    # ── indexing ─────────────────────────────────────────────────────

    def ensure_index(self) -> bool:
        """
        Rebuild the indexes when the store changed since the last build.

        Returns True when a rebuild happened.
        """
        docs = load_docs()
        fp = fingerprint(docs)
        if db.get_meta("rag_fingerprint") == fp and self._fts_ready:
            return False

        self._build_fts(docs)
        self._build_dense(docs)
        db.set_meta("rag_fingerprint", fp)
        logger.info("Retrieval index rebuilt: %d documents", len(docs))
        return True

    def _build_fts(self, docs: list[Doc]) -> None:
        with closing(db.connect()) as con, con:
            con.execute("DROP TABLE IF EXISTS rag_fts")
            con.execute(
                "CREATE VIRTUAL TABLE rag_fts USING fts5("
                "ref_id UNINDEXED, title, body, kind UNINDEXED)"
            )
            con.executemany(
                "INSERT INTO rag_fts (ref_id, title, body, kind) VALUES (?, ?, ?, ?)",
                [(d.ref_id, d.title, d.text, d.kind) for d in docs],
            )
        self._fts_ready = True

    def _build_dense(self, docs: list[Doc]) -> None:
        embed = self._get_embedder()
        if embed is None or not docs:
            self._vectors = None
            self._index_docs = docs
            return
        try:
            import numpy as np

            vectors = np.asarray(
                embed([d.text[:1500] for d in docs]), dtype="float32"
            )
            if vectors.ndim == 1:
                vectors = vectors.reshape(1, -1)
            self._vectors = np.atleast_2d(vectors)
            self._index_docs = docs

            # Persist the matrix so a fresh process can mmap it instead of
            # re-embedding the whole store. (NumPy exact search is the right
            # tool at personal-store scale — and avoids faiss+torch duplicate
            # OpenMP runtime crashes on macOS.)
            out_dir = Path(settings.rag_index_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            np.save(out_dir / "vectors.npy", self._vectors)
            (out_dir / "docs.json").write_text(
                json.dumps(
                    [d.__dict__ for d in docs], ensure_ascii=False, default=str
                ),
                encoding="utf-8",
            )
        except Exception as e:  # noqa: BLE001 — dense leg must never break search
            logger.warning("Dense index build failed: %s", e)
            self._vectors = None

    # ── legs ─────────────────────────────────────────────────────────

    def _bm25_hits(self, query: str, k: int) -> dict[str, float]:
        """ref_id -> rank (0 = best)."""
        fts_q = _fts_query(query)
        if not fts_q or not self._fts_ready:
            return {}
        try:
            with closing(db.connect()) as con:
                rows = con.execute(
                    "SELECT ref_id FROM rag_fts WHERE rag_fts MATCH ? "
                    "ORDER BY rank LIMIT ?",
                    (fts_q, k),
                ).fetchall()
            return {r["ref_id"]: rank for rank, r in enumerate(rows)}
        except Exception as e:  # noqa: BLE001
            logger.warning("BM25 leg failed: %s", e)
            return {}

    def _dense_hits(self, query: str, k: int) -> dict[str, float]:
        """ref_id -> rank (0 = best)."""
        embed = self._get_embedder()
        if embed is None or self._vectors is None or not self._index_docs:
            return {}
        try:
            import numpy as np

            vec = np.asarray(embed([query[:512]]), dtype="float32")
            if vec.ndim == 1:
                vec = vec.reshape(1, -1)
            sims = (self._vectors @ vec.T).ravel()  # unit vectors → cosine
            order = np.argsort(sims)[::-1][:k]
            return {
                self._index_docs[int(i)].ref_id: rank
                for rank, i in enumerate(order)
                if sims[i] > 0.05
            }
        except Exception as e:  # noqa: BLE001
            logger.warning("Dense leg failed: %s", e)
            return {}

    # ── search ───────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        k: int = 8,
        *,
        kinds: tuple[str, ...] = ("item", "brief"),
    ) -> list[dict[str, Any]]:
        """
        Hybrid search over the store. Returns dicts shaped like:
            {"ref_id", "kind", "title", "url", "snippet", "source",
             "published_at", "score"} — best first.
        """
        try:
            self.ensure_index()
        except Exception as e:  # noqa: BLE001 — stale index beats no search
            logger.warning("Index refresh failed, searching stale state: %s", e)

        pool = max(k * 4, _RERANK_CANDIDATES)
        bm25 = self._bm25_hits(query, pool)
        dense = self._dense_hits(query, pool)

        all_ids = set(bm25) | set(dense)
        if not all_ids:
            return []

        # Reciprocal-rank fusion across the legs.
        rrf: dict[str, float] = {}
        for leg in (bm25, dense):
            for ref_id, rank in leg.items():
                rrf[ref_id] = rrf.get(ref_id, 0.0) + 1.0 / (_RRF_K + rank + 1)

        by_id = {d.ref_id: d for d in self._index_docs}
        if not by_id:  # dense leg never built — resolve docs from the store
            by_id = {d.ref_id: d for d in load_docs() if d.ref_id in all_ids}

        candidates = [by_id[ref_id] for ref_id in all_ids if ref_id in by_id]
        if not candidates:
            return []
        candidates.sort(key=lambda d: rrf.get(d.ref_id, 0.0), reverse=True)
        candidates = candidates[:_RERANK_CANDIDATES]

        scores: dict[str, float] | None = None
        rerank = self._get_reranker()
        if rerank is not None and len(candidates) > 1:
            try:
                ce = rerank(query, [d.text[:1200] for d in candidates])
                if ce:
                    scores = {
                        d.ref_id: 1.0 / (1.0 + math.exp(-min(s, 20.0)))
                        for d, s in zip(candidates, ce)
                    }
                    candidates.sort(key=lambda d: scores[d.ref_id], reverse=True)
            except Exception as e:  # noqa: BLE001 — fall back to RRF order
                logger.warning("Rerank failed, using RRF order: %s", e)
                scores = None

        max_rrf = max((rrf.get(d.ref_id, 0.0) for d in candidates), default=1.0) or 1.0
        results = []
        for d in candidates[:k]:
            if d.kind not in kinds:
                continue
            if scores and d.ref_id in scores:
                score = scores[d.ref_id]
            else:
                score = rrf.get(d.ref_id, 0.0) / max_rrf
            results.append(
                {
                    "ref_id": d.ref_id,
                    "kind": d.kind,
                    "title": d.title,
                    "url": d.url,
                    "snippet": " ".join(d.text.split())[:_SNIPPET_LEN],
                    "source": d.source,
                    "published_at": d.published_at,
                    "score": round(score, 4),
                }
            )
        return results


# ── module-level singleton ───────────────────────────────────────────

_retriever: Retriever | None = None


def get_retriever() -> Retriever:
    global _retriever
    if _retriever is None:
        _retriever = Retriever()
    return _retriever


def reset_retriever() -> None:
    """Drop the cached retriever (used by tests and the reindex endpoint)."""
    global _retriever
    _retriever = None
