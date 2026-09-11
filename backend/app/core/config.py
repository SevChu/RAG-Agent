from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.distribution import DEFAULT_EDITION, RESEARCH_AVAILABLE


@dataclass(frozen=True, slots=True)
class LLMProviderConfig:
    """Resolved runtime configuration for one OpenAI-compatible provider."""

    id: str
    name: str
    base_url: str
    api_key: str
    models: tuple[str, ...]
    api_key_env: str
    models_env: str

    @property
    def configured(self) -> bool:
        return bool(self.api_key.strip() and self.models)


class Settings(BaseSettings):
    """Environment-backed application settings."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    agentic_edition: Literal["product", "research"] = DEFAULT_EDITION

    @model_validator(mode="after")
    def validate_edition(self) -> "Settings":
        if self.agentic_edition == "research" and not RESEARCH_AVAILABLE:
            raise ValueError("此产品版不包含研究模块，请使用研发/科研版安装包。")
        return self

    app_name: str = "Agentic"
    app_env: str = "development"
    debug: bool = True
    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"

    llm_provider: str = "deepseek"
    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: str = ""
    llm_model: str = "deepseek-v4-flash"
    llm_available_models: str = "deepseek-v4-flash,deepseek-v4-pro"
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_api_key: str = ""
    qwen_models: str = ""
    kimi_base_url: str = "https://api.moonshot.cn/v1"
    kimi_api_key: str = ""
    kimi_models: str = ""
    glm_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    glm_api_key: str = ""
    glm_models: str = ""
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
    external_search_model: str = ""
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
        models: dict[str, None] = {}
        for provider in self.llm_providers:
            for model in provider.models:
                models.setdefault(model, None)
        return list(models)

    @property
    def llm_providers(self) -> tuple[LLMProviderConfig, ...]:
        return (
            LLMProviderConfig(
                id=self.llm_provider.strip().lower() or "deepseek",
                name="DeepSeek",
                base_url=self.llm_base_url.strip(),
                api_key=self.llm_api_key,
                models=self._models(self.llm_available_models),
                api_key_env="LLM_API_KEY",
                models_env="LLM_AVAILABLE_MODELS",
            ),
            LLMProviderConfig(
                id="qwen",
                name="Qwen",
                base_url=self.qwen_base_url.strip(),
                api_key=self.qwen_api_key,
                models=self._models(self.qwen_models),
                api_key_env="QWEN_API_KEY",
                models_env="QWEN_MODELS",
            ),
            LLMProviderConfig(
                id="kimi",
                name="Kimi",
                base_url=self.kimi_base_url.strip(),
                api_key=self.kimi_api_key,
                models=self._models(self.kimi_models),
                api_key_env="KIMI_API_KEY",
                models_env="KIMI_MODELS",
            ),
            LLMProviderConfig(
                id="glm",
                name="GLM",
                base_url=self.glm_base_url.strip(),
                api_key=self.glm_api_key,
                models=self._models(self.glm_models),
                api_key_env="GLM_API_KEY",
                models_env="GLM_MODELS",
            ),
        )

    def provider_for_model(self, model: str) -> LLMProviderConfig | None:
        return next(
            (provider for provider in self.llm_providers if model in provider.models),
            None,
        )

    @staticmethod
    def _models(value: str) -> tuple[str, ...]:
        return tuple(dict.fromkeys(item.strip() for item in value.split(",") if item.strip()))

    @property
    def allowed_cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
