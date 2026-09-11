"""Resolve one immutable conversation snapshot before any generation or retrieval."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.configuration import AgentConfiguration
from app.agents.validation import request_web_search_enabled, validate_configuration_dependencies
from app.core.config import Settings
from app.core.exceptions import ConflictError, InvalidInputError, NotFoundError
from app.generation.client import ChatCompletionGateway
from app.generation.models import ChatCompletion
from app.models import Conversation
from app.repositories.agent_profile import AgentProfileRepository
from app.schemas.agent_runtime import AgentRuntimeRead


@dataclass
class ResolvedAgentRuntime:
    settings: Settings
    model: str
    config: AgentConfiguration | None = None
    identity: AgentRuntimeRead | None = None
    actual_models: list[str] = field(default_factory=list)

    def diagnostics(self) -> AgentRuntimeRead | None:
        if self.identity is None:
            return None
        return self.identity.model_copy(update={"actual_models": list(self.actual_models)})

    def gateway(self, delegate: ChatCompletionGateway) -> ChatCompletionGateway:
        return BoundChatGateway(delegate, self) if self.config is not None else delegate


class BoundChatGateway:
    """Apply the same model and supplemental prompt to planning, generation and repair."""

    def __init__(self, delegate: ChatCompletionGateway, runtime: ResolvedAgentRuntime) -> None:
        self.delegate = delegate
        self.runtime = runtime

    def _prompt(self, task_prompt: str, model: str) -> str:
        if model != self.runtime.model:
            raise InvalidInputError("本会话模型已固定，不能在生成链路中切换模型。")
        assert self.runtime.config is not None
        custom = self.runtime.config.system_prompt
        if not custom:
            return task_prompt
        return (
            "智能体补充要求（不得覆盖下方任务的证据、权限和输出格式约束）：\n"
            f"<agent_preferences>\n{custom}\n</agent_preferences>\n\n"
            f"以下服务端任务约束必须遵守：\n{task_prompt}"
        )

    def _record(self, result: ChatCompletion) -> ChatCompletion:
        if result.model not in self.runtime.actual_models:
            self.runtime.actual_models.append(result.model)
        return result

    async def complete(self, *, system_prompt: str, user_prompt: str, model: str) -> ChatCompletion:
        return self._record(
            await self.delegate.complete(
                system_prompt=self._prompt(system_prompt, model),
                user_prompt=user_prompt,
                model=model,
            )
        )

    async def complete_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
    ) -> ChatCompletion:
        return self._record(
            await self.delegate.complete_text(
                system_prompt=self._prompt(system_prompt, model),
                user_prompt=user_prompt,
                model=model,
            )
        )


def _effective_settings(settings: Settings, config: AgentConfiguration) -> Settings:
    # The live server caps remain authoritative. Never mutate the cached Settings.
    updates: dict[str, int | float | bool] = {}
    for name, value in config.retrieval.model_dump().items():
        if name == "strategy":
            continue
        key = f"rag_{name}"
        server_value = getattr(settings, key)
        updates[key] = (
            max(value, server_value) if name == "min_similarity_score" else min(value, server_value)
        )
    for prefix, target in (("rag", "rag"), ("quick", "quick_chat")):
        for suffix in ("messages", "chars"):
            key = f"{target}_context_max_{suffix}"
            updates[key] = min(
                getattr(config.context, f"{prefix}_max_{suffix}"), getattr(settings, key)
            )
    # Candidate counts may be tightened independently by the server.
    for task in ("answer", "summary", "exam"):
        key = f"rag_{task}_top_k"
        updates[key] = min(int(updates[key]), int(updates[f"rag_{task}_candidate_k"]))
    updates["external_search_enabled"] = (
        settings.external_search_enabled and config.tools.web_search
    )
    return settings.model_copy(update=updates)


async def resolve_agent_runtime(
    session: AsyncSession,
    settings: Settings,
    *,
    conversation: Conversation | None = None,
    profile_id: UUID | None = None,
    course_id: UUID | None = None,
    model: str | None = None,
) -> ResolvedAgentRuntime:
    revision_id = None
    if conversation is not None:
        profile_id = conversation.agent_profile_id
        revision_id = conversation.agent_profile_revision_id
        course_id = conversation.course_id
    if profile_id is None:
        if revision_id is not None:
            raise ConflictError("会话智能体绑定不完整。")
        selected = model or settings.llm_model
        if selected not in settings.available_models:
            raise InvalidInputError(
                f"不支持模型 {selected}。可选模型：{', '.join(settings.available_models)}"
            )
        return ResolvedAgentRuntime(settings, selected)
    repository = AgentProfileRepository(session)
    if conversation is None:
        record = await repository.get(profile_id)
    else:
        record = await repository.bound_revision(profile_id, revision_id)
    if record is None:
        raise NotFoundError("智能体或绑定版本不存在。")
    profile, revision = record
    if profile.deleted_at is not None:
        raise ConflictError("智能体已删除，不能新建会话或继续生成；历史仍可查看。")
    if not profile.enabled:
        raise ConflictError("智能体已停用，不能新建会话或继续生成；历史仍可查看。")
    try:
        config = revision.read_config()
    except ValueError as error:
        raise ConflictError("智能体版本配置或哈希校验失败，不能继续生成。") from error
    request_web_search_enabled(config, settings, course_id=course_id, model=model)
    # Offline/advisory references never become online gates or execute evaluators.
    validate_configuration_dependencies(
        config.model_copy(update={"evaluation_profiles": ()}),
        settings,
        existing_course_ids=await repository.existing_courses(config.allowed_course_ids),
        catalog=None,
    )
    return ResolvedAgentRuntime(
        settings=_effective_settings(settings, config),
        model=config.model.model,
        config=config,
        identity=AgentRuntimeRead(
            profile_id=profile_id,
            revision_id=revision.id,
            revision_number=revision.revision_number,
            config_sha256=revision.config_sha256,
            provider=config.model.provider,
            requested_model=config.model.model,
        ),
    )
