from functools import lru_cache

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

    llm_provider: str = "deepseek"
    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: str = ""
    llm_model: str = "deepseek-v4-flash"
    llm_available_models: str = "deepseek-v4-flash,deepseek-v4-pro"

    max_upload_mb: int = Field(default=100, gt=0)

    @property
    def available_models(self) -> list[str]:
        return [
            model.strip()
            for model in self.llm_available_models.split(",")
            if model.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
