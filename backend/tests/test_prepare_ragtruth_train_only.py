from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.evaluation import RagTruthAdapter, RagTruthManifest, hash_file
from scripts.prepare_ragtruth_train_only import derive_train_only


def _write_parent_fixture(root: Path) -> RagTruthManifest:
    raw = root / "raw"
    raw.mkdir(parents=True)
    response_path = raw / "response.jsonl"
    source_path = raw / "source_info.jsonl"
    response_path.write_text(
        json.dumps(
            {
                "id": "train-response",
                "source_id": "train-source",
                "model": "fixture-model",
                "split": "train",
                "quality": "good",
                "response": "supported",
                "labels": [],
            }
        )
        + "\n"
        + '{"id":"excluded","source_id":"excluded-source","split":"test",BROKEN\n',
        encoding="utf-8",
    )
    source_path.write_text(
        json.dumps(
            {
                "source_id": "train-source",
                "task_type": "QA",
                "source": "fixture",
                "source_info": "supported context",
            }
        )
        + "\n"
        + '{"source_id":"excluded-source",BROKEN\n',
        encoding="utf-8",
    )
    return RagTruthManifest.model_validate(
        {
            "schema_version": "1.0",
            "dataset_id": "ragtruth",
            "lifecycle": "frozen",
            "source_url": "https://example.test/ragtruth",
            "source_revision": "a" * 40,
            "files": {
                "response.jsonl": hash_file(response_path),
                "source_info.jsonl": hash_file(source_path),
            },
            "file_bytes": {
                "response.jsonl": response_path.stat().st_size,
                "source_info.jsonl": source_path.stat().st_size,
            },
            "split_counts": {
                "all": {
                    "sources": 2,
                    "responses": 2,
                    "hallucinated_responses": 0,
                    "spans": 0,
                },
                "train": {
                    "sources": 1,
                    "responses": 1,
                    "hallucinated_responses": 0,
                    "spans": 0,
                },
                "test": {
                    "sources": 1,
                    "responses": 1,
                    "hallucinated_responses": 0,
                    "spans": 0,
                },
            },
        }
    )


def test_derivation_never_decodes_excluded_rows(tmp_path: Path) -> None:
    parent = _write_parent_fixture(tmp_path)
    output = tmp_path / "derived" / "train-only"

    payload = derive_train_only(tmp_path / "raw", output, parent, Path(__file__))

    assert RagTruthAdapter(output).validate(("train",))["train"] == {
        "sources": 1,
        "responses": 1,
        "hallucinated_responses": 0,
        "spans": 0,
    }
    assert payload["boundary"] == {
        "selected_split": "train",
        "excluded_rows_decoded": False,
        "sample_payloads_recorded": False,
    }
    assert "excluded" not in (output / "response.jsonl").read_text(encoding="utf-8")
    assert "excluded" not in (output / "source_info.jsonl").read_text(encoding="utf-8")


def test_derivation_refuses_changed_parent_and_existing_output(tmp_path: Path) -> None:
    parent = _write_parent_fixture(tmp_path)
    response_path = tmp_path / "raw" / "response.jsonl"
    response_path.write_text(response_path.read_text(encoding="utf-8") + " ", encoding="utf-8")

    with pytest.raises(ValueError, match="differs from its frozen hash"):
        derive_train_only(tmp_path / "raw", tmp_path / "derived", parent, Path(__file__))

    parent = _write_parent_fixture(tmp_path / "fresh")
    output = tmp_path / "fresh" / "derived"
    derive_train_only(tmp_path / "fresh" / "raw", output, parent, Path(__file__))
    with pytest.raises(FileExistsError, match="refusing to replace"):
        derive_train_only(tmp_path / "fresh" / "raw", output, parent, Path(__file__))
