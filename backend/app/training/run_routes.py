from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.schemas.api import APIResponse
from app.training.run_schemas import EventRead, ResourceEstimate, RetryRequest, RunCreate, RunRead
from app.training.run_store import RunStore
from app.training.trainer import FakeTrainer

router = APIRouter(prefix="/training-runs", tags=["training-runs"])


def get_store(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RunStore:
    return RunStore(session, settings)


Store = Annotated[RunStore, Depends(get_store)]
Limit = Annotated[int, Query(ge=1, le=100)]


@router.get("/options", response_model=APIResponse[dict[str, Any]])
async def options(store: Store) -> APIResponse[dict[str, Any]]:
    return APIResponse(
        data={
            "trainer": "fake-v1",
            "mode": "simulated",
            "real_training_available": False,
            "worker_enabled": store.settings.training_worker_enabled,
            "base_models": ["fake-scorer-v1", "fake-reranker-v1"],
            "max_simulation_steps": 100,
            "checkpoint_interval_seconds": store.settings.training_fake_step_seconds,
            "lease_seconds": store.settings.training_lease_seconds,
        }
    )


@router.post("/estimate", response_model=APIResponse[ResourceEstimate])
async def estimate(payload: RunCreate, store: Store) -> APIResponse[ResourceEstimate]:
    return APIResponse(
        data=FakeTrainer(store.settings.training_fake_step_seconds).estimate(payload)
    )


@router.post("", response_model=APIResponse[RunRead], status_code=201)
async def create(payload: RunCreate, store: Store) -> APIResponse[RunRead]:
    return APIResponse(data=await store.create(payload))


@router.get("", response_model=APIResponse[list[RunRead]])
async def list_runs(
    store: Store,
    limit: Limit = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    agent_profile_id: UUID | None = None,
) -> APIResponse[list[RunRead]]:
    return APIResponse(data=await store.list_runs(limit, offset, agent_profile_id))


@router.get("/{run_id}", response_model=APIResponse[RunRead])
async def get_run(run_id: UUID, store: Store) -> APIResponse[RunRead]:
    return APIResponse(data=await store.get(run_id))


@router.get("/{run_id}/events", response_model=APIResponse[list[EventRead]])
async def events(
    run_id: UUID, store: Store, after: Annotated[int, Query(ge=0)] = 0, limit: Limit = 50
) -> APIResponse[list[EventRead]]:
    return APIResponse(data=await store.events(run_id, after, limit))


@router.post("/{run_id}/cancel", response_model=APIResponse[RunRead])
async def cancel(run_id: UUID, store: Store) -> APIResponse[RunRead]:
    return APIResponse(data=await store.cancel(run_id))


@router.post("/{run_id}/retry", response_model=APIResponse[RunRead], status_code=201)
async def retry(run_id: UUID, payload: RetryRequest, store: Store) -> APIResponse[RunRead]:
    return APIResponse(
        data=await store.create(None, retry_of=run_id, retry_key=payload.idempotency_key)
    )
