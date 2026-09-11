from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.schemas.agent_profile import (
    AgentProfileCopy,
    AgentProfileCreate,
    AgentProfileOptions,
    AgentProfileRead,
    AgentProfileRestore,
    AgentProfileUpdate,
    AgentRevisionRead,
)
from app.schemas.api import APIResponse
from app.services.agent_profile import AgentProfileService

router = APIRouter(prefix="/agent-profiles", tags=["agent-profiles"])


def get_agent_profile_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AgentProfileService:
    return AgentProfileService(session, settings)


Service = Annotated[AgentProfileService, Depends(get_agent_profile_service)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


@router.get("/options", response_model=APIResponse[AgentProfileOptions])
async def agent_options(service: Service) -> APIResponse[AgentProfileOptions]:
    return APIResponse(data=service.options())


@router.post("", response_model=APIResponse[AgentProfileRead], status_code=status.HTTP_201_CREATED)
async def create_agent(
    payload: AgentProfileCreate, service: Service
) -> APIResponse[AgentProfileRead]:
    return APIResponse(data=await service.create(payload))


@router.get("", response_model=APIResponse[list[AgentProfileRead]])
async def list_agents(
    service: Service,
    enabled: bool | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> APIResponse[list[AgentProfileRead]]:
    return APIResponse(
        data=await service.list_profiles(enabled=enabled, limit=limit, offset=offset)
    )


@router.get("/{profile_id}", response_model=APIResponse[AgentProfileRead])
async def get_agent(profile_id: UUID, service: Service) -> APIResponse[AgentProfileRead]:
    return APIResponse(data=await service.get(profile_id))


@router.patch("/{profile_id}", response_model=APIResponse[AgentProfileRead])
async def update_agent(
    profile_id: UUID,
    payload: AgentProfileUpdate,
    service: Service,
) -> APIResponse[AgentProfileRead]:
    return APIResponse(data=await service.update(profile_id, payload))


@router.post(
    "/{profile_id}/copy",
    response_model=APIResponse[AgentProfileRead],
    status_code=status.HTTP_201_CREATED,
)
async def copy_agent(
    profile_id: UUID,
    payload: AgentProfileCopy,
    service: Service,
) -> APIResponse[AgentProfileRead]:
    return APIResponse(data=await service.copy(profile_id, payload))


@router.get("/{profile_id}/revisions", response_model=APIResponse[list[AgentRevisionRead]])
async def list_revisions(
    profile_id: UUID,
    service: Service,
    limit: Limit = 50,
    offset: Offset = 0,
) -> APIResponse[list[AgentRevisionRead]]:
    return APIResponse(data=await service.revisions(profile_id, limit=limit, offset=offset))


@router.get("/{profile_id}/revisions/{revision_id}", response_model=APIResponse[AgentRevisionRead])
async def get_revision(
    profile_id: UUID,
    revision_id: UUID,
    service: Service,
) -> APIResponse[AgentRevisionRead]:
    return APIResponse(data=await service.revision(profile_id, revision_id))


@router.post("/{profile_id}/restore", response_model=APIResponse[AgentProfileRead])
async def restore_agent(
    profile_id: UUID,
    payload: AgentProfileRestore,
    service: Service,
) -> APIResponse[AgentProfileRead]:
    return APIResponse(data=await service.restore(profile_id, payload))


@router.delete("/{profile_id}", response_model=APIResponse[None])
async def delete_agent(
    profile_id: UUID,
    expected_row_version: Annotated[int, Query(ge=1)],
    service: Service,
) -> APIResponse[None]:
    await service.delete(profile_id, expected_row_version)
    return APIResponse(data=None)
