"""Materialize verified evaluation outcomes beneath one owning project."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from scitaste.evaluation.cell_plan import load_evaluation_cell_plan
from scitaste.evaluation.prelaunch import load_prelaunch_manifest
from scitaste.evaluation.results import (
    EvaluationOutcomeAssessment,
    EvaluationResultArtifact,
    EvaluationResultSet,
    inspect_evaluation_results,
)
from scitaste.project import (
    ProjectEvaluationArtifact,
    ProjectEvaluationResultBundle,
    ProjectEvaluationResultEvidence,
    ProjectRuntime,
    ProjectSnapshot,
)
from scitaste.project.models import content_sha256, validate_entry_id, validate_project_id

_MAX_RESULT_SET_BYTES = 64 * 1024 * 1024
_ARTIFACT_NAMES = {
    "result_set": "RESULT_SET.json",
    "assessment": "ASSESSMENT.json",
}


@dataclass(frozen=True)
class PreparedProjectEvaluationResult:
    """Validated result bundle plus exact bytes awaiting atomic publication."""

    bundle: ProjectEvaluationResultBundle
    artifact_payloads: dict[str, bytes]
    assessment: EvaluationOutcomeAssessment


def prepare_project_evaluation_result(
    runtime: ProjectRuntime,
    *,
    project_id: str,
    result_id: str,
    evaluation_id: str,
    result_set_path: str | Path,
) -> PreparedProjectEvaluationResult:
    """Verify project-owned result bytes against one registered proposal and plan."""

    validate_project_id(project_id)
    validate_entry_id(result_id, field_name="result_id")
    validate_entry_id(evaluation_id, field_name="evaluation_id")
    evaluation = runtime.open_evaluation(project_id, evaluation_id)
    project_root = runtime.projects_root / project_id
    source = _project_owned_regular_file(project_root, result_set_path)
    if source.stat().st_size > _MAX_RESULT_SET_BYTES:
        raise ValueError("evaluation result set exceeds its size limit")
    raw_result_set = source.read_bytes()
    results = EvaluationResultSet.model_validate_json(raw_result_set)

    evaluation_dir = project_root / "evaluations" / evaluation_id
    manifest = load_prelaunch_manifest(
        evaluation_dir / evaluation.files["prelaunch_manifest"].locator
    ).manifest
    plan = load_evaluation_cell_plan(evaluation_dir / evaluation.files["cell_plan"].locator)
    assessment = inspect_evaluation_results(
        manifest,
        plan,
        results,
        project_root=project_root,
        project_id=project_id,
        evaluation_id=evaluation_id,
        execution_authorized=evaluation.execution_authorized,
    )
    assessment_bytes = _json_bytes(assessment.model_dump(mode="json"))
    payloads = {
        _ARTIFACT_NAMES["result_set"]: raw_result_set,
        _ARTIFACT_NAMES["assessment"]: assessment_bytes,
    }
    files = {
        label: ProjectEvaluationArtifact(
            locator=locator,
            sha256=hashlib.sha256(payloads[locator]).hexdigest(),
            size_bytes=len(payloads[locator]),
        )
        for label, locator in _ARTIFACT_NAMES.items()
    }
    evidence = _evidence_bindings(results)
    payload = {
        "schema_version": "1.0",
        "project_id": project_id,
        "result_id": result_id,
        "evaluation_id": evaluation_id,
        "proposal_sha256": assessment.proposal_sha256,
        "plan_sha256": assessment.plan_sha256,
        "result_set_sha256": assessment.result_set_sha256,
        "assessment_sha256": assessment.assessment_sha256,
        "status": assessment.status,
        "planned_cells": assessment.planned_cells,
        "verified_records": assessment.verified_records,
        "succeeded_cells": assessment.succeeded_cells,
        "failed_cells": assessment.failed_cells,
        "missing_cells": assessment.missing_cells,
        "invalid_cells": assessment.invalid_cells,
        "valid_external_reviews": assessment.valid_external_reviews,
        "scientific_evidence_complete": assessment.scientific_evidence_complete,
        "headline_eligible": assessment.headline_eligible,
        "scientific_effectiveness_established": (assessment.scientific_effectiveness_established),
        "blocker_codes": assessment.blocker_codes,
        "files": {key: value.model_dump(mode="json") for key, value in files.items()},
        "evidence": [item.model_dump(mode="json") for item in evidence],
    }
    payload["bundle_sha256"] = content_sha256(payload)
    bundle = ProjectEvaluationResultBundle.model_validate(payload)
    return PreparedProjectEvaluationResult(
        bundle=bundle,
        artifact_payloads=payloads,
        assessment=assessment,
    )


def publish_project_evaluation_result(
    runtime: ProjectRuntime,
    prepared: PreparedProjectEvaluationResult,
    *,
    expected_revision: int,
    select: bool = False,
) -> ProjectSnapshot:
    """Publish an admitted result and optionally make it the lifecycle selection."""

    snapshot = runtime.publish_evaluation_result(
        prepared.bundle.project_id,
        prepared.bundle,
        artifact_payloads=prepared.artifact_payloads,
        expected_revision=expected_revision,
    )
    if select:
        snapshot = runtime.select_evaluation_result(
            prepared.bundle.project_id,
            prepared.bundle.result_id,
            expected_revision=snapshot.revision,
        )
    return snapshot


def _project_owned_regular_file(project_root: Path, value: str | Path) -> Path:
    requested = Path(value)
    source = requested if requested.is_absolute() else Path.cwd() / requested
    resolved_root = project_root.resolve(strict=True)
    resolved = source.resolve(strict=True)
    try:
        relative = resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError("evaluation result set must already belong to its project") from exc
    current = resolved_root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ValueError("evaluation result set cannot traverse a symbolic link")
    if not resolved.is_file():
        raise ValueError("evaluation result set must be a regular file")
    return resolved


def _evidence_bindings(
    results: EvaluationResultSet,
) -> tuple[ProjectEvaluationResultEvidence, ...]:
    artifacts: list[EvaluationResultArtifact] = []
    for record in results.cell_results:
        artifacts.extend(record.artifacts)
    artifacts.extend(review.attestation for review in results.blind_reviews)
    artifacts.extend(item.analysis_artifact for item in results.primary_comparisons)
    artifacts.extend(
        item.objective_measurement_set_artifact
        for item in results.primary_comparisons
        if item.objective_measurement_set_artifact is not None
    )
    by_locator: dict[str, EvaluationResultArtifact] = {}
    for artifact in artifacts:
        previous = by_locator.get(artifact.locator)
        if previous is not None and previous != artifact:
            raise ValueError(f"evaluation evidence has conflicting bindings: {artifact.locator}")
        by_locator[artifact.locator] = artifact
    return tuple(
        ProjectEvaluationResultEvidence(
            locator=locator,
            sha256=artifact.sha256,
            size_bytes=artifact.size_bytes,
        )
        for locator, artifact in sorted(by_locator.items())
    )


def _json_bytes(payload: object) -> bytes:
    return (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


__all__ = [
    "PreparedProjectEvaluationResult",
    "prepare_project_evaluation_result",
    "publish_project_evaluation_result",
]
