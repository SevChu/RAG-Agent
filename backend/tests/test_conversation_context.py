from __future__ import annotations

import json
from uuid import uuid4

from app.generation import (
    ChatCompletion,
    QueryRewriter,
    bounded_history,
    quick_chat_prompt,
    quick_chat_search_query,
    quick_chat_web_search_decision,
)
from app.generation.context import HistoryMessage
from app.models import Message, MessageRole, MessageStatus


def _message(sequence: int, role: MessageRole, content: str) -> Message:
    return Message(
        conversation_id=uuid4(),
        sequence_number=sequence,
        role=role,
        status=MessageStatus.COMPLETED,
        content=content,
        citations=[],
    )


class RewriteGateway:
    def __init__(self) -> None:
        self.user_prompt = ""

    async def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
    ) -> ChatCompletion:
        assert "检索查询改写器" in system_prompt
        assert model == "model-a"
        self.user_prompt = user_prompt
        return ChatCompletion(
            content=json.dumps(
                {"standalone_query": "二叉搜索树最坏情况下的查找复杂度"},
                ensure_ascii=False,
            ),
            model=model,
        )

    async def complete_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
    ) -> ChatCompletion:
        raise AssertionError("not used")


def test_bounded_history_keeps_newest_messages_under_both_limits() -> None:
    messages = [
        _message(1, MessageRole.USER, "旧问题" * 20),
        _message(2, MessageRole.ASSISTANT, "旧回答" * 20),
        _message(3, MessageRole.USER, "新问题"),
        _message(4, MessageRole.ASSISTANT, "新回答"),
    ]

    selected = bounded_history(messages, max_messages=3, max_chars=20)

    assert [message.sequence_number for message in selected] == [3, 4]


async def test_query_rewriter_uses_history_for_reference_resolution() -> None:
    history = [
        _message(1, MessageRole.USER, "什么是二叉搜索树？"),
        _message(2, MessageRole.ASSISTANT, "二叉搜索树满足左小右大的次序关系。"),
    ]
    gateway = RewriteGateway()

    query, completion = await QueryRewriter(gateway).rewrite(
        question="它最坏情况下的查找复杂度是多少？",
        history=history,
        model="model-a",
    )

    assert query == "二叉搜索树最坏情况下的查找复杂度"
    assert completion is not None
    assert "助手：二叉搜索树" in gateway.user_prompt
    assert "当前追问：它最坏情况下" in gateway.user_prompt


def test_quick_chat_prompt_marks_history_as_context_only() -> None:
    history = [_message(1, MessageRole.USER, "我刚才问了排序")]

    prompt = quick_chat_prompt("继续", history)

    assert "<conversation_history>" in prompt
    assert "当前用户消息：继续" in prompt
    assert "快速对话的连贯性" in prompt


def test_quick_chat_web_search_defaults_to_information_questions() -> None:
    assert quick_chat_web_search_decision("Python 最近有什么变化？", enabled=True)[0]
    assert not quick_chat_web_search_decision("你好", enabled=True)[0]
    assert not quick_chat_web_search_decision("请不要联网，只按常识回答", enabled=True)[0]


def test_quick_chat_search_query_adds_nearest_user_context_for_follow_up() -> None:
    history = (
        HistoryMessage(1, MessageRole.USER, "介绍 Python 3.14"),
        HistoryMessage(2, MessageRole.ASSISTANT, "它是 Python 的新版本。"),
    )
    assert quick_chat_search_query("那它现在稳定了吗？", history) == (
        "对话背景：介绍 Python 3.14\n当前问题：那它现在稳定了吗？"
    )
