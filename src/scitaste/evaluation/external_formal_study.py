"""Admit preregistered external formal studies into project evidence.

This adapter is intentionally narrower than the native prelaunch/campaign path.
It does not authorize or execute an experiment.  It imports a protocol that was
frozen before execution, replays its result statistics from project-owned arm
receipts, and exposes the verified result through the same project lifecycle
used by native evaluations.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import random
import statistics
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.evaluation.project_materialization import PreparedProjectEvaluation
from scitaste.evaluation.result_materialization import PreparedProjectEvaluationResult
from scitaste.project import (
    ProjectEvaluationArtifact,
    ProjectEvaluationBundle,
    ProjectEvaluationResultBundle,
    ProjectEvaluationResultEvidence,
    ProjectRuntime,
)
from scitaste.project.models import content_sha256, validate_entry_id, validate_project_id

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"
_ADAPTER_ID = "researchclawbench-formal-v1"
_EVALUATION_FILES = {
    "formal_protocol": "FORMAL_PROTOCOL.yaml",
    "admission": "ADMISSION.json",
}
_RESULT_FILES = {
    "formal_result": "FORMAL_RESULT.json",
    "integrity_audit": "INTEGRITY_AUDIT.json",
}
_PAIR_FIELDS = (
    "benchmark",
    "benchmark_commit",
    "task_id",
    "visible_task_sha256",
    "model",
    "api_base",
    "api_key_env",
    "extra_body",
    "tools",
    "max_retries",
    "max_rounds",
    "max_runtime_seconds",
    "max_input_tokens",
    "max_output_tokens",
    "compact_trigger_tokens",
    "seed",
    "upstream_role_prompt_sha256",
    "target_study_visible_to_agent",
)


class ExternalFormalStudyAdmission(BaseModel):
    """Self-hashed projection of an already-frozen external protocol."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    adapter_id: Literal["researchclawbench-formal-v1"] = _ADAPTER_ID
    project_id: str
    evaluation_id: str
    study_id: str
    benchmark_name: Literal["ResearchClawBench"] = "ResearchClawBench"
    protocol_sha256: str = Field(pattern=_SHA256)
    benchmark_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    task_ids: tuple[str, ...] = Field(min_length=2, max_length=500)
    condition_ids: tuple[Literal["native-base", "full-scitaste"], ...] = Field(
        min_length=2, max_length=2
    )
    planned_cells: int = Field(gt=0)
    agent_model: str = Field(min_length=1, max_length=200)
    judge_model: str = Field(min_length=1, max_length=200)
    runtime_source_hashes_verified: bool
    prior_execution_authority_acknowledged: bool
    no_execution_performed: Literal[True] = True
    blocker_codes: tuple[str, ...] = Field(default=(), max_length=100)
    record_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def admission_is_closed(self) -> ExternalFormalStudyAdmission:
        validate_project_id(self.project_id)
        validate_entry_id(self.evaluation_id, field_name="evaluation_id")
        validate_entry_id(self.study_id, field_name="study_id")
        for task_id in self.task_ids:
            validate_entry_id(task_id.lower(), field_name="task_id")
        if len(self.task_ids) != len(set(self.task_ids)):
            raise ValueError("external formal task IDs must be unique")
        if set(self.condition_ids) != {"native-base", "full-scitaste"}:
            raise ValueError("external formal study requires the exact matched pair")
        if self.planned_cells != 2 * len(self.task_ids):
            raise ValueError("external formal planned cells must close the paired matrix")
        if not self.blocker_codes and not (
            self.runtime_source_hashes_verified and self.prior_execution_authority_acknowledged
        ):
            raise ValueError("blocker-free admission requires source and authority evidence")
        expected = content_sha256(self.model_dump(mode="json", exclude={"record_sha256"}))
        if self.record_sha256 != expected:
            raise ValueError("external formal admission hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> ExternalFormalStudyAdmission:
        payload = {"schema_version": "1.0", "adapter_id": _ADAPTER_ID, **values}
        payload.pop("record_sha256", None)
        unsigned = cls.model_construct(record_sha256="0" * 64, **payload)
        return cls(
            **payload,
            record_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"record_sha256"})
            ),
        )


class ExternalFormalStudyVerification(BaseModel):
    """Replayed scientific and integrity verdict for one imported cohort."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    adapter_id: Literal["researchclawbench-formal-v1"] = _ADAPTER_ID
    study_id: str
    protocol_sha256: str = Field(pattern=_SHA256)
    result_sha256: str = Field(pattern=_SHA256)
    audit_sha256: str = Field(pattern=_SHA256)
    planned_cells: int = Field(gt=0)
    verified_records: int = Field(ge=0)
    succeeded_cells: int = Field(ge=0)
    missing_cells: int = Field(ge=0)
    invalid_cells: int = Field(ge=0)
    complete_pairs: int = Field(ge=0)
    mean_paired_delta: float | None = None
    interval_lower: float | None = None
    interval_upper: float | None = None
    exact_sign_flip_p: float | None = Field(default=None, ge=0, le=1)
    full_wins: int = Field(ge=0)
    base_wins: int = Field(ge=0)
    ties: int = Field(ge=0)
    scientific_evidence_complete: bool
    claim_authorized: bool
    blocker_codes: tuple[str, ...]


@dataclass(frozen=True)
class _ProtocolInspection:
    raw: bytes
    payload: dict[str, Any]
    sha256: str
    task_ids: tuple[str, ...]
    blockers: tuple[str, ...]


def prepare_external_formal_evaluation(
    *,
    project_id: str,
    evaluation_id: str,
    protocol_path: str | Path,
    repository_root: str | Path,
    acknowledge_prior_execution_authority: bool,
) -> PreparedProjectEvaluation:
    """Project a frozen ResearchClawBench protocol without launching anything."""

    validate_project_id(project_id)
    validate_entry_id(evaluation_id, field_name="evaluation_id")
    protocol = _inspect_protocol(protocol_path, repository_root=repository_root)
    payload = protocol.payload
    blockers = list(protocol.blockers)
    if payload.get("project_id") != project_id:
        blockers.append("protocol-project-mismatch")
    if not acknowledge_prior_execution_authority:
        blockers.append("prior-execution-authority-unacknowledged")
    admission = ExternalFormalStudyAdmission.create(
        project_id=project_id,
        evaluation_id=evaluation_id,
        study_id=str(payload["study_id"]),
        protocol_sha256=protocol.sha256,
        benchmark_commit=str(payload["benchmark"]["commit"]),
        task_ids=protocol.task_ids,
        condition_ids=tuple(item["condition_id"] for item in payload["conditions"]),
        planned_cells=2 * len(protocol.task_ids),
        agent_model=str(payload["agent"]["model"]),
        judge_model=str(payload["judge"]["model"]),
        runtime_source_hashes_verified="runtime-source-hash-mismatch" not in blockers,
        prior_execution_authority_acknowledged=acknowledge_prior_execution_authority,
        no_execution_performed=True,
        blocker_codes=tuple(sorted(set(blockers))),
    )
    admission_bytes = _json_bytes(admission.model_dump(mode="json"))
    artifact_payloads = {
        _EVALUATION_FILES["formal_protocol"]: protocol.raw,
        _EVALUATION_FILES["admission"]: admission_bytes,
    }
    files = _artifact_bindings(artifact_payloads)
    ready = not admission.blocker_codes
    bundle_payload: dict[str, object] = {
        "schema_version": "1.1",
        "origin": "external-formal-study",
        "project_id": project_id,
        "evaluation_id": evaluation_id,
        "manifest_id": str(payload["study_id"]),
        "protocol_id": str(payload["study_id"]),
        "study_scope": "formal",
        "status": "execution_authorized" if ready else "blocked",
        "proposal_sha256": protocol.sha256,
        "planned_cells": 2 * len(protocol.task_ids),
        "system_ids": ("native-base", "full-scitaste"),
        "task_ids": protocol.task_ids,
        "lane_ids": ("researchclawbench-matched-backbone",),
        "api_resources": (
            f"agent:{payload['agent']['provider']}/{payload['agent']['model']}",
            f"judge:{payload['judge']['provider']}/{payload['judge']['model']}",
        ),
        "gpu_resources": (),
        "ready_for_author_review": ready,
        "execution_authorized": ready,
        "observed_source_commit": None,
        "source_tree_clean": None,
        "readiness_blocker_codes": admission.blocker_codes,
        "authorization_blocker_codes": (),
        "critic_blocking_codes": (),
        "cell_plan_blockers": (),
        "files": {key: value.model_dump(mode="json") for key, value in files.items()},
        "no_execution_performed": True,
    }
    bundle_payload["bundle_sha256"] = content_sha256(bundle_payload)
    return PreparedProjectEvaluation(
        bundle=ProjectEvaluationBundle.model_validate(bundle_payload),
        artifact_payloads=artifact_payloads,
    )


def prepare_external_formal_result(
    runtime: ProjectRuntime,
    *,
    project_id: str,
    evaluation_id: str,
    result_id: str,
    result_path: str | Path,
    audit_path: str | Path,
    evidence_root: str | Path,
) -> PreparedProjectEvaluationResult:
    """Replay and package a completed cohort from project-owned exact bytes."""

    validate_project_id(project_id)
    validate_entry_id(evaluation_id, field_name="evaluation_id")
    validate_entry_id(result_id, field_name="result_id")
    evaluation = runtime.open_evaluation(project_id, evaluation_id)
    if evaluation.schema_version != "1.1" or evaluation.origin != "external-formal-study":
        raise ValueError("evaluation is not an external formal study")
    project_root = runtime.projects_root / project_id
    result_source = _project_file(project_root, result_path)
    audit_source = _project_file(project_root, audit_path)
    evidence_directory = _project_directory(project_root, evidence_root)
    result_raw = result_source.read_bytes()
    audit_raw = audit_source.read_bytes()
    verification = verify_external_formal_study(
        project_root=project_root,
        evaluation=evaluation,
        result_raw=result_raw,
        audit_raw=audit_raw,
        evidence_root=evidence_directory,
    )
    evidence = _evidence_bindings(project_root, evidence_directory)
    artifact_payloads = {
        _RESULT_FILES["formal_result"]: result_raw,
        _RESULT_FILES["integrity_audit"]: audit_raw,
    }
    files = _artifact_bindings(artifact_payloads)
    complete = verification.scientific_evidence_complete
    payload: dict[str, object] = {
        "schema_version": "1.1",
        "origin": "external-formal-study",
        "project_id": project_id,
        "result_id": result_id,
        "evaluation_id": evaluation_id,
        "proposal_sha256": evaluation.proposal_sha256,
        "plan_sha256": evaluation.proposal_sha256,
        "result_set_sha256": verification.result_sha256,
        "assessment_sha256": verification.audit_sha256,
        "status": "complete" if complete else "incomplete",
        "planned_cells": verification.planned_cells,
        "verified_records": verification.verified_records,
        "succeeded_cells": verification.succeeded_cells,
        "failed_cells": 0,
        "missing_cells": verification.missing_cells,
        "invalid_cells": verification.invalid_cells,
        "valid_external_reviews": 0,
        "scientific_evidence_complete": complete,
        "headline_eligible": complete,
        "scientific_effectiveness_established": (complete and verification.claim_authorized),
        "blocker_codes": verification.blocker_codes,
        "files": {key: value.model_dump(mode="json") for key, value in files.items()},
        "evidence": [item.model_dump(mode="json") for item in evidence],
    }
    payload["bundle_sha256"] = content_sha256(payload)
    bundle = ProjectEvaluationResultBundle.model_validate(payload)
    return PreparedProjectEvaluationResult(
        bundle=bundle,
        artifact_payloads=artifact_payloads,
        assessment=verification,  # type: ignore[arg-type]
    )


def verify_external_formal_evaluation(
    directory: Path,
    bundle: ProjectEvaluationBundle,
) -> ExternalFormalStudyAdmission:
    """Revalidate one imported protocol bundle without consulting mutable source."""

    if bundle.schema_version != "1.1" or bundle.origin != "external-formal-study":
        raise ValueError("evaluation is not an external formal study")
    protocol_path = directory / bundle.files["formal_protocol"].locator
    admission_path = directory / bundle.files["admission"].locator
    protocol = _inspect_protocol(protocol_path, repository_root=None)
    admission = ExternalFormalStudyAdmission.model_validate_json(admission_path.read_bytes())
    expected = (
        bundle.project_id,
        bundle.evaluation_id,
        bundle.manifest_id,
        bundle.protocol_id,
        bundle.proposal_sha256,
        bundle.planned_cells,
        bundle.system_ids,
        bundle.task_ids,
        bundle.study_scope,
        bundle.status,
        bundle.ready_for_author_review,
        bundle.execution_authorized,
    )
    ready = not admission.blocker_codes
    observed = (
        admission.project_id,
        admission.evaluation_id,
        admission.study_id,
        admission.study_id,
        protocol.sha256,
        admission.planned_cells,
        ("native-base", "full-scitaste"),
        admission.task_ids,
        "formal",
        "execution_authorized" if ready else "blocked",
        ready,
        ready,
    )
    if expected != observed:
        raise ValueError("external formal evaluation summary differs from its protocol")
    return admission


def verify_external_formal_study(
    *,
    project_root: Path,
    evaluation: ProjectEvaluationBundle,
    result_raw: bytes,
    audit_raw: bytes,
    evidence_root: Path,
) -> ExternalFormalStudyVerification:
    """Recompute the paired result and bind every compact arm artifact."""

    evaluation_dir = project_root / "evaluations" / evaluation.evaluation_id
    protocol_path = evaluation_dir / evaluation.files["formal_protocol"].locator
    admission_path = evaluation_dir / evaluation.files["admission"].locator
    protocol = _inspect_protocol(protocol_path, repository_root=None)
    admission = ExternalFormalStudyAdmission.model_validate_json(admission_path.read_bytes())
    result = _mapping_from_json(result_raw, "formal result")
    audit = _mapping_from_json(audit_raw, "integrity audit")
    blockers: list[str] = []
    if admission.protocol_sha256 != protocol.sha256:
        blockers.append("admission-protocol-mismatch")
    if result.get("study_id") != admission.study_id:
        blockers.append("result-study-mismatch")
    if result.get("protocol_sha256") != protocol.sha256:
        blockers.append("result-protocol-mismatch")
    if audit.get("study_id") != admission.study_id:
        blockers.append("audit-study-mismatch")
    if audit.get("protocol_sha256") != protocol.sha256:
        blockers.append("audit-protocol-mismatch")
    if audit.get("status") != "passed" or audit.get("failure_count") != 0:
        blockers.append("integrity-audit-failed")
    if result.get("rrmot_touched") is not False:
        blockers.append("rrmot-boundary-violated")
    if result.get("deferred_validation_project_executed") is not False:
        blockers.append("deferred-project-boundary-violated")

    task_records = result.get("tasks")
    if not isinstance(task_records, list):
        task_records = []
        blockers.append("result-tasks-invalid")
    by_task = {
        item.get("task_id"): item
        for item in task_records
        if isinstance(item, dict) and isinstance(item.get("task_id"), str)
    }
    deltas: list[float] = []
    verified_records = 0
    invalid_records = 0
    missing_records = 0
    expected_agent = protocol.payload["agent"]
    expected_judge = protocol.payload["judge"]
    registered_tasks = {item["task_id"]: item for item in protocol.payload["population"]["tasks"]}
    audit_tasks = audit.get("tasks") if isinstance(audit.get("tasks"), list) else []
    audit_by_task = {
        item.get("task_id"): item
        for item in audit_tasks
        if isinstance(item, dict) and isinstance(item.get("task_id"), str)
    }
    overlay_contract = protocol.payload.get("taste_control", {}).get("receipt_requirements", {})
    for task_id in admission.task_ids:
        task = by_task.get(task_id)
        if task is None:
            missing_records += 2
            blockers.append(f"task:{task_id}:result-missing")
            continue
        overlay_path = evidence_root / task_id / "taste-overlay" / "TASTE_CONTROL_OVERLAY.md"
        overlay_receipt_path = evidence_root / task_id / "taste-overlay" / "RECEIPT.json"
        overlay_sha: str | None = None
        if not overlay_path.is_file() or not overlay_receipt_path.is_file():
            blockers.append(f"task:{task_id}:taste-overlay-evidence-missing")
        else:
            overlay_raw = overlay_path.read_bytes()
            overlay_sha = _sha256(overlay_raw)
            overlay_receipt = _mapping_from_json(
                overlay_receipt_path.read_bytes(), "Taste overlay receipt"
            )
            overlay_checks = (
                overlay_receipt.get("task_id") == task_id,
                overlay_receipt.get("overlay_file_sha256") == overlay_sha,
                overlay_receipt.get("overlay_bytes") == len(overlay_raw),
                len(overlay_raw) <= int(overlay_contract.get("maximum_overlay_bytes", -1)),
                overlay_receipt.get("treatment") == overlay_contract.get("treatment"),
                overlay_receipt.get("render_format") == overlay_contract.get("render_format"),
                overlay_receipt.get("mechanism_claim_count", 10**9)
                <= int(overlay_contract.get("maximum_mechanism_claims", -1)),
                overlay_receipt.get("conditional_action_count", 10**9)
                <= int(overlay_contract.get("maximum_conditional_actions", -1)),
                overlay_receipt.get("unconditional_recommended_action_present") is False,
                overlay_receipt.get("native_fallback_required_when_abstaining") is True,
            )
            if not all(overlay_checks):
                blockers.append(f"task:{task_id}:taste-overlay-evidence-invalid")
        scores: dict[str, float] = {}
        receipts: dict[str, dict[str, Any]] = {}
        arms = task.get("arms") if isinstance(task.get("arms"), dict) else {}
        for condition in ("native-base", "full-scitaste"):
            arm = arms.get(condition) if isinstance(arms, dict) else None
            receipt_path = evidence_root / task_id / condition / "SCITASTE_SYSTEM_RUN_RECEIPT.json"
            score_path = evidence_root / task_id / condition / "_score.json"
            if not isinstance(arm, dict) or not receipt_path.is_file() or not score_path.is_file():
                missing_records += 1
                blockers.append(f"task:{task_id}:{condition}:evidence-missing")
                continue
            receipt = _mapping_from_json(receipt_path.read_bytes(), "arm receipt")
            score = _mapping_from_json(score_path.read_bytes(), "official score")
            total = score.get("total_score")
            checks = (
                arm.get("receipt_sha256") == _sha256(receipt_path.read_bytes()),
                arm.get("score_sha256") == _sha256(score_path.read_bytes()),
                receipt.get("status") == "completed",
                receipt.get("condition") == condition,
                receipt.get("task_id") == task_id,
                receipt.get("visible_task_sha256") == registered_tasks[task_id]["visible_sha256"],
                receipt.get("benchmark_commit") == protocol.payload["benchmark"]["commit"],
                receipt.get("model") == expected_agent["model"],
                receipt.get("api_base") == expected_agent["api_base"],
                receipt.get("target_study_visible_to_agent") is False,
                receipt.get("scoring", {}).get("judge_model") == expected_judge["model"],
                receipt.get("scoring", {}).get("judge_api_base") == expected_judge["api_base"],
                receipt.get("scoring", {}).get("score_sha256") == _sha256(score_path.read_bytes()),
                receipt.get("taste_overlay_sha256")
                == (overlay_sha if condition == "full-scitaste" else None),
                isinstance(total, (int, float)),
                isinstance(score.get("items"), list) and bool(score.get("items")),
                all(
                    isinstance(item, dict)
                    and str(item.get("reasoning", "")).strip()
                    not in {"", "Failed to parse scoring response.", "Scoring failed."}
                    for item in score.get("items", [])
                ),
            )
            if not all(checks):
                invalid_records += 1
                blockers.append(f"task:{task_id}:{condition}:evidence-invalid")
                continue
            verified_records += 1
            receipts[condition] = receipt
            scores[condition] = float(total)
        if len(receipts) == 2 and any(
            receipts["native-base"].get(field) != receipts["full-scitaste"].get(field)
            for field in _PAIR_FIELDS
        ):
            blockers.append(f"task:{task_id}:pair-parity-failed")
        elif len(scores) == 2:
            delta = scores["full-scitaste"] - scores["native-base"]
            if task.get("paired_delta") != delta:
                blockers.append(f"task:{task_id}:paired-delta-mismatch")
            deltas.append(delta)
        audit_task = audit_by_task.get(task_id)
        if not isinstance(audit_task, dict) or not _all_nested_checks_pass(audit_task):
            blockers.append(f"task:{task_id}:audit-detail-invalid")

    analysis = result.get("analysis") if isinstance(result.get("analysis"), dict) else {}
    required = len(admission.task_ids)
    mean_delta = statistics.fmean(deltas) if deltas else None
    interval: tuple[float, float] | None = None
    p_value: float | None = None
    full_wins = sum(value > 0 for value in deltas)
    base_wins = sum(value < 0 for value in deltas)
    ties = sum(value == 0 for value in deltas)
    if deltas:
        interval = _bootstrap_interval(
            deltas,
            resamples=int(protocol.payload["analysis"]["bootstrap_resamples"]),
            seed=int(protocol.payload["analysis"]["bootstrap_seed"]),
            alpha=1.0 - float(protocol.payload["analysis"]["confidence_level"]),
        )
        p_value = _exact_sign_flip_p(deltas)
    observed_values = (
        analysis.get("complete_pair_count"),
        analysis.get("mean_paired_delta"),
        analysis.get("bootstrap_interval_95"),
        analysis.get("exact_sign_flip_p"),
        analysis.get("full_wins"),
        analysis.get("base_wins"),
        analysis.get("ties"),
    )
    expected_values = (
        len(deltas),
        round(mean_delta, 6) if mean_delta is not None else None,
        [round(value, 6) for value in interval] if interval is not None else None,
        round(p_value, 8) if p_value is not None else None,
        full_wins,
        base_wins,
        ties,
    )
    if observed_values != expected_values:
        blockers.append("registered-analysis-replay-mismatch")
    complete = (
        not blockers
        and len(deltas) == required
        and verified_records == admission.planned_cells
        and result.get("status") == "formal-complete"
        and result.get("formal_evidence_complete") is True
    )
    win_rate = full_wins / required if required else 0.0
    claim_authorized = bool(
        complete
        and mean_delta is not None
        and interval is not None
        and mean_delta >= float(protocol.payload["analysis"]["minimum_claim_effect_points"])
        and interval[0] > 0
        and win_rate >= float(protocol.payload["analysis"]["minimum_claim_win_rate"])
    )
    if result.get("claim_authorized") is not claim_authorized:
        blockers.append("claim-decision-replay-mismatch")
        complete = False
        claim_authorized = False
    return ExternalFormalStudyVerification(
        study_id=admission.study_id,
        protocol_sha256=protocol.sha256,
        result_sha256=_sha256(result_raw),
        audit_sha256=_sha256(audit_raw),
        planned_cells=admission.planned_cells,
        verified_records=verified_records,
        succeeded_cells=verified_records,
        missing_cells=missing_records,
        invalid_cells=invalid_records,
        complete_pairs=len(deltas),
        mean_paired_delta=round(mean_delta, 6) if mean_delta is not None else None,
        interval_lower=round(interval[0], 6) if interval is not None else None,
        interval_upper=round(interval[1], 6) if interval is not None else None,
        exact_sign_flip_p=round(p_value, 8) if p_value is not None else None,
        full_wins=full_wins,
        base_wins=base_wins,
        ties=ties,
        scientific_evidence_complete=complete,
        claim_authorized=claim_authorized,
        blocker_codes=tuple(sorted(set(blockers))),
    )


def _inspect_protocol(
    path: str | Path,
    *,
    repository_root: str | Path | None,
) -> _ProtocolInspection:
    source = Path(path).resolve(strict=True)
    raw = source.read_bytes()
    if not raw or len(raw) > 1_048_576:
        raise ValueError("external formal protocol must be a bounded regular file")
    payload = yaml.safe_load(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("external formal protocol must contain a YAML mapping")
    blockers: list[str] = []
    required_mappings = ("benchmark", "population", "agent", "judge", "analysis", "execution")
    if any(not isinstance(payload.get(key), dict) for key in required_mappings):
        raise ValueError("external formal protocol is missing a required mapping")
    tasks = payload["population"].get("tasks")
    conditions = payload.get("conditions")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("external formal protocol has no task population")
    if not isinstance(conditions, list) or {
        item.get("condition_id") for item in conditions if isinstance(item, dict)
    } != {"native-base", "full-scitaste"}:
        blockers.append("matched-condition-pair-invalid")
    task_ids = tuple(str(item["task_id"]) for item in tasks)
    if int(payload["population"].get("required_task_count", -1)) != len(task_ids):
        blockers.append("task-population-count-mismatch")
    if payload["benchmark"].get("name") != "ResearchClawBench":
        blockers.append("benchmark-identity-mismatch")
    separation = payload.get("separation")
    if not isinstance(separation, dict):
        blockers.append("downstream-separation-missing")
    else:
        if separation.get("deferred_validation_project") != "perceptual-visual-relexing":
            blockers.append("downstream-project-identity-mismatch")
        if separation.get("execution_authorized_in_this_study") is not False:
            blockers.append("downstream-project-not-deferred")
        if "RRMOT" not in separation.get("isolation_targets", []):
            blockers.append("rrmot-isolation-missing")
    if repository_root is not None:
        root = Path(repository_root).resolve(strict=True)
        for item in payload.get("runtime_bundle", {}).get("sources", []):
            candidate = root / PurePosixPath(str(item.get("locator", "")))
            try:
                resolved = candidate.resolve(strict=True)
                resolved.relative_to(root)
            except (OSError, ValueError):
                blockers.append("runtime-source-hash-mismatch")
                break
            if not resolved.is_file() or _sha256(resolved.read_bytes()) != item.get("sha256"):
                blockers.append("runtime-source-hash-mismatch")
                break
    return _ProtocolInspection(
        raw=raw,
        payload=payload,
        sha256=_sha256(raw),
        task_ids=task_ids,
        blockers=tuple(sorted(set(blockers))),
    )


def _artifact_bindings(payloads: dict[str, bytes]) -> dict[str, ProjectEvaluationArtifact]:
    by_locator = {
        **{value: key for key, value in _EVALUATION_FILES.items()},
        **{value: key for key, value in _RESULT_FILES.items()},
    }
    return {
        by_locator[locator]: ProjectEvaluationArtifact(
            locator=locator,
            sha256=_sha256(raw),
            size_bytes=len(raw),
        )
        for locator, raw in payloads.items()
    }


def _evidence_bindings(
    project_root: Path, evidence_root: Path
) -> tuple[ProjectEvaluationResultEvidence, ...]:
    allowed_names = {
        "SCITASTE_SYSTEM_RUN_RECEIPT.json",
        "_score.json",
        "TASTE_CONTROL_OVERLAY.md",
        "RECEIPT.json",
        "RESUME_MANIFEST.json",
        "EXECUTION_INDEX.json",
    }
    bindings: list[ProjectEvaluationResultEvidence] = []
    for path in sorted(evidence_root.rglob("*")):
        if not path.is_file() or path.is_symlink() or path.name not in allowed_names:
            continue
        raw = path.read_bytes()
        locator = path.relative_to(project_root).as_posix()
        bindings.append(
            ProjectEvaluationResultEvidence(
                locator=locator,
                sha256=_sha256(raw),
                size_bytes=len(raw),
            )
        )
    if not bindings:
        raise ValueError("external formal evidence root contains no admissible artifacts")
    return tuple(bindings)


def _project_file(project_root: Path, value: str | Path) -> Path:
    source = Path(value)
    candidate = source if source.is_absolute() else Path.cwd() / source
    resolved = candidate.resolve(strict=True)
    if (
        candidate.is_symlink()
        or not resolved.is_file()
        or not resolved.is_relative_to(project_root)
    ):
        raise ValueError("external formal artifact must be a project-owned regular file")
    return resolved


def _project_directory(project_root: Path, value: str | Path) -> Path:
    source = Path(value)
    candidate = source if source.is_absolute() else Path.cwd() / source
    resolved = candidate.resolve(strict=True)
    if candidate.is_symlink() or not resolved.is_dir() or not resolved.is_relative_to(project_root):
        raise ValueError("external formal evidence must be a project-owned directory")
    return resolved


def _mapping_from_json(raw: bytes, label: str) -> dict[str, Any]:
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a JSON mapping")
    return value


def _all_nested_checks_pass(value: object) -> bool:
    """Require every dictionary explicitly named ``checks`` to contain only true values."""

    found = False

    def visit(item: object) -> bool:
        nonlocal found
        if isinstance(item, dict):
            for key, child in item.items():
                if key.endswith("checks"):
                    found = True
                    if (
                        not isinstance(child, dict)
                        or not child
                        or not all(value is True for value in child.values())
                    ):
                        return False
                elif not visit(child):
                    return False
        elif isinstance(item, list):
            return all(visit(child) for child in item)
        return True

    return visit(value) and found


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = probability * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _bootstrap_interval(
    deltas: list[float], *, resamples: int, seed: int, alpha: float
) -> tuple[float, float]:
    rng = random.Random(seed)
    means = [statistics.fmean(rng.choices(deltas, k=len(deltas))) for _ in range(resamples)]
    return _percentile(means, alpha / 2), _percentile(means, 1 - alpha / 2)


def _exact_sign_flip_p(deltas: list[float]) -> float:
    observed = abs(statistics.fmean(deltas))
    values = (
        abs(statistics.fmean(sign * delta for sign, delta in zip(signs, deltas, strict=True)))
        for signs in itertools.product((-1.0, 1.0), repeat=len(deltas))
    )
    results = list(values)
    return sum(value >= observed - 1e-12 for value in results) / len(results)


__all__ = [
    "ExternalFormalStudyAdmission",
    "ExternalFormalStudyVerification",
    "prepare_external_formal_evaluation",
    "prepare_external_formal_result",
    "verify_external_formal_evaluation",
    "verify_external_formal_study",
]
