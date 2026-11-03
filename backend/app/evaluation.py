"""RAG evaluation: synthetic QA set from your own papers, retrieval ablation, optional LLM-as-judge."""
import json
import random
import time

from . import db, llm, pipeline, store
from .schemas import Judgement, QABatch

MODES = ["dense", "bm25", "hybrid", "hybrid_rerank"]
MIN_CHARS = 250
SKIP = {"front_matter", "references", "acknowledgments", "appendix"}

GEN_PROMPT = """Below are passages from research papers. For EACH passage write one question that can be answered
using only that passage, plus a short reference answer.
Rules: the question must be self-contained and specific (name the method, dataset or concept so it is not ambiguous
across papers); do not say "the passage", "the text" or "the paper"; do not ask yes/no questions.
Return one item per passage with the exact chunk_id.

{passages}"""

JUDGE_PROMPT = """You grade a RAG answer. Score each criterion from 1 (bad) to 5 (excellent).
- faithfulness: every claim in the answer is supported by the context
- relevance: the answer addresses the question
- correctness: the answer agrees with the reference answer

Question: {q}
Reference answer: {ref}
Context:
{ctx}
Answer to grade:
{ans}"""


def generate_set(paper_ids, n=10):
    pool = [c for c in store.all_chunks(paper_ids) if c.meta["section"] not in SKIP and len(c.text) > MIN_CHARS]
    if not pool:
        raise ValueError("Not enough text chunks to build a test set. Upload papers first.")
    random.shuffle(pool)
    chosen = pool[: max(1, n)]
    by_id = {c.id: c for c in chosen}
    items = []
    for i in range(0, len(chosen), 5):
        batch = chosen[i : i + 5]
        passages = "\n\n".join(f"chunk_id: {c.id}\n{c.text}" for c in batch)
        res = llm.structured(QABatch, GEN_PROMPT.format(passages=passages))
        for it in res.items:
            c = by_id.get(it.chunk_id)
            if c and it.question.strip():
                items.append({"chunk_id": c.id, "paper_id": c.meta["paper_id"], "section": c.meta["section"],
                              "question": it.question.strip(), "reference_answer": it.reference_answer.strip()})
    if not items:
        raise ValueError("The model returned no usable questions. Try again.")
    sid = db.new_id()
    db.execute("INSERT INTO eval_sets VALUES (?,?,?,?)",
               (sid, json.dumps(sorted({i["paper_id"] for i in items})), json.dumps(items), db.now()))
    return {"id": sid, "n": len(items), "items": items}


def run_eval(set_id, k=5, judge=False):
    row = db.one("SELECT * FROM eval_sets WHERE id=?", (set_id,))
    items = json.loads(row["items"])
    paper_ids = json.loads(row["paper_ids"])
    agg = {m: {"hit": 0, "rr": 0.0, "ms": []} for m in MODES}
    scores = {"faithfulness": [], "relevance": [], "correctness": []}
    details = []
    for it in items:
        q, gold = it["question"], it["chunk_id"]
        d = {"question": q, "section": it["section"], "ranks": {}}
        final_hits = []
        for m in MODES:
            t0 = time.time()
            cands = store.retrieve([q], m, paper_ids, (), max(30, k))
            ranked = store.rerank(q, cands, 10) if m == "hybrid_rerank" else cands[:10]
            agg[m]["ms"].append((time.time() - t0) * 1000)
            rank = next((i for i, h in enumerate(ranked, 1) if h.id == gold), None)
            d["ranks"][m] = rank
            if rank and rank <= k:
                agg[m]["hit"] += 1
            if rank:
                agg[m]["rr"] += 1 / rank
            if m == "hybrid_rerank":
                final_hits = ranked[:k]
        if judge and final_hits:
            try:
                ans = pipeline.answer_once(q, final_hits)
                j = llm.structured(Judgement, JUDGE_PROMPT.format(
                    q=q, ref=it["reference_answer"], ctx=pipeline.build_context(final_hits), ans=ans))
                for key in scores:
                    scores[key].append(max(1, min(5, getattr(j, key))))
                d["answer"], d["judge"] = ans, j.model_dump()
            except Exception as e:
                d["judge_error"] = str(e)[:200]
        details.append(d)
    n = len(items)
    results = {
        "n": n, "k": k,
        "modes": {m: {"hit_rate": agg[m]["hit"] / n, "mrr": agg[m]["rr"] / n,
                      "avg_ms": sum(agg[m]["ms"]) / n} for m in MODES},
        "judge": {key: sum(v) / len(v) for key, v in scores.items()} if judge and scores["faithfulness"] else None,
        "details": details,
    }
    rid = db.new_id()
    db.execute("INSERT INTO eval_runs VALUES (?,?,?,?,?)",
               (rid, set_id, json.dumps({"k": k, "judge": judge}), json.dumps(results), db.now()))
    return {"id": rid, "set_id": set_id, "created_at": db.now(), **results}
