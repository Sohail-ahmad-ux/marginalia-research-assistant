"""Gemini access: chat model, structured output, embeddings (with retry for free-tier 429s)."""
import logging
import time
from functools import lru_cache

from google import genai
from google.genai import types
from langchain_google_genai import ChatGoogleGenerativeAI

from .config import settings

log = logging.getLogger(__name__)


def has_key() -> bool:
    return bool(settings.google_api_key)


def retry(fn, tries=5):
    for i in range(tries):
        try:
            return fn()
        except Exception as e:  # retry only on rate-limit / overload
            msg = str(e)
            transient = any(s in msg for s in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE", "overloaded"))
            if not transient or i == tries - 1:
                raise
            wait = 3 * 2**i
            log.warning("Gemini busy, retrying in %ss", wait)
            time.sleep(wait)


@lru_cache
def chat_model():
    return ChatGoogleGenerativeAI(model=settings.llm_model, max_retries=2)


def structured(schema, prompt: str):
    return retry(lambda: chat_model().with_structured_output(schema).invoke(prompt))


def text_of(content) -> str:
    if isinstance(content, str):
        return content
    parts = []
    for c in content or []:
        if isinstance(c, str):
            parts.append(c)
        elif isinstance(c, dict) and c.get("type") == "text":
            parts.append(c.get("text", ""))
    return "".join(parts)


@lru_cache
def _client():
    return genai.Client(api_key=settings.google_api_key)


def _embed_batch(batch, cfg):
    """One embedding per text. Newer embedding models can merge a list into ONE vector, so verify the count."""
    contents = [types.Content(parts=[types.Part(text=t)]) for t in batch]
    resp = retry(lambda: _client().models.embed_content(model=settings.embedding_model, contents=contents, config=cfg))
    vecs = [list(e.values) for e in resp.embeddings]
    if len(vecs) == len(batch):
        return vecs
    log.warning("Embedding API returned %d vectors for %d texts; embedding one by one", len(vecs), len(batch))
    out = []
    for t in batch:
        r = retry(lambda t=t: _client().models.embed_content(model=settings.embedding_model, contents=t, config=cfg))
        out.append(list(r.embeddings[0].values))
    return out


def embed(texts: list[str], kind: str = "doc") -> list[list[float]]:
    """kind: 'doc' or 'query'. gemini-embedding-2 uses text prefixes; older models use task types."""
    v2 = "embedding-2" in settings.embedding_model
    out: list[list[float]] = []
    for i in range(0, len(texts), 32):
        batch = texts[i : i + 32]
        cfg = None
        if v2:
            batch = [f"title: none | text: {t}" if kind == "doc" else f"task: search result | query: {t}" for t in batch]
        else:
            cfg = types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT" if kind == "doc" else "RETRIEVAL_QUERY")
        out += _embed_batch(batch, cfg)
    if len(out) != len(texts):
        raise RuntimeError(f"Embedding count mismatch: {len(out)} vectors for {len(texts)} texts")
    return out


@lru_cache(maxsize=4096)
def embed_query(text: str) -> tuple:
    return tuple(embed([text], "query")[0])
