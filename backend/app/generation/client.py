from __future__ import annotations

from typing import Annotated, Any, Protocol

import httpx
from fastapi import Depends

from app.core.config import Settings, get_settings
from app.core.exceptions import LLMConfigurationError, LLMServiceError
from app.generation.models import ChatCompletion, TokenUsage
from app.token_usage import TokenUsageRecorder, TokenUsageService, get_token_usage_service


class ChatCompletionGateway(Protocol):
    async def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
    ) -> ChatCompletion: ...

    async def complete_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
    ) -> ChatCompletion: ...


class OpenAICompatibleChatClient:
    """Minimal async client for an OpenAI-compatible chat-completions API."""

    def __init__(
        self,
        settings: Settings,
        usage_recorder: TokenUsageRecorder | None = None,
    ) -> None:
        self.settings = settings
        self.usage_recorder = usage_recorder

    async def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
    ) -> ChatCompletion:
        return await self._complete(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
            json_mode=True,
        )

    async def complete_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
    ) -> ChatCompletion:
        return await self._complete(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
            json_mode=False,
        )

    async def _complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
        json_mode: bool,
    ) -> ChatCompletion:
        api_key = self.settings.llm_api_key.strip()
        if not api_key:
            raise LLMConfigurationError(
                "尚未配置 LLM API Key。请在项目根目录 .env 中填写 LLM_API_KEY，然后重启后端服务。"
            )

        effective_system_prompt = (
            f"{system_prompt}\nReturn exactly one valid json object."
            if json_mode
            else system_prompt
        )
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": effective_system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.settings.llm_temperature,
            "max_tokens": self.settings.llm_max_output_tokens,
            "stream": False,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if self.settings.llm_provider.strip().lower() == "deepseek":
            payload["thinking"] = {"type": "disabled"}

        url = f"{self.settings.llm_base_url.rstrip('/')}/chat/completions"
        response: httpx.Response | None = None
        async with httpx.AsyncClient(
            timeout=self.settings.llm_request_timeout_seconds
        ) as client:
            for attempt in range(2):
                try:
                    response = await client.post(
                        url,
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    )
                except httpx.TimeoutException as error:
                    if attempt == 0:
                        continue
                    raise LLMServiceError("模型响应超时，请稍后重试。") from error
                except httpx.RequestError as error:
                    if attempt == 0:
                        continue
                    raise LLMServiceError(
                        "无法连接到模型服务，请检查网络和 LLM_BASE_URL。"
                    ) from error
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt == 0:
                        continue
                break

        if response is None:
            raise LLMServiceError("模型服务没有返回响应，请稍后重试。")

        if response.status_code == 401:
            raise LLMServiceError("模型服务拒绝了 API Key，请检查密钥是否正确。")
        if response.status_code == 429:
            raise LLMServiceError("模型服务当前请求过多或额度不足，请稍后重试。")
        if response.status_code == 400:
            detail = _response_error_detail(response)
            if any(
                marker in detail.casefold()
                for marker in ("context", "token", "maximum", "length")
            ):
                raise LLMServiceError("模型输入上下文过长，请缩小总结范围后重试。")
            suffix = f"（上游原因：{detail}）" if detail else ""
            raise LLMServiceError(
                f"模型请求格式或参数未被上游服务接受{suffix}，请稍后重试。"
            )
        if response.is_error:
            raise LLMServiceError(
                f"模型服务返回异常状态（HTTP {response.status_code}），请稍后重试。"
            )

        try:
            body = response.json()
            if not isinstance(body, dict):
                raise TypeError
            response_model = str(body.get("model") or model)
        except (TypeError, ValueError) as error:
            raise LLMServiceError("模型服务返回了无法识别的响应。") from error

        usage = _parse_usage(body.get("usage"))
        if usage is not None and self.usage_recorder is not None:
            await self.usage_recorder.record(
                model=response_model,
                input_cache_hit_tokens=usage.prompt_cache_hit_tokens,
                input_cache_miss_tokens=usage.prompt_cache_miss_tokens,
                output_tokens=usage.completion_tokens,
            )

        try:
            choice = body["choices"][0]
            content = choice["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise LLMServiceError("模型服务返回了无法识别的响应。") from error
        if not isinstance(content, str) or not content.strip():
            raise LLMServiceError("模型服务没有返回回答内容，请重试。")

        return ChatCompletion(content=content.strip(), model=response_model, usage=usage)


def _parse_usage(value: object) -> TokenUsage | None:
    if not isinstance(value, dict):
        return None
    try:
        prompt_tokens = int(value["prompt_tokens"])
        cache_hit_value = value.get("prompt_cache_hit_tokens")
        cache_miss_value = value.get("prompt_cache_miss_tokens")
        cache_hit_tokens = int(cache_hit_value) if cache_hit_value is not None else None
        cache_miss_tokens = int(cache_miss_value) if cache_miss_value is not None else None
        if cache_hit_tokens is None and cache_miss_tokens is None:
            cache_hit_tokens = 0
            cache_miss_tokens = prompt_tokens
        elif cache_hit_tokens is None:
            cache_hit_tokens = max(prompt_tokens - (cache_miss_tokens or 0), 0)
        elif cache_miss_tokens is None:
            cache_miss_tokens = max(prompt_tokens - cache_hit_tokens, 0)
        return TokenUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=int(value["completion_tokens"]),
            total_tokens=int(value["total_tokens"]),
            prompt_cache_hit_tokens=max(cache_hit_tokens or 0, 0),
            prompt_cache_miss_tokens=max(cache_miss_tokens or 0, 0),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _response_error_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return ""
    if not isinstance(body, dict):
        return ""
    error = body.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        return str(message)[:500] if message is not None else ""
    return ""


def get_chat_completion_gateway(
    settings: Annotated[Settings, Depends(get_settings)],
    usage_service: Annotated[TokenUsageService, Depends(get_token_usage_service)],
) -> ChatCompletionGateway:
    return OpenAICompatibleChatClient(settings, usage_service)
