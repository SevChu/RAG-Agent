from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.config import Settings, get_settings
from app.schemas.api import APIResponse
from app.schemas.token_usage import ModelTokenUsageRead, TokenUsageSummaryRead
from app.token_usage import ModelTokenUsage, TokenUsageService, get_token_usage_service

router = APIRouter(prefix="/llm/token-usage", tags=["settings"])

SettingsDependency = Annotated[Settings, Depends(get_settings)]
UsageDependency = Annotated[TokenUsageService, Depends(get_token_usage_service)]


@router.get("", response_model=APIResponse[TokenUsageSummaryRead])
async def read_token_usage(
    settings: SettingsDependency,
    usage_service: UsageDependency,
) -> APIResponse[TokenUsageSummaryRead]:
    models = await usage_service.summarize(settings.available_models)
    return APIResponse(data=_summary_read(models))


@router.delete("", response_model=APIResponse[TokenUsageSummaryRead])
async def reset_token_usage(
    settings: SettingsDependency,
    usage_service: UsageDependency,
) -> APIResponse[TokenUsageSummaryRead]:
    await usage_service.reset()
    models = await usage_service.summarize(settings.available_models)
    return APIResponse(data=_summary_read(models))


def _summary_read(models: list[ModelTokenUsage]) -> TokenUsageSummaryRead:
    model_reads = [_model_read(item) for item in models]
    total = ModelTokenUsage(
        model="全部模型",
        input_cache_hit_tokens=sum(item.input_cache_hit_tokens for item in models),
        input_cache_miss_tokens=sum(item.input_cache_miss_tokens for item in models),
        output_tokens=sum(item.output_tokens for item in models),
    )
    return TokenUsageSummaryRead(models=model_reads, total=_model_read(total))


def _model_read(item: ModelTokenUsage) -> ModelTokenUsageRead:
    return ModelTokenUsageRead(
        model=item.model,
        input_cache_hit_tokens=item.input_cache_hit_tokens,
        input_cache_miss_tokens=item.input_cache_miss_tokens,
        input_tokens=item.input_tokens,
        output_tokens=item.output_tokens,
        total_tokens=item.total_tokens,
    )
