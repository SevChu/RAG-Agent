from app.schemas.api import APIError, APIResponse
from app.schemas.course import CourseCreate, CourseDeleteResult, CourseRead
from app.schemas.document import DocumentDeleteResult, DocumentRead

__all__ = [
    "APIError",
    "APIResponse",
    "CourseCreate",
    "CourseDeleteResult",
    "CourseRead",
    "DocumentDeleteResult",
    "DocumentRead",
]
