"""Structured paper analysis and retrieval-grounded multi-paper comparison."""
import json

from . import db, llm, store
from .schemas import Comparison, PaperAnalysis

DEFAULT_ASPECTS = ["Research problem", "Methodology", "Datasets", "Results and metrics", "Limitations"]

ANALYSIS_PROMPT = """Analyse this research paper. Be specific and exact: include names, numbers and metrics as written.
If something is not reported, say "Not reported" (or return an empty list).

PAPER: {title}

TEXT:
{text}"""

COMPARE_PROMPT = """Compare the papers below on each aspect, using ONLY the numbered passages.
For every aspect return one cell per paper (use the exact paper_id shown). Each cell value must be 1-3 sentences,
cite passages like [4], and say "Not reported" when the passages do not cover it.
Then write a short summary of the key similarities and differences.

Aspects: {aspects}

{context}"""


def paper_text(pid, limit=90000):
    return "\n\n".join(f"[{h.meta['section']}] {h.text}" for h in store.paper_chunks(pid))[:limit]


def analyze(pid, force=False):
    row = db.one("SELECT * FROM papers WHERE id=?", (pid,))
    if row["analysis"] and not force:
        return json.loads(row["analysis"])
    res = llm.structured(PaperAnalysis, ANALYSIS_PROMPT.format(title=row["title"], text=paper_text(pid)))
    db.execute("UPDATE papers SET analysis=? WHERE id=?", (res.model_dump_json(), pid))
    return res.model_dump()


def compare(paper_ids, aspects):
    aspects = [a.strip() for a in aspects if a.strip()] or DEFAULT_ASPECTS
    papers = {p: db.one("SELECT id, title FROM papers WHERE id=?", (p,)) for p in paper_ids}
    numbering, hits_all, blocks = {}, [], []
    for pid, p in papers.items():
        blocks.append(f"=== PAPER paper_id={pid} | {p['title']} ===")
        for asp in aspects:
            top = store.rerank(asp, store.retrieve([f"{asp}: {p['title']}"], "hybrid", [pid], (), 12), 3)
            lines = []
            for h in top:
                if h.id not in numbering:
                    numbering[h.id] = len(numbering) + 1
                    hits_all.append(h)
                lines.append(f"[{numbering[h.id]}] ({h.meta['section']}, p.{h.meta['page']}) {h.text}")
            blocks.append(f"--- Aspect: {asp} ---\n" + ("\n".join(lines) or "(no passages found)"))
    res = llm.structured(Comparison, COMPARE_PROMPT.format(aspects="; ".join(aspects), context="\n\n".join(blocks)))
    by_aspect = {r.aspect.strip().lower(): {c.paper_id: c.value for c in r.cells} for r in res.rows}
    rows = []
    for asp in aspects:
        cells = by_aspect.get(asp.lower()) or next(
            (v for k, v in by_aspect.items() if asp.lower() in k or k in asp.lower()), {})
        rows.append({"aspect": asp, "cells": {pid: cells.get(pid, "Not reported") for pid in paper_ids}})
    sources = [{"n": numbering[h.id], "paper_id": h.meta["paper_id"], "title": h.meta["title"], "page": h.meta["page"],
                "section": h.meta["section"], "text": h.text} for h in hits_all]
    return {"papers": [{"id": p, "title": papers[p]["title"]} for p in paper_ids], "rows": rows,
            "summary": res.summary, "sources": sources}
