from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.core.exceptions import LLMOutputError
from app.generation.client import ChatCompletionGateway
from app.generation.models import ChatCompletion
from app.models import Message, MessageRole


class _RewritePayload(BaseModel):
    standalone_query: str = Field(min_length=1, max_length=2000)

    @field_validator("standalone_query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        return " ".join(value.split())


class HistoryItem(Protocol):
    @property
    def role(self) -> MessageRole: ...

    @property
    def content(self) -> str: ...


@dataclass(frozen=True, slots=True)
class HistoryMessage:
    sequence_number: int
    role: MessageRole
    content: str


def bounded_history(
    messages: Sequence[Message],
    *,
    max_messages: int,
    max_chars: int,
) -> tuple[HistoryMessage, ...]:
    """Keep the newest completed messages inside both explicit limits."""

    selected: list[HistoryMessage] = []
    used_chars = 0
    for message in reversed(messages[-max_messages:]):
        remaining = max_chars - used_chars
        if remaining <= 0:
            break
        content = message.content
        if len(content) > remaining:
            if selected:
                break
            content = content[-remaining:]
        selected.append(
            HistoryMessage(
                sequence_number=message.sequence_number,
                role=message.role,
                content=content,
            )
        )
        used_chars += len(content)
    return tuple(reversed(selected))


class QueryRewriter:
    def __init__(self, gateway: ChatCompletionGateway) -> None:
        self.gateway = gateway

    async def rewrite(
        self,
        *,
        question: str,
        history: Sequence[HistoryItem],
        model: str,
    ) -> tuple[str, ChatCompletion | None]:
        normalized = " ".join(question.split())
        if not history:
            return normalized, None

        completion = await self.gateway.complete(
            system_prompt=(
                "你是课程检索查询改写器。只输出 JSON："
                '{"standalone_query":"可独立检索的问题"}。'
                "结合对话消解‘它’‘这个算法’等指代，但不得回答问题，不得引入对话中"
                "没有出现的新事实。历史助手回答仅用于理解指代，绝不是课程证据。"
            ),
            user_prompt=_rewrite_prompt(normalized, history),
            model=model,
        )
        try:
            payload = _RewritePayload.model_validate(json.loads(completion.content))
        except (json.JSONDecodeError, ValidationError, TypeError) as error:
            raise LLMOutputError("问题改写器没有返回有效查询，请重试。") from error
        return payload.standalone_query, completion


def quick_chat_prompt(question: str, history: Sequence[HistoryItem]) -> str:
    history_text = _history_text(history)
    return f"""<conversation_history>
{history_text or "（新会话，没有历史消息）"}
</conversation_history>

当前用户消息：{question.strip()}

请直接回答当前用户消息。历史仅用于保持本次快速对话的连贯性。"""


def _rewrite_prompt(question: str, history: Sequence[HistoryItem]) -> str:
    return f"""<conversation_history>
{_history_text(history)}
</conversation_history>

当前追问：{question}

把当前追问改写成不依赖历史也能理解和检索的单句查询。"""


def _history_text(history: Sequence[HistoryItem]) -> str:
    lines = []
    for message in history:
        role = "用户" if message.role is MessageRole.USER else "助手"
        lines.append(f"{role}：{message.content}")
    return "\n".join(lines)
