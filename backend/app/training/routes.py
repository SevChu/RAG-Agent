from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings, get_settings
from app.core.exceptions import FileTooLargeError, InvalidInputError
from app.db.session import get_session
from app.schemas.api import APIResponse
from app.training.schemas import (
    DatasetCreate,
    DatasetRead,
    EligibilityRead,
    ReviewRead,
    ReviewRequest,
    RevisionRead,
    ValidationReport,
)
from app.training.service import DatasetService
from app.training.validation import MAX_BYTES, parse_manifest, validate_jsonl

router = APIRouter(prefix="/training-datasets", tags=["training-datasets"])


def get_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> DatasetService:
    return DatasetService(session, settings)


Service = Annotated[DatasetService, Depends(get_service)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


async def uploaded(file: UploadFile) -> bytes:
    try:
        # The supplied filename is never used as a path or echoed into logs.
        data = await file.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise FileTooLargeError("训练文件最多 8 MiB。")
        return data
    finally:
        await file.close()


@router.post("/validate", response_model=APIResponse[ValidationReport])
async def validate_upload(
    service: Service,
    manifest: Annotated[str, Form(max_length=16000)],
    file: Annotated[UploadFile, File()],
) -> APIResponse[ValidationReport]:
    data = await uploaded(file)
    try:
        parsed = parse_manifest(manifest)
    except (ValueError, RecursionError) as error:
        raise InvalidInputError("manifest 格式或字段不合法。") from error
    return APIResponse(data=await run_in_threadpool(validate_jsonl, data, parsed))


@router.post("", response_model=APIResponse[DatasetRead], status_code=201)
async def create(payload: DatasetCreate, service: Service) -> APIResponse[DatasetRead]:
    return APIResponse(data=await service.create(payload))


@router.get("", response_model=APIResponse[list[DatasetRead]])
async def list_datasets(
    service: Service, limit: Limit = 50, offset: Offset = 0
) -> APIResponse[list[DatasetRead]]:
    return APIResponse(data=await service.list_datasets(limit, offset))


@router.get("/{dataset_id}", response_model=APIResponse[DatasetRead])
async def get_dataset(dataset_id: UUID, service: Service) -> APIResponse[DatasetRead]:
    return APIResponse(data=await service.get(dataset_id))


@router.post("/{dataset_id}/revisions", response_model=APIResponse[RevisionRead], status_code=201)
async def import_revision(
    dataset_id: UUID,
    service: Service,
    expected_row_version: Annotated[int, Form(ge=1)],
    manifest: Annotated[str, Form(max_length=16000)],
    file: Annotated[UploadFile, File()],
) -> APIResponse[RevisionRead]:
    data = await uploaded(file)
    try:
        parsed = parse_manifest(manifest)
    except (ValueError, RecursionError) as error:
        raise InvalidInputError("manifest 格式或字段不合法。") from error
    return APIResponse(
        data=await service.import_revision(dataset_id, expected_row_version, parsed, data)
    )


@router.get("/{dataset_id}/revisions", response_model=APIResponse[list[RevisionRead]])
async def list_revisions(
    dataset_id: UUID, service: Service, limit: Limit = 50, offset: Offset = 0
) -> APIResponse[list[RevisionRead]]:
    return APIResponse(data=await service.list_revisions(dataset_id, limit, offset))


@router.get("/{dataset_id}/revisions/{revision_id}", response_model=APIResponse[RevisionRead])
async def get_revision(
    dataset_id: UUID, revision_id: UUID, service: Service
) -> APIResponse[RevisionRead]:
    return APIResponse(data=await service.get_revision(dataset_id, revision_id))


@router.post(
    "/{dataset_id}/revisions/{revision_id}/reviews", response_model=APIResponse[ReviewRead]
)
async def review(
    dataset_id: UUID, revision_id: UUID, payload: ReviewRequest, service: Service
) -> APIResponse[ReviewRead]:
    return APIResponse(data=await service.review(dataset_id, revision_id, payload))


@router.get(
    "/{dataset_id}/revisions/{revision_id}/reviews", response_model=APIResponse[list[ReviewRead]]
)
async def reviews(
    dataset_id: UUID, revision_id: UUID, service: Service, limit: Limit = 50, offset: Offset = 0
) -> APIResponse[list[ReviewRead]]:
    return APIResponse(data=await service.reviews(dataset_id, revision_id, limit, offset))


@router.get(
    "/{dataset_id}/revisions/{revision_id}/eligibility", response_model=APIResponse[EligibilityRead]
)
async def eligibility(
    dataset_id: UUID, revision_id: UUID, agent_profile_id: UUID, service: Service
) -> APIResponse[EligibilityRead]:
    return APIResponse(data=await service.eligibility(dataset_id, revision_id, agent_profile_id))
