"""Advanced RAG pipeline as a LangGraph: plan (rewrite + multi-query) -> hybrid retrieve -> rerank -> grounded answer."""
import time
from typing import Any, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from . import llm, store
from .schemas import QueryPlan

CANDIDATES = 30


class State(TypedDict, total=False):
    question: str
    history: list
    paper_ids: list
    sections: list
    opts: dict
    standalone: str
    intent: str
    queries: list
    candidates: list
    hits: list
    trace: dict


PLAN_PROMPT = """You prepare search queries for a retrieval system over academic papers.

Conversation so far:
{history}

Latest user question: {question}

Return:
- standalone_question: the latest question rewritten to be fully self-contained (resolve words like "it",
  "that paper", "the second method" using the conversation). If it is already standalone, copy it.
- intent: one of factual, summary, methodology, results, comparison, limitations, other.
- alternative_queries: exactly {n_alt} different search queries (technical synonyms, sub-questions) that could
  surface relevant passages. Return an empty list if {n_alt} is 0."""


def fmt_history(history):
    return "\n".join(f"{m['role']}: {m['content'][:500]}" for m in history[-6:]) or "(none)"


def _tr(state, **kw):
    return {**state.get("trace", {}), **kw}


def plan_node(state: State):
    t0, q, o = time.time(), state["question"], state["opts"]
    standalone, intent, queries = q, "other", [q]
    note = None
    if o["rewrite"] or o["multi_query"]:
        try:
            plan = llm.structured(QueryPlan, PLAN_PROMPT.format(
                history=fmt_history(state.get("history", [])), question=q, n_alt=3 if o["multi_query"] else 0))
            intent = plan.intent
            if o["rewrite"] and plan.standalone_question.strip():
                standalone = plan.standalone_question.strip()
            queries = [standalone]
            if o["multi_query"]:
                queries += [a.strip() for a in plan.alternative_queries if a.strip()][:3]
        except Exception as e:
            note = f"Query planning failed, using the original question ({str(e)[:120]})"
    queries = list(dict.fromkeys(queries))
    return {"standalone": standalone, "intent": intent, "queries": queries,
            "trace": _tr(state, standalone=standalone, intent=intent, queries=queries, warning=note,
                         plan_ms=int((time.time() - t0) * 1000))}


def retrieve_node(state: State):
    t0 = time.time()
    cands = store.retrieve(state["queries"], "hybrid", state.get("paper_ids", []), state.get("sections", []), CANDIDATES)
    return {"candidates": cands, "trace": _tr(state, candidates=len(cands), retrieve_ms=int((time.time() - t0) * 1000))}


def rerank_node(state: State):
    t0, o = time.time(), state["opts"]
    cands = state["candidates"]
    hits = store.rerank(state["standalone"], cands, o["top_k"]) if o["rerank"] else cands[: o["top_k"]]
    return {"hits": hits, "trace": _tr(state, reranked=bool(o["rerank"]) and store.reranker_active(), rerank_ms=int((time.time() - t0) * 1000))}


def _route(state: State):
    return "rerank" if state.get("candidates") else END


_g = StateGraph(State)
_g.add_node("plan", plan_node)
_g.add_node("retrieve", retrieve_node)
_g.add_node("rerank", rerank_node)
_g.add_edge(START, "plan")
_g.add_edge("plan", "retrieve")
_g.add_conditional_edges("retrieve", _route, {"rerank": "rerank", END: END})
_g.add_edge("rerank", END)
graph = _g.compile()


def run_retrieval(question, history, paper_ids, sections, opts) -> dict:
    return graph.invoke({"question": question, "history": history, "paper_ids": paper_ids,
                         "sections": sections, "opts": opts, "hits": [], "trace": {}})


# ---------- answer generation ----------
SYSTEM = """You are a careful research assistant answering questions about academic papers.
Rules:
- Use ONLY the numbered context passages. If they do not contain the answer, say so plainly instead of guessing.
- Cite every factual claim with its passage number in square brackets, like [1] or [2][3].
- Keep numbers, metrics and names exact. When several papers are involved, name them.
- Be concise and structured. Use Markdown lists or tables when they help.
{hint}"""

HINTS = {
    "comparison": "- The user wants a comparison: prefer a Markdown table with one column per paper.",
    "summary": "- The user wants a summary: give a short structured overview (problem, method, results).",
    "limitations": "- Separate limitations the authors state from ones you can infer, and label which is which.",
}


def build_context(hits):
    return "\n\n".join(
        f"[{i}] {h.meta['title']} (p.{h.meta['page']}, {h.meta['section']})\n{h.text}" for i, h in enumerate(hits, 1))


def sources_payload(hits):
    return [{"n": i, "id": h.id, "paper_id": h.meta["paper_id"], "title": h.meta["title"], "page": h.meta["page"],
             "section": h.meta["section"], "text": h.text,
             "scores": {k: round(v, 4) for k, v in h.scores.items()}} for i, h in enumerate(hits, 1)]


def _messages(question, history, hits, intent="other"):
    msgs: list[Any] = [SystemMessage(SYSTEM.format(hint=HINTS.get(intent, "")))]
    for m in history[-6:]:
        msgs.append(HumanMessage(m["content"]) if m["role"] == "user" else AIMessage(m["content"]))
    msgs.append(HumanMessage(f"Context passages:\n\n{build_context(hits)}\n\nQuestion: {question}"))
    return msgs


def stream_answer(question, history, hits, intent="other"):
    msgs = _messages(question, history, hits, intent)
    for attempt in range(3):
        started = False
        try:
            for chunk in llm.chat_model().stream(msgs):
                t = llm.text_of(chunk.content)
                if t:
                    started = True
                    yield t
            return
        except Exception as e:
            if started or attempt == 2 or not any(s in str(e) for s in ("429", "RESOURCE_EXHAUSTED", "503")):
                raise
            time.sleep(4 * 2**attempt)


def answer_once(question, hits):
    return llm.text_of(llm.retry(lambda: llm.chat_model().invoke(_messages(question, [], hits))).content)
