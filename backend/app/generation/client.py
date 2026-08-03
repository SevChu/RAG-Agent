from __future__ import annotations

from typing import Annotated, Any, Protocol

import httpx
from fastapi import Depends

from app.core.config import Settings, get_settings
from app.core.exceptions import LLMConfigurationError, LLMServiceError
from app.generation.models import ChatCompletion, TokenUsage


class ChatCompletionGateway(Protocol):
    async def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> ChatCompletion: ...


class OpenAICompatibleChatClient:
    """Minimal async client for an OpenAI-compatible chat-completions API."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> ChatCompletion:
        api_key = self.settings.llm_api_key.strip()
        if not api_key:
            raise LLMConfigurationError(
                "尚未配置 LLM API Key。请在项目根目录 .env 中填写 LLM_API_KEY，"
                "然后重启后端服务。"
            )

        payload: dict[str, Any] = {
            "model": self.settings.llm_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.settings.llm_temperature,
            "max_tokens": self.settings.llm_max_output_tokens,
            "response_format": {"type": "json_object"},
            "stream": False,
        }
        if self.settings.llm_provider.strip().lower() == "deepseek":
            payload["thinking"] = {"type": "disabled"}

        url = f"{self.settings.llm_base_url.rstrip('/')}/chat/completions"
        try:
            async with httpx.AsyncClient(
                timeout=self.settings.llm_request_timeout_seconds
            ) as client:
                response = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
        except httpx.TimeoutException as error:
            raise LLMServiceError("模型响应超时，请稍后重试。") from error
        except httpx.RequestError as error:
            raise LLMServiceError("无法连接到模型服务，请检查网络和 LLM_BASE_URL。") from error

        if response.status_code == 401:
            raise LLMServiceError("模型服务拒绝了 API Key，请检查密钥是否正确。")
        if response.status_code == 429:
            raise LLMServiceError("模型服务当前请求过多或额度不足，请稍后重试。")
        if response.is_error:
            raise LLMServiceError(
                f"模型服务返回异常状态（HTTP {response.status_code}），请稍后重试。"
            )

        try:
            body = response.json()
            choice = body["choices"][0]
            content = choice["message"]["content"]
            model = str(body.get("model") or self.settings.llm_model)
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise LLMServiceError("模型服务返回了无法识别的响应。") from error
        if not isinstance(content, str) or not content.strip():
            raise LLMServiceError("模型服务没有返回回答内容，请重试。")

        usage = _parse_usage(body.get("usage"))
        return ChatCompletion(content=content.strip(), model=model, usage=usage)


def _parse_usage(value: object) -> TokenUsage | None:
    if not isinstance(value, dict):
        return None
    try:
        return TokenUsage(
            prompt_tokens=int(value["prompt_tokens"]),
            completion_tokens=int(value["completion_tokens"]),
            total_tokens=int(value["total_tokens"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def get_chat_completion_gateway(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ChatCompletionGateway:
    return OpenAICompatibleChatClient(settings)
