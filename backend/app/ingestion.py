"""PDF -> cleaned text -> section-aware chunks -> metadata -> vector index."""
import hashlib
import json
import logging
import re
from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass
from itertools import groupby

import pymupdf as fitz  # PyMuPDF
from langchain_text_splitters import RecursiveCharacterTextSplitter

from . import db, llm, store
from .config import settings
from .schemas import PaperMeta

log = logging.getLogger(__name__)

CANON = [
    ("abstract", r"abstract"),
    ("introduction", r"introduction"),
    ("related_work", r"related work|background|literature review|prior work"),
    ("methods", r"methods?|methodology|approach|model|proposed (?:method|approach|framework)|framework|materials and methods"),
    ("experiments", r"experiments?|experimental (?:setup|results)|evaluation|setup|implementation details|datasets?"),
    ("results", r"results?(?: and discussion)?|findings|analysis"),
    ("discussion", r"discussion"),
    ("limitations", r"limitations?|threats to validity"),
    ("conclusion", r"conclusions?(?: and future work)?|future work|concluding remarks"),
    ("references", r"references|bibliography"),
    ("acknowledgments", r"acknowledge?ments?"),
    ("appendix", r"appendix|appendices|supplementary material"),
]
NUM_RE = re.compile(r"^(?:\d+(?:\.\d+)*\.?|[IVX]{1,4}\.|[A-Z]\.)\s+")
TOP_NUM_RE = re.compile(r"^\d+\.?\s+")
INLINE_ABSTRACT = re.compile(r"^abstract\s*[\u2014\u2013:\-.]\s*(.{30,})", re.I)


@dataclass
class Segment:
    section: str
    title: str
    page: int
    text: str


def detect_heading(text, size, bold, body):
    """Return (section, title, leftover_text) if the line is a top-level heading."""
    t = text.strip()
    m = INLINE_ABSTRACT.match(t)
    if m:
        return "abstract", "Abstract", m.group(1)
    if not 2 < len(t) <= 80:
        return None
    nm = NUM_RE.match(t)
    rest = (t[nm.end():] if nm else t).strip().rstrip(":.").strip()
    emph = bold or size >= body * 1.08 or (len(rest) > 3 and rest.isupper())
    for name, pat in CANON:
        if re.fullmatch(pat, rest, re.I):
            return (name, t, None) if (emph or nm) else None
    if nm and TOP_NUM_RE.match(t) and emph and rest[:1].isupper() and len(rest.split()) <= 8 and not t.endswith("."):
        return "other", t, None
    return None


def join_lines(lines):
    out = ""
    for t in lines:
        if not out:
            out = t
        elif out.endswith("-") and t[:1].islower():
            out = out[:-1] + t  # de-hyphenate line breaks
        else:
            out += " " + t
    return re.sub(r"\s+", " ", out).strip()


def parse_pdf(path):
    doc = fitz.open(path)
    sizes, pages = Counter(), []
    for page in doc:
        blocks = []
        for b in page.get_text("dict")["blocks"]:
            if b.get("type") != 0:
                continue
            lines = []
            for ln in b["lines"]:
                spans = [s for s in ln["spans"] if s["text"].strip()]
                if not spans:
                    continue
                text = "".join(s["text"] for s in spans).strip()
                size = max(s["size"] for s in spans)
                bold = any((s["flags"] & 16) or "bold" in s["font"].lower() for s in spans)
                for s in spans:
                    sizes[round(s["size"], 1)] += len(s["text"])
                lines.append((text, size, bold))
            if lines:
                blocks.append(lines)
        pages.append(blocks)
    n = len(doc)
    first_text = doc[0].get_text()[:5000] if n else ""
    doc.close()
    body = sizes.most_common(1)[0][0] if sizes else 10.0

    title_guess = ""
    if pages and pages[0]:
        flat = [l for blk in pages[0] for l in blk]
        mx = max(l[1] for l in flat)
        title_guess = " ".join(l[0] for l in flat if l[1] >= mx - 0.6)[:300]

    norm = lambda s: re.sub(r"\d+", "#", s.lower())
    freq = Counter()
    for blocks in pages:
        freq.update({norm(l[0]) for blk in blocks for l in blk if len(l[0]) < 90})
    drop = {k for k, v in freq.items() if n >= 4 and v >= max(3, 0.4 * n)}  # running headers/footers

    segs, sec, title = [], "front_matter", ""
    for pno, blocks in enumerate(pages, 1):
        for lines in blocks:
            buf = []
            for text, size, bold in lines:
                if norm(text) in drop or re.fullmatch(r"\d{1,4}", text):
                    continue
                h = detect_heading(text, size, bold, body)
                if h:
                    if buf:
                        segs.append(Segment(sec, title, pno, join_lines(buf)))
                        buf = []
                    sec, title, rest = h
                    if rest:
                        buf.append(rest)
                    continue
                buf.append(text)
            if buf:
                segs.append(Segment(sec, title, pno, join_lines(buf)))

    segs = [s for s in segs if len(s.text) >= 30 and (settings.index_references or s.section != "references")]
    if segs and all(s.section == "front_matter" for s in segs):
        for s in segs:
            s.section = "body"
    return segs, n, first_text, title_guess


def chunk_segments(segs):
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""])
    out = []
    for sec, grp in groupby(segs, key=lambda s: s.section):
        grp = list(grp)
        text = "\n\n".join(s.text for s in grp)
        starts, pos = [], 0
        for s in grp:
            starts.append(pos)
            pos += len(s.text) + 2
        cursor = 0
        for piece in splitter.split_text(text):
            if len(piece.strip()) < 40:
                continue
            i = text.find(piece, max(0, cursor - settings.chunk_overlap - 50))
            if i < 0:
                i = text.find(piece[:60])
            if i < 0:
                i = cursor
            cursor = i
            p0 = grp[max(0, bisect_right(starts, i) - 1)].page
            p1 = grp[max(0, bisect_right(starts, i + len(piece) - 1) - 1)].page
            out.append({"text": piece, "section": sec, "section_title": grp[0].title,
                        "page": p0, "page_end": p1, "index": len(out)})
    return out


META_PROMPT = """Extract bibliographic metadata from the first page of a research paper.
Return the exact title, authors in order, publication year (0 if not visible), the abstract verbatim
(empty string if absent) and 3-8 topical keywords.

FIRST PAGE:
{text}"""


def extract_metadata(first_text, title_guess, filename, segs):
    m = None
    try:
        m = llm.structured(PaperMeta, META_PROMPT.format(text=first_text[:4500]))
    except Exception as e:
        log.warning("Metadata extraction failed, using heuristics: %s", e)
    if m is None:
        m = PaperMeta(title=title_guess, authors=[], year=0, abstract="", keywords=[])
    if not m.title.strip():
        m.title = title_guess or filename.rsplit(".", 1)[0]
    if not m.abstract.strip():
        m.abstract = " ".join(s.text for s in segs if s.section == "abstract")[:2500]
    return m


def ingest_pdf(data: bytes, filename: str):
    """Returns (paper_dict, is_duplicate)."""
    pid = hashlib.sha1(data).hexdigest()[:12]
    existing = db.one("SELECT * FROM papers WHERE id=?", (pid,))
    if existing:
        return db.paper_out(existing), True
    path = settings.data_dir / "pdfs" / f"{pid}.pdf"
    path.write_bytes(data)
    try:
        segs, n_pages, first_text, title_guess = parse_pdf(path)
        if not segs:
            raise ValueError("No extractable text found. Scanned PDFs need OCR, which is not supported.")
        meta = extract_metadata(first_text, title_guess, filename, segs)
        chunks = chunk_segments(segs)
        if not chunks:
            raise ValueError("The PDF has too little text to index.")
        store.add_chunks(pid, meta, chunks)
        db.execute(
            "INSERT INTO papers (id, filename, title, authors, year, abstract, keywords, pages, chunks, analysis, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,NULL,?)",
            (pid, filename, meta.title.strip(), json.dumps(meta.authors), meta.year or None,
             meta.abstract, json.dumps(meta.keywords), n_pages, len(chunks), db.now()))
    except Exception:
        path.unlink(missing_ok=True)
        store.delete_paper(pid)
        raise
    return db.paper_out(db.one("SELECT * FROM papers WHERE id=?", (pid,))), False
