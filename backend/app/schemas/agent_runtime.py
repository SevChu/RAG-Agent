from uuid import UUID

from pydantic import BaseModel, Field


class AgentRuntimeRead(BaseModel):
    profile_id: UUID
    revision_id: UUID
    revision_number: int
    config_sha256: str
    provider: str
    requested_model: str
    actual_models: list[str] = Field(default_factory=list)
