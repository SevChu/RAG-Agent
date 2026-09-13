from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from app.training.run_schemas import LoraParameters
from app.training.schemas import Contract, Target


class SimulationResult(Contract):
    artifact_kind: Literal["simulated"]
    deployable: Literal[False]
    evaluation_status: Literal["not_evaluated"]
    trainer: Literal["fake-v1"]
    simulation_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")


class AdapterManifest(Contract):
    schema_version: Literal[1] = 1
    registry_version: Literal["simulated-adapter-v1"] = "simulated-adapter-v1"
    dataset_schema_version: Literal[1] = 1
    adapter_id: UUID
    run_id: UUID
    predecessor_id: UUID | None
    run_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source: dict[str, Any]
    finished_at: float
    result: SimulationResult


class AdapterRead(Contract):
    id: UUID
    run_id: UUID
    predecessor_id: UUID | None
    manifest_sha256: str
    artifact_kind: Literal["simulated"] = "simulated"
    deployable: Literal[False] = False
    evaluation_status: Literal["not_evaluated"] = "not_evaluated"
    integrity: Literal["valid", "missing", "invalid"]
    created_at: datetime
    archived_at: datetime | None
    manifest: AdapterManifest


class CompatibilityRequest(Contract):
    target: Target
    base_model: str = Field(min_length=1, max_length=120)
    base_model_revision: str = Field(min_length=1, max_length=120)
    dataset_schema_version: int = Field(ge=1, le=100, strict=True)
    parameters: LoraParameters


class CompatibilityRead(Contract):
    contract_compatible: bool
    deployable: Literal[False] = False
    reasons: list[str]
