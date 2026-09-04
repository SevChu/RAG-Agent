from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Iterable
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.evaluation.baseline_profiles import BaselineTask

DEFAULT_EXPERIMENT_REGISTRY_PATH = Path(__file__).with_name("experiment-registry.json")
TEST_SPLIT_POLICY = (
    "test is forbidden during optimization; train and validation are the only allowed splits"
)

ScalarValue = str | int | float | bool


class OptimizationSplit(StrEnum):
    TRAIN = "train"
    VALIDATION = "validation"


class ExperimentStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    REJECTED = "rejected"


class MetricDirection(StrEnum):
    MAXIMIZE = "maximize"
    MINIMIZE = "minimize"


class RevisionState(StrEnum):
    FROZEN = "frozen"
    PENDING_APPROVAL = "pending_approval"


class SliceDimension(StrEnum):
    DOMAIN = "domain"
    CLASS = "class"
    LENGTH = "length"
    EVIDENCE_COUNT = "evidence_count"
    ERROR_TYPE = "error_type"


class SliceClass(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"


STANDARD_SLICE_DIMENSIONS = frozenset(SliceDimension)


class ArtifactRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["dataset", "model", "code"]
    name: str = Field(min_length=1)
    revision: str | None = None
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    state: RevisionState

    @model_validator(mode="after")
    def validate_state(self) -> ArtifactRevision:
        if self.state == RevisionState.FROZEN and not self.revision:
            raise ValueError("frozen artifacts require an exact revision")
        if self.state == RevisionState.PENDING_APPROVAL and (
            self.revision is not None or self.sha256 is not None
        ):
            raise ValueError("pending artifacts cannot claim a revision or hash")
        return self


class ExperimentRevisions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    datasets: tuple[ArtifactRevision, ...] = Field(min_length=1)
    models: tuple[ArtifactRevision, ...] = ()
    code: ArtifactRevision

    @model_validator(mode="after")
    def validate_kinds(self) -> ExperimentRevisions:
        if any(item.kind != "dataset" for item in self.datasets):
            raise ValueError("dataset revisions must have kind=dataset")
        if any(item.kind != "model" for item in self.models):
            raise ValueError("model revisions must have kind=model")
        if self.code.kind != "code":
            raise ValueError("code revision must have kind=code")
        names = [item.name for item in (*self.datasets, *self.models, self.code)]
        if len(names) != len(set(names)):
            raise ValueError("artifact names must be unique within an experiment")
        return self

    @property
    def all_frozen(self) -> bool:
        return all(
            item.state == RevisionState.FROZEN
            for item in (*self.datasets, *self.models, self.code)
        )


class PrimaryVariable(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    baseline: ScalarValue
    candidate: ScalarValue

    @model_validator(mode="after")
    def validate_changed_value(self) -> PrimaryVariable:
        if self.baseline == self.candidate:
            raise ValueError("the primary variable must change exactly one declared value")
        return self


class PrimaryMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-z][a-z0-9@._-]*$")
    direction: MetricDirection
    minimum_improvement: float = Field(default=0.0, ge=0)


class GuardrailMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-z][a-z0-9@._-]*$")
    direction: MetricDirection
    maximum_regression: float = Field(default=0.0, ge=0)


class CandidateExperiment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experiment_id: str = Field(pattern=r"^w6-d[2-4]-[a-z0-9-]+$")
    status: ExperimentStatus
    task: BaselineTask
    hypothesis: str = Field(min_length=20)
    primary_variable: PrimaryVariable
    revisions: ExperimentRevisions
    random_seeds: tuple[int, ...] = Field(min_length=1)
    optimization_splits: tuple[OptimizationSplit, ...] = Field(min_length=1)
    primary_metric: PrimaryMetric
    guardrail_metrics: tuple[GuardrailMetric, ...] = Field(min_length=1)
    slice_dimensions: tuple[SliceDimension, ...] = Field(min_length=5, max_length=5)
    test_access: Literal["forbidden"] = "forbidden"
    notes: tuple[str, ...] = ()

    @field_validator("random_seeds")
    @classmethod
    def validate_unique_seeds(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if len(value) != len(set(value)):
            raise ValueError("random seeds must be unique")
        return value

    @field_validator("optimization_splits")
    @classmethod
    def validate_unique_splits(
        cls, value: tuple[OptimizationSplit, ...]
    ) -> tuple[OptimizationSplit, ...]:
        if len(value) != len(set(value)):
            raise ValueError("optimization splits must be unique")
        return value

    @model_validator(mode="after")
    def validate_execution_contract(self) -> CandidateExperiment:
        if set(self.slice_dimensions) != STANDARD_SLICE_DIMENSIONS:
            raise ValueError("experiments must declare all five standard slice dimensions")
        metric_names = [self.primary_metric.name]
        metric_names.extend(metric.name for metric in self.guardrail_metrics)
        if len(metric_names) != len(set(metric_names)):
            raise ValueError("primary and guardrail metric names must be unique")
        executable = {
            ExperimentStatus.READY,
            ExperimentStatus.RUNNING,
            ExperimentStatus.COMPLETED,
        }
        if self.status in executable and not self.revisions.all_frozen:
            raise ValueError("executable experiments require frozen artifact revisions")
        return self


class ExperimentRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    target_release_version: Literal["1.2.0"]
    test_policy: Literal[
        "test is forbidden during optimization; train and validation are the only allowed splits"
    ]
    experiments: tuple[CandidateExperiment, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> ExperimentRegistry:
        ids = [experiment.experiment_id for experiment in self.experiments]
        if len(ids) != len(set(ids)):
            raise ValueError("experiment ids must be unique")
        return self

    def get(self, experiment_id: str) -> CandidateExperiment:
        try:
            return next(
                experiment
                for experiment in self.experiments
                if experiment.experiment_id == experiment_id
            )
        except StopIteration as exc:
            raise KeyError(f"unknown experiment: {experiment_id}") from exc


class SliceSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    short_max_chars: int = Field(default=256, ge=1)
    medium_max_chars: int = Field(default=1024, ge=2)

    @model_validator(mode="after")
    def validate_thresholds(self) -> SliceSpec:
        if self.medium_max_chars <= self.short_max_chars:
            raise ValueError("medium length threshold must exceed the short threshold")
        return self


class SliceObservation(BaseModel):
    """Privacy-preserving numeric observation; intentionally stores no sample id or text."""

    model_config = ConfigDict(extra="forbid")

    split: OptimizationSplit
    domain: str = Field(min_length=1)
    class_label: SliceClass
    text_length_chars: int = Field(ge=0)
    evidence_count: int = Field(ge=0)
    error_types: tuple[str, ...] = ()
    metrics: dict[str, float] = Field(min_length=1)

    @field_validator("domain")
    @classmethod
    def normalize_domain(cls, value: str) -> str:
        return _slug(value)

    @field_validator("error_types")
    @classmethod
    def normalize_error_types(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_slug(item) for item in value)
        if len(normalized) != len(set(normalized)):
            raise ValueError("error types must be unique")
        return normalized

    @field_validator("metrics")
    @classmethod
    def validate_metrics(cls, value: dict[str, float]) -> dict[str, float]:
        if any(not re.fullmatch(r"[a-z][a-z0-9@._-]*", name) for name in value):
            raise ValueError("metric names must be normalized slugs")
        if any(not math.isfinite(metric) for metric in value.values()):
            raise ValueError("slice metrics must be finite")
        return value


class SliceKey(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dimension: SliceDimension
    value: str


class SliceAggregate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dimension: SliceDimension
    value: str
    metric: str
    count: int = Field(ge=1)
    mean: float
    minimum: float
    maximum: float


def require_optimization_split(split: str) -> OptimizationSplit:
    try:
        return OptimizationSplit(split)
    except ValueError as exc:
        if split == "test":
            raise ValueError(
                "test split access is forbidden during optimization "
                "and requires later user approval"
            ) from exc
        raise ValueError(f"unsupported optimization split: {split}") from exc


def slice_memberships(
    observation: SliceObservation, spec: SliceSpec | None = None
) -> tuple[SliceKey, ...]:
    resolved_spec = spec or SliceSpec()
    if observation.text_length_chars <= resolved_spec.short_max_chars:
        length_bucket = "short"
    elif observation.text_length_chars <= resolved_spec.medium_max_chars:
        length_bucket = "medium"
    else:
        length_bucket = "long"

    if observation.evidence_count == 0:
        evidence_bucket = "none"
    elif observation.evidence_count == 1:
        evidence_bucket = "single"
    else:
        evidence_bucket = "multiple"

    keys = [
        SliceKey(dimension=SliceDimension.DOMAIN, value=observation.domain),
        SliceKey(dimension=SliceDimension.CLASS, value=observation.class_label.value),
        SliceKey(dimension=SliceDimension.LENGTH, value=length_bucket),
        SliceKey(dimension=SliceDimension.EVIDENCE_COUNT, value=evidence_bucket),
    ]
    error_types = observation.error_types or ("none",)
    keys.extend(
        SliceKey(dimension=SliceDimension.ERROR_TYPE, value=error_type)
        for error_type in error_types
    )
    return tuple(keys)


def aggregate_slices(
    observations: Iterable[SliceObservation], spec: SliceSpec | None = None
) -> tuple[SliceAggregate, ...]:
    grouped: defaultdict[tuple[SliceDimension, str, str], list[float]] = defaultdict(list)
    for observation in observations:
        for key in slice_memberships(observation, spec):
            for metric_name, metric_value in observation.metrics.items():
                grouped[(key.dimension, key.value, metric_name)].append(metric_value)

    aggregates = (
        SliceAggregate(
            dimension=dimension,
            value=value,
            metric=metric,
            count=len(values),
            mean=sum(values) / len(values),
            minimum=min(values),
            maximum=max(values),
        )
        for (dimension, value, metric), values in grouped.items()
    )
    return tuple(
        sorted(
            aggregates,
            key=lambda item: (item.dimension.value, item.value, item.metric),
        )
    )


def load_experiment_registry(
    path: Path = DEFAULT_EXPERIMENT_REGISTRY_PATH,
) -> ExperimentRegistry:
    return ExperimentRegistry.model_validate_json(path.read_text(encoding="utf-8"))


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    if not normalized:
        raise ValueError("slice labels cannot be blank")
    return normalized
