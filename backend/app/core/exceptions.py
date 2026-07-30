class DomainError(Exception):
    """Base exception for expected business-rule failures."""


class ConflictError(DomainError):
    """Raised when a unique business rule would be violated."""


class NotFoundError(DomainError):
    """Raised when a requested entity does not exist."""
