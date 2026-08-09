from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed application settings."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "基于 RAG 的计算机专业学习 Agent"
    app_env: str = "development"
    debug: bool = True
    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"

    llm_provider: str = "deepseek"
    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: str = ""
    llm_model: str = "deepseek-v4-flash"
    llm_available_models: str = "deepseek-v4-flash,deepseek-v4-pro"
    llm_request_timeout_seconds: float = Field(default=90.0, gt=0)
    llm_max_output_tokens: int = Field(default=1600, gt=0)
    llm_temperature: float = Field(default=0.2, ge=0, le=2)
    rag_answer_top_k: int = Field(default=6, ge=1, le=20)
    rag_answer_candidate_k: int = Field(default=20, ge=1, le=100)
    rag_summary_top_k: int = Field(default=12, ge=1, le=30)
    rag_summary_candidate_k: int = Field(default=40, ge=1, le=100)
    rag_summary_max_sources: int = Field(default=10, ge=1, le=30)
    rag_summary_context_max_chars: int = Field(default=8000, ge=2000, le=50000)
    rag_exam_top_k: int = Field(default=12, ge=1, le=30)
    rag_exam_candidate_k: int = Field(default=40, ge=1, le=100)
    rag_exam_max_sources: int = Field(default=10, ge=1, le=30)
    rag_exam_context_max_chars: int = Field(default=8000, ge=2000, le=50000)
    rag_min_similarity_score: float = Field(default=0.3, ge=-1, le=1)
    rag_context_max_messages: int = Field(default=6, ge=1, le=20)
    rag_context_max_chars: int = Field(default=6000, ge=500, le=30000)
    quick_chat_context_max_messages: int = Field(default=10, ge=1, le=30)
    quick_chat_context_max_chars: int = Field(default=8000, ge=500, le=40000)
    external_search_enabled: bool = True
    external_search_timeout_seconds: float = Field(default=60.0, gt=0)
    external_search_max_uses: int = Field(default=1, ge=1, le=5)
    external_search_max_results: int = Field(default=6, ge=1, le=20)
    external_search_trigger_score: float = Field(default=0.55, ge=-1, le=1)

    database_url: str = "sqlite+aiosqlite:///../data/app.db"
    qdrant_path: Path = Path("../data/qdrant")
    qdrant_collection_name: str = "knowledge_chunks_v1"
    upload_dir: Path = Path("../data/uploads")
    paddle_ocr_base_dir: Path = Path("../data/models/paddleocr")
    embedding_model_path: Path = Path("../data/models/embedding/bge-m3")
    embedding_device: Literal["auto", "cuda", "cpu"] = "auto"
    embedding_batch_size: int = Field(default=8, gt=0)
    reranker_model_path: Path = Path("../data/models/reranker/bge-reranker-v2-m3")
    reranker_device: Literal["auto", "cuda", "cpu"] = "auto"
    reranker_batch_size: int = Field(default=4, gt=0)
    reranker_max_length: int = Field(default=512, ge=32, le=8192)
    auto_index_documents: bool = True
    max_upload_mb: int = Field(default=100, gt=0)

    @property
    def available_models(self) -> list[str]:
        return [model.strip() for model in self.llm_available_models.split(",") if model.strip()]

    @property
    def allowed_cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
