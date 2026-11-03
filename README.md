# Marginalia: AI Research Paper Assistant

Upload research PDFs, ask questions across all of them, compare papers, and measure how good the retrieval is.
Backend: FastAPI + LangGraph + Chroma + BM25 + cross-encoder reranker + Gemini. Frontend: React (Vite).

## Features
- **Multi-PDF library**: parsing with PyMuPDF, header/footer removal, de-hyphenation, section detection
  (abstract, methods, results...), section-aware chunking, metadata extraction (title, authors, year, keywords).
- **Advanced RAG chat** (streamed): query rewriting for follow-ups, multi-query expansion, hybrid search
  (dense + BM25 fused with Reciprocal Rank Fusion), cross-encoder reranking, section/paper filters,
  grounded answers with clickable `[n]` citations that open the exact PDF page.
- **Structured analysis** of each paper: problem, contributions, methodology, datasets, metrics, results, limitations.
- **Compare papers** on any aspects, each table cell grounded in retrieved passages with citations.
- **Evaluation lab**: generates a test set from your own papers, then compares dense vs BM25 vs hybrid vs
  hybrid + rerank (Hit rate @k, MRR, latency), with optional LLM-as-judge (faithfulness, relevance, correctness).

## Run it (two terminals)
Requirements: Python 3.10+, Node 18+, a free Gemini API key from https://aistudio.google.com/apikey

```bash
# 1) Backend
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # Windows: copy .env.example .env  -> add GOOGLE_API_KEY
uvicorn app.main:app --reload --reload-dir app --port 8000

# 2) Frontend
cd frontend
npm install
npm run dev                                            # open http://localhost:5173
```
The first start downloads the reranker model (about 90 MB) once. To run without it, set `RERANKER=none` in `.env`.
Optional single-server mode: `npm run build` in `frontend/`, then open http://localhost:8000.

## How a question flows
```
question + chat history
  -> plan        (1 LLM call: standalone rewrite, intent, 3 alternative queries)
  -> retrieve    (per query: Chroma dense top-20 + BM25 top-20 -> RRF -> 30 candidates)
  -> rerank      (cross-encoder scores query vs passage -> top-k)
  -> generate    (Gemini answers only from numbered passages, streamed over SSE)
```
The graph lives in `backend/app/pipeline.py`. Planning is one call to stay inside free-tier rate limits.

## Project layout
```
backend/app/  config.py  db.py  schemas.py  llm.py       settings, SQLite, Pydantic models, Gemini wrapper
              ingestion.py   PDF parsing, sections, chunking, metadata
              store.py       Chroma, BM25, RRF, reranker
              pipeline.py    LangGraph RAG pipeline + answer generation
              analysis.py    structured analysis + comparison
              evaluation.py  test-set generation, ablation, judge
              api.py main.py REST + SSE routes, app entry
frontend/src/ App.jsx api.js styles.css components/{Chat,Library,Compare,Eval}View.jsx ...
```
Data (SQLite, Chroma, PDFs) lives in `backend/data/`. Delete that folder to reset everything.

## Troubleshooting
- **404 / model not found**: Gemini model ids change. Check current ids in Google AI Studio and set
  `LLM_MODEL` and `EMBEDDING_MODEL` in `backend/.env`.
- **429 / quota errors**: free-tier rate limit. Calls retry with backoff automatically. For more headroom try a
  Flash-Lite model in `LLM_MODEL`, and keep evaluation sets small.
- **Changed `EMBEDDING_MODEL` after indexing**: delete `backend/data/chroma` and re-upload, because vectors from
  different models cannot be mixed.
- **Scanned PDFs** (images only) are rejected, since OCR is not included.
- Free-tier Gemini may use your inputs to improve Google's models. Do not upload confidential papers on it.
