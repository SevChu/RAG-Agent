"""Local dependency validation; no models, benchmark samples or network calls."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from app.agents.configuration import AgentConfiguration
from app.core.config import Settings
from app.core.exceptions import ConflictError, InvalidInputError, LLMConfigurationError

if TYPE_CHECKING:
    from app.evaluation.baseline_profiles import BaselineProfileRegistry, FrozenBaselineProfile

DEFAULT_BASELINE_PROFILES_PATH = (
    Path(__file__).resolve().parents[1] / "evaluation" / "baseline-profiles.json"
)

Usage = Literal["offline", "advisory"]


def profile_usages(profile: FrozenBaselineProfile) -> list[Usage]:
    # Only explicit grants in the frozen registry count as permission.
    result: list[Usage] = []
    if "offline benchmark reference" in profile.allowed_usage:
        result.append("offline")
    if {"advisory error analysis", "advisory span-localization error analysis"}.intersection(
        profile.allowed_usage
    ):
        result.append("advisory")
    return result


@dataclass(frozen=True)
class EvaluationCatalog:
    registry: BaselineProfileRegistry
    sha256: str


def load_evaluation_catalog(
    path: Path = DEFAULT_BASELINE_PROFILES_PATH,
) -> EvaluationCatalog:
    try:
        from app.evaluation.baseline_profiles import BaselineProfileRegistry

        payload = path.read_bytes()
        registry = BaselineProfileRegistry.model_validate_json(payload)
    except (ImportError, OSError, ValueError) as error:
        raise ConflictError("评测配置注册表不可用，请检查本地安装。") from error
    return EvaluationCatalog(registry, sha256(payload).hexdigest())


def validate_configuration_dependencies(
    config: AgentConfiguration,
    settings: Settings,
    *,
    existing_course_ids: set[UUID],
    catalog: EvaluationCatalog | None,
) -> None:
    providers = [p for p in settings.llm_providers if p.id == config.model.provider]
    if len(providers) != 1 or config.model.model not in providers[0].models:
        raise InvalidInputError("供应商与模型不匹配，或模型不在服务端白名单中。")
    if sum(config.model.model in p.models for p in settings.llm_providers) != 1:
        raise InvalidInputError("该模型在多个供应商中重复登记，请先消除路由歧义。")
    if not providers[0].configured:
        raise LLMConfigurationError("所选模型供应商尚未配置凭据。")
    if set(config.allowed_course_ids) != existing_course_ids:
        raise InvalidInputError("允许的资料空间不存在或已删除，请刷新后重新选择。")
    for reference in config.evaluation_profiles:
        if catalog is None:
            raise ConflictError("评测配置注册表不可用。")
        if (
            reference.registry_version != catalog.registry.release_version
            or reference.registry_sha256 != catalog.sha256
        ):
            raise InvalidInputError("评测注册表版本或哈希已变化，请重新选择配置。")
        try:
            profile = catalog.registry.get(reference.profile_id)
        except KeyError as error:
            raise InvalidInputError("评测配置未登记，不能使用实验候选代替冻结配置。") from error
        if reference.usage not in profile_usages(profile):
            raise InvalidInputError("所选评测配置不允许该用途。")


def request_web_search_enabled(
    config: AgentConfiguration,
    settings: Settings,
    *,
    course_id: UUID | None,
    model: str | None = None,
    requested: bool = True,
    course_only: bool = False,
    task_type: Literal["question", "summary", "exam"] = "question",
) -> bool:
    """Day 3 integration hook: requests can narrow but never expand permissions.

    None course_id denotes quick chat, which grants no course retrieval access.
    """
    if model is not None and model != config.model.model:
        raise InvalidInputError("本会话模型已由智能体版本固定，请新建会话以切换模型。")
    if course_id is not None and course_id not in config.allowed_course_ids:
        raise InvalidInputError("当前智能体版本不允许访问该资料空间。")
    return (
        settings.external_search_enabled
        and config.tools.web_search
        and requested
        and not course_only
        and task_type != "summary"
    )
