from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile, ZipInfo

from app.ingestion.errors import DocumentReadError, InvalidDocumentFormatError

MAX_XML_MEMBER_BYTES = 32 * 1024 * 1024


class OoxmlPackage:
    """Small, bounded OOXML reader shared by the DOCX and PPTX parsers."""

    def __init__(self, path: Path, *, required_members: Iterable[str]) -> None:
        self._path = path
        self._required_members = frozenset(required_members)
        self._archive: ZipFile | None = None

    def __enter__(self) -> OoxmlPackage:
        try:
            archive = ZipFile(self._path)
        except BadZipFile as exc:
            raise InvalidDocumentFormatError(
                f"{self._path.name} is not a readable OOXML package."
            ) from exc
        except OSError as exc:
            raise DocumentReadError(
                f"Unable to read document: {self._path.name}."
            ) from exc

        names = frozenset(archive.namelist())
        missing = self._required_members - names
        if missing:
            archive.close()
            missing_names = ", ".join(sorted(missing))
            raise InvalidDocumentFormatError(
                f"{self._path.name} is missing required OOXML members: {missing_names}."
            )
        self._archive = archive
        return self

    def __exit__(self, *_args: object) -> None:
        if self._archive is not None:
            self._archive.close()
            self._archive = None

    @property
    def names(self) -> frozenset[str]:
        return frozenset(self._require_archive().namelist())

    def read_xml(self, member_name: str) -> ElementTree.Element:
        archive = self._require_archive()
        try:
            member = archive.getinfo(member_name)
        except KeyError as exc:
            raise InvalidDocumentFormatError(
                f"{self._path.name} is missing OOXML member {member_name}."
            ) from exc
        self._validate_xml_member(member)
        try:
            with archive.open(member) as stream:
                return ElementTree.parse(stream).getroot()
        except (BadZipFile, ElementTree.ParseError, OSError, RuntimeError) as exc:
            raise InvalidDocumentFormatError(
                f"{self._path.name} contains invalid XML in {member_name}."
            ) from exc

    def _validate_xml_member(self, member: ZipInfo) -> None:
        if member.flag_bits & 0x1:
            raise InvalidDocumentFormatError(
                f"{self._path.name} contains an encrypted OOXML member."
            )
        if member.file_size > MAX_XML_MEMBER_BYTES:
            raise InvalidDocumentFormatError(
                f"{self._path.name} contains an oversized XML member."
            )

    def _require_archive(self) -> ZipFile:
        if self._archive is None:
            raise DocumentReadError("The OOXML package is not open.")
        return self._archive


def resolve_ooxml_target(source_member: str, target: str) -> str:
    """Resolve an OOXML relationship target without allowing package traversal."""

    source_directory = PurePosixPath(source_member).parent
    target_path = PurePosixPath(target)
    resolved = (
        target_path.as_posix().lstrip("/")
        if target_path.is_absolute()
        else source_directory.joinpath(target_path).as_posix()
    )
    normalized_parts: list[str] = []
    for part in PurePosixPath(resolved).parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not normalized_parts:
                raise InvalidDocumentFormatError(
                    "An OOXML relationship points outside the package."
                )
            normalized_parts.pop()
            continue
        normalized_parts.append(part)
    return "/".join(normalized_parts)


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
