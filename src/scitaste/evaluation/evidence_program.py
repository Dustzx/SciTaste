"""Resource-independent scientific program and staged operational admission."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from scitaste.evaluation.resources import (
    EvaluationResourceKind,
    ExternalResourceCorpus,
    ResourceGateName,
    ResourceGateStatus,
    ResourceUse,
    evaluate_resource_feasibility,
    load_external_resource_corpus,
)

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_PROGRAM_BYTES = 1_048_576


class EvidenceHypothesis(StrEnum):
    TASTE_ABSTRACTION = "H1_taste_abstraction"
    TASTE_SPECIFICITY = "H2_taste_specificity"
    NATIVE_EFFECT = "H3_native_effect"
    ECOLOGICAL_COMPARISON = "E1_ecological_comparison"
    INTEGRITY_DIAGNOSTIC = "D1_integrity_diagnostic"
    SELF_DEVELOPMENT = "P1_self_development"


class EvidenceLayer(StrEnum):
    DECISION_MECHANISM = "decision_mechanism"
    OBJECTIVE_PROGRESS = "objective_progress"
    FULL_LIFECYCLE = "full_lifecycle"
    EXPERIMENT_INTEGRITY = "experiment_integrity"
    PROCESS_CASE = "process_case"


class InferenceRole(StrEnum):
    CONFIRMATORY = "confirmatory"
    SUPPORTING = "supporting"
    DIAGNOSTIC = "diagnostic"
    PROCESS_ONLY = "process_only"


class ProgramConditionKind(StrEnum):
    FULL_SCITASTE = "full_scitaste"
    MATCHED_TASTE = "matched_abstracted_taste"
    RAW_SOURCE_RAG = "raw_source_rag"
    MISMATCHED_TASTE = "source_disjoint_mismatched_taste"
    NATIVE_BASE = "native_base"
    DIRECT_TOOL_AGENT = "direct_tool_agent"


class TaskSourceRole(StrEnum):
    DECISION_CASES = "decision_cases"
    OBJECTIVE_PROGRESS = "objective_progress"
    FULL_LIFECYCLE = "full_lifecycle"
    INTEGRITY_DIAGNOSTIC = "integrity_diagnostic"
    PROCESS_CASE = "process_case"


class FormalSourceRole(StrEnum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    DIAGNOSTIC = "diagnostic"
    CONTINGENT = "contingent"
    CONSTRUCTION_TARGET = "construction_target"


class ReadinessStatus(StrEnum):
    PENDING = "pending"
    VERIFIED = "verified"
    BLOCKED = "blocked"


class FindingPhase(StrEnum):
    SCIENTIFIC = "scientific"
    ACQUISITION = "acquisition"
    EXPERIMENT = "experiment"
    AUTHORIZATION = "authorization"


class PaperClaim(BaseModel):
    model_config = _CONFIG

    claim_id: str = Field(pattern=_ID)
    statement: str = Field(min_length=1, max_length=2_000)
    title_critical: bool
    study_ids: tuple[str, ...] = Field(min_length=1, max_length=20)


class ProgramCondition(BaseModel):
    model_config = _CONFIG

    condition_id: str = Field(pattern=_ID)
    kind: ProgramConditionKind
    intervention: str = Field(min_length=1, max_length=2_000)
    keeps_fixed: tuple[str, ...] = Field(min_length=1, max_length=30)


class TaskSourceCandidate(BaseModel):
    model_config = _CONFIG

    source_id: str = Field(pattern=_ID)
    role: TaskSourceRole
    formal_role: FormalSourceRole
    resource_id: str | None = Field(default=None, pattern=_ID)
    accepted_venue: str | None = Field(default=None, max_length=300)
    selection_basis: Literal["scientific_fit"] = "scientific_fit"
    selected_for_acquisition_proposal: bool
    rationale: str = Field(min_length=1, max_length=2_000)


class ExternalMethodCandidate(BaseModel):
    model_config = _CONFIG

    system_id: str = Field(pattern=_ID)
    resource_id: str | None = Field(default=None, pattern=_ID)
    accepted_venue: str = Field(min_length=1, max_length=300)
    accepted_archival_method: Literal[True] = True
    selection_basis: Literal["scientific_relevance"] = "scientific_relevance"
    selected_for_adapter_proposal: bool
    rationale: str = Field(min_length=1, max_length=2_000)


class EvidenceStudy(BaseModel):
    model_config = _CONFIG

    study_id: str = Field(pattern=_ID)
    hypothesis: EvidenceHypothesis
    layer: EvidenceLayer
    inference_role: InferenceRole
    claim_ids: tuple[str, ...] = Field(default=(), max_length=20)
    condition_ids: tuple[str, ...] = Field(min_length=1, max_length=20)
    task_source_ids: tuple[str, ...] = Field(min_length=1, max_length=20)
    system_candidate_ids: tuple[str, ...] = Field(default=(), max_length=20)
    primary_endpoint: str = Field(min_length=1, max_length=2_000)
    estimand: str = Field(min_length=1, max_length=2_000)
    experimental_unit: str = Field(min_length=1, max_length=1_000)
    matched_backbone: bool
    matched_starting_information: bool
    matched_tool_permissions: bool
    matched_repair_policy: bool
    final_paper_required: bool

    @model_validator(mode="after")
    def references_are_unique(self) -> EvidenceStudy:
        for values, label in (
            (self.claim_ids, "claim"),
            (self.condition_ids, "condition"),
            (self.task_source_ids, "task source"),
            (self.system_candidate_ids, "system candidate"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"study {label} references must be unique")
        return self


class ModelSelectionPolicy(BaseModel):
    model_config = _CONFIG

    inventory_can_select_scientific_design: Literal[False] = False
    primary_model_id: str | None = Field(default=None, max_length=300)
    primary_selection_stage: Literal["after_conformance_pilot"]
    selection_criteria: tuple[str, ...] = Field(min_length=3, max_length=30)
    matched_within_confirmatory_study: Literal[True] = True
    robustness_provider_non_pooled: Literal[True] = True
    local_models_role: Literal["capacity_and_robustness_candidates"]


class SamplingPolicy(BaseModel):
    model_config = _CONFIG

    sample_size_basis: Literal["pilot_then_power_analysis"]
    fixed_formal_sample_size: None = None
    fixed_repetitions: None = None
    independent_unit: Literal["held_out_task"]
    source_group_split_required: Literal[True] = True
    intention_to_run: Literal[True] = True
    failures_are_outcomes: Literal[True] = True
    pilot_data_excluded_from_formal_test: Literal[True] = True


class HumanReviewPolicy(BaseModel):
    model_config = _CONFIG

    minimum_independent_reviewers: int = Field(ge=2, le=20)
    condition_blinded: Literal[True] = True
    conflict_screening: Literal[True] = True
    adjudication: Literal[True] = True
    automated_judge_role: Literal["secondary_calibrated_measure"]
    judge_validation_required: Literal[True] = True


class OperationalReadiness(BaseModel):
    model_config = _CONFIG

    task_subset_freeze: ReadinessStatus
    task_data_acquisition: ReadinessStatus
    adapter_preflight: ReadinessStatus
    model_conformance_pilot: ReadinessStatus
    power_analysis: ReadinessStatus
    reviewer_recruitment: ReadinessStatus
    judge_validation: ReadinessStatus


class ProgramApproval(BaseModel):
    model_config = _CONFIG

    approved: bool = False
    approved_program_sha256: str | None = Field(default=None, pattern=_SHA256)
    approved_by: str | None = Field(default=None, max_length=300)
    approved_at: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def approval_is_hash_bound(self) -> ProgramApproval:
        details = (self.approved_program_sha256, self.approved_by, self.approved_at)
        if self.approved and not all(details):
            raise ValueError("approved evidence programs require hash-bound attribution")
        if not self.approved and any(details):
            raise ValueError("unapproved evidence programs cannot carry approval details")
        return self


class IclrEvidenceProgram(BaseModel):
    """Scientific commitments that remain stable as operational resources change."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    program_id: str = Field(pattern=_ID)
    paper_title: str = Field(min_length=1, max_length=500)
    target_venue: Literal["ICLR 2027"]
    design_authority: Literal["scientific_question_not_available_inventory"]
    resource_corpus_sha256: str = Field(pattern=_SHA256)
    claims: tuple[PaperClaim, ...] = Field(min_length=3, max_length=30)
    conditions: tuple[ProgramCondition, ...] = Field(min_length=6, max_length=30)
    task_sources: tuple[TaskSourceCandidate, ...] = Field(min_length=4, max_length=30)
    system_candidates: tuple[ExternalMethodCandidate, ...] = Field(min_length=2, max_length=30)
    study_layers: tuple[EvidenceStudy, ...] = Field(min_length=4, max_length=30)
    model_policy: ModelSelectionPolicy
    sampling_policy: SamplingPolicy
    human_review: HumanReviewPolicy
    operational_readiness: OperationalReadiness
    approval: ProgramApproval = Field(default_factory=ProgramApproval)
    authorizes_download: Literal[False] = False
    authorizes_api_calls: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False
    authorizes_execution: Literal[False] = False

    @model_validator(mode="after")
    def references_are_closed(self) -> IclrEvidenceProgram:
        groups = (
            ([item.claim_id for item in self.claims], "claim"),
            ([item.condition_id for item in self.conditions], "condition"),
            ([item.source_id for item in self.task_sources], "task source"),
            ([item.system_id for item in self.system_candidates], "external method"),
            ([item.study_id for item in self.study_layers], "study"),
        )
        for values, label in groups:
            if len(values) != len(set(values)):
                raise ValueError(f"evidence-program {label} IDs must be unique")
        claim_ids = {item.claim_id for item in self.claims}
        condition_ids = {item.condition_id for item in self.conditions}
        source_ids = {item.source_id for item in self.task_sources}
        system_ids = {item.system_id for item in self.system_candidates}
        study_ids = {item.study_id for item in self.study_layers}
        hypotheses = [item.hypothesis for item in self.study_layers]
        if len(hypotheses) != len(set(hypotheses)):
            raise ValueError("evidence-program hypotheses must be unique")
        studies_by_id = {item.study_id: item for item in self.study_layers}
        for claim in self.claims:
            if set(claim.study_ids) - study_ids:
                raise ValueError(f"claim {claim.claim_id} references unknown studies")
            if any(claim.claim_id not in studies_by_id[item].claim_ids for item in claim.study_ids):
                raise ValueError(f"claim {claim.claim_id} and study references must be reciprocal")
        for study in self.study_layers:
            if set(study.claim_ids) - claim_ids:
                raise ValueError(f"study {study.study_id} references unknown claims")
            if set(study.condition_ids) - condition_ids:
                raise ValueError(f"study {study.study_id} references unknown conditions")
            if set(study.task_source_ids) - source_ids:
                raise ValueError(f"study {study.study_id} references unknown task sources")
            if set(study.system_candidate_ids) - system_ids:
                raise ValueError(f"study {study.study_id} references unknown system candidates")
            linked_claims = [claim for claim in self.claims if claim.claim_id in study.claim_ids]
            if any(study.study_id not in claim.study_ids for claim in linked_claims):
                raise ValueError(f"study {study.study_id} and claim references must be reciprocal")
        return self

    @property
    def external_methods(self) -> tuple[ExternalMethodCandidate, ...]:
        """Return method candidates without conflating them with task benchmarks."""

        return self.system_candidates

    @property
    def studies(self) -> tuple[EvidenceStudy, ...]:
        """Compatibility view over the canonical layered evidence architecture."""

        return self.study_layers

    @computed_field
    @property
    def proposal_sha256(self) -> str:
        payload = self.model_dump(
            mode="json",
            exclude={"approval", "proposal_sha256", "resource_corpus_sha256"},
        )
        return _canonical_sha256(payload)


class EvidenceProgramFinding(BaseModel):
    model_config = _CONFIG

    phase: FindingPhase
    code: str = Field(pattern=_ID)
    message: str = Field(min_length=1, max_length=2_000)


class EvidenceProgramReport(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    program_id: str
    program_sha256: str = Field(pattern=_SHA256)
    resource_corpus_id: str
    resource_corpus_sha256: str = Field(pattern=_SHA256)
    scientifically_coherent: bool
    ready_for_acquisition_proposal: bool
    ready_for_experiment: bool
    execution_authorized: bool
    scientific_findings: tuple[EvidenceProgramFinding, ...]
    acquisition_findings: tuple[EvidenceProgramFinding, ...]
    experiment_findings: tuple[EvidenceProgramFinding, ...]
    authorization_findings: tuple[EvidenceProgramFinding, ...]

    @property
    def scientific_blockers(self) -> tuple[EvidenceProgramFinding, ...]:
        return _translate_findings(
            self.scientific_findings,
            {
                "method_is_not_system": "benchmark_used_as_system",
                "self_case_in_confirmatory_evidence": "self_case_in_inference",
            },
        )

    @property
    def acquisition_blockers(self) -> tuple[EvidenceProgramFinding, ...]:
        return _translate_findings(
            self.acquisition_findings,
            {
                "task_source_unpinned": "task_source_not_resource_bound",
                "task_source_dataset_license_not_verified": ("task_source_dataset_license_blocked"),
            },
        )

    @property
    def experiment_blockers(self) -> tuple[EvidenceProgramFinding, ...]:
        return _translate_findings(
            self.experiment_findings,
            {
                "readiness_power_analysis": "power_not_frozen",
                "readiness_reviewer_recruitment": "reviewers_not_recruited",
                "readiness_judge_validation": "judge_not_validated",
            },
        )

    @property
    def authorization_blockers(self) -> tuple[EvidenceProgramFinding, ...]:
        return _translate_findings(
            self.authorization_findings,
            {"explicit_owner_approval_required": "owner_approval_required"},
        )


class EvidenceProgramInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    program: IclrEvidenceProgram
    report: EvidenceProgramReport | None = None

    def __getitem__(self, index: int):
        return (self.path, self.file_sha256, self.program)[index]

    def _require_report(self) -> EvidenceProgramReport:
        if self.report is None:
            raise ValueError("evidence program has not been inspected against a resource corpus")
        return self.report

    @property
    def scientifically_coherent(self) -> bool:
        return self._require_report().scientifically_coherent

    @property
    def ready_for_acquisition_proposal(self) -> bool:
        return self._require_report().ready_for_acquisition_proposal

    @property
    def ready_for_experiment(self) -> bool:
        return self._require_report().ready_for_experiment

    @property
    def execution_authorized(self) -> bool:
        return self._require_report().execution_authorized

    @property
    def scientific_blockers(self) -> tuple[EvidenceProgramFinding, ...]:
        return self._require_report().scientific_blockers

    @property
    def acquisition_blockers(self) -> tuple[EvidenceProgramFinding, ...]:
        return self._require_report().acquisition_blockers

    @property
    def experiment_blockers(self) -> tuple[EvidenceProgramFinding, ...]:
        return self._require_report().experiment_blockers

    @property
    def authorization_blockers(self) -> tuple[EvidenceProgramFinding, ...]:
        return self._require_report().authorization_blockers


def load_evidence_program(path: str | Path) -> EvidenceProgramInspection:
    requested = Path(path)
    if requested.is_symlink():
        raise ValueError("evidence program must not be a symlink")
    resolved = requested.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size > _MAX_PROGRAM_BYTES:
        raise ValueError("evidence program must be a bounded regular file")
    raw = resolved.read_bytes()
    try:
        payload = yaml.safe_load(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ValueError("evidence program must be UTF-8") from exc
    if not isinstance(payload, dict):
        raise ValueError("evidence program must contain a YAML mapping")
    return EvidenceProgramInspection(
        path=resolved,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        program=IclrEvidenceProgram.model_validate(payload),
    )


def inspect_evidence_program(
    path: str | Path | IclrEvidenceProgram,
    resource_corpus_path: str | Path | ExternalResourceCorpus,
) -> EvidenceProgramInspection | EvidenceProgramReport:
    """Evaluate scientific coherence before mutable operational feasibility."""

    in_memory = isinstance(path, IclrEvidenceProgram)
    if in_memory:
        program = path
        resolved = Path("<in-memory-evidence-program>")
        file_sha256 = program.proposal_sha256
    else:
        loaded = load_evidence_program(path)
        program = loaded.program
        resolved = loaded.path
        file_sha256 = loaded.file_sha256
    if isinstance(resource_corpus_path, ExternalResourceCorpus):
        corpus = resource_corpus_path
    else:
        corpus = load_external_resource_corpus(resource_corpus_path).corpus
    scientific = _scientific_findings(program, corpus)
    acquisition = _acquisition_findings(program, corpus)
    experiment = _experiment_findings(program, corpus)
    authorization = _authorization_findings(program)
    scientifically_coherent = not scientific
    ready_for_acquisition = scientifically_coherent and not acquisition
    ready_for_experiment = ready_for_acquisition and not experiment
    execution_authorized = ready_for_experiment and not authorization
    report = EvidenceProgramReport(
        program_id=program.program_id,
        program_sha256=program.proposal_sha256,
        resource_corpus_id=corpus.corpus_id,
        resource_corpus_sha256=corpus.semantic_sha256,
        scientifically_coherent=scientifically_coherent,
        ready_for_acquisition_proposal=ready_for_acquisition,
        ready_for_experiment=ready_for_experiment,
        execution_authorized=execution_authorized,
        scientific_findings=tuple(scientific),
        acquisition_findings=tuple(acquisition),
        experiment_findings=tuple(experiment),
        authorization_findings=tuple(authorization),
    )
    inspection = EvidenceProgramInspection(
        path=resolved,
        file_sha256=file_sha256,
        program=program,
        report=report,
    )
    return report if in_memory else inspection


def _scientific_findings(
    program: IclrEvidenceProgram,
    corpus: ExternalResourceCorpus,
) -> list[EvidenceProgramFinding]:
    findings: list[EvidenceProgramFinding] = []
    studies = {item.hypothesis: item for item in program.study_layers}
    conditions = {item.condition_id: item.kind for item in program.conditions}
    sources = {item.source_id: item for item in program.task_sources}
    resources = {item.resource_id: item for item in corpus.resources}
    required = {
        EvidenceHypothesis.TASTE_ABSTRACTION: {
            ProgramConditionKind.MATCHED_TASTE,
            ProgramConditionKind.RAW_SOURCE_RAG,
        },
        EvidenceHypothesis.TASTE_SPECIFICITY: {
            ProgramConditionKind.MATCHED_TASTE,
            ProgramConditionKind.MISMATCHED_TASTE,
        },
        EvidenceHypothesis.NATIVE_EFFECT: {
            ProgramConditionKind.FULL_SCITASTE,
            ProgramConditionKind.NATIVE_BASE,
        },
    }
    expected_layers = {
        EvidenceHypothesis.TASTE_ABSTRACTION: EvidenceLayer.DECISION_MECHANISM,
        EvidenceHypothesis.TASTE_SPECIFICITY: EvidenceLayer.DECISION_MECHANISM,
        EvidenceHypothesis.NATIVE_EFFECT: EvidenceLayer.OBJECTIVE_PROGRESS,
        EvidenceHypothesis.ECOLOGICAL_COMPARISON: EvidenceLayer.FULL_LIFECYCLE,
        EvidenceHypothesis.INTEGRITY_DIAGNOSTIC: EvidenceLayer.EXPERIMENT_INTEGRITY,
        EvidenceHypothesis.SELF_DEVELOPMENT: EvidenceLayer.PROCESS_CASE,
    }
    expected_source_roles = {
        EvidenceLayer.DECISION_MECHANISM: TaskSourceRole.DECISION_CASES,
        EvidenceLayer.OBJECTIVE_PROGRESS: TaskSourceRole.OBJECTIVE_PROGRESS,
        EvidenceLayer.FULL_LIFECYCLE: TaskSourceRole.FULL_LIFECYCLE,
        EvidenceLayer.EXPERIMENT_INTEGRITY: TaskSourceRole.INTEGRITY_DIAGNOSTIC,
        EvidenceLayer.PROCESS_CASE: TaskSourceRole.PROCESS_CASE,
    }
    for study in program.study_layers:
        if study.layer is not expected_layers[study.hypothesis]:
            findings.append(
                _finding(
                    FindingPhase.SCIENTIFIC,
                    "hypothesis_layer_mismatch",
                    study.study_id,
                )
            )
        expected_source_role = expected_source_roles[study.layer]
        for source_id in study.task_source_ids:
            if sources[source_id].role is not expected_source_role:
                findings.append(
                    _finding(
                        FindingPhase.SCIENTIFIC,
                        "task_source_role_mismatch",
                        f"{source_id} cannot serve {study.layer.value}",
                    )
                )
        if study.layer is EvidenceLayer.FULL_LIFECYCLE and not study.final_paper_required:
            findings.append(
                _finding(
                    FindingPhase.SCIENTIFIC,
                    "full_lifecycle_without_paper",
                    study.study_id,
                )
            )
        if (
            study.hypothesis is EvidenceHypothesis.SELF_DEVELOPMENT
            and study.inference_role is not InferenceRole.PROCESS_ONLY
        ):
            findings.append(
                _finding(
                    FindingPhase.SCIENTIFIC,
                    "self_case_in_confirmatory_evidence",
                    study.study_id,
                )
            )
    for hypothesis, required_conditions in required.items():
        study = studies.get(hypothesis)
        if study is None:
            findings.append(
                _finding(
                    FindingPhase.SCIENTIFIC,
                    "missing_required_hypothesis",
                    hypothesis,
                )
            )
            continue
        observed = {conditions[item] for item in study.condition_ids}
        if not required_conditions <= observed:
            findings.append(
                _finding(
                    FindingPhase.SCIENTIFIC,
                    "missing_required_contrast",
                    (
                        f"{hypothesis.value} lacks "
                        f"{sorted(item.value for item in required_conditions - observed)}"
                    ),
                )
            )
        if study.inference_role is not InferenceRole.CONFIRMATORY:
            findings.append(
                _finding(
                    FindingPhase.SCIENTIFIC,
                    "title_hypothesis_not_confirmatory",
                    f"{hypothesis.value} must be confirmatory",
                )
            )
        if not all(
            (
                study.matched_backbone,
                study.matched_starting_information,
                study.matched_tool_permissions,
                study.matched_repair_policy,
            )
        ):
            findings.append(
                _finding(
                    FindingPhase.SCIENTIFIC,
                    "unmatched_confirmatory_study",
                    study.study_id,
                )
            )

    if EvidenceHypothesis.ECOLOGICAL_COMPARISON not in studies:
        findings.append(
            _finding(
                FindingPhase.SCIENTIFIC,
                "missing_ecological_comparison",
                "a full-lifecycle external comparison is required",
            )
        )

    confirmatory_ids = {
        item.study_id
        for item in program.study_layers
        if item.inference_role is InferenceRole.CONFIRMATORY
    }
    for claim in program.claims:
        if claim.title_critical and not (set(claim.study_ids) & confirmatory_ids):
            findings.append(
                _finding(
                    FindingPhase.SCIENTIFIC,
                    "title_claim_without_confirmatory_study",
                    claim.claim_id,
                )
            )

    source_roles = {
        source_id: sources[source_id].role
        for study in program.study_layers
        for source_id in study.task_source_ids
    }
    h3 = studies.get(EvidenceHypothesis.NATIVE_EFFECT)
    if h3 and not any(
        source_roles[item] is TaskSourceRole.OBJECTIVE_PROGRESS for item in h3.task_source_ids
    ):
        findings.append(
            _finding(
                FindingPhase.SCIENTIFIC,
                "native_effect_without_objective_tasks",
                h3.study_id,
            )
        )
    ecological = studies.get(EvidenceHypothesis.ECOLOGICAL_COMPARISON)
    if ecological and not any(
        source_roles[item] is TaskSourceRole.FULL_LIFECYCLE for item in ecological.task_source_ids
    ):
        findings.append(
            _finding(
                FindingPhase.SCIENTIFIC,
                "ecological_study_without_full_lifecycle_tasks",
                ecological.study_id,
            )
        )
    if ecological and len(ecological.system_candidate_ids) < 2:
        findings.append(
            _finding(
                FindingPhase.SCIENTIFIC,
                "ecological_study_lacks_accepted_methods",
                "the full-lifecycle layer must bind at least two accepted methods",
            )
        )
    if len(program.system_candidates) < 2:
        findings.append(
            _finding(
                FindingPhase.SCIENTIFIC,
                "insufficient_accepted_external_methods",
                "at least two accepted archival methods are required",
            )
        )
    if program.model_policy.inventory_can_select_scientific_design:
        findings.append(
            _finding(
                FindingPhase.SCIENTIFIC,
                "inventory_driven_scientific_design",
                (
                    "available checkpoints may constrain capacity but cannot select "
                    "the scientific design"
                ),
            )
        )

    for source in program.task_sources:
        if source.resource_id is None:
            continue
        resource = resources.get(source.resource_id)
        if resource is None:
            findings.append(
                _finding(
                    FindingPhase.SCIENTIFIC,
                    "unknown_task_source_resource",
                    source.resource_id,
                )
            )
        elif resource.resource_kind is not EvaluationResourceKind.BENCHMARK:
            findings.append(
                _finding(
                    FindingPhase.SCIENTIFIC,
                    "task_source_is_not_benchmark",
                    source.resource_id,
                )
            )
    for method in program.system_candidates:
        if method.resource_id is None:
            continue
        resource = resources.get(method.resource_id)
        if resource is None:
            findings.append(
                _finding(FindingPhase.SCIENTIFIC, "unknown_method_resource", method.resource_id)
            )
        elif resource.resource_kind is not EvaluationResourceKind.SYSTEM:
            findings.append(
                _finding(FindingPhase.SCIENTIFIC, "method_is_not_system", method.resource_id)
            )
        elif resource.accepted_venue != method.accepted_venue:
            findings.append(
                _finding(
                    FindingPhase.SCIENTIFIC,
                    "method_venue_identity_mismatch",
                    method.resource_id,
                )
            )
    return _deduplicate(findings)


def _acquisition_findings(
    program: IclrEvidenceProgram,
    corpus: ExternalResourceCorpus,
) -> list[EvidenceProgramFinding]:
    findings: list[EvidenceProgramFinding] = []
    if program.resource_corpus_sha256 != corpus.semantic_sha256:
        findings.append(
            _finding(
                FindingPhase.ACQUISITION,
                "resource_corpus_hash_mismatch",
                "the supplied resource corpus does not match the program binding",
            )
        )
    selected = [item for item in program.task_sources if item.selected_for_acquisition_proposal]
    if not selected:
        findings.append(
            _finding(
                FindingPhase.ACQUISITION,
                "no_task_source_selected",
                (
                    "select at least one scientifically motivated task source for an "
                    "acquisition proposal"
                ),
            )
        )
    for source in selected:
        if source.resource_id is None:
            findings.append(
                _finding(FindingPhase.ACQUISITION, "task_source_unpinned", source.source_id)
            )
            continue
        report = _resource_report(corpus, source.resource_id, ResourceUse.REFERENCE)
        if report is None or not report.eligible:
            findings.append(
                _finding(
                    FindingPhase.ACQUISITION,
                    "task_source_reference_not_admitted",
                    source.resource_id,
                )
            )
            continue
        resource = next(item for item in corpus.resources if item.resource_id == source.resource_id)
        for gate_name in (ResourceGateName.DATASET_PIN, ResourceGateName.DATASET_LICENSE):
            decision = resource.gates.get(gate_name)
            if decision is None or decision.status is not ResourceGateStatus.VERIFIED:
                findings.append(
                    _finding(
                        FindingPhase.ACQUISITION,
                        f"task_source_{gate_name.value}_not_verified",
                        source.resource_id,
                    )
                )
    for method in program.system_candidates:
        if method.resource_id is None:
            findings.append(
                _finding(FindingPhase.ACQUISITION, "system_reference_blocked", method.system_id)
            )
            continue
        report = _resource_report(corpus, method.resource_id, ResourceUse.REFERENCE)
        if report is None or not report.eligible:
            findings.append(
                _finding(FindingPhase.ACQUISITION, "system_reference_blocked", method.resource_id)
            )
    return _deduplicate(findings)


def _experiment_findings(
    program: IclrEvidenceProgram,
    corpus: ExternalResourceCorpus,
) -> list[EvidenceProgramFinding]:
    findings: list[EvidenceProgramFinding] = []
    for source in program.task_sources:
        if not source.selected_for_acquisition_proposal or source.resource_id is None:
            continue
        report = _resource_report(corpus, source.resource_id, ResourceUse.TASK_SOURCE)
        if report is None or not report.eligible:
            findings.append(
                _finding(
                    FindingPhase.EXPERIMENT,
                    "task_source_not_experiment_ready",
                    source.resource_id,
                )
            )
    selected_methods = [
        item for item in program.system_candidates if item.selected_for_adapter_proposal
    ]
    if len(selected_methods) < 2:
        findings.append(
            _finding(
                FindingPhase.EXPERIMENT,
                "insufficient_selected_external_methods",
                "select at least two accepted methods for adapter qualification",
            )
        )
    for method in selected_methods:
        if method.resource_id is None:
            findings.append(
                _finding(FindingPhase.EXPERIMENT, "external_method_unpinned", method.system_id)
            )
            continue
        report = _resource_report(corpus, method.resource_id, ResourceUse.COMPARISON_SYSTEM)
        if report is None or not report.eligible:
            findings.append(
                _finding(
                    FindingPhase.EXPERIMENT,
                    "external_method_not_experiment_ready",
                    method.resource_id,
                )
            )
    if program.model_policy.primary_model_id is None:
        findings.append(
            _finding(
                FindingPhase.EXPERIMENT,
                "primary_model_not_frozen",
                "select the primary model only after the registered conformance pilot",
            )
        )
    for field_name, status in program.operational_readiness:
        if status is not ReadinessStatus.VERIFIED:
            findings.append(
                _finding(
                    FindingPhase.EXPERIMENT,
                    f"readiness_{field_name}",
                    f"{field_name} is {status.value}",
                )
            )
    return _deduplicate(findings)


def _authorization_findings(program: IclrEvidenceProgram) -> list[EvidenceProgramFinding]:
    findings = [
        _finding(
            FindingPhase.AUTHORIZATION,
            "evidence_program_is_no_run_contract",
            "execution requires a separate exact prelaunch manifest",
        )
    ]
    if not program.approval.approved:
        findings.append(
            _finding(
                FindingPhase.AUTHORIZATION,
                "explicit_owner_approval_required",
                "the exact evidence-program hash has not received launch approval",
            )
        )
    elif program.approval.approved_program_sha256 != program.proposal_sha256:
        findings.append(
            _finding(
                FindingPhase.AUTHORIZATION,
                "approval_hash_mismatch",
                "approval does not bind the current evidence program",
            )
        )
    return findings


def _resource_report(
    corpus: ExternalResourceCorpus,
    resource_id: str,
    use: ResourceUse,
):
    try:
        return evaluate_resource_feasibility(corpus, resource_id, use)
    except ValueError:
        return None


def _finding(phase: FindingPhase, code: str, message: object) -> EvidenceProgramFinding:
    return EvidenceProgramFinding(phase=phase, code=code, message=str(message))


def _deduplicate(findings: list[EvidenceProgramFinding]) -> list[EvidenceProgramFinding]:
    observed: set[tuple[str, str]] = set()
    output: list[EvidenceProgramFinding] = []
    for item in findings:
        identity = (item.code, item.message)
        if identity not in observed:
            observed.add(identity)
            output.append(item)
    return output


def _translate_findings(
    findings: tuple[EvidenceProgramFinding, ...],
    code_map: dict[str, str],
) -> tuple[EvidenceProgramFinding, ...]:
    return tuple(
        item.model_copy(update={"code": code_map[item.code]}) if item.code in code_map else item
        for item in findings
    )


def _canonical_sha256(payload: object) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
