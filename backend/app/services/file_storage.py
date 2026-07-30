from __future__ import annotations

import codecs
import hashlib
import os
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from uuid import UUID, uuid4

import anyio
from fastapi import UploadFile

from app.core.exceptions import (
    FileTooLargeError,
    InvalidInputError,
    UnsupportedFileTypeError,
)

ALLOWED_EXTENSIONS = {".pdf", ".pptx", ".docx", ".md", ".txt"}
CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class StagedUpload:
    path: Path
    original_name: str
    extension: str
    file_size: int
    sha256: str


@dataclass(frozen=True)
class PromotedUpload:
    path: Path
    stored_name: str


class FileStorageService:
    def __init__(self, *, upload_dir: Path, max_upload_mb: int) -> None:
        self.upload_dir = upload_dir.resolve()
        self.max_upload_bytes = max_upload_mb * 1024 * 1024
        self.staging_dir = self.upload_dir / ".staging"
        self.trash_dir = self.upload_dir / ".trash"

    async def stage_upload(self, upload: UploadFile) -> StagedUpload:
        original_name = self._safe_original_name(upload.filename)
        extension = Path(original_name).suffix.lower()
        if extension not in ALLOWED_EXTENSIONS:
            raise UnsupportedFileTypeError(
                f"Unsupported file type: {extension or 'no extension'}."
            )

        await anyio.to_thread.run_sync(
            lambda: self.staging_dir.mkdir(parents=True, exist_ok=True)
        )
        temp_path = self.staging_dir / f"{uuid4()}.upload"
        digest = hashlib.sha256()
        total_size = 0

        try:
            async with await anyio.open_file(temp_path, "wb") as target:
                while chunk := await upload.read(CHUNK_SIZE):
                    total_size += len(chunk)
                    if total_size > self.max_upload_bytes:
                        raise FileTooLargeError(
                            f"File exceeds the {self.max_upload_bytes // 1024 // 1024} MB limit."
                        )
                    digest.update(chunk)
                    await target.write(chunk)
            if total_size == 0:
                raise InvalidInputError("Empty files cannot be uploaded.")
            await anyio.to_thread.run_sync(
                self._validate_content,
                temp_path,
                extension,
            )
            return StagedUpload(
                path=temp_path,
                original_name=original_name,
                extension=extension,
                file_size=total_size,
                sha256=digest.hexdigest(),
            )
        except Exception:
            await self.discard_path(temp_path)
            raise
        finally:
            await upload.close()

    async def promote(
        self,
        staged: StagedUpload,
        *,
        course_id: UUID,
        document_id: UUID,
    ) -> PromotedUpload:
        course_dir = self.upload_dir / str(course_id)
        await anyio.to_thread.run_sync(
            lambda: course_dir.mkdir(parents=True, exist_ok=True)
        )
        stored_name = f"{document_id}{staged.extension}"
        destination = course_dir / stored_name
        await anyio.to_thread.run_sync(os.replace, staged.path, destination)
        return PromotedUpload(path=destination, stored_name=stored_name)

    async def discard_path(self, path: Path) -> None:
        await anyio.to_thread.run_sync(lambda: path.unlink(missing_ok=True))

    async def stage_document_deletion(
        self,
        *,
        course_id: UUID,
        stored_name: str,
    ) -> tuple[Path, Path] | None:
        source = self.upload_dir / str(course_id) / stored_name
        if not await anyio.to_thread.run_sync(source.is_file):
            return None
        await anyio.to_thread.run_sync(
            lambda: self.trash_dir.mkdir(parents=True, exist_ok=True)
        )
        staged = self.trash_dir / f"{uuid4()}-{stored_name}"
        await anyio.to_thread.run_sync(os.replace, source, staged)
        return source, staged

    async def stage_course_deletion(self, course_id: UUID) -> tuple[Path, Path] | None:
        source = self.upload_dir / str(course_id)
        if not await anyio.to_thread.run_sync(source.is_dir):
            return None
        await anyio.to_thread.run_sync(
            lambda: self.trash_dir.mkdir(parents=True, exist_ok=True)
        )
        staged = self.trash_dir / f"course-{course_id}-{uuid4()}"
        await anyio.to_thread.run_sync(os.replace, source, staged)
        return source, staged

    async def restore_deletion(self, staged_deletion: tuple[Path, Path] | None) -> None:
        if staged_deletion is None:
            return
        source, staged = staged_deletion
        if not await anyio.to_thread.run_sync(staged.exists):
            return
        await anyio.to_thread.run_sync(
            lambda: source.parent.mkdir(parents=True, exist_ok=True)
        )
        await anyio.to_thread.run_sync(os.replace, staged, source)

    async def complete_deletion(self, staged_deletion: tuple[Path, Path] | None) -> None:
        if staged_deletion is None:
            return
        _, staged = staged_deletion
        if await anyio.to_thread.run_sync(staged.is_dir):
            await anyio.to_thread.run_sync(shutil.rmtree, staged)
        else:
            await self.discard_path(staged)

    async def remove_empty_course_dir(self, course_id: UUID) -> None:
        course_dir = self.upload_dir / str(course_id)
        if not await anyio.to_thread.run_sync(course_dir.is_dir):
            return
        try:
            await anyio.to_thread.run_sync(course_dir.rmdir)
        except OSError:
            return

    @staticmethod
    def _safe_original_name(filename: str | None) -> str:
        if not filename:
            raise InvalidInputError("A file name is required.")
        normalized = filename.replace("\\", "/")
        safe_name = PurePosixPath(normalized).name.strip()
        if not safe_name or safe_name in {".", ".."}:
            raise InvalidInputError("Invalid file name.")
        if len(safe_name) > 255:
            raise InvalidInputError("File name cannot exceed 255 characters.")
        return safe_name

    @staticmethod
    def _validate_content(path: Path, extension: str) -> None:
        if extension == ".pdf":
            with path.open("rb") as stream:
                if stream.read(5) != b"%PDF-":
                    raise UnsupportedFileTypeError("The file is not a valid PDF.")
            return

        if extension in {".docx", ".pptx"}:
            if not zipfile.is_zipfile(path):
                raise UnsupportedFileTypeError(
                    f"The file is not a valid {extension.removeprefix('.').upper()} container."
                )
            required_member = (
                "word/document.xml"
                if extension == ".docx"
                else "ppt/presentation.xml"
            )
            try:
                with zipfile.ZipFile(path) as archive:
                    names = set(archive.namelist())
            except (OSError, zipfile.BadZipFile) as error:
                raise UnsupportedFileTypeError("The Office file is damaged.") from error
            if "[Content_Types].xml" not in names or required_member not in names:
                raise UnsupportedFileTypeError(
                    f"The file content does not match its {extension} extension."
                )
            return

        decoder = codecs.getincrementaldecoder("utf-8-sig")(errors="strict")
        try:
            with path.open("rb") as stream:
                while chunk := stream.read(CHUNK_SIZE):
                    if b"\x00" in chunk:
                        raise UnsupportedFileTypeError(
                            "Text files cannot contain null bytes."
                        )
                    decoder.decode(chunk)
                decoder.decode(b"", final=True)
        except UnicodeDecodeError as error:
            raise UnsupportedFileTypeError(
                "Markdown and text files must use UTF-8 encoding."
            ) from error
