from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from app.ingestion.models import ParsedDocument

ParseProgressCallback = Callable[[int, int, str], None]


class DocumentParser(Protocol):
    file_types: frozenset[str]
    parser_name: str

    def parse(
        self,
        path: Path,
        *,
        display_name: str | None = None,
        progress_callback: ParseProgressCallback | None = None,
    ) -> ParsedDocument: ...
