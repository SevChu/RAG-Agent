from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.exceptions import (
    ConflictError,
    DomainError,
    FileTooLargeError,
    IndexStorageError,
    InvalidInputError,
    LLMConfigurationError,
    LLMOutputError,
    LLMServiceError,
    NotFoundError,
    UnsupportedFileTypeError,
)

ERROR_MAPPING: dict[type[DomainError], tuple[int, str]] = {
    NotFoundError: (404, "NOT_FOUND"),
    ConflictError: (409, "CONFLICT"),
    FileTooLargeError: (413, "FILE_TOO_LARGE"),
    UnsupportedFileTypeError: (415, "UNSUPPORTED_FILE_TYPE"),
    InvalidInputError: (400, "INVALID_INPUT"),
    IndexStorageError: (503, "INDEX_STORAGE_ERROR"),
    LLMConfigurationError: (503, "LLM_NOT_CONFIGURED"),
    LLMServiceError: (502, "LLM_SERVICE_ERROR"),
    LLMOutputError: (502, "LLM_OUTPUT_ERROR"),
}


def error_payload(*, code: str, message: str) -> dict[str, object]:
    return {
        "data": None,
        "error": {
            "code": code,
            "message": message,
        },
    }


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def handle_domain_error(_: Request, error: DomainError) -> JSONResponse:
        status_code, code = ERROR_MAPPING.get(
            type(error),
            (400, "DOMAIN_ERROR"),
        )
        return JSONResponse(
            status_code=status_code,
            content=error_payload(code=code, message=str(error)),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        first_error = error.errors()[0] if error.errors() else None
        message = (
            str(first_error.get("msg", "Invalid request."))
            if first_error
            else "Invalid request."
        )
        return JSONResponse(
            status_code=422,
            content=error_payload(code="VALIDATION_ERROR", message=message),
        )
