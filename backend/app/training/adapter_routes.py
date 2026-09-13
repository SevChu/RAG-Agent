from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.schemas.api import APIResponse
from app.training.adapter_schemas import AdapterRead, CompatibilityRead, CompatibilityRequest
from app.training.adapter_service import AdapterService

router = APIRouter(prefix="/model-adapters", tags=["model-adapters"])


def get_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AdapterService:
    return AdapterService(session, settings)


Service = Annotated[AdapterService, Depends(get_service)]
Limit = Annotated[int, Query(ge=1, le=100)]


@router.get("", response_model=APIResponse[list[AdapterRead]])
async def listing(
    service: Service,
    limit: Limit = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    agent_profile_id: UUID | None = None,
    include_archived: bool = False,
) -> APIResponse[list[AdapterRead]]:
    return APIResponse(
        data=await service.list_adapters(limit, offset, agent_profile_id, include_archived)
    )


@router.get("/storage-audit", response_model=APIResponse[dict[str, Any]])
async def storage_audit(
    service: Service, limit: Limit = 50, offset: Annotated[int, Query(ge=0)] = 0
) -> APIResponse[dict[str, Any]]:
    return APIResponse(data=await service.inventory(offset, limit))


@router.post("/from-run/{run_id}", response_model=APIResponse[AdapterRead])
async def reconcile(run_id: UUID, service: Service) -> APIResponse[AdapterRead]:
    return APIResponse(data=await service.reconcile(run_id))


@router.get("/{adapter_id}", response_model=APIResponse[AdapterRead])
async def detail(adapter_id: UUID, service: Service) -> APIResponse[AdapterRead]:
    return APIResponse(data=await service.get(adapter_id))


@router.get("/{adapter_id}/lineage", response_model=APIResponse[dict[str, Any]])
async def lineage(
    adapter_id: UUID, service: Service, limit: Limit = 50
) -> APIResponse[dict[str, Any]]:
    return APIResponse(data=await service.lineage(adapter_id, limit))


@router.post("/{adapter_id}/archive", response_model=APIResponse[AdapterRead])
async def archive(adapter_id: UUID, service: Service) -> APIResponse[AdapterRead]:
    return APIResponse(data=await service.archive(adapter_id))


@router.post("/{adapter_id}/compatibility", response_model=APIResponse[CompatibilityRead])
async def compatibility(
    adapter_id: UUID, payload: CompatibilityRequest, service: Service
) -> APIResponse[CompatibilityRead]:
    return APIResponse(data=await service.compatibility(adapter_id, payload))
