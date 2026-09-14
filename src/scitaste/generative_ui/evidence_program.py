"""Project-owned projection of a bounded scientific evidence campaign."""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath

from pydantic import ValidationError

from scitaste.evaluation.decision_dossier import (
    CampaignStageState,
    ExperimentDecisionDossierReport,
)
from scitaste.evaluation.program_action import (
    EffectiveProgramActionRoute,
    route_effective_program_action,
    route_program_stage_action,
)
from scitaste.evaluation.program_control import EffectiveExperimentProgram
from scitaste.generative_ui.factory import ProjectSurfaceChangedError
from scitaste.generative_ui.models import (
    ProjectEvidenceProgramData,
    ProjectProgramActionRouteData,
)
from scitaste.model_nodes.verification_policy import VerificationAdvisory
from scitaste.project.models import ProjectRun, ProjectSnapshot

ICLR_EVIDENCE_PROGRAM_PROJECTION = "iclr-evidence-program-v1"
ICLR_EVIDENCE_PROGRAM_STAGE_PATH = "iclr_evidence_program"
_MAX_REPORT_BYTES = 2 * 1024 * 1024

_LEGACY_PHASES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
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

_LIFECYCLE_PHASES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("research-basis", "research-basis", ("freeze-lifecycle-science",)),
    ("taste-instrument", "taste-instrument", ("admit-natural-lifecycle-episodes",)),
    (
        "method-readiness",
        "method-readiness",
        ("qualify-objective-and-external-assets",),
    ),
    ("independent-review", "independent-review", ("freeze-independent-review",)),
    (
        "prepilot-evidence",
        "prepilot-evidence",
        ("select-primary-model", "run-disjoint-pilots-and-power"),
    ),
    ("formal-evidence", "formal-evidence", ("run-formal-evidence",)),
    ("paper-review-loop", "paper-review-loop", ("revise-and-review-paper",)),
)

_PHASE_VOCABULARIES = (_LEGACY_PHASES, _LIFECYCLE_PHASES)


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
    effective_program: EffectiveExperimentProgram,
    run: ProjectRun,
    project_ref_id: str,
    run_ref_id: str,
    artifact_ref_id: str,
    current_action_run: ProjectRun | None = None,
    current_action_run_ref_id: str | None = None,
    verification_advisory: VerificationAdvisory | None = None,
    verification_advisory_stage_id: str | None = None,
) -> ProjectEvidenceProgramData:
    """Collapse the full campaign DAG into seven truthful, progressive-disclosure phases."""

    stages = {item.stage_id: item for item in report.stages}
    phases = next(
        (
            vocabulary
            for vocabulary in _PHASE_VOCABULARIES
            if set(stages)
            == {stage_id for _, _, phase in vocabulary for stage_id in phase}
        ),
        None,
    )
    if phases is None:
        raise ProjectSurfaceChangedError(
            "registered ICLR evidence program does not match the canonical phase vocabulary"
        )
    if (
        effective_program.dossier_id != report.dossier_id
        or effective_program.dossier_sha256 != report.dossier_sha256
    ):
        raise ProjectSurfaceChangedError(
            "effective experiment program belongs to another evidence dossier"
        )

    effective_next_stage_ids = effective_program.effective_next_stage_ids
    current_stage_id = effective_program.effective_current_stage_id
    current_stage = stages[current_stage_id]
    support_ref_ids = [project_ref_id, run_ref_id, artifact_ref_id]
    if current_action_run_ref_id is not None:
        support_ref_ids.append(current_action_run_ref_id)
    support_ref_ids = list(dict.fromkeys(support_ref_ids))

    phase_rows: list[dict[str, object]] = []
    for phase_id, label_code, stage_ids in phases:
        rows = [stages[stage_id] for stage_id in stage_ids]
        decision_ids = tuple(
            stage_id for stage_id in effective_next_stage_ids if stage_id in stage_ids
        )
        completed = sum(item.state is CampaignStageState.COMPLETE for item in rows)
        if completed == len(rows):
            state = "complete"
        elif decision_ids:
            state = "current"
        elif any(
            item.state is CampaignStageState.BLOCKED and item.dependencies_complete for item in rows
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
                    dict.fromkeys(action.value for item in rows for action in item.external_actions)
                ),
                "support_ref_ids": support_ref_ids,
            }
        )
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
    completed_stage_count = sum(item.state is CampaignStageState.COMPLETE for item in report.stages)
    action_route = route_effective_program_action(
        report,
        effective_program,
        advisory=(
            verification_advisory if current_stage_id == verification_advisory_stage_id else None
        ),
    )
    projected_action_route = _project_action_route(action_route)
    next_gate_action_routes = tuple(
        _project_action_route(
            route_program_stage_action(
                report,
                effective_program,
                stage_id=stage_id,
                advisory=(
                    verification_advisory if stage_id == verification_advisory_stage_id else None
                ),
            )
        )
        for stage_id in effective_next_stage_ids
    )
    return ProjectEvidenceProgramData(
        run_id=run.run_id,
        run_ref_id=run_ref_id,
        artifact_ref_id=artifact_ref_id,
        dossier_id=report.dossier_id,
        dossier_sha256=report.dossier_sha256,
        dossier_report_sha256=effective_program.dossier_report_sha256,
        paper_title=report.paper_title,
        target_venue=report.target_venue,
        central_question=report.central_question,
        claim_boundary=report.claim_boundary,
        artifact_bindings_verified=report.artifact_bindings_verified,
        exact_cell_count=report.exact_cell_count,
        total_stage_count=len(report.stages),
        completed_stage_count=completed_stage_count,
        next_stage_count=len(effective_next_stage_ids),
        planning_authority=effective_program.planning_authority,
        control_effect=effective_program.control_effect,
        source_publication_id=effective_program.source_publication_id,
        source_publication_sha256=effective_program.source_publication_sha256,
        effective_program_sha256=effective_program.program_sha256,
        planning_verification_route=effective_program.verification_route.value,
        planning_verification_reason_codes=effective_program.verification_reason_codes,
        baseline_next_stage_ids=effective_program.baseline_next_stage_ids,
        effective_next_stage_ids=effective_next_stage_ids,
        current_phase_id=current_phase_id,
        current_stage_id=current_stage_id,
        current_decision=current_stage.next_decision,
        current_blocker_count=len(current_stage.blocker_codes),
        current_owner_approval_required=current_stage.owner_approval_required,
        current_external_actions=tuple(action.value for action in current_stage.external_actions),
        gate_action_route=projected_action_route,
        next_gate_action_routes=next_gate_action_routes,
        current_action_run_id=current_action_run.run_id if current_action_run else None,
        current_action_run_ref_id=current_action_run_ref_id,
        phases=phase_rows,
        tracks=track_rows,
        scientific_effectiveness_established=False,
        no_external_action_performed=report.no_external_action_performed,
        support_ref_ids=support_ref_ids,
    )


def _project_action_route(
    action_route: EffectiveProgramActionRoute,
) -> ProjectProgramActionRouteData:
    return ProjectProgramActionRouteData(
        route_sha256=action_route.route_sha256,
        effective_program_sha256=action_route.effective_program_sha256,
        stage_id=action_route.stage_id,
        stage_state=action_route.stage_state.value,
        blocker_codes=action_route.blocker_codes,
        external_actions=tuple(item.value for item in action_route.external_actions),
        routing_basis=action_route.routing_basis,
        next_action_kind=action_route.next_action_kind,
        verification_route=action_route.verification.route.value,
        verification_reason_codes=action_route.verification.reason_codes,
        action_effects=tuple(item.value for item in action_route.verification_input.effects),
        expected_loss_units=action_route.verification.expected_loss_units,
        targeted_net_gain_units=action_route.verification.targeted_net_gain_units,
        full_preflight_net_gain_units=action_route.verification.full_preflight_net_gain_units,
        owner_approval_required=action_route.verification.owner_approval_required,
        model_advisory_eligible=action_route.verification.model_advisory_eligible,
        decision_source=action_route.verification.decision_source,
        advisory_fingerprint=action_route.verification.advisory_fingerprint,
        selected_by_tool_intelligence=True,
        authorizes_external_action=False,
        authorizes_execution=False,
        execution_authority="none",
        no_external_action_performed=True,
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
