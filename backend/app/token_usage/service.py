from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Protocol

import structlog
from fastapi import Depends
from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.models import TokenUsageEvent

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ModelTokenUsage:
    model: str
    input_cache_hit_tokens: int
    input_cache_miss_tokens: int
    output_tokens: int

    @property
    def input_tokens(self) -> int:
        return self.input_cache_hit_tokens + self.input_cache_miss_tokens

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class TokenUsageRecorder(Protocol):
    async def record(
        self,
        *,
        model: str,
        input_cache_hit_tokens: int,
        input_cache_miss_tokens: int,
        output_tokens: int,
    ) -> None: ...


class TokenUsageService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        *,
        model: str,
        input_cache_hit_tokens: int,
        input_cache_miss_tokens: int,
        output_tokens: int,
    ) -> None:
        normalized_model = model.strip() or "unknown"
        event = TokenUsageEvent(
            model=normalized_model,
            input_cache_hit_tokens=max(input_cache_hit_tokens, 0),
            input_cache_miss_tokens=max(input_cache_miss_tokens, 0),
            output_tokens=max(output_tokens, 0),
        )
        self.session.add(event)
        try:
            # Usage is billed even when a later generation/validation step fails, so each
            # upstream response is committed independently from the answer transaction.
            await self.session.commit()
        except SQLAlchemyError:
            await self.session.rollback()
            logger.exception("token_usage_record_failed", model=normalized_model)

    async def summarize(self, configured_models: list[str]) -> list[ModelTokenUsage]:
        statement = (
            select(
                TokenUsageEvent.model,
                func.sum(TokenUsageEvent.input_cache_hit_tokens),
                func.sum(TokenUsageEvent.input_cache_miss_tokens),
                func.sum(TokenUsageEvent.output_tokens),
            )
            .group_by(TokenUsageEvent.model)
            .order_by(TokenUsageEvent.model)
        )
        rows = (await self.session.execute(statement)).all()
        aggregates = {
            str(row[0]): ModelTokenUsage(
                model=str(row[0]),
                input_cache_hit_tokens=int(row[1] or 0),
                input_cache_miss_tokens=int(row[2] or 0),
                output_tokens=int(row[3] or 0),
            )
            for row in rows
        }
        ordered_models = list(dict.fromkeys([*configured_models, *sorted(aggregates)]))
        return [
            aggregates.get(
                model,
                ModelTokenUsage(
                    model=model,
                    input_cache_hit_tokens=0,
                    input_cache_miss_tokens=0,
                    output_tokens=0,
                ),
            )
            for model in ordered_models
        ]

    async def reset(self) -> None:
        await self.session.execute(delete(TokenUsageEvent))
        await self.session.commit()


def get_token_usage_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TokenUsageService:
    return TokenUsageService(session)
