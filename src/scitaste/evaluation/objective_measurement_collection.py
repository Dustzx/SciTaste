"""Compile scorer-owned native cell artifacts into the generic objective schema."""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath

from scitaste.evaluation.cell_plan import EvaluationCellPlan
from scitaste.evaluation.native_benchmark_adapter import NativeBenchmarkObjectiveMeasurement
from scitaste.evaluation.objective_analysis import (
    ObjectiveCellMeasurement,
    ObjectiveMeasurementSet,
    ObjectiveOutcomeContractInspection,
    objective_cell_population_sha256,
)
from scitaste.evaluation.results import (
    EvaluationResultArtifact,
    EvaluationResultSet,
)

_MAX_MEASUREMENT_BYTES = 16 * 1024 * 1024


def collect_native_objective_measurements(
    plan: EvaluationCellPlan,
    results: EvaluationResultSet,
    contract: ObjectiveOutcomeContractInspection,
    *,
    project_root: str | Path,
    selected_cell_ids: tuple[str, ...],
) -> ObjectiveMeasurementSet:
    """Collect exact successful selected cells; failed cells remain scoreless floors."""

    root = Path(project_root).resolve(strict=True)
    if (
        results.proposal_sha256 != plan.proposal_sha256
        or results.plan_sha256 != plan.plan_sha256
    ):
        raise ValueError("native measurement collection proposal or plan differs")
    planned = {cell.cell_id: cell for cell in plan.cells}
    selected = set(selected_cell_ids)
    if not selected or selected - set(planned):
        raise ValueError("native measurement collection selected unknown cells")
    records = {record.cell_id: record for record in results.cell_results}
    if selected - set(records):
        raise ValueError("native measurement collection requires every selected cell result")
    if set(records) - selected:
        raise ValueError("native measurement collection contains cells outside its campaign")
    task_scores = {item.task_id: item for item in contract.contract.task_scores}

    measurements: list[ObjectiveCellMeasurement] = []
    for cell_id in selected_cell_ids:
        cell = planned[cell_id]
        record = records[cell_id]
        if record.status == "failed":
            continue
        try:
            task_score = task_scores[cell.task_id]
        except KeyError as exc:
            raise ValueError(
                f"objective outcome contract has no selected task: {cell.task_id}"
            ) from exc
        artifact = _measurement_artifact(record.artifacts)
        path = _verified_project_artifact(root, artifact)
        native = NativeBenchmarkObjectiveMeasurement.model_validate_json(path.read_bytes())
        if (
            native.cell_id != cell.cell_id
            or native.task_id != cell.task_id
            or native.condition_id != cell.system_id
        ):
            raise ValueError(f"native objective measurement identity differs: {cell.cell_id}")
        if native.metric_name != task_score.metric_id:
            raise ValueError(f"native objective metric differs: {cell.cell_id}")
        if native.metric_direction != task_score.direction.value:
            raise ValueError(f"native objective direction differs: {cell.cell_id}")
        if abs(native.baseline_heldout_score - task_score.starting_score) > 1e-12:
            raise ValueError(f"native objective starting score differs: {cell.cell_id}")
        measurements.append(
            ObjectiveCellMeasurement.create(
                cell_id=cell.cell_id,
                result_record_sha256=record.record_sha256,
                metric_id=task_score.metric_id,
                metric_version=task_score.metric_version,
                raw_score=native.heldout_score,
                score_artifact=artifact,
            )
        )

    return ObjectiveMeasurementSet.create(
        project_id=results.project_id,
        evaluation_id=results.evaluation_id,
        proposal_sha256=plan.proposal_sha256,
        plan_sha256=plan.plan_sha256,
        cell_result_population_sha256=objective_cell_population_sha256(results),
        objective_outcome_contract_sha256=contract.file_sha256,
        measurements=tuple(measurements),
    )


def _measurement_artifact(
    artifacts: tuple[EvaluationResultArtifact, ...],
) -> EvaluationResultArtifact:
    matches = [
        artifact
        for artifact in artifacts
        if PurePosixPath(artifact.locator).name == "OBJECTIVE_MEASUREMENT.json"
    ]
    if len(matches) != 1:
        raise ValueError("successful native cell requires one objective measurement artifact")
    return matches[0]


def _verified_project_artifact(root: Path, artifact: EvaluationResultArtifact) -> Path:
    candidate = root.joinpath(*PurePosixPath(artifact.locator).parts)
    current = root
    for part in PurePosixPath(artifact.locator).parts:
        current /= part
        if current.is_symlink():
            raise ValueError("native objective measurement cannot traverse a symbolic link")
    resolved = candidate.resolve(strict=True)
    if (
        not resolved.is_relative_to(root)
        or not resolved.is_file()
        or resolved.stat().st_size < 1
        or resolved.stat().st_size > _MAX_MEASUREMENT_BYTES
        or resolved.stat().st_size != artifact.size_bytes
        or _sha256_file(resolved) != artifact.sha256
    ):
        raise ValueError("native objective measurement artifact differs from its result record")
    return resolved


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = ["collect_native_objective_measurements"]
