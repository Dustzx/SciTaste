"""Content-bound projection of measured Evidence into writing contracts."""

from __future__ import annotations

import hashlib
import json
import math
import os
import statistics
import tempfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scitaste.evidence.interpretation import InterpretationReview
from scitaste.executor.base import ExecutionResult
from scitaste.executor.native_store import NativeExecutionRecord
from scitaste.project.models import content_sha256
from scitaste.state.research_state import EvidenceItem, ResearchState, ScientificClaim

_T = TypeVar("_T")


class WritingEvidenceProjection(BaseModel):
    """One verified measured result that may be cited by Communication."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    project_id: str = Field(min_length=1)
    source_state_locator: str = Field(min_length=1)
    source_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_decision_id: str = Field(min_length=1)
    source_action_id: str = Field(min_length=1)
    execution_record_locator: str = Field(min_length=1)
    execution_record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    metrics_artifact_locator: str = Field(min_length=1)
    metrics_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    result_basis: Literal["sandbox-measured-replicates"]
    result_id: str = Field(min_length=1)
    experiment_id: str = Field(min_length=1)
    claim: ScientificClaim
    evidence: EvidenceItem
    relation: Literal["supports"]
    observation: str = Field(min_length=1)
    metrics: dict[str, float] = Field(min_length=1)
    primary_metric: str = Field(min_length=1)
    primary_value: float
    replicate_ids: list[str] = Field(min_length=2)
    primary_values: list[float] = Field(min_length=2)
    primary_dispersion: float = Field(ge=0.0)
    reproducible: Literal[True]
    stability: float = Field(ge=0.0, le=1.0)
    statistical_uncertainty: float = Field(ge=0.0, le=1.0)
    metric_derivation: Literal["arithmetic-mean-of-validated-replicates"]
    record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("source_state_locator", "execution_record_locator", "metrics_artifact_locator")
    @classmethod
    def locators_are_normalized(cls, value: str) -> str:
        _validate_locator(value)
        return value

    @field_validator("metrics")
    @classmethod
    def metrics_are_finite(cls, value: dict[str, float]) -> dict[str, float]:
        if any(not name or not math.isfinite(metric) for name, metric in value.items()):
            raise ValueError("writing projection metrics must be named finite values")
        return value

    @field_validator("primary_value", "primary_dispersion")
    @classmethod
    def scalar_measurements_are_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("writing projection measurements must be finite")
        return value

    @field_validator("primary_values")
    @classmethod
    def replicate_values_are_finite(cls, value: list[float]) -> list[float]:
        if any(not math.isfinite(item) for item in value):
            raise ValueError("writing projection replicates must be finite")
        return value

    @model_validator(mode="after")
    def bindings_are_consistent(self) -> WritingEvidenceProjection:
        if len(self.replicate_ids) != len(set(self.replicate_ids)):
            raise ValueError("writing projection replicate IDs must be unique")
        if len(self.replicate_ids) != len(self.primary_values):
            raise ValueError("writing projection replicate IDs and values must align")
        if self.primary_metric not in self.metrics:
            raise ValueError("writing projection omits its primary metric")
        if not _close(self.primary_value, self.metrics[self.primary_metric]):
            raise ValueError("writing projection primary value does not match its metrics")
        if not _close(self.primary_value, statistics.fmean(self.primary_values)):
            raise ValueError("writing projection primary value is not the replicate mean")
        if not _close(self.primary_dispersion, statistics.pstdev(self.primary_values)):
            raise ValueError("writing projection dispersion does not match its replicates")
        if self.evidence.experiment_id != self.experiment_id:
            raise ValueError("writing projection evidence belongs to another experiment")
        if self.evidence.evidence_id not in self.claim.supporting_evidence_ids:
            raise ValueError("writing projection claim does not cite its evidence")
        if self.claim.claim_id not in self.evidence.supports_claim_ids:
            raise ValueError("writing projection evidence does not support its claim")
        if self.evidence.observation != self.observation:
            raise ValueError("writing projection observation does not match its evidence")
        if self.claim.status not in {"supported", "partially_supported"}:
            raise ValueError("writing projection cannot promote an unsupported claim")
        expected = content_sha256(self.model_dump(mode="json", exclude={"record_sha256"}))
        if self.record_sha256 != expected:
            raise ValueError("writing evidence projection hash mismatch")
        return self


def build_writing_evidence_projection(
    *,
    state_path: str | Path,
    run_root: str | Path,
    expected_claim_id: str,
    expected_experiment_id: str,
) -> WritingEvidenceProjection:
    """Verify and project one native measured result from canonical state."""

    root = Path(run_root).resolve(strict=True)
    state_file = _owned_path(root, Path(state_path))
    state = ResearchState.model_validate_json(state_file.read_text(encoding="utf-8"))
    state_locator = state_file.relative_to(root).as_posix()

    matches = []
    for decision in state.decision_history:
        outcome = decision.actual_outcome
        data = outcome.get("data") if isinstance(outcome, dict) else None
        if (
            isinstance(data, dict)
            and data.get("result_basis") == "sandbox-measured-replicates"
            and data.get("experiment_id") == expected_experiment_id
        ):
            matches.append((decision, ExecutionResult.model_validate(outcome)))
    if len(matches) != 1:
        raise ValueError("writing requires exactly one matching sandbox-measured result")
    decision, execution = matches[0]
    data = execution.data
    if execution.status.value != "SUCCEEDED" or execution.executor != "scitaste-native":
        raise ValueError("writing cannot consume a non-successful native measurement")
    if decision.executor_result_id != execution.result_id:
        raise ValueError("writing measurement result is not bound to its decision")
    if decision.selected_action.parameters.get("experiment_id") != expected_experiment_id:
        raise ValueError("writing measurement action targets another experiment")

    record_locator = _required_string(data, "execution_record")
    record_digest = _required_string(data, "execution_record_sha256")
    record_path = _owned_locator(root, record_locator)
    record = NativeExecutionRecord.model_validate_json(record_path.read_text(encoding="utf-8"))
    if record.record_sha256 != record_digest:
        raise ValueError("writing measurement execution record hash mismatch")
    if record.action != decision.selected_action:
        raise ValueError("writing measurement execution record action mismatch")
    expected_execution = record.result.model_copy(
        update={
            "data": {
                **record.result.data,
                "execution_record": record_locator,
                "execution_record_sha256": record_digest,
                "execution_sequence": record.sequence,
            }
        }
    )
    if expected_execution != execution:
        raise ValueError("writing measurement differs from its native execution record")

    metrics_locator = _required_string(data, "metrics_artifact")
    if metrics_locator not in record.artifact_sha256:
        raise ValueError("writing measurement metric artifact is not execution-bound")
    metrics_path = _owned_locator(root, metrics_locator)
    metrics_digest = _file_sha256(metrics_path)
    if metrics_digest != record.artifact_sha256[metrics_locator]:
        raise ValueError("writing measurement metric artifact hash mismatch")
    try:
        metric_record = json.loads(metrics_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("writing measurement metric artifact is invalid") from exc
    if not isinstance(metric_record, dict):
        raise ValueError("writing measurement metric artifact must be a mapping")

    metrics = _numeric_mapping(data.get("metrics"), name="metrics")
    primary_metric = _required_string(data, "primary_metric")
    primary_value = _finite_number(data.get("primary_value"), name="primary_value")
    replicate_ids = _string_list(data.get("replicate_ids"), name="replicate_ids")
    primary_values = _number_list(data.get("primary_values"), name="primary_values")
    primary_dispersion = _finite_number(data.get("primary_dispersion"), name="primary_dispersion")
    stability = _finite_number(data.get("stability"), name="stability")
    uncertainty = _finite_number(
        data.get("statistical_uncertainty"), name="statistical_uncertainty"
    )
    if data.get("reproducible") is not True:
        raise ValueError("writing measurement is not reproducible")
    if data.get("metric_assessment") != "supports" or data.get("relation") != "supports":
        raise ValueError("writing measurement does not support the expected claim")
    if data.get("metric_derivation") != "arithmetic-mean-of-validated-replicates":
        raise ValueError("writing measurement has an unsupported metric derivation")
    _verify_metric_artifact(
        metric_record,
        experiment_id=expected_experiment_id,
        metrics=metrics,
        primary_metric=primary_metric,
        replicate_ids=replicate_ids,
        primary_values=primary_values,
        primary_dispersion=primary_dispersion,
    )

    reviews = [
        InterpretationReview.model_validate(item)
        for item in state.interpretation_history
        if isinstance(item, dict)
        and isinstance(item.get("result"), dict)
        and item["result"].get("result_id") == execution.result_id
    ]
    if len(reviews) != 1:
        raise ValueError("writing measurement requires one canonical interpretation review")
    review = reviews[0]
    if (
        review.result.experiment_id != expected_experiment_id
        or review.claim_assessment.claim_id != expected_claim_id
        or review.claim_assessment.disposition.value != "support"
        or review.result.metrics != metrics
        or review.observation.statement != execution.observations[0]
    ):
        raise ValueError("writing measurement conflicts with its interpretation review")

    evidence_id = f"evidence-{execution.result_id}-{expected_claim_id}"
    evidence = _exactly_one(
        state.evidence_graph.items,
        lambda item: item.evidence_id == evidence_id,
        "writing measurement evidence",
    )
    expected_evidence = EvidenceItem.model_validate(review.to_evidence_item().model_dump())
    if evidence != expected_evidence:
        raise ValueError("writing measurement evidence differs from its interpretation")
    claim = _exactly_one(
        state.claims,
        lambda item: item.claim_id == expected_claim_id,
        "writing measurement claim",
    )

    payload = {
        "schema_version": "1.0",
        "project_id": state.project_id,
        "source_state_locator": state_locator,
        "source_state_sha256": _file_sha256(state_file),
        "source_decision_id": decision.decision_id,
        "source_action_id": decision.selected_action.action_id,
        "execution_record_locator": record_locator,
        "execution_record_sha256": record_digest,
        "metrics_artifact_locator": metrics_locator,
        "metrics_artifact_sha256": metrics_digest,
        "result_basis": "sandbox-measured-replicates",
        "result_id": execution.result_id,
        "experiment_id": expected_experiment_id,
        "claim": claim.model_dump(mode="json"),
        "evidence": evidence.model_dump(mode="json"),
        "relation": "supports",
        "observation": review.observation.statement,
        "metrics": metrics,
        "primary_metric": primary_metric,
        "primary_value": primary_value,
        "replicate_ids": replicate_ids,
        "primary_values": primary_values,
        "primary_dispersion": primary_dispersion,
        "reproducible": True,
        "stability": stability,
        "statistical_uncertainty": uncertainty,
        "metric_derivation": "arithmetic-mean-of-validated-replicates",
    }
    return WritingEvidenceProjection(**payload, record_sha256=content_sha256(payload))


def write_writing_evidence_projection(
    projection: WritingEvidenceProjection,
    path: str | Path,
) -> Path:
    """Atomically materialize the projection beside the Communication draft."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(projection.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(rendered)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return target


def _verify_metric_artifact(
    record: dict[str, object],
    *,
    experiment_id: str,
    metrics: dict[str, float],
    primary_metric: str,
    replicate_ids: list[str],
    primary_values: list[float],
    primary_dispersion: float,
) -> None:
    if record.get("schema_version") != "1.0" or record.get("experiment_id") != experiment_id:
        raise ValueError("writing measurement metric artifact identity mismatch")
    if _numeric_mapping(record.get("metrics"), name="artifact metrics") != metrics:
        raise ValueError("writing measurement metrics differ from their artifact")
    raw = record.get("raw_measurements")
    if not isinstance(raw, list) or len(raw) != len(replicate_ids):
        raise ValueError("writing measurement artifact has invalid replicate rows")
    artifact_ids: list[str] = []
    artifact_values: list[float] = []
    for row in raw:
        if not isinstance(row, dict):
            raise ValueError("writing measurement artifact has invalid replicate rows")
        identifier = row.get("replicate_id")
        row_metrics = row.get("metrics")
        if not isinstance(identifier, str) or not isinstance(row_metrics, dict):
            raise ValueError("writing measurement artifact has invalid replicate rows")
        artifact_ids.append(identifier)
        artifact_values.append(
            _finite_number(row_metrics.get(primary_metric), name="replicate primary metric")
        )
    if artifact_ids != replicate_ids or artifact_values != primary_values:
        raise ValueError("writing measurement replicates differ from their artifact")
    if not _close(statistics.fmean(artifact_values), metrics[primary_metric]):
        raise ValueError("writing measurement artifact mean mismatch")
    if not _close(statistics.pstdev(artifact_values), primary_dispersion):
        raise ValueError("writing measurement artifact dispersion mismatch")


def _owned_path(root: Path, path: Path) -> Path:
    resolved = path.resolve(strict=True)
    try:
        locator = resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError("writing projection source state escapes its run") from exc
    return _owned_locator(root, locator)


def _owned_locator(root: Path, locator: str) -> Path:
    _validate_locator(locator)
    current = root
    for part in PurePosixPath(locator).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("writing projection locator contains a symlink")
    if not current.is_file():
        raise ValueError("writing projection locator is not a regular file")
    resolved = current.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:  # pragma: no cover - guarded by component checks
        raise ValueError("writing projection locator escapes its run") from exc
    return resolved


def _validate_locator(value: str) -> None:
    path = PurePosixPath(value)
    if (
        "\\" in value
        or "//" in value
        or path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("writing projection locators must be normalized relative paths")


def _required_string(data: dict[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"writing measurement is missing {key}")
    return value


def _finite_number(value: object, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"writing measurement {name} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"writing measurement {name} must be finite")
    return number


def _number_list(value: object, *, name: str) -> list[float]:
    if not isinstance(value, list):
        raise ValueError(f"writing measurement {name} must be a list")
    return [_finite_number(item, name=name) for item in value]


def _string_list(value: object, *, name: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"writing measurement {name} must be a string list")
    return list(value)


def _numeric_mapping(value: object, *, name: str) -> dict[str, float]:
    if not isinstance(value, dict) or not value:
        raise ValueError(f"writing measurement {name} must be a non-empty mapping")
    normalized: dict[str, float] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key:
            raise ValueError(f"writing measurement {name} has an invalid key")
        normalized[key] = _finite_number(item, name=f"{name}.{key}")
    return normalized


def _exactly_one(items: list[_T], predicate: Callable[[_T], bool], name: str) -> _T:
    selected = [item for item in items if predicate(item)]
    if len(selected) != 1:
        raise ValueError(f"{name} must resolve exactly once")
    return selected[0]


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _close(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-12)


__all__ = [
    "WritingEvidenceProjection",
    "build_writing_evidence_projection",
    "write_writing_evidence_projection",
]
