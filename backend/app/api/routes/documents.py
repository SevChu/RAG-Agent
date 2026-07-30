from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.schemas import DocumentDeleteResult, DocumentRead
from app.schemas.api import APIResponse
from app.services import CourseService, DocumentService
from app.services.file_storage import FileStorageService, PromotedUpload

router = APIRouter(tags=["documents"])

SessionDependency = Annotated[AsyncSession, Depends(get_session)]
SettingsDependency = Annotated[Settings, Depends(get_settings)]


@router.post(
    "/courses/{course_id}/documents",
    response_model=APIResponse[DocumentRead],
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    course_id: UUID,
    file: Annotated[UploadFile, File(...)],
    session: SessionDependency,
    settings: SettingsDependency,
) -> APIResponse[DocumentRead]:
    await CourseService(session).get(course_id)
    storage = FileStorageService(
        upload_dir=settings.upload_dir,
        max_upload_mb=settings.max_upload_mb,
    )
    staged = await storage.stage_upload(file)
    document_id = uuid4()
    promoted: PromotedUpload | None = None
    try:
        promoted = await storage.promote(
            staged,
            course_id=course_id,
            document_id=document_id,
        )
        document = await DocumentService(session).register(
            document_id=document_id,
            course_id=course_id,
            original_name=staged.original_name,
            stored_name=promoted.stored_name,
            file_type=staged.extension.removeprefix("."),
            file_size=staged.file_size,
            sha256=staged.sha256,
        )
    except Exception:
        if promoted is not None:
            await storage.discard_path(promoted.path)
            await storage.remove_empty_course_dir(course_id)
        else:
            await storage.discard_path(staged.path)
        raise
    return APIResponse(data=DocumentRead.model_validate(document))


@router.get(
    "/courses/{course_id}/documents",
    response_model=APIResponse[list[DocumentRead]],
)
async def list_documents(
    course_id: UUID,
    session: SessionDependency,
) -> APIResponse[list[DocumentRead]]:
    documents = await DocumentService(session).list_for_course(course_id)
    return APIResponse(
        data=[DocumentRead.model_validate(document) for document in documents]
    )


@router.get(
    "/documents/{document_id}",
    response_model=APIResponse[DocumentRead],
)
@router.get(
    "/documents/{document_id}/status",
    response_model=APIResponse[DocumentRead],
)
async def get_document(
    document_id: UUID,
    session: SessionDependency,
) -> APIResponse[DocumentRead]:
    document = await DocumentService(session).get(document_id)
    return APIResponse(data=DocumentRead.model_validate(document))


@router.delete(
    "/documents/{document_id}",
    response_model=APIResponse[DocumentDeleteResult],
)
async def delete_document(
    document_id: UUID,
    session: SessionDependency,
    settings: SettingsDependency,
) -> APIResponse[DocumentDeleteResult]:
    service = DocumentService(session)
    document = await service.get(document_id)
    storage = FileStorageService(
        upload_dir=settings.upload_dir,
        max_upload_mb=settings.max_upload_mb,
    )
    staged_deletion = await storage.stage_document_deletion(
        course_id=document.course_id,
        stored_name=document.stored_name,
    )
    try:
        await service.delete(document_id)
    except Exception:
        await storage.restore_deletion(staged_deletion)
        raise
    await storage.complete_deletion(staged_deletion)
    await storage.remove_empty_course_dir(document.course_id)
    return APIResponse(data=DocumentDeleteResult(id=document_id))
