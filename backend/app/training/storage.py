from __future__ import annotations

import os
import stat
from pathlib import Path
from uuid import UUID

from app.core.exceptions import InvalidInputError
from app.training.validation import MAX_BYTES


class DatasetStorage:
    """UUID-only local store. Does not accept client filenames or server paths."""

    def __init__(self, root: Path) -> None:
        self.root = Path(os.path.abspath(root))

    @staticmethod
    def _check(path: Path) -> None:
        for part in reversed((path, *path.parents)):
            try:
                info = part.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(info.st_mode) or (
                getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
            ):
                raise InvalidInputError("训练目录不允许符号链接或重解析点。")

    def path(self, revision_id: UUID) -> Path:
        path = self.root / (revision_id.hex + ".jsonl")
        self._check(path)
        if not path.resolve().is_relative_to(self.root.resolve()):
            raise InvalidInputError("训练文件超出允许目录。")
        return path

    def write(self, revision_id: UUID, data: bytes) -> None:
        if len(data) > MAX_BYTES:
            raise InvalidInputError("训练文件超出大小限制。")
        target = self.path(revision_id)
        self.root.mkdir(parents=True, exist_ok=True)
        self._check(target)
        # Exclusive creation never replaces a revision. Only the DB commit makes it visible.
        try:
            with target.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as error:
            raise InvalidInputError("无法保存训练文件，请检查存储空间和目录权限。") from error

    def read(self, revision_id: UUID) -> bytes:
        target = self.path(revision_id)
        try:
            with target.open("rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise InvalidInputError("训练文件类型或链接状态不安全。")
                result = stream.read(MAX_BYTES + 1)
        except OSError as error:
            raise InvalidInputError("训练文件缺失或无法读取。") from error
        if len(result) > MAX_BYTES:
            raise InvalidInputError("训练文件超出大小限制。")
        return result
