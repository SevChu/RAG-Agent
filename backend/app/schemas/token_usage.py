from pydantic import BaseModel


class ModelTokenUsageRead(BaseModel):
    model: str
    input_cache_hit_tokens: int
    input_cache_miss_tokens: int
    input_tokens: int
    output_tokens: int
    total_tokens: int


class TokenUsageSummaryRead(BaseModel):
    models: list[ModelTokenUsageRead]
    total: ModelTokenUsageRead
