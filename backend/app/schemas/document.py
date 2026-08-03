from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import DocumentProcessingStage, DocumentStatus


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    course_id: UUID
    original_name: str
    file_type: str
    file_size: int
    sha256: str
    status: DocumentStatus
    error_message: str | None
    progress_percent: int = Field(ge=0, le=100)
    processing_stage: DocumentProcessingStage
    progress_detail: str | None
    created_at: datetime
    updated_at: datetime


class DocumentDeleteResult(BaseModel):
    id: UUID
    deleted: bool = True


class DocumentBulkDeleteRequest(BaseModel):
    document_ids: list[UUID] = Field(min_length=1, max_length=500)

    @field_validator("document_ids")
    @classmethod
    def document_ids_must_be_unique(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("Document IDs must be unique.")
        return value


class DocumentBulkDeleteResult(BaseModel):
    deleted_ids: list[UUID]
    deleted_count: int
