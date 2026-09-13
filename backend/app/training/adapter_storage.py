from __future__ import annotations

import os
import stat
from pathlib import Path
from uuid import UUID, uuid4

from app.core.exceptions import InvalidInputError
from app.training.storage import DatasetStorage

MAX_MANIFEST_BYTES = 128 * 1024


class AdapterStorage:
    """Writer must hold the registry's SQLite write transaction; no client paths."""

    def __init__(self, root: Path) -> None:
        self.root = Path(os.path.abspath(root))

    def path(self, adapter_id: UUID) -> Path:
        path = self.root / (adapter_id.hex + ".json")
        DatasetStorage._check(path)
        if not path.resolve().is_relative_to(self.root.resolve()):
            raise InvalidInputError("产物文件超出允许目录。")
        return path

    def read(self, adapter_id: UUID) -> bytes:
        path = self.path(adapter_id)
        with path.open("rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise InvalidInputError("产物文件类型或链接状态不安全。")
            data = stream.read(MAX_MANIFEST_BYTES + 1)
        if len(data) > MAX_MANIFEST_BYTES:
            raise InvalidInputError("产物文件超出大小限制。")
        return data

    def promote(self, adapter_id: UUID, data: bytes) -> None:
        if len(data) > MAX_MANIFEST_BYTES:
            raise InvalidInputError("产物文件超出大小限制。")
        target = self.path(adapter_id)
        if target.exists():
            if self.read(adapter_id) != data:
                raise InvalidInputError("已有产物文件不匹配，需人工核对。")
            return
        self.root.mkdir(parents=True, exist_ok=True)
        stage = self.root / f".{adapter_id.hex}.{uuid4().hex}.tmp"
        DatasetStorage._check(stage)
        # A failed write/promotion remains visible to the bounded storage audit.
        with stage.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if stage.read_bytes() != data:
            raise InvalidInputError("临时产物校验失败。")
        DatasetStorage._check(target)
        os.rename(stage, target)
        if self.read(adapter_id) != data:
            raise InvalidInputError("产物提交后校验失败。")

    def inventory(self) -> tuple[list[UUID], int, int, bool]:
        DatasetStorage._check(self.root)
        if not self.root.exists():
            return [], 0, 0, False
        finals: list[UUID] = []
        staged = unknown = 0
        truncated = False
        with os.scandir(self.root) as entries:
            for index, entry in enumerate(entries):
                if index >= 5000:
                    truncated = True
                    break
                name = entry.name
                try:
                    value = UUID(hex=name[:-5])
                    if name != value.hex + ".json":
                        raise ValueError
                except ValueError:
                    if name.startswith(".") and name.endswith(".tmp"):
                        staged += 1
                    else:
                        unknown += 1
                else:
                    finals.append(value)
        return sorted(finals, key=str), staged, unknown, truncated
