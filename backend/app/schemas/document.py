from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models import DocumentStatus


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
    created_at: datetime
    updated_at: datetime
