import json
import logging

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from . import analysis, db, evaluation, ingestion, llm, pipeline, store
from .config import settings
from .schemas import ChatRequest, CompareRequest, EvalGenRequest, EvalRunRequest

log = logging.getLogger(__name__)
router = APIRouter()


def sse(obj) -> str:
    return f"data: {json.dumps(obj)}\n\n"


def _paper(pid):
    row = db.one("SELECT * FROM papers WHERE id=?", (pid,))
    if not row:
        raise HTTPException(404, "Paper not found")
    return row


def _need_key():
    if not llm.has_key():
        raise HTTPException(400, "GOOGLE_API_KEY is not set. Add it to backend/.env and restart the server.")


@router.get("/health")
def health():
    return {"ok": True, "has_key": llm.has_key(), "llm": settings.llm_model, "embedding": settings.embedding_model,
            "reranker": settings.reranker, "papers": len(db.query("SELECT id FROM papers"))}


# ---------- papers ----------
@router.get("/papers")
def list_papers():
    return [db.paper_out(r) for r in db.query("SELECT * FROM papers ORDER BY created_at DESC")]


@router.post("/papers")
def upload(files: list[UploadFile] = File(...)):
    _need_key()
    out = []
    for f in files:
        if not (f.filename or "").lower().endswith(".pdf"):
            out.append({"filename": f.filename, "error": "Only PDF files are supported."})
            continue
        try:
            paper, dup = ingestion.ingest_pdf(f.file.read(), f.filename)
            out.append({"filename": f.filename, "paper": paper, "duplicate": dup})
        except Exception as e:
            log.exception("Ingestion failed for %s", f.filename)
            out.append({"filename": f.filename, "error": str(e)})
    return out


@router.get("/papers/{pid}")
def get_paper(pid: str):
    return db.paper_out(_paper(pid))


@router.delete("/papers/{pid}")
def delete_paper(pid: str):
    _paper(pid)
    store.delete_paper(pid)
    db.execute("DELETE FROM papers WHERE id=?", (pid,))
    (settings.data_dir / "pdfs" / f"{pid}.pdf").unlink(missing_ok=True)
    return {"ok": True}


@router.get("/papers/{pid}/pdf")
def paper_pdf(pid: str):
    _paper(pid)
    return FileResponse(settings.data_dir / "pdfs" / f"{pid}.pdf", media_type="application/pdf")


@router.get("/papers/{pid}/sections")
def paper_sections(pid: str):
    _paper(pid)
    return store.section_stats(pid)


@router.post("/papers/{pid}/analyze")
def analyze(pid: str, force: bool = False):
    _paper(pid)
    _need_key()
    try:
        return analysis.analyze(pid, force)
    except Exception as e:
        raise HTTPException(500, f"Analysis failed: {e}")


# ---------- compare ----------
@router.post("/compare")
def compare(req: CompareRequest):
    _need_key()
    if len(req.paper_ids) < 2:
        raise HTTPException(400, "Select at least two papers to compare.")
    for p in req.paper_ids:
        _paper(p)
    try:
        return analysis.compare(req.paper_ids, req.aspects)
    except Exception as e:
        raise HTTPException(500, f"Comparison failed: {e}")


# ---------- conversations ----------
@router.get("/conversations")
def conversations():
    return db.query("SELECT * FROM conversations ORDER BY created_at DESC")


@router.delete("/conversations/{cid}")
def delete_conversation(cid: str):
    db.execute("DELETE FROM messages WHERE conversation_id=?", (cid,))
    db.execute("DELETE FROM conversations WHERE id=?", (cid,))
    return {"ok": True}


@router.get("/conversations/{cid}/messages")
def messages(cid: str):
    rows = db.query("SELECT * FROM messages WHERE conversation_id=? ORDER BY id", (cid,))
    return [{"role": r["role"], "content": r["content"], "sources": db.loads(r["sources"], []),
             "trace": db.loads(r["trace"], None)} for r in rows]


# ---------- chat (Server-Sent Events) ----------
@router.post("/chat")
def chat(req: ChatRequest):
    _need_key()

    def gen():
        try:
            if not db.query("SELECT id FROM papers LIMIT 1"):
                yield sse({"type": "error", "message": "Upload at least one paper in the Library first."})
                return
            cid = req.conversation_id
            if not cid:
                cid = db.new_id()
                db.execute("INSERT INTO conversations VALUES (?,?,?)", (cid, req.question[:60], db.now()))
            history = db.history(cid)
            db.execute("INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?,?,?,?)",
                       (cid, "user", req.question, db.now()))
            yield sse({"type": "start", "conversation_id": cid})

            opts = {"top_k": max(1, min(req.top_k, 20)), "rewrite": req.rewrite,
                    "multi_query": req.multi_query, "rerank": req.rerank}
            state = pipeline.run_retrieval(req.question, history, req.paper_ids, req.sections, opts)
            hits, trace = state.get("hits", []), state.get("trace", {})
            sources = pipeline.sources_payload(hits)
            yield sse({"type": "retrieval", "sources": sources, "trace": trace})

            parts = []
            if not hits:
                parts.append("I could not find any passages for that. Try removing the section filter or selecting more papers.")
                yield sse({"type": "token", "text": parts[0]})
            else:
                for t in pipeline.stream_answer(state.get("standalone", req.question), history, hits, state.get("intent", "other")):
                    parts.append(t)
                    yield sse({"type": "token", "text": t})
            db.execute("INSERT INTO messages (conversation_id, role, content, sources, trace, created_at) VALUES (?,?,?,?,?,?)",
                       (cid, "assistant", "".join(parts), json.dumps(sources), json.dumps(trace), db.now()))
            yield sse({"type": "done"})
        except Exception as e:
            log.exception("chat failed")
            yield sse({"type": "error", "message": str(e)})

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------- evaluation ----------
@router.post("/eval/sets")
def eval_generate(req: EvalGenRequest):
    _need_key()
    ids = req.paper_ids or [p["id"] for p in db.query("SELECT id FROM papers")]
    if not ids:
        raise HTTPException(400, "Upload papers first.")
    try:
        return evaluation.generate_set(ids, max(3, min(req.n, 40)))
    except Exception as e:
        raise HTTPException(500, f"Could not generate test set: {e}")


@router.get("/eval/sets")
def eval_sets():
    rows = db.query("SELECT * FROM eval_sets ORDER BY created_at DESC")
    return [{"id": r["id"], "created_at": r["created_at"], "n": len(db.loads(r["items"], [])),
             "paper_ids": db.loads(r["paper_ids"], []), "items": db.loads(r["items"], [])} for r in rows]


@router.post("/eval/run")
def eval_run(req: EvalRunRequest):
    if not db.one("SELECT id FROM eval_sets WHERE id=?", (req.set_id,)):
        raise HTTPException(404, "Test set not found")
    if req.judge:
        _need_key()
    try:
        return evaluation.run_eval(req.set_id, max(1, min(req.k, 10)), req.judge)
    except Exception as e:
        raise HTTPException(500, f"Evaluation failed: {e}")


@router.get("/eval/runs")
def eval_runs():
    rows = db.query("SELECT * FROM eval_runs ORDER BY created_at DESC LIMIT 20")
    return [{"id": r["id"], "set_id": r["set_id"], "created_at": r["created_at"],
             **db.loads(r["config"], {}), **db.loads(r["results"], {})} for r in rows]
