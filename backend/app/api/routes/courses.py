from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.schemas import CourseCreate, CourseDeleteResult, CourseRead
from app.schemas.api import APIResponse
from app.services import CourseService
from app.services.file_storage import FileStorageService

router = APIRouter(prefix="/courses", tags=["courses"])

SessionDependency = Annotated[AsyncSession, Depends(get_session)]
SettingsDependency = Annotated[Settings, Depends(get_settings)]


@router.post(
    "",
    response_model=APIResponse[CourseRead],
    status_code=status.HTTP_201_CREATED,
)
async def create_course(
    payload: CourseCreate,
    session: SessionDependency,
) -> APIResponse[CourseRead]:
    course = await CourseService(session).create(
        name=payload.name,
        description=payload.description,
    )
    return APIResponse(data=CourseRead.model_validate(course))


@router.get("", response_model=APIResponse[list[CourseRead]])
async def list_courses(session: SessionDependency) -> APIResponse[list[CourseRead]]:
    courses = await CourseService(session).list()
    return APIResponse(data=[CourseRead.model_validate(course) for course in courses])


@router.get("/{course_id}", response_model=APIResponse[CourseRead])
async def get_course(
    course_id: UUID,
    session: SessionDependency,
) -> APIResponse[CourseRead]:
    course = await CourseService(session).get(course_id)
    return APIResponse(data=CourseRead.model_validate(course))


@router.delete(
    "/{course_id}",
    response_model=APIResponse[CourseDeleteResult],
)
async def delete_course(
    course_id: UUID,
    session: SessionDependency,
    settings: SettingsDependency,
) -> APIResponse[CourseDeleteResult]:
    service = CourseService(session)
    await service.get(course_id)
    storage = FileStorageService(
        upload_dir=settings.upload_dir,
        max_upload_mb=settings.max_upload_mb,
    )
    staged_deletion = await storage.stage_course_deletion(course_id)
    try:
        await service.delete(course_id)
    except Exception:
        await storage.restore_deletion(staged_deletion)
        raise
    await storage.complete_deletion(staged_deletion)
    return APIResponse(data=CourseDeleteResult(id=course_id))
