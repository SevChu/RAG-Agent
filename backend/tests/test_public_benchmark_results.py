from __future__ import annotations

import json
from pathlib import Path

from scripts.export_public_benchmark_results import validate_public_payload

_RESULTS = Path(__file__).resolve().parents[2] / "benchmarks" / "v1.1.0" / "results.json"


def test_public_benchmark_results_are_aggregate_only_and_versioned() -> None:
    payload = json.loads(_RESULTS.read_text(encoding="utf-8"))

    validate_public_payload(payload)
    assert payload["release_version"] == "1.1.0"
    assert set(payload["datasets"]) == {"beir-fiqa-2018", "ragtruth", "ragbench"}
    assert payload["publication_policy"] == {
        "aggregation_only": True,
        "contains_sample_text": False,
        "contains_row_level_predictions": False,
        "contains_local_paths": False,
        "contains_personal_or_workspace_data": False,
        "raw_datasets_redistributed": False,
        "artifact_hashes_are_identifiers_only": True,
    }


def test_public_benchmark_results_keep_reference_metrics_and_artifact_hashes() -> None:
    payload = json.loads(_RESULTS.read_text(encoding="utf-8"))
    datasets = payload["datasets"]

    assert (
        datasets["beir-fiqa-2018"]["methods"]["dense"]["metrics"]["recall@100"]
        == 0.7187787349824389
    )
    assert (
        datasets["ragtruth"]["methods"]["lexical_coverage"]["response_level"]["auroc"]
        == 0.7247703625733395
    )
    assert (
        datasets["ragbench"]["methods"]["lexical_dense_linear"]["continuous"]["completeness"][
            "spearman"
        ]
        == 0.3967062587518067
    )
    assert len(datasets["ragtruth"]["prediction_artifact_sha256"]) == 64
    assert len(datasets["ragbench"]["prediction_artifact_sha256"]) == 64
