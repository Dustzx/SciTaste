"""Project-owned projection of a bounded scientific evidence campaign."""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath

from pydantic import ValidationError

from scitaste.evaluation.decision_dossier import (
    CampaignStageState,
    ExperimentDecisionDossierReport,
)
from scitaste.generative_ui.factory import ProjectSurfaceChangedError
from scitaste.generative_ui.models import ProjectEvidenceProgramData
from scitaste.project.models import ProjectRun, ProjectSnapshot

ICLR_EVIDENCE_PROGRAM_PROJECTION = "iclr-evidence-program-v1"
ICLR_EVIDENCE_PROGRAM_STAGE_PATH = "iclr_evidence_program"
_MAX_REPORT_BYTES = 2 * 1024 * 1024

_PHASES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "research-basis",
        "research-basis",
        (
            "audit-evaluation-basis",
            "freeze-dual-estimand-design",
            "approve-exact-source-acquisition",
        ),
    ),
    (
        "taste-instrument",
        "taste-instrument",
        ("qualify-scientific-taste-source-pilot",),
    ),
    (
        "method-readiness",
        "method-readiness",
        (
            "qualify-held-out-task-bytes",
            "attest-native-condition-implementations",
            "qualify-best-native-adapters",
            "attest-remote-qwen-runtime",
        ),
    ),
    (
        "independent-review",
        "independent-review",
        ("freeze-independent-review",),
    ),
    (
        "prepilot-evidence",
        "prepilot-evidence",
        ("run-gpu-native-prepilot", "run-api-best-native-prepilot"),
    ),
    (
        "formal-evidence",
        "formal-evidence",
        ("freeze-and-run-formal-scaleout",),
    ),
    (
        "paper-review-loop",
        "paper-review-loop",
        (
            "bind-results-and-revise-paper",
            "run-internal-model-review",
            "obtain-independent-expert-review",
            "verify-review-response-closure",
        ),
    ),
)


def find_iclr_evidence_program_run(snapshot: ProjectSnapshot) -> ProjectRun | None:
    """Return the latest run explicitly declaring the trusted program projection."""

    for run in reversed(snapshot.manifest.runs):
        extra = run.model_extra or {}
        if extra.get("generative_ui_projection") == ICLR_EVIDENCE_PROGRAM_PROJECTION:
            return run
    return None


def load_iclr_evidence_program_report(
    project_root: Path,
    run: ProjectRun,
) -> tuple[ExperimentDecisionDossierReport, str]:
    """Load the exact bounded report nested under its declaring project run."""

    expected = f"runs/{run.run_id}/{ICLR_EVIDENCE_PROGRAM_STAGE_PATH}/REPORT.json"
    if run.stage_path != ICLR_EVIDENCE_PROGRAM_STAGE_PATH or run.artifact != expected:
        raise ProjectSurfaceChangedError(
            "registered ICLR evidence program does not use its canonical run-owned artifact"
        )
    root = project_root.resolve(strict=True)
    candidate = root.joinpath(*PurePosixPath(expected).parts)
    if candidate.is_symlink() or not candidate.is_file():
        raise ProjectSurfaceChangedError("registered ICLR evidence program is unavailable")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(root) or resolved.stat().st_size > _MAX_REPORT_BYTES:
        raise ProjectSurfaceChangedError("registered ICLR evidence program escaped its project")
    raw = resolved.read_bytes()
    try:
        report = ExperimentDecisionDossierReport.model_validate_json(raw)
    except ValidationError as exc:
        raise ProjectSurfaceChangedError("registered ICLR evidence program is invalid") from exc
    return report, hashlib.sha256(raw).hexdigest()


def project_iclr_evidence_program(
    report: ExperimentDecisionDossierReport,
    *,
    run: ProjectRun,
    project_ref_id: str,
    run_ref_id: str,
    artifact_ref_id: str,
    current_action_run: ProjectRun | None = None,
    current_action_run_ref_id: str | None = None,
) -> ProjectEvidenceProgramData:
    """Collapse the full campaign DAG into seven truthful, progressive-disclosure phases."""

    stages = {item.stage_id: item for item in report.stages}
    expected_stage_ids = {stage_id for _, _, phase in _PHASES for stage_id in phase}
    if set(stages) != expected_stage_ids:
        raise ProjectSurfaceChangedError(
            "registered ICLR evidence program does not match the canonical phase vocabulary"
        )

    if report.next_stage_ids:
        current_stage_id = report.next_stage_ids[0]
    else:
        current_stage_id = next(
            (
                item.stage_id
                for item in report.stages
                if item.state is not CampaignStageState.COMPLETE
            ),
            report.stages[-1].stage_id,
        )
    current_stage = stages[current_stage_id]
    support_ref_ids = [project_ref_id, run_ref_id, artifact_ref_id]
    if current_action_run_ref_id is not None:
        support_ref_ids.append(current_action_run_ref_id)
    support_ref_ids = list(dict.fromkeys(support_ref_ids))

    phase_rows: list[dict[str, object]] = []
    current_phase_id: str | None = None
    for phase_id, label_code, stage_ids in _PHASES:
        rows = [stages[stage_id] for stage_id in stage_ids]
        decision_ids = tuple(
            stage_id for stage_id in report.next_stage_ids if stage_id in stage_ids
        )
        completed = sum(item.state is CampaignStageState.COMPLETE for item in rows)
        if completed == len(rows):
            state = "complete"
        elif decision_ids:
            state = "current"
            current_phase_id = current_phase_id or phase_id
        elif any(
            item.state is CampaignStageState.BLOCKED and item.dependencies_complete
            for item in rows
        ):
            state = "blocked"
        else:
            state = "future"
        phase_rows.append(
            {
                "phase_id": phase_id,
                "label_code": label_code,
                "state": state,
                "stage_ids": stage_ids,
                "decision_stage_ids": decision_ids,
                "completed_stage_count": completed,
                "stage_count": len(rows),
                "blocker_count": sum(len(item.blocker_codes) for item in rows),
                "owner_approval_required": any(item.owner_approval_required for item in rows),
                "external_actions": list(
                    dict.fromkeys(
                        action.value for item in rows for action in item.external_actions
                    )
                ),
                "support_ref_ids": support_ref_ids,
            }
        )
    if current_phase_id is None:
        current_phase_id = next(
            row["phase_id"] for row in phase_rows if current_stage_id in row["stage_ids"]
        )

    track_rows = [
        {
            "track_id": track.track_id,
            "role": track.role.value,
            "state": track.state.value,
            "resource_kind": track.model.kind.value,
            "planned_cells": track.matrix.planned_cells,
            "population_floor": track.data.population_floor,
            "blocker_count": len(track.blocker_codes),
            "support_ref_ids": support_ref_ids,
        }
        for track in report.tracks
    ]
    completed_stage_count = sum(
        item.state is CampaignStageState.COMPLETE for item in report.stages
    )
    return ProjectEvidenceProgramData(
        run_id=run.run_id,
        run_ref_id=run_ref_id,
        artifact_ref_id=artifact_ref_id,
        dossier_id=report.dossier_id,
        dossier_sha256=report.dossier_sha256,
        paper_title=report.paper_title,
        target_venue=report.target_venue,
        central_question=report.central_question,
        claim_boundary=report.claim_boundary,
        artifact_bindings_verified=report.artifact_bindings_verified,
        exact_cell_count=report.exact_cell_count,
        total_stage_count=len(report.stages),
        completed_stage_count=completed_stage_count,
        next_stage_count=len(report.next_stage_ids),
        current_phase_id=current_phase_id,
        current_stage_id=current_stage_id,
        current_decision=current_stage.next_decision,
        current_blocker_count=len(current_stage.blocker_codes),
        current_owner_approval_required=current_stage.owner_approval_required,
        current_external_actions=tuple(action.value for action in current_stage.external_actions),
        current_action_run_id=current_action_run.run_id if current_action_run else None,
        current_action_run_ref_id=current_action_run_ref_id,
        phases=phase_rows,
        tracks=track_rows,
        scientific_effectiveness_established=False,
        no_external_action_performed=report.no_external_action_performed,
        support_ref_ids=support_ref_ids,
    )


def find_current_action_run(
    snapshot: ProjectSnapshot,
    current_stage_id: str,
) -> ProjectRun | None:
    """Resolve the latest exact project run that materializes the current campaign gate."""

    stage_paths = {
        "qualify-scientific-taste-source-pilot": "reference_quality_calibration",
    }
    stage_path = stage_paths.get(current_stage_id)
    if stage_path is None:
        return None
    return next(
        (run for run in reversed(snapshot.manifest.runs) if run.stage_path == stage_path),
        None,
    )


__all__ = [
    "ICLR_EVIDENCE_PROGRAM_PROJECTION",
    "ICLR_EVIDENCE_PROGRAM_STAGE_PATH",
    "find_current_action_run",
    "find_iclr_evidence_program_run",
    "load_iclr_evidence_program_report",
    "project_iclr_evidence_program",
]
