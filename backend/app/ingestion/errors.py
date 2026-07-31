class IngestionError(Exception):
    """Base class for expected document ingestion failures."""


class DocumentReadError(IngestionError):
    """Raised when a source document cannot be read."""


class InvalidDocumentEncodingError(IngestionError):
    """Raised when a text document is not valid UTF-8."""


class EmptyDocumentError(IngestionError):
    """Raised when parsing produces no meaningful content."""


class UnsupportedParserError(IngestionError):
    """Raised when no parser is registered for a document type."""
