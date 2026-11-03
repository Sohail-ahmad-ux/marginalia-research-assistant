from typing import Literal, Optional

from pydantic import BaseModel, Field


# ---- LLM structured outputs (all fields required: Gemini handles these best) ----
class PaperMeta(BaseModel):
    title: str = Field(description="Exact title of the paper")
    authors: list[str] = Field(description="Author names in order")
    year: int = Field(description="Publication year, 0 if not visible")
    abstract: str = Field(description="The abstract verbatim, or empty string if absent")
    keywords: list[str] = Field(description="3-8 topical keywords")


class PaperAnalysis(BaseModel):
    tldr: str = Field(description="2-3 sentence plain summary")
    problem: str = Field(description="The problem or research question")
    contributions: list[str] = Field(description="Main contributions")
    methodology: str = Field(description="How the method / study works, concretely")
    datasets: list[str] = Field(description="Datasets or data sources used, with sizes if stated")
    metrics: list[str] = Field(description="Evaluation metrics used")
    key_results: list[str] = Field(description="Most important quantitative or qualitative results, exact numbers")
    limitations: list[str] = Field(description="Limitations acknowledged or clearly implied")
    future_work: list[str] = Field(description="Future work suggested")


class QueryPlan(BaseModel):
    standalone_question: str
    intent: Literal["factual", "summary", "methodology", "results", "comparison", "limitations", "other"]
    alternative_queries: list[str]


class Cell(BaseModel):
    paper_id: str
    value: str


class Row(BaseModel):
    aspect: str
    cells: list[Cell]


class Comparison(BaseModel):
    rows: list[Row]
    summary: str


class QAItem(BaseModel):
    chunk_id: str
    question: str
    reference_answer: str


class QABatch(BaseModel):
    items: list[QAItem]


class Judgement(BaseModel):
    faithfulness: int = Field(description="1-5: every claim is supported by the context")
    relevance: int = Field(description="1-5: answers the question asked")
    correctness: int = Field(description="1-5: agrees with the reference answer")


# ---- API requests ----
class ChatRequest(BaseModel):
    question: str
    conversation_id: Optional[str] = None
    paper_ids: list[str] = []
    sections: list[str] = []
    top_k: int = 6
    rewrite: bool = True
    multi_query: bool = True
    rerank: bool = True


class CompareRequest(BaseModel):
    paper_ids: list[str]
    aspects: list[str] = []


class EvalGenRequest(BaseModel):
    paper_ids: list[str] = []
    n: int = 10


class EvalRunRequest(BaseModel):
    set_id: str
    k: int = 5
    judge: bool = False
