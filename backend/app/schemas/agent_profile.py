from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.agents.configuration import AgentConfiguration


class AgentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("name", "description", "change_summary", check_fields=False)
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @field_validator("name", check_fields=False)
    @classmethod
    def nonblank_name(cls, value: str | None) -> str | None:
        if value is not None and not value:
            raise ValueError("智能体名称不能为空。")
        return value


class AgentProfileCreate(AgentInput):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    config: AgentConfiguration
    enabled: bool = Field(default=True, strict=True)
    change_summary: str = Field(default="初始配置", max_length=500)


class AgentProfileCopy(AgentInput):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    revision_id: UUID | None = None
    enabled: bool = Field(default=True, strict=True)


class AgentProfileUpdate(AgentInput):
    expected_row_version: int = Field(ge=1, strict=True)
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    enabled: bool | None = Field(default=None, strict=True)
    config: AgentConfiguration | None = None
    change_summary: str = Field(default="修改配置", max_length=500)

    @model_validator(mode="after")
    def validate_patch(self) -> Self:
        fields = self.model_fields_set
        if not fields.intersection({"name", "description", "enabled", "config"}):
            raise ValueError("至少提供一项要修改的内容。")
        for field in ("name", "enabled", "config"):
            if field in fields and getattr(self, field) is None:
                raise ValueError(f"{field} 不允许为空。")
        if "change_summary" in fields and "config" not in fields:
            raise ValueError("仅修改执行配置时填写变更说明。")
        return self


class AgentProfileRestore(AgentInput):
    expected_row_version: int = Field(ge=1, strict=True)
    revision_id: UUID
    change_summary: str = Field(default="恢复历史配置", max_length=500)


class AgentRevisionRead(BaseModel):
    id: UUID
    agent_profile_id: UUID
    revision_number: int
    config: AgentConfiguration
    config_sha256: str
    change_summary: str
    created_at: datetime


class AgentProfileRead(BaseModel):
    id: UUID
    name: str
    description: str | None
    enabled: bool
    deleted_at: datetime | None
    row_version: int
    created_at: datetime
    updated_at: datetime
    current_revision: AgentRevisionRead


class AgentProviderOption(BaseModel):
    id: str
    name: str
    models: list[str]
    configured: bool


class AgentEvaluationOption(BaseModel):
    profile_id: str
    registry_version: str
    registry_sha256: str
    allowed_usages: list[Literal["offline", "advisory"]]


class AgentProfileOptions(BaseModel):
    edition: Literal["product", "research"]
    providers: list[AgentProviderOption]
    evaluation_profiles: list[AgentEvaluationOption]
    external_search_enabled: bool
