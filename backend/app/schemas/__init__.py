from app.schemas.api import APIError, APIResponse
from app.schemas.course import CourseCreate, CourseDeleteResult, CourseRead
from app.schemas.document import (
    DocumentBulkDeleteRequest,
    DocumentBulkDeleteResult,
    DocumentDeleteResult,
    DocumentRead,
)

__all__ = [
    "APIError",
    "APIResponse",
    "CourseCreate",
    "CourseDeleteResult",
    "CourseRead",
    "DocumentBulkDeleteRequest",
    "DocumentBulkDeleteResult",
    "DocumentDeleteResult",
    "DocumentRead",
]
