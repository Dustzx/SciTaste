"""AI-only operational review finality and objective title authority.

Operational review and scientific claim authority are deliberately separate.
An identity-distinct AI panel may finish an internal review node, while only
registered, scorer-owned, held-out objective results may authorize a strong
paper title.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.evaluation.evidence_program import IclrEvidenceProgram
from scitaste.evaluation.prelaunch import (
    AutomatedJudgeRole,
    ConfirmatoryEstimandKind,
    ScientificEndpointKind,
    load_prelaunch_manifest,
)
from scitaste.evaluation.results import EvaluationOutcomeAssessment
from scitaste.project import ProjectRuntime
from scitaste.project.models import content_sha256, validate_project_id

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_POLICY_BYTES = 1_048_576
_REQUIRED_FORBIDDEN_CLAIMS = {
    "human preference",
    "expert agreement",
    "expert-aligned scientific quality",
    "human-validated SciTasteBench",
    "general scientific-taste construct validity from AI-panel evidence alone",
}
_REQUIRED_ENDPOINT_OVERRIDES = {
    "H1_taste_abstraction": "ai-panel-and-natural-outcome-proxy",
    "H2_taste_specificity": "ai-panel-and-transfer-error-proxy",
    "H2b_taste_selection": "ai-panel-and-reversal-proxy",
    "H3_lifecycle_credit": "ai-panel-and-heldout-decision-proxy",
    "H4_objective_progress": "scorer-owned-objective-endpoint-unchanged",
}


class OperationalReviewNode(StrEnum):
    PROTOCOL = "protocol"
    SOURCE = "source"
    ABSTRACTION = "abstraction"
    OUTCOME_ATTRIBUTION = "outcome-attribution"
    PAPER_REVIEW = "paper-review"


class OperationalReviewRole(StrEnum):
    PRIMARY = "primary"
    ADJUDICATOR = "adjudicator"


class OperationalReviewVerdict(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"


_ALL_REVIEW_NODES = tuple(OperationalReviewNode)


class AIReviewFinalityPolicy(BaseModel):
    """Self-hashed v2 separation between review finality and title authority."""

    model_config = _CONFIG

    schema_version: Literal["2.0"] = "2.0"
    contract_id: str = Field(pattern=_ID)
    base_program_id: str = Field(pattern=_ID)
    base_program_proposal_sha256: str = Field(pattern=_SHA256)
    primary_role_count: Literal[2] = 2
    maximum_adjudicator_count: Literal[1] = 1
    require_distinct_reviewer_identities: Literal[True] = True
    require_distinct_models: Literal[True] = True
    require_distinct_run_identities: Literal[True] = True
    require_distinct_raw_responses: Literal[True] = True
    adjudication_trigger: Literal["primary-disagreement-only"] = "primary-disagreement-only"
    operationally_final_nodes: tuple[OperationalReviewNode, ...] = _ALL_REVIEW_NODES
    accepted_review_effect: Literal["close-node-and-admit-subject"] = "close-node-and-admit-subject"
    rejected_review_effect: Literal["close-node-and-block-subject"] = "close-node-and-block-subject"
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    human_validity_claim_allowed: Literal[False] = False
    human_review_required_to_close_node: Literal[False] = False
    human_staffing_gate_active: Literal[False] = False
    operational_readiness_override: Literal[
        "replace-reviewer-recruitment-with-ai-panel-completion"
    ] = "replace-reviewer-recruitment-with-ai-panel-completion"
    endpoint_overrides: dict[str, str] = Field(min_length=5, max_length=10)
    ai_panel_evidence_role: Literal["mechanism-and-proxy-only"] = "mechanism-and-proxy-only"
    ai_panel_can_authorize_title: Literal[False] = False
    title_authority_source: Literal["held-out-objective-scorer-only"] = (
        "held-out-objective-scorer-only"
    )
    candidate_title: str = Field(min_length=1, max_length=500)
    fallback_title: str = Field(min_length=1, max_length=500)
    required_title_claim_ids: tuple[str, ...] = Field(min_length=1, max_length=30)
    require_all_registered_title_critical_claims: Literal[True] = True
    require_all_positive_confirmatory_contrasts: Literal[True] = True
    require_formal_objective_endpoint: Literal[True] = True
    require_project_registered_complete_results: Literal[True] = True
    forbidden_claims: tuple[str, ...] = Field(min_length=5, max_length=30)
    authorizes_download: Literal[False] = False
    authorizes_api_calls: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False
    authorizes_execution: Literal[False] = False
    contract_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def policy_is_closed(self) -> AIReviewFinalityPolicy:
        if self.operationally_final_nodes != _ALL_REVIEW_NODES:
            raise ValueError("v2 AI review finality must cover every internal review node")
        if len(self.required_title_claim_ids) != len(set(self.required_title_claim_ids)):
            raise ValueError("required title claim IDs must be unique")
        if not _REQUIRED_FORBIDDEN_CLAIMS.issubset(self.forbidden_claims):
            raise ValueError("v2 AI review policy omits a required forbidden claim")
        if self.endpoint_overrides != _REQUIRED_ENDPOINT_OVERRIDES:
            raise ValueError("v2 AI review endpoint overrides differ from the active route")
        expected = content_sha256(self.model_dump(mode="json", exclude={"contract_sha256"}))
        if self.contract_sha256 != expected:
            raise ValueError("AI review finality policy hash differs")
        return self

    @classmethod
    def create(cls, **values: object) -> AIReviewFinalityPolicy:
        payload = {"schema_version": "2.0", **values}
        payload.pop("contract_sha256", None)
        payload["operationally_final_nodes"] = tuple(
            OperationalReviewNode(item)  # type: ignore[arg-type]
            for item in payload.get("operationally_final_nodes", _ALL_REVIEW_NODES)
        )
        payload["required_title_claim_ids"] = tuple(payload.get("required_title_claim_ids", ()))
        payload["forbidden_claims"] = tuple(payload.get("forbidden_claims", ()))
        unsigned = cls.model_construct(contract_sha256="0" * 64, **payload)
        return cls(
            **payload,
            contract_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"contract_sha256"})
            ),
        )


class AIReviewDecisionRecord(BaseModel):
    model_config = _CONFIG

    review_id: str = Field(pattern=_ID)
    role: OperationalReviewRole
    reviewer_id: str = Field(pattern=_ID)
    provider_id: str = Field(min_length=1, max_length=300)
    model_id: str = Field(min_length=1, max_length=500)
    model_revision: str = Field(min_length=1, max_length=500)
    run_id: str = Field(pattern=_ID)
    raw_response_sha256: str = Field(pattern=_SHA256)
    verdict: OperationalReviewVerdict
    completed_at: datetime
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True

    @model_validator(mode="after")
    def completion_has_timezone(self) -> AIReviewDecisionRecord:
        if self.completed_at.utcoffset() is None:
            raise ValueError("AI review completion time must include a timezone")
        return self

    @property
    def model_identity(self) -> tuple[str, str, str]:
        return self.provider_id, self.model_id, self.model_revision


class AIOperationalReviewClosure(BaseModel):
    """Terminal AI-only review record; rejection closes review but blocks admission."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    closure_id: str = Field(pattern=_ID)
    policy_contract_sha256: str = Field(pattern=_SHA256)
    node: OperationalReviewNode
    subject_locator: str = Field(min_length=1, max_length=2_000)
    subject_sha256: str = Field(pattern=_SHA256)
    primary_reviews: tuple[AIReviewDecisionRecord, AIReviewDecisionRecord]
    adjudicator_review: AIReviewDecisionRecord | None = None
    final_verdict: OperationalReviewVerdict
    operationally_final: Literal[True] = True
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    human_assessment_count: Literal[0] = 0
    human_validity_claim_allowed: Literal[False] = False
    human_review_required_to_close_node: Literal[False] = False
    human_or_expert_validity_claimed: Literal[False] = False
    closure_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def closure_is_terminal_and_independent(self) -> AIOperationalReviewClosure:
        primaries = self.primary_reviews
        if any(item.role is not OperationalReviewRole.PRIMARY for item in primaries):
            raise ValueError("operational review closure requires exactly two primary roles")
        for values, label in (
            ([item.review_id for item in primaries], "review"),
            ([item.reviewer_id for item in primaries], "reviewer"),
            ([item.model_identity for item in primaries], "model"),
            ([item.run_id for item in primaries], "run"),
            ([item.raw_response_sha256 for item in primaries], "raw response"),
        ):
            if len(set(values)) != 2:
                raise ValueError(f"AI primary {label} identities must be distinct")
        split = primaries[0].verdict is not primaries[1].verdict
        if split != (self.adjudicator_review is not None):
            raise ValueError("AI adjudication is required if and only if primaries disagree")
        if self.adjudicator_review is not None:
            adjudicator = self.adjudicator_review
            if adjudicator.role is not OperationalReviewRole.ADJUDICATOR:
                raise ValueError("disagreement resolver must have the adjudicator role")
            if adjudicator.reviewer_id in {item.reviewer_id for item in primaries}:
                raise ValueError("AI adjudicator must have a distinct reviewer identity")
            if adjudicator.model_identity in {item.model_identity for item in primaries}:
                raise ValueError("AI adjudicator must have a distinct model identity")
            if adjudicator.run_id in {item.run_id for item in primaries}:
                raise ValueError("AI adjudicator must have a distinct run identity")
            if adjudicator.raw_response_sha256 in {item.raw_response_sha256 for item in primaries}:
                raise ValueError("AI adjudicator must have a distinct raw response")
            expected_verdict = adjudicator.verdict
        else:
            expected_verdict = primaries[0].verdict
        if self.final_verdict is not expected_verdict:
            raise ValueError("final review verdict differs from the closed panel")
        expected = content_sha256(self.model_dump(mode="json", exclude={"closure_sha256"}))
        if self.closure_sha256 != expected:
            raise ValueError("AI operational review closure hash differs")
        return self


class ObjectiveClaimRegistration(BaseModel):
    model_config = _CONFIG

    claim_id: str = Field(pattern=_ID)
    study_id: str = Field(pattern=_ID)
    evaluation_id: str = Field(pattern=_ID)
    planned_result_id: str = Field(pattern=_ID)
    prelaunch_manifest_file_sha256: str = Field(pattern=_SHA256)
    prelaunch_proposal_sha256: str = Field(pattern=_SHA256)


class ObjectiveTitleEvidenceRegistration(BaseModel):
    """Prospective claim-to-prelaunch bindings later resolved through project results."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    registration_id: str = Field(pattern=_ID)
    policy_contract_sha256: str = Field(pattern=_SHA256)
    program_id: str = Field(pattern=_ID)
    program_proposal_sha256: str = Field(pattern=_SHA256)
    project_id: str
    registered_at: datetime
    claims: tuple[ObjectiveClaimRegistration, ...] = Field(min_length=1, max_length=30)
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    human_validity_claim_allowed: Literal[False] = False
    title_authority_claimed_at_registration: Literal[False] = False
    registration_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def registration_is_prospective_and_closed(self) -> ObjectiveTitleEvidenceRegistration:
        validate_project_id(self.project_id)
        if self.registered_at.utcoffset() is None:
            raise ValueError("objective title registration time must include a timezone")
        for values, label in (
            ([item.claim_id for item in self.claims], "claim"),
            ([item.study_id for item in self.claims], "study"),
            ([item.evaluation_id for item in self.claims], "evaluation"),
            ([item.planned_result_id for item in self.claims], "result"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"objective title {label} registrations must be unique")
        expected = content_sha256(self.model_dump(mode="json", exclude={"registration_sha256"}))
        if self.registration_sha256 != expected:
            raise ValueError("objective title evidence registration hash differs")
        return self


class TitleAuthorityFinding(BaseModel):
    model_config = _CONFIG

    code: str = Field(pattern=r"^[a-z0-9]+(?:[a-z0-9_:.-]*[a-z0-9])?$")
    message: str = Field(min_length=1, max_length=4_000)


class ObjectiveTitleAuthorityReport(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    policy_contract_sha256: str = Field(pattern=_SHA256)
    program_proposal_sha256: str = Field(pattern=_SHA256)
    registration_sha256: str = Field(pattern=_SHA256)
    project_id: str
    required_title_claim_ids: tuple[str, ...]
    verified_positive_claim_ids: tuple[str, ...]
    all_title_critical_claims_registered: bool
    all_registered_results_complete: bool
    all_confirmatory_contrasts_positive: bool
    heldout_objective_scorer_only: Literal[True] = True
    ai_panel_used_as_title_authority: Literal[False] = False
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    human_validity_claim_allowed: Literal[False] = False
    objective_title_authorized: bool
    active_title: str
    findings: tuple[TitleAuthorityFinding, ...]
    report_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def authority_matches_evidence(self) -> ObjectiveTitleAuthorityReport:
        expected_authorized = (
            not self.findings
            and set(self.verified_positive_claim_ids) == set(self.required_title_claim_ids)
            and self.all_title_critical_claims_registered
            and self.all_registered_results_complete
            and self.all_confirmatory_contrasts_positive
        )
        if self.objective_title_authorized != expected_authorized:
            raise ValueError("objective title authority differs from its evidence gates")
        expected = content_sha256(self.model_dump(mode="json", exclude={"report_sha256"}))
        if self.report_sha256 != expected:
            raise ValueError("objective title authority report hash differs")
        return self


def load_ai_review_finality_policy(path: str | Path) -> AIReviewFinalityPolicy:
    return AIReviewFinalityPolicy.model_validate(_load_yaml(path, "AI review finality policy"))


def load_ai_operational_review_closure(path: str | Path) -> AIOperationalReviewClosure:
    return AIOperationalReviewClosure.model_validate(
        _load_yaml(path, "AI operational review closure")
    )


def load_objective_title_evidence_registration(
    path: str | Path,
) -> ObjectiveTitleEvidenceRegistration:
    return ObjectiveTitleEvidenceRegistration.model_validate(
        _load_yaml(path, "objective title evidence registration")
    )


def inspect_ai_operational_review_closure(
    policy: AIReviewFinalityPolicy,
    closure: AIOperationalReviewClosure,
) -> AIOperationalReviewClosure:
    """Verify that a valid panel closes one internal node without claim inflation."""

    if closure.policy_contract_sha256 != policy.contract_sha256:
        raise ValueError("AI operational closure binds another finality policy")
    if closure.node not in policy.operationally_final_nodes:
        raise ValueError("AI operational closure node is outside policy authority")
    return closure


def inspect_objective_title_authority(
    policy: AIReviewFinalityPolicy,
    program: IclrEvidenceProgram,
    registration: ObjectiveTitleEvidenceRegistration,
    *,
    outputs_root: str | Path,
) -> ObjectiveTitleAuthorityReport:
    """Resolve preregistered claims through project-owned formal objective results."""

    findings: list[TitleAuthorityFinding] = []
    required = tuple(policy.required_title_claim_ids)
    program_title_claims = tuple(item.claim_id for item in program.claims if item.title_critical)
    if (
        policy.base_program_id != program.program_id
        or policy.base_program_proposal_sha256 != program.proposal_sha256
    ):
        _add(findings, "program:policy-binding", "policy binds another evidence program")
    if (
        registration.policy_contract_sha256 != policy.contract_sha256
        or registration.program_id != program.program_id
        or registration.program_proposal_sha256 != program.proposal_sha256
    ):
        _add(findings, "registration:authority-binding", "registration authority differs")
    registered_ids = tuple(item.claim_id for item in registration.claims)
    title_critical_registered = set(registered_ids) == set(program_title_claims) == set(required)
    if not title_critical_registered:
        _add(
            findings,
            "registration:title-claim-coverage",
            "registration must cover every and only title-critical program claim",
        )

    runtime = ProjectRuntime(outputs_root)
    try:
        snapshot = runtime.open(registration.project_id)
    except (OSError, ValueError) as exc:
        _add(findings, "project:unavailable", f"registered project cannot be opened: {exc}")
        snapshot = None
    if snapshot is not None and snapshot.warnings:
        _add(findings, "project:integrity-warning", "; ".join(snapshot.warnings))

    claims_by_id = {item.claim_id: item for item in program.claims}
    studies_by_id = {item.study_id: item for item in program.study_layers}
    verified_positive: list[str] = []
    complete = True
    all_positive = True
    for binding in registration.claims:
        claim = claims_by_id.get(binding.claim_id)
        study = studies_by_id.get(binding.study_id)
        if claim is None or not claim.title_critical or binding.study_id not in claim.study_ids:
            _add(
                findings,
                f"claim:{binding.claim_id}:program-mapping",
                "registered claim/study is not a title-critical program mapping",
            )
            complete = False
            all_positive = False
            continue
        if study is None or binding.claim_id not in study.claim_ids:
            _add(
                findings,
                f"claim:{binding.claim_id}:study-mapping",
                "registered study does not reciprocally bind the claim",
            )
            complete = False
            all_positive = False
            continue
        if snapshot is None:
            complete = False
            all_positive = False
            continue
        try:
            evaluation = runtime.open_evaluation(registration.project_id, binding.evaluation_id)
            result = runtime.open_evaluation_result(
                registration.project_id, binding.planned_result_id
            )
            if result.evaluation_id != binding.evaluation_id:
                raise ValueError("registered result belongs to another evaluation")
            project_root = runtime.projects_root / registration.project_id
            prelaunch_path = (
                project_root
                / "evaluations"
                / binding.evaluation_id
                / evaluation.files["prelaunch_manifest"].locator
            )
            raw_prelaunch = prelaunch_path.read_bytes()
            if hashlib.sha256(raw_prelaunch).hexdigest() != binding.prelaunch_manifest_file_sha256:
                raise ValueError("prelaunch manifest file hash differs from registration")
            prelaunch = load_prelaunch_manifest(prelaunch_path).manifest
            if prelaunch.proposal_sha256 != binding.prelaunch_proposal_sha256:
                raise ValueError("prelaunch proposal hash differs from registration")
            if result.proposal_sha256 != prelaunch.proposal_sha256:
                raise ValueError("registered result differs from preregistered proposal")
            if (
                prelaunch.evidence_program is None
                or prelaunch.evidence_program.program_id != program.program_id
                or prelaunch.evidence_program.proposal_sha256 != program.proposal_sha256
            ):
                raise ValueError("prelaunch does not bind the title evidence program")
            if (
                prelaunch.study_scope != "formal"
                or prelaunch.primary_endpoint is not ScientificEndpointKind.OBJECTIVE_PROGRESS
                or prelaunch.automated_judge_role is AutomatedJudgeRole.CALIBRATED_PRIMARY
                or prelaunch.analysis is None
                or prelaunch.analysis.claim_admission is None
            ):
                raise ValueError("title claim lacks formal objective claim-admission semantics")
            claim_admission = prelaunch.analysis.claim_admission
            claim_lane = next(
                (item for item in prelaunch.lanes if item.lane_id == claim_admission.lane_id),
                None,
            )
            if claim_lane is None:
                raise ValueError("objective claim-admission lane is absent")
            tasks = {item.task_id: item for item in prelaunch.tasks}
            if any(
                not tasks[task_id].held_out or not tasks[task_id].source_group_disjoint
                for task_id in claim_lane.task_ids
            ):
                raise ValueError(
                    "title authority requires held-out source-group-disjoint claim-lane tasks"
                )
            approved_at = _approved_at(prelaunch.approval.approved_at)
            if not prelaunch.approval.approved or registration.registered_at > approved_at:
                raise ValueError("title claim was not registered before prelaunch approval")
            result_dir = project_root / "evaluation-results" / binding.planned_result_id
            assessment_path = result_dir / result.files["assessment"].locator
            assessment = EvaluationOutcomeAssessment.model_validate_json(
                assessment_path.read_bytes()
            )
            _require_positive_objective_assessment(assessment)
        except (KeyError, OSError, ValueError) as exc:
            _add(findings, f"claim:{binding.claim_id}:objective-evidence", str(exc))
            complete = False
            all_positive = False
            continue
        verified_positive.append(binding.claim_id)

    authorized = (
        not findings
        and title_critical_registered
        and complete
        and all_positive
        and set(verified_positive) == set(required)
    )
    payload = {
        "schema_version": "1.0",
        "policy_contract_sha256": policy.contract_sha256,
        "program_proposal_sha256": program.proposal_sha256,
        "registration_sha256": registration.registration_sha256,
        "project_id": registration.project_id,
        "required_title_claim_ids": required,
        "verified_positive_claim_ids": tuple(verified_positive),
        "all_title_critical_claims_registered": title_critical_registered,
        "all_registered_results_complete": complete,
        "all_confirmatory_contrasts_positive": all_positive,
        "heldout_objective_scorer_only": True,
        "ai_panel_used_as_title_authority": False,
        "reviewer_kind": "ai",
        "not_human_review": True,
        "human_validity_claim_allowed": False,
        "objective_title_authorized": authorized,
        "active_title": policy.candidate_title if authorized else policy.fallback_title,
        "findings": tuple(findings),
    }
    unsigned = ObjectiveTitleAuthorityReport.model_construct(
        **payload,
        report_sha256="0" * 64,
    )
    return ObjectiveTitleAuthorityReport(
        **payload,
        report_sha256=content_sha256(unsigned.model_dump(mode="json", exclude={"report_sha256"})),
    )


def _require_positive_objective_assessment(assessment: EvaluationOutcomeAssessment) -> None:
    if assessment.schema_version != "1.2":
        raise ValueError("title authority requires explicit confirmatory comparison counts")
    if (
        assessment.status != "complete"
        or not assessment.scientific_evidence_complete
        or not assessment.headline_eligible
        or not assessment.scientific_effectiveness_established
        or not assessment.title_claim_eligible
        or not assessment.confirmatory_evidence_complete
        or not assessment.confirmatory_conclusion_supported
        or assessment.confirmatory_estimand_kind
        not in {
            ConfirmatoryEstimandKind.NATIVE_TASTE_CAUSAL,
            ConfirmatoryEstimandKind.NATIVE_TASTE_MECHANISMS,
        }
        or assessment.required_confirmatory_comparisons is None
        or assessment.required_confirmatory_comparisons < 1
        or assessment.supported_confirmatory_comparisons
        != assessment.required_confirmatory_comparisons
        or assessment.valid_confirmatory_comparisons != assessment.required_confirmatory_comparisons
    ):
        raise ValueError("objective result is incomplete or does not support every causal contrast")


def _approved_at(value: str | None) -> datetime:
    if value is None:
        raise ValueError("approved objective prelaunch lacks an approval timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("objective prelaunch approval timestamp lacks a timezone")
    return parsed


def _load_yaml(path: str | Path, label: str) -> dict[str, object]:
    requested = Path(path)
    if requested.is_symlink():
        raise ValueError(f"{label} must not be a symlink")
    resolved = requested.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size > _MAX_POLICY_BYTES:
        raise ValueError(f"{label} must be a bounded regular file")
    payload = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a YAML mapping")
    return payload


def _add(findings: list[TitleAuthorityFinding], code: str, message: str) -> None:
    findings.append(TitleAuthorityFinding(code=code, message=message))


__all__ = [
    "AIOperationalReviewClosure",
    "AIReviewDecisionRecord",
    "AIReviewFinalityPolicy",
    "ObjectiveClaimRegistration",
    "ObjectiveTitleAuthorityReport",
    "ObjectiveTitleEvidenceRegistration",
    "OperationalReviewNode",
    "OperationalReviewRole",
    "OperationalReviewVerdict",
    "TitleAuthorityFinding",
    "inspect_ai_operational_review_closure",
    "inspect_objective_title_authority",
    "load_ai_operational_review_closure",
    "load_ai_review_finality_policy",
    "load_objective_title_evidence_registration",
]
