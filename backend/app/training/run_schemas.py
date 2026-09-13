from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.agents.configuration import AgentConfiguration
from app.training.schemas import Contract, SplitSummary, Target

RunStatus = Literal[
    "queued", "running", "cancelling", "succeeded", "failed", "cancelled", "interrupted"
]
Key = Annotated[str, Field(pattern=r"^[A-Za-z0-9._-]{8,100}$")]


class LoraParameters(Contract):
    method: Literal["lora", "qlora"] = "lora"
    rank: int = Field(default=8, ge=1, le=256, strict=True)
    alpha: int = Field(default=16, ge=1, le=512, strict=True)
    dropout: float = Field(default=0.05, ge=0, lt=1, allow_inf_nan=False, strict=True)
    learning_rate: float = Field(default=0.0002, gt=0, le=1, allow_inf_nan=False, strict=True)
    batch_size: int = Field(default=4, ge=1, le=64, strict=True)
    accumulation_steps: int = Field(default=1, ge=1, le=64, strict=True)
    epochs: int = Field(default=3, ge=1, le=20, strict=True)
    max_length: int = Field(default=512, ge=32, le=4096, strict=True)
    seed: int = Field(default=42, ge=0, le=2147483647, strict=True)


class RunCreate(Contract):
    idempotency_key: Key
    agent_profile_id: UUID
    dataset_id: UUID
    dataset_revision_id: UUID
    target: Target
    base_model: Literal["fake-scorer-v1", "fake-reranker-v1"]
    base_model_revision: Literal["fake-1"] = "fake-1"
    trainer: Literal["fake-v1"] = "fake-v1"
    parameters: LoraParameters = Field(default_factory=LoraParameters)
    simulation_steps: int = Field(default=20, ge=1, le=100, strict=True)
    predecessor_adapter_id: UUID | None = None
    expected_agent_revision_id: UUID | None = None

    @model_validator(mode="after")
    def matching_model(self) -> RunCreate:
        if self.base_model != f"fake-{self.target}-v1":
            raise ValueError("模拟基础模型与训练目标不匹配。")
        return self


class RetryRequest(Contract):
    idempotency_key: Key


class RunSnapshot(Contract):
    schema_version: Literal[1] = 1
    request: RunCreate
    agent_revision_id: UUID
    agent_config_sha256: str
    agent_configuration: AgentConfiguration
    manifest_sha256: str
    content_sha256: str
    splits: dict[str, SplitSummary]
    source_course_ids: tuple[UUID, ...]
    dataset_review_sequence: int
    code_sha256: str
    python_version: str


class ResourceEstimate(Contract):
    mode: Literal["simulated"] = "simulated"
    simulation_steps: int
    checkpoint_interval_seconds: float
    nominal_simulation_seconds: float
    available_memory_bytes: int | None
    real_training_seconds: None = None
    real_vram_bytes: None = None
    real_cost: None = None
    note: str = "仅模拟步骤耗时；不含排队、数据校验和数据库开销。真实训练资源与成本待评估。"


class RunRead(Contract):
    id: UUID
    agent_profile_id: UUID
    agent_revision_id: UUID
    dataset_revision_id: UUID
    retry_of: UUID | None
    status: RunStatus
    completed_steps: int
    total_steps: int
    last_code: str
    snapshot_sha256: str
    source: dict[str, Any]
    result: dict[str, Any] | None
    started_at: float | None
    finished_at: float | None
    created_at: datetime


class EventRead(Contract):
    run_id: UUID
    sequence: int
    phase: RunStatus
    code: str
    completed_steps: int
    total_steps: int
    created_at: datetime
