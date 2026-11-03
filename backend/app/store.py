"""Vector store (Chroma) + BM25 + Reciprocal Rank Fusion + cross-encoder reranking."""
import logging
import math
import re
import threading
from dataclasses import dataclass, field

import chromadb
import numpy as np
from rank_bm25 import BM25Okapi

from . import llm
from .config import settings

log = logging.getLogger(__name__)

_client = chromadb.PersistentClient(path=str(settings.data_dir / "chroma"))
_col = _client.get_or_create_collection("papers", metadata={"hnsw:space": "cosine"})
_lock = threading.Lock()
_bm25, _rows = None, []
_ce, _ce_failed = None, False
STOP = set("a an the of and or in on to for with is are was were be by as at from that this these those it its we our can which".split())


@dataclass
class Hit:
    id: str
    text: str
    meta: dict
    scores: dict = field(default_factory=dict)


def tok(s):
    return [w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in STOP]


def count():
    return _col.count()


def _invalidate():
    global _bm25, _rows
    with _lock:
        _bm25, _rows = None, []


def add_chunks(paper_id, meta, chunks):
    ids = [f"{paper_id}:{c['index']}" for c in chunks]
    docs = [c["text"] for c in chunks]
    # contextual header helps retrieval; the stored text stays clean for display + BM25
    embs = llm.embed([f"{meta.title} | {c['section']}\n{c['text']}" for c in chunks], "doc")
    metas = [{"paper_id": paper_id, "title": meta.title, "section": c["section"], "section_title": c["section_title"],
              "page": c["page"], "page_end": c["page_end"], "chunk_index": c["index"]} for c in chunks]
    _col.add(ids=ids, documents=docs, embeddings=embs, metadatas=metas)
    _invalidate()


def delete_paper(paper_id):
    _col.delete(where={"paper_id": paper_id})
    _invalidate()


def _where(paper_ids, sections):
    conds = []
    if paper_ids:
        conds.append({"paper_id": {"$in": list(paper_ids)}})
    if sections:
        conds.append({"section": {"$in": list(sections)}})
    if not conds:
        return None
    return conds[0] if len(conds) == 1 else {"$and": conds}


def _ensure_bm25():
    global _bm25, _rows
    with _lock:
        if _bm25 is None:
            data = _col.get(include=["documents", "metadatas"])
            _rows = [Hit(i, d, m) for i, d, m in zip(data["ids"], data["documents"], data["metadatas"])]
            _bm25 = BM25Okapi([tok(r.text) or ["_"] for r in _rows]) if _rows else None
        return _bm25, _rows


def dense_search(query, n=20, paper_ids=(), sections=()):
    total = _col.count()
    if not total:
        return []
    res = _col.query(query_embeddings=[list(llm.embed_query(query))], n_results=min(n, total),
                     where=_where(paper_ids, sections), include=["documents", "metadatas", "distances"])
    return [Hit(i, d, m, {"dense": 1 - dist}) for i, d, m, dist in
            zip(res["ids"][0], res["documents"][0], res["metadatas"][0], res["distances"][0])]


def bm25_search(query, n=20, paper_ids=(), sections=()):
    bm25, rows = _ensure_bm25()
    if bm25 is None:
        return []
    scores = bm25.get_scores(tok(query))
    out = []
    for idx in np.argsort(-scores):
        r = rows[idx]
        if scores[idx] <= 0:
            break
        if paper_ids and r.meta["paper_id"] not in paper_ids:
            continue
        if sections and r.meta["section"] not in sections:
            continue
        out.append(Hit(r.id, r.text, r.meta, {"bm25": float(scores[idx])}))
        if len(out) >= n:
            break
    return out


def rrf(lists, k=60):
    """Reciprocal Rank Fusion over several ranked lists of Hits."""
    merged = {}
    for hits in lists:
        for rank, h in enumerate(hits, 1):
            m = merged.setdefault(h.id, Hit(h.id, h.text, h.meta, {"rrf": 0.0}))
            m.scores["rrf"] += 1.0 / (k + rank)
            for key, val in h.scores.items():
                m.scores[key] = max(m.scores.get(key, val), val)
            src = "dense" if "dense" in h.scores else "bm25"
            m.scores[f"{src}_rank"] = min(m.scores.get(f"{src}_rank", rank), rank)
    return sorted(merged.values(), key=lambda h: h.scores["rrf"], reverse=True)


def retrieve(queries, mode="hybrid", paper_ids=(), sections=(), candidate_k=30, per_list=20):
    """mode: dense | bm25 | hybrid | hybrid_rerank (rerank is applied separately via rerank())."""
    lists = []
    for q in queries:
        if mode in ("dense", "hybrid", "hybrid_rerank"):
            lists.append(dense_search(q, per_list, paper_ids, sections))
        if mode in ("bm25", "hybrid", "hybrid_rerank"):
            lists.append(bm25_search(q, per_list, paper_ids, sections))
    return rrf(lists)[:candidate_k]


def _get_reranker():
    global _ce, _ce_failed
    if settings.reranker != "cross-encoder" or _ce_failed:
        return None
    if _ce is None:
        try:
            from sentence_transformers import CrossEncoder
            _ce = CrossEncoder(settings.reranker_model)
        except Exception as e:
            log.warning("Reranker unavailable, falling back to RRF order: %s", e)
            _ce_failed = True
    return _ce


def rerank(query, hits, top_k):
    ce = _get_reranker()
    if ce is None or not hits:
        return hits[:top_k]
    s = np.asarray(ce.predict([(query, h.text) for h in hits], batch_size=16), dtype=float)
    if s.min() < 0 or s.max() > 1:
        s = 1 / (1 + np.exp(-s))
    for h, v in zip(hits, s):
        h.scores["rerank"] = float(v)
    return sorted(hits, key=lambda h: h.scores["rerank"], reverse=True)[:top_k]


def reranker_active():
    return _get_reranker() is not None


def warmup():
    try:
        _ensure_bm25()
        _get_reranker()
    except Exception as e:
        log.warning("Warmup failed: %s", e)


def paper_chunks(paper_id):
    data = _col.get(where={"paper_id": paper_id}, include=["documents", "metadatas"])
    rows = [Hit(i, d, m) for i, d, m in zip(data["ids"], data["documents"], data["metadatas"])]
    return sorted(rows, key=lambda h: h.meta["chunk_index"])


def all_chunks(paper_ids=()):
    data = _col.get(where=_where(paper_ids, ()), include=["documents", "metadatas"])
    return [Hit(i, d, m) for i, d, m in zip(data["ids"], data["documents"], data["metadatas"])]


def section_stats(paper_id):
    counts = {}
    for h in paper_chunks(paper_id):
        counts[h.meta["section"]] = counts.get(h.meta["section"], 0) + 1
    return [{"section": k, "chunks": v} for k, v in counts.items()]
