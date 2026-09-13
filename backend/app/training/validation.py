from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from typing import Any

from pydantic import ValidationError

from app.training.schemas import (
    DatasetManifest,
    Issue,
    RerankerSample,
    ScorerSample,
    Split,
    SplitSummary,
    ValidationReport,
)

MAX_BYTES = 8 * 1024 * 1024
MAX_ROWS = 5000
MAX_LINE_BYTES = 64 * 1024
MAX_COMPARISONS = 200000
MAX_SHINGLES = 1000000
PII = re.compile(
    r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?<!\d)1[3-9]\d{9}(?!\d)|"
    r"(?i:sk-[a-z0-9_-]{16,}|(?:api[_ -]?key|password|secret)\s*[:=]\s*\S{6,})"
)


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def strict_json(data: str) -> Any:
    return json.loads(data, object_pairs_hook=_object)


def parse_manifest(raw: str) -> DatasetManifest:
    if len(raw.encode("utf-8")) > 16000:
        raise ValueError("manifest too large")
    parsed = DatasetManifest.model_validate(strict_json(raw))
    canonical(parsed.model_dump(mode="json"))  # Reject escaped unpaired Unicode surrogates.
    return parsed


def has_sensitive_text(text: str) -> bool:
    return PII.search(text) is not None


def normalized(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKC", text).casefold() if c.isalnum())


def validate_jsonl(data: bytes, manifest: DatasetManifest) -> ValidationReport:
    issues: list[Issue] = []
    issue_count = 0
    valid = True
    counts: dict[Split, int] = {"train": 0, "validation": 0}
    hashes = {split: hashlib.sha256() for split in counts}
    sample_count = 0

    def issue(
        code: str, line: int | None = None, related: int | None = None, *, structural: bool = False
    ) -> None:
        nonlocal issue_count, valid
        issue_count += 1
        if structural:
            valid = False
        if len(issues) < 50:
            issues.append(Issue(code=code, line=line, related_line=related))

    def report() -> ValidationReport:
        return ValidationReport(
            valid=valid,
            approvable=valid and issue_count == 0,
            content_sha256=digest(data),
            byte_count=len(data),
            sample_count=sample_count,
            splits={
                split: SplitSummary(count=counts[split], sha256=hashes[split].hexdigest())
                for split in counts
            },
            issues=tuple(issues),
            issue_count=issue_count,
        )

    if len(data) > MAX_BYTES:
        issue("FILE_TOO_LARGE", structural=True)
        return report()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        issue("INVALID_UTF8", structural=True)
        return report()
    lines = text.splitlines()
    if len(lines) > MAX_ROWS:
        issue("TOO_MANY_ROWS", structural=True)
        return report()
    if not manifest.training_allowed or normalized(manifest.license_id) in {
        "unknown",
        "unspecified",
        "none",
        "na",
        "未知",
        "不明",
    }:
        issue("LICENSE_NOT_CLEARED")
    if manifest.pii_status == "pending":
        issue("PII_REVIEW_PENDING")
    if has_sensitive_text(canonical(manifest.model_dump(mode="json")).decode()):
        issue("METADATA_SENSITIVE_PATTERN")
    identities: dict[str, int] = {}
    origins: dict[tuple[str, str], tuple[Split, int]] = {}
    contents: dict[str, int] = {}
    fingerprints: dict[int, tuple[Split, set[str]]] = {}
    inverted: dict[str, list[int]] = defaultdict(list)
    comparisons = 0
    shingle_count = 0
    for number, line in enumerate(lines, 1):
        if len(line.encode("utf-8")) > MAX_LINE_BYTES:
            issue("LINE_TOO_LARGE", number, structural=True)
            continue
        try:
            value = strict_json(line)
            if not isinstance(value, dict):
                raise ValueError("object required")
            # No split aliases, implicit split, or nested test records are accepted.
            if value.get("split") not in ("train", "validation"):
                issue("SPLIT_NOT_ALLOWED", number, structural=True)
                continue
            sample = (
                ScorerSample.model_validate(value)
                if manifest.target == "scorer"
                else RerankerSample.model_validate(value)
            )
        except (ValueError, ValidationError, RecursionError):
            issue("INVALID_SAMPLE_SCHEMA", number, structural=True)
            continue
        try:
            encoded_sample = canonical(sample.model_dump(mode="json"))
        except UnicodeError:
            issue("INVALID_UNICODE", number, structural=True)
            continue
        sample_count += 1
        counts[sample.split] += 1
        hashes[sample.split].update(encoded_sample + b"\n")
        if has_sensitive_text(encoded_sample.decode("utf-8")):
            issue("SENSITIVE_PATTERN", number)
        if sample.id in identities:
            issue("DUPLICATE_ID", number, identities[sample.id])
        identities[sample.id] = number
        for kind, origin in (("source", sample.source_id), ("group", sample.group_id)):
            origin_key = (kind, normalized(origin))
            if not origin_key[1]:
                issue("INVALID_ORIGIN", number, structural=True)
            if origin_key in origins and origins[origin_key][0] != sample.split:
                issue("CROSS_SPLIT_" + kind.upper(), number, origins[origin_key][1])
            origins.setdefault(origin_key, (sample.split, number))
        inputs = (
            [sample.query, sample.response, *sample.evidence]
            if isinstance(sample, ScorerSample)
            else [sample.query, sample.document]
        )
        norm = normalized(" ".join(inputs))
        if not norm:
            issue("EMPTY_NORMALIZED_CONTENT", number, structural=True)
        key = digest(norm.encode())
        if key in contents:
            issue("DUPLICATE_CONTENT", number, contents[key])
        contents.setdefault(key, number)
        shingles = {norm[i : i + 5] for i in range(max(1, len(norm) - 4))}
        shingle_count += len(shingles)
        if shingle_count > MAX_SHINGLES:
            issue("DEDUP_WORK_LIMIT", number, structural=True)
            break
        candidates: set[int] = set()
        for shingle in shingles:
            candidates.update(inverted[shingle])
        for previous in sorted(candidates):
            other_split, other = fingerprints[previous]
            if other_split == sample.split:
                continue
            comparisons += 1
            if comparisons > MAX_COMPARISONS:
                issue("DEDUP_WORK_LIMIT", number, structural=True)
                return report()
            union = len(shingles | other)
            if union and len(shingles & other) / union >= 0.85:
                issue("CROSS_SPLIT_NEAR_DUPLICATE", number, previous)
                break
        fingerprints[number] = (sample.split, shingles)
        for shingle in shingles:
            inverted[shingle].append(number)
    for split, count in counts.items():
        if count == 0:
            issue("EMPTY_" + split.upper(), structural=True)
    return report()
