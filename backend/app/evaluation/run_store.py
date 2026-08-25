from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class EvaluationRunStore:
    """Persist one immutable run identity and one atomic result per case."""

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir.resolve()
        self.results_dir = self.output_dir / "cases"
        self.state_path = self.output_dir / "run-state.json"

    def initialize(self, identity: dict[str, Any]) -> dict[str, Any]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.results_dir.mkdir(parents=True, exist_ok=True)
        if self.state_path.exists():
            stored = _read_json_object(self.state_path)
            stored_identity = stored.get("identity")
            if stored_identity != identity:
                raise ValueError(
                    "existing evaluation output belongs to a different dataset, "
                    "baseline, course or model"
                )
            return stored
        state = {
            "schema_version": "1.0",
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
            "identity": identity,
            "stopped_reason": None,
        }
        _write_json_atomic(self.state_path, state)
        return state

    def write_case_result(self, case_id: str, result: dict[str, Any]) -> None:
        _write_json_atomic(self.case_path(case_id), result)
        state = _read_json_object(self.state_path)
        state["updated_at"] = datetime.now(UTC).isoformat()
        _write_json_atomic(self.state_path, state)

    def set_stopped_reason(self, reason: str | None) -> None:
        state = _read_json_object(self.state_path)
        state["stopped_reason"] = reason
        state["updated_at"] = datetime.now(UTC).isoformat()
        _write_json_atomic(self.state_path, state)

    def result(self, case_id: str) -> dict[str, Any] | None:
        path = self.case_path(case_id)
        return _read_json_object(path) if path.exists() else None

    def results(self) -> list[dict[str, Any]]:
        return [
            _read_json_object(path)
            for path in sorted(self.results_dir.glob("W5-*.json"))
        ]

    def case_path(self, case_id: str) -> Path:
        if not case_id.startswith("W5-") or not case_id[3:].isdigit():
            raise ValueError("invalid evaluation case id")
        return self.results_dir / f"{case_id}.json"


def write_json_atomic(path: Path, payload: object) -> None:
    _write_json_atomic(path, payload)


def _read_json_object(path: Path) -> dict[str, Any]:
    payload: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected a JSON object in {path}")
    return dict(payload)


def _write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)
