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

    database_url: str = "sqlite+aiosqlite:///../data/app.db"
    qdrant_path: Path = Path("../data/qdrant")
    qdrant_collection_name: str = "knowledge_chunks_v1"
    upload_dir: Path = Path("../data/uploads")
    paddle_ocr_base_dir: Path = Path("../data/models/paddleocr")
    embedding_model_path: Path = Path("../data/models/embedding/bge-m3")
    embedding_device: Literal["auto", "cuda", "cpu"] = "auto"
    embedding_batch_size: int = Field(default=8, gt=0)
    auto_index_documents: bool = True
    max_upload_mb: int = Field(default=100, gt=0)

    @property
    def available_models(self) -> list[str]:
        return [
            model.strip()
            for model in self.llm_available_models.split(",")
            if model.strip()
        ]

    @property
    def allowed_cors_origins(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.cors_origins.split(",")
            if origin.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
