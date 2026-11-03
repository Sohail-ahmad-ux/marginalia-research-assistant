import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    google_api_key: str = ""
    llm_model: str = "gemini-3.5-flash"
    embedding_model: str = "gemini-embedding-2"
    reranker: str = "cross-encoder"  # "cross-encoder" | "none"
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    chunk_size: int = 1100
    chunk_overlap: int = 150
    index_references: bool = False
    data_dir: Path = ROOT / "data"


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
(settings.data_dir / "pdfs").mkdir(exist_ok=True)
if settings.google_api_key:
    os.environ["GOOGLE_API_KEY"] = settings.google_api_key
