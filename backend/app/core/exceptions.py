class DomainError(Exception):
    """Base exception for expected business-rule failures."""


class ConflictError(DomainError):
    """Raised when a unique business rule would be violated."""


class NotFoundError(DomainError):
    """Raised when a requested entity does not exist."""


class InvalidInputError(DomainError):
    """Raised when user-provided content fails validation."""


class UnsupportedFileTypeError(InvalidInputError):
    """Raised when an uploaded file type is not supported or is disguised."""


class FileTooLargeError(InvalidInputError):
    """Raised when an upload exceeds the configured size limit."""


class IndexStorageError(DomainError):
    """Raised when vectors cannot be safely updated or removed."""


class LLMConfigurationError(DomainError):
    """Raised when a model-backed operation has no usable server configuration."""


class LLMServiceError(DomainError):
    """Raised when the configured model service cannot complete a request."""


class LLMOutputError(DomainError):
    """Raised when generated output fails the grounded-answer contract."""
