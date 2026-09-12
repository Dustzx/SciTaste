"""No-run alignment between the frozen ICLR program and SciTasteBench v3."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from scitaste.benchmark.models import (
    BenchmarkCondition,
    BenchmarkEvidenceTier,
    BenchmarkSuite,
    ContrastDifference,
    ContrastPrimaryEndpoint,
    RunnerMetricRole,
)
from scitaste.evaluation.evidence_program import (
    EvidenceHypothesis,
    IclrEvidenceProgram,
    ProgramConditionKind,
)

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class EvidenceBenchmarkAlignmentFinding(BaseModel):
    model_config = _CONFIG

    code: str = Field(pattern=r"^[a-z0-9]+(?:[a-z0-9_:-]*[a-z0-9])?$")
    message: str = Field(min_length=1, max_length=2_000)


class EvidenceBenchmarkAlignmentReport(BaseModel):
    """Scientific alignment only; it never authorizes a benchmark execution."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    program_id: str
    program_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    suite_id: str
    suite_version: str
    suite_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    mechanism_design_aligned: bool
    formal_population_bound: bool
    ready_for_diagnostic_runner: bool
    ready_for_confirmatory_collection: bool
    confirmatory_evidence_complete: Literal[False] = False
    confirmatory_blocker: Literal["condition_blinded_human_review_not_attached"]
    findings: tuple[EvidenceBenchmarkAlignmentFinding, ...]
    no_external_action_performed: Literal[True] = True
    authorizes_execution: Literal[False] = False


def align_evidence_program_to_benchmark(
    program: IclrEvidenceProgram,
    suite: BenchmarkSuite,
) -> EvidenceBenchmarkAlignmentReport:
    """Check exact H1/H2 arms, contrasts, endpoint roles, and formal population."""

    findings: list[EvidenceBenchmarkAlignmentFinding] = []
    if suite.version != "3.0":
        _add(findings, "suite_version_not_v3", "H1/H2 require SciTasteBench suite v3")
    if suite.reference_treatment_manifest_sha256 is None:
        _add(
            findings,
            "treatment_manifest_unbound",
            "H1/H2 require a content-bound reference-treatment manifest",
        )

    mechanism_conditions = {
        BenchmarkCondition.RAW_SOURCE_RAG,
        BenchmarkCondition.MATCHED_ABSTRACTED_TASTE,
        BenchmarkCondition.MISMATCHED_TASTE,
    }
    missing_conditions = mechanism_conditions - set(suite.conditions)
    if missing_conditions:
        _add(
            findings,
            "mechanism_conditions_missing",
            "missing suite conditions: "
            + ", ".join(sorted(item.value for item in missing_conditions)),
        )
    missing_context = [
        item.case_id
        for item in suite.cases
        if item.headline_eligible and item.mechanism_context is None
    ]
    if missing_context:
        _add(
            findings,
            "mechanism_context_missing",
            f"{len(missing_context)} headline cases lack qualified treatment triplets",
        )

    conditions_by_id = {item.condition_id: item.kind for item in program.conditions}
    studies = {item.hypothesis: item for item in program.study_layers}
    expected = {
        EvidenceHypothesis.TASTE_ABSTRACTION: (
            BenchmarkCondition.MATCHED_ABSTRACTED_TASTE,
            BenchmarkCondition.RAW_SOURCE_RAG,
            ContrastDifference.REPRESENTATION,
            {ProgramConditionKind.MATCHED_TASTE, ProgramConditionKind.RAW_SOURCE_RAG},
        ),
        EvidenceHypothesis.TASTE_SPECIFICITY: (
            BenchmarkCondition.MATCHED_ABSTRACTED_TASTE,
            BenchmarkCondition.MISMATCHED_TASTE,
            ContrastDifference.SOURCE_DOMAIN_RELATION,
            {ProgramConditionKind.MATCHED_TASTE, ProgramConditionKind.MISMATCHED_TASTE},
        ),
    }
    for hypothesis, specification in expected.items():
        treatment, comparator, difference, program_kinds = specification
        study = studies.get(hypothesis)
        if study is None:
            _add(findings, "program_study_missing", hypothesis.value)
            continue
        observed_kinds = {conditions_by_id[item] for item in study.condition_ids}
        if observed_kinds != program_kinds:
            _add(
                findings,
                "program_contrast_mismatch",
                f"{hypothesis.value} does not bind the exact expected program conditions",
            )
        candidates = [
            item
            for item in suite.registered_contrasts
            if item.hypothesis_id == hypothesis.value
            and item.treatment is treatment
            and item.comparator is comparator
            and item.only_permitted_difference is difference
        ]
        if len(candidates) != 1:
            _add(
                findings,
                "registered_contrast_missing",
                f"{hypothesis.value} requires exactly one directionally matched contrast",
            )
            continue
        contrast = candidates[0]
        if (
            contrast.primary_endpoint is not ContrastPrimaryEndpoint.BLINDED_EXPERT_PREFERENCE
            or contrast.runner_metric_role is not RunnerMetricRole.DIAGNOSTIC
        ):
            _add(
                findings,
                "endpoint_role_mismatch",
                (
                    f"{hypothesis.value} must keep runner accuracy diagnostic "
                    "and expert review primary"
                ),
            )

    formal_population_bound = (
        suite.evidence_tier is BenchmarkEvidenceTier.FORMAL
        and len([item for item in suite.cases if item.headline_eligible]) >= 120
    )
    design_aligned = not findings
    return EvidenceBenchmarkAlignmentReport(
        program_id=program.program_id,
        program_sha256=program.proposal_sha256,
        suite_id=suite.suite_id,
        suite_version=suite.version,
        suite_sha256=suite.sha256,
        mechanism_design_aligned=design_aligned,
        formal_population_bound=formal_population_bound,
        ready_for_diagnostic_runner=design_aligned,
        ready_for_confirmatory_collection=design_aligned and formal_population_bound,
        confirmatory_evidence_complete=False,
        confirmatory_blocker="condition_blinded_human_review_not_attached",
        findings=tuple(findings),
    )


def _add(
    findings: list[EvidenceBenchmarkAlignmentFinding],
    code: str,
    message: str,
) -> None:
    findings.append(EvidenceBenchmarkAlignmentFinding(code=code, message=message))


__all__ = [
    "EvidenceBenchmarkAlignmentFinding",
    "EvidenceBenchmarkAlignmentReport",
    "align_evidence_program_to_benchmark",
]
