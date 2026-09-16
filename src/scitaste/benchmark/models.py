"""Versioned schemas for controlled SciTasteBench evaluation."""

from __future__ import annotations

import hashlib
import json
import math
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.backends.base import PreferenceRequest, Usage
from scitaste.schema.actions import ResearchAction
from scitaste.taste.decision_families import ScientificTasteDecisionFamily
from scitaste.taste.intrinsic import TasteTask


class BenchmarkCondition(StrEnum):
    BASE = "base"
    KNOWLEDGE_RAG = "knowledge_rag"
    TASTE_LIBRARY = "taste_library"
    TASTE_CRITICS = "taste_critics"
    FULL_SCITASTE = "full_scitaste"
    TASTE_PLACEBO = "taste_placebo"
    RAW_SOURCE_RAG = "raw_source_rag"
    MATCHED_ABSTRACTED_TASTE = "matched_abstracted_taste"
    MISMATCHED_TASTE = "mismatched_taste"


class ReferenceRepresentation(StrEnum):
    RAW_SOURCE = "raw_source"
    ABSTRACTED_TASTE = "abstracted_taste"


class ReferenceDomainRelation(StrEnum):
    MATCHED = "matched"
    MISMATCHED = "mismatched"


class ReferenceTreatmentArm(StrEnum):
    RAW_SOURCE_RAG = "raw_source_rag"
    MATCHED_ABSTRACTED_TASTE = "matched_abstracted_taste"
    MISMATCHED_TASTE = "mismatched_taste"


class ContrastDifference(StrEnum):
    REPRESENTATION = "representation"
    SOURCE_DOMAIN_RELATION = "source_domain_relation"


class ContrastPrimaryEndpoint(StrEnum):
    EXPERT_LABEL_AGREEMENT = "expert_label_agreement"
    BLINDED_EXPERT_PREFERENCE = "blinded_expert_preference"
    AI_PANEL_PREFERENCE = "ai_panel_preference"
    BUDGETED_DECISION_REGRET = "budgeted_decision_regret"


class RunnerMetricRole(StrEnum):
    PRIMARY = "primary"
    DIAGNOSTIC = "diagnostic"


class ReferenceSourceArtifact(BaseModel):
    """Immutable source identity behind one rendered reference context."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    artifact_id: str = Field(min_length=1, max_length=300)
    source_group_id: str = Field(min_length=1, max_length=300)
    source_locator: str = Field(min_length=1, max_length=2_000)
    source_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ReferenceTreatmentContext(BaseModel):
    """One blinded, token-accounted context used by a mechanism arm."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    arm: ReferenceTreatmentArm
    representation: ReferenceRepresentation
    domain_relation: ReferenceDomainRelation
    rendered_context: str = Field(min_length=1, max_length=40_000)
    rendered_context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sources: tuple[ReferenceSourceArtifact, ...] = Field(min_length=1, max_length=20)
    tokenizer_id: str = Field(min_length=1, max_length=300)
    tokenizer_revision: str = Field(min_length=1, max_length=300)
    tokenizer_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    retrieval_query_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    render_template_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    construction_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    context_token_budget: int = Field(ge=128, le=100_000)
    observed_token_count: int = Field(ge=1, le=100_000)
    truncation_policy: Literal["none", "tail", "source-balanced"]
    provenance_tier: str = Field(min_length=1, max_length=100)
    curation_tier: str = Field(min_length=1, max_length=100)
    outcome_information_availability: Literal["available", "withheld"]

    @model_validator(mode="after")
    def content_and_sources_are_bound(self) -> ReferenceTreatmentContext:
        observed = hashlib.sha256(self.rendered_context.encode()).hexdigest()
        if observed != self.rendered_context_sha256:
            raise ValueError("rendered reference context SHA-256 mismatch")
        if self.observed_token_count > self.context_token_budget:
            raise ValueError("reference context exceeds its token budget")
        artifact_ids = [item.artifact_id for item in self.sources]
        identities = [
            (item.source_group_id, item.source_locator, item.source_content_sha256)
            for item in self.sources
        ]
        if len(artifact_ids) != len(set(artifact_ids)):
            raise ValueError("reference source artifact ids must be unique")
        if len(identities) != len(set(identities)):
            raise ValueError("reference source identities must be unique")
        return self


class MechanismContextBundle(BaseModel):
    """Fail-closed H1/H2 treatment triplet for one held-out decision."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    bundle_id: str = Field(min_length=1, max_length=300)
    raw_source_rag: ReferenceTreatmentContext
    matched_abstracted_taste: ReferenceTreatmentContext
    mismatched_taste: ReferenceTreatmentContext
    held_out_source_group_id: str = Field(min_length=1, max_length=300)
    held_out_source_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def only_registered_mechanisms_differ(self) -> MechanismContextBundle:
        raw = self.raw_source_rag
        matched = self.matched_abstracted_taste
        mismatched = self.mismatched_taste
        expected = (
            (
                raw,
                ReferenceTreatmentArm.RAW_SOURCE_RAG,
                ReferenceRepresentation.RAW_SOURCE,
                ReferenceDomainRelation.MATCHED,
            ),
            (
                matched,
                ReferenceTreatmentArm.MATCHED_ABSTRACTED_TASTE,
                ReferenceRepresentation.ABSTRACTED_TASTE,
                ReferenceDomainRelation.MATCHED,
            ),
            (
                mismatched,
                ReferenceTreatmentArm.MISMATCHED_TASTE,
                ReferenceRepresentation.ABSTRACTED_TASTE,
                ReferenceDomainRelation.MISMATCHED,
            ),
        )
        for context, arm, representation, relation in expected:
            if (context.arm, context.representation, context.domain_relation) != (
                arm,
                representation,
                relation,
            ):
                raise ValueError("reference treatment arm semantics are inconsistent")

        def identities(
            context: ReferenceTreatmentContext,
        ) -> tuple[tuple[str, str, str, str], ...]:
            return tuple(
                (
                    item.artifact_id,
                    item.source_group_id,
                    item.source_locator,
                    item.source_content_sha256,
                )
                for item in context.sources
            )

        raw_ids = identities(raw)
        matched_ids = identities(matched)
        mismatched_ids = identities(mismatched)
        if raw_ids != matched_ids:
            raise ValueError("raw and abstracted matched arms must use identical sources")
        if set(raw_ids) & set(mismatched_ids):
            raise ValueError("matched and mismatched reference sources must be disjoint")
        raw_groups = {item[1] for item in raw_ids}
        mismatch_groups = {item[1] for item in mismatched_ids}
        raw_hashes = {item[3] for item in raw_ids}
        mismatch_hashes = {item[3] for item in mismatched_ids}
        raw_locators = {item[2] for item in raw_ids}
        mismatch_locators = {item[2] for item in mismatched_ids}
        if (
            raw_groups & mismatch_groups
            or raw_hashes & mismatch_hashes
            or raw_locators & mismatch_locators
        ):
            raise ValueError("matched and mismatched source identities must be fully disjoint")
        if self.held_out_source_group_id in raw_groups | mismatch_groups:
            raise ValueError("held-out decision source group entered a reference arm")
        if self.held_out_source_content_sha256 in raw_hashes | mismatch_hashes:
            raise ValueError("held-out decision content entered a reference arm")

        parity = {
            (
                len(context.sources),
                context.tokenizer_id,
                context.tokenizer_revision,
                context.tokenizer_artifact_sha256,
                context.retrieval_query_sha256,
                context.render_template_sha256,
                context.context_token_budget,
                context.observed_token_count,
                context.truncation_policy,
                context.provenance_tier,
                context.curation_tier,
                context.outcome_information_availability,
            )
            for context in (raw, matched, mismatched)
        }
        if len(parity) != 1:
            raise ValueError("reference arms violate source-count, token, or evidence-tier parity")
        return self

    def for_condition(self, condition: BenchmarkCondition) -> ReferenceTreatmentContext:
        mapping = {
            BenchmarkCondition.RAW_SOURCE_RAG: self.raw_source_rag,
            BenchmarkCondition.MATCHED_ABSTRACTED_TASTE: self.matched_abstracted_taste,
            BenchmarkCondition.MISMATCHED_TASTE: self.mismatched_taste,
        }
        try:
            return mapping[condition]
        except KeyError as exc:
            raise ValueError(f"condition {condition.value!r} is not a mechanism treatment") from exc


class RegisteredBenchmarkContrast(BaseModel):
    """A preregistered directional comparison, independent of Base deltas."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    contrast_id: str = Field(min_length=1, max_length=200)
    hypothesis_id: str = Field(min_length=1, max_length=100)
    treatment: BenchmarkCondition
    comparator: BenchmarkCondition
    only_permitted_difference: ContrastDifference
    primary_endpoint: ContrastPrimaryEndpoint = ContrastPrimaryEndpoint.EXPERT_LABEL_AGREEMENT
    runner_metric: Literal["pairwise_accuracy", "budgeted_decision_regret"] = "pairwise_accuracy"
    runner_metric_role: RunnerMetricRole = RunnerMetricRole.PRIMARY

    @model_validator(mode="after")
    def contrast_is_directional(self) -> RegisteredBenchmarkContrast:
        if self.treatment is self.comparator:
            raise ValueError("registered contrast requires distinct treatment and comparator")
        return self


class BenchmarkEvidenceTier(StrEnum):
    SYNTHETIC_ACCEPTANCE = "synthetic_acceptance"
    NATURAL_PILOT = "natural_pilot"
    FORMAL = "formal"


class BenchmarkDecisionContextFamily(StrEnum):
    """Where in the research process a decision occurs, not what judgment it uses."""

    PROBLEM_AND_IDEA_VALUE = "problem-and-idea-value"
    HYPOTHESIS_AND_FALSIFIABILITY = "hypothesis-and-falsifiability"
    EXPERIMENT_DESIGN_AND_CONFOUND_CONTROL = "experiment-design-and-confound-control"
    EVIDENCE_INTERPRETATION_AND_CONTRADICTION = "evidence-interpretation-and-contradiction"
    RESOURCE_ALLOCATION_PIVOT_CONTINUE_OR_STOP = "resource-allocation-pivot-continue-or-stop"
    CLAIM_CALIBRATION_AND_REVIEW_CLOSURE = "claim-calibration-and-review-closure"


class BenchmarkLabelAuthority(StrEnum):
    SYNTHETIC = "synthetic"
    HUMAN_EXPERT = "human-expert"
    AI_PANEL_PROXY = "ai-panel-proxy"
    OBJECTIVE_OUTCOME = "objective-outcome"


class CandidateOrder(StrEnum):
    DECLARED = "declared"
    REVERSED = "reversed"


class TransferAxis(StrEnum):
    FUTURE_YEAR = "future_year"
    CROSS_VENUE = "cross_venue"
    CROSS_DOMAIN = "cross_domain"


class BenchmarkCase(BaseModel):
    """One held-out, fixed-pair scientific decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    task: TasteTask
    decision_context_family: BenchmarkDecisionContextFamily | None = None
    taste_judgment_family: ScientificTasteDecisionFamily | None = None
    stage: str
    domain: str
    venue: str
    publication_year: int = Field(ge=1900)
    decision_context: str = Field(min_length=1)
    candidate_actions: list[ResearchAction] = Field(min_length=2, max_length=2)
    action_roles: dict[str, str]
    preferred_action_id: str
    wrong_level_action_ids: list[str] = Field(default_factory=list)
    expert_distribution: dict[str, float]
    label_authority: BenchmarkLabelAuthority = BenchmarkLabelAuthority.SYNTHETIC
    action_utilities: dict[str, float] = Field(default_factory=dict)
    utility_contract_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    abstention_action_ids: tuple[str, ...] = ()
    transfer_axes: set[TransferAxis] = Field(default_factory=set)
    style_group: str | None = None
    paraphrase_group: str | None = None
    knowledge_context: str = ""
    knowledge_evidence_ids: tuple[str, ...] = ()
    taste_principle: str = ""
    taste_precedent_ids: tuple[str, ...] = ()
    taste_precedent_source_group_ids: tuple[str, ...] = ()
    placebo_taste_principle: str = ""
    placebo_precedent_ids: tuple[str, ...] = ()
    placebo_precedent_source_group_ids: tuple[str, ...] = ()
    critic_feedback: str = ""
    controller_context: str = ""
    mechanism_context: MechanismContextBundle | None = None
    source_group_id: str | None = None
    source_ref: str | None = None
    source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    primary_label_count: int | None = Field(default=None, ge=2)
    primary_label_agreement: float | None = Field(default=None, ge=0, le=1)
    annotation_manifest_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    prompt_version: str = Field(default="scitastebench-v1", min_length=1, max_length=100)
    headline_eligible: bool = True
    self_referential: bool = False
    scripted_selections: dict[BenchmarkCondition, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def references_are_valid(self) -> BenchmarkCase:
        candidate_ids = [action.action_id for action in self.candidate_actions]
        candidate_set = set(candidate_ids)
        if len(candidate_set) != 2:
            raise ValueError("benchmark candidate action ids must be unique")
        if set(self.action_roles) != candidate_set:
            raise ValueError("action_roles must cover exactly the candidate action ids")
        if self.preferred_action_id not in candidate_set:
            raise ValueError("preferred_action_id must be a candidate")
        if not set(self.wrong_level_action_ids).issubset(candidate_set):
            raise ValueError("wrong_level_action_ids must be candidates")
        if set(self.expert_distribution) != candidate_set:
            raise ValueError("expert_distribution must cover exactly the candidates")
        if any(value < 0 or value > 1 for value in self.expert_distribution.values()):
            raise ValueError("expert_distribution values must be between zero and one")
        if abs(sum(self.expert_distribution.values()) - 1.0) > 1e-6:
            raise ValueError("expert_distribution must sum to one")
        if any(selection not in candidate_set for selection in self.scripted_selections.values()):
            raise ValueError("scripted selections must be candidates")
        if self.action_utilities:
            if set(self.action_utilities) != candidate_set:
                raise ValueError("action_utilities must cover exactly the candidate actions")
            if self.utility_contract_sha256 is None:
                raise ValueError("action utilities require a utility contract hash")
            if any(
                not math.isfinite(value) or value < -10.0 or value > 10.0
                for value in self.action_utilities.values()
            ):
                raise ValueError("action utilities must be finite and lie in [-10, 10]")
            best = max(self.action_utilities.values())
            if self.action_utilities[self.preferred_action_id] != best:
                raise ValueError("preferred action must maximize registered utility")
        elif self.utility_contract_sha256 is not None:
            raise ValueError("utility contract hash requires action utilities")
        if not set(self.abstention_action_ids).issubset(candidate_set):
            raise ValueError("abstention_action_ids must be candidate actions")
        if len(self.abstention_action_ids) != len(set(self.abstention_action_ids)):
            raise ValueError("abstention_action_ids must be unique")
        if self.self_referential and self.headline_eligible:
            raise ValueError("self-referential cases cannot be headline eligible")
        provenance_groups = (
            self.taste_precedent_source_group_ids,
            self.placebo_precedent_source_group_ids,
        )
        if any(len(values) != len(set(values)) for values in provenance_groups):
            raise ValueError("benchmark precedent source-group ids must be unique")
        if len(self.knowledge_evidence_ids) != len(set(self.knowledge_evidence_ids)):
            raise ValueError("benchmark knowledge evidence ids must be unique")
        if len(self.taste_precedent_ids) != len(set(self.taste_precedent_ids)):
            raise ValueError("benchmark taste precedent ids must be unique")
        if len(self.placebo_precedent_ids) != len(set(self.placebo_precedent_ids)):
            raise ValueError("benchmark placebo precedent ids must be unique")
        if set(self.taste_precedent_ids) & set(self.placebo_precedent_ids):
            raise ValueError("matched and placebo Taste precedents must be disjoint")
        if self.source_group_id is not None and self.source_group_id in {
            *self.taste_precedent_source_group_ids,
            *self.placebo_precedent_source_group_ids,
        }:
            raise ValueError("benchmark source group cannot enter its Taste context")
        if self.mechanism_context is not None:
            if self.source_group_id != self.mechanism_context.held_out_source_group_id:
                raise ValueError("mechanism context must bind the benchmark source group")
            if self.source_sha256 != self.mechanism_context.held_out_source_content_sha256:
                raise ValueError("mechanism context must bind the benchmark source content")
        return self

    def request_id(
        self,
        condition: BenchmarkCondition,
        candidate_order: CandidateOrder = CandidateOrder.DECLARED,
    ) -> str:
        suffix = "" if candidate_order is CandidateOrder.DECLARED else "::reversed"
        return f"{self.case_id}::{condition.value}{suffix}"

    def to_request(
        self,
        condition: BenchmarkCondition,
        *,
        seed: int,
        candidate_order: CandidateOrder = CandidateOrder.DECLARED,
    ) -> PreferenceRequest:
        sections = [self.decision_context]
        if condition in {BenchmarkCondition.KNOWLEDGE_RAG, BenchmarkCondition.FULL_SCITASTE}:
            sections.append(f"Retrieved knowledge:\n{self.knowledge_context}")
        if condition in {BenchmarkCondition.TASTE_LIBRARY, BenchmarkCondition.FULL_SCITASTE}:
            sections.append(f"Retrieved taste principle:\n{self.taste_principle}")
        if condition is BenchmarkCondition.TASTE_PLACEBO:
            sections.append(f"Retrieved taste principle:\n{self.placebo_taste_principle}")
        if condition in {
            BenchmarkCondition.RAW_SOURCE_RAG,
            BenchmarkCondition.MATCHED_ABSTRACTED_TASTE,
            BenchmarkCondition.MISMATCHED_TASTE,
        }:
            if self.mechanism_context is None:
                raise ValueError(
                    f"condition {condition.value!r} requires a bound mechanism context"
                )
            treatment = self.mechanism_context.for_condition(condition)
            sections.append(f"Reference context:\n{treatment.rendered_context}")
        if condition in {BenchmarkCondition.TASTE_CRITICS, BenchmarkCondition.FULL_SCITASTE}:
            sections.append(f"Independent critic feedback:\n{self.critic_feedback}")
        if condition == BenchmarkCondition.FULL_SCITASTE:
            sections.append(f"Controller state:\n{self.controller_context}")
        return PreferenceRequest(
            request_id=self.request_id(condition, candidate_order),
            task=self.task.value,
            stage=self.stage,
            decision_context="\n\n".join(sections),
            candidate_actions=(
                self.candidate_actions
                if candidate_order is CandidateOrder.DECLARED
                else list(reversed(self.candidate_actions))
            ),
            seed=seed,
            prompt_version=(
                f"{self.prompt_version}/{condition.value}"
                if candidate_order is CandidateOrder.DECLARED
                else f"{self.prompt_version}/{condition.value}/reversed"
            ),
        )


class BenchmarkSuite(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    suite_id: str
    version: str
    description: str
    evidence_tier: BenchmarkEvidenceTier = BenchmarkEvidenceTier.SYNTHETIC_ACCEPTANCE
    annotation_manifest_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    precedent_corpus_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    precedent_source_group_ids: tuple[str, ...] = ()
    reference_treatment_manifest_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    registered_contrasts: tuple[RegisteredBenchmarkContrast, ...] = ()
    conditions: list[BenchmarkCondition]
    cases: list[BenchmarkCase] = Field(min_length=1)

    @model_validator(mode="after")
    def suite_is_controlled(self) -> BenchmarkSuite:
        if len(set(self.conditions)) != len(self.conditions):
            raise ValueError("benchmark conditions must be unique")
        contrast_ids = [item.contrast_id for item in self.registered_contrasts]
        if len(contrast_ids) != len(set(contrast_ids)):
            raise ValueError("registered benchmark contrast ids must be unique")
        if any(
            item.treatment not in self.conditions or item.comparator not in self.conditions
            for item in self.registered_contrasts
        ):
            raise ValueError("registered contrasts must reference declared conditions")
        required = (
            {
                BenchmarkCondition.BASE,
                BenchmarkCondition.RAW_SOURCE_RAG,
                BenchmarkCondition.MATCHED_ABSTRACTED_TASTE,
                BenchmarkCondition.MISMATCHED_TASTE,
            }
            if self.version in {"3.0", "4.0"}
            else {BenchmarkCondition.BASE, BenchmarkCondition.FULL_SCITASTE}
        )
        if not required.issubset(self.conditions):
            raise ValueError("suite does not include its version-required conditions")
        case_ids = [case.case_id for case in self.cases]
        if len(set(case_ids)) != len(case_ids):
            raise ValueError("benchmark case ids must be unique")
        if not any(case.headline_eligible for case in self.cases):
            raise ValueError("suite must contain at least one headline-eligible case")
        if self.evidence_tier is BenchmarkEvidenceTier.FORMAL:
            headline = [case for case in self.cases if case.headline_eligible]
            if len(headline) < 120:
                raise ValueError("formal SciTasteBench requires at least 120 headline cases")
            if len({case.domain for case in headline}) < 3:
                raise ValueError("formal SciTasteBench requires at least three domains")
            if self.version == "4.0":
                if {case.decision_context_family for case in headline} != set(
                    BenchmarkDecisionContextFamily
                ):
                    raise ValueError(
                        "formal SciTasteBench v4 must cover every decision-context family"
                    )
                if {case.taste_judgment_family for case in headline} != set(
                    ScientificTasteDecisionFamily
                ):
                    raise ValueError(
                        "formal SciTasteBench v4 must cover every Taste judgment family"
                    )
            elif {case.task for case in headline} != set(TasteTask):
                raise ValueError("formal SciTasteBench must cover every legacy task family")
            if (
                self.version not in {"3.0", "4.0"}
                and BenchmarkCondition.TASTE_PLACEBO not in self.conditions
            ):
                raise ValueError("formal SciTasteBench requires a mismatched-Taste placebo")
            if self.annotation_manifest_sha256 is None:
                raise ValueError("formal SciTasteBench requires an annotation hash")
            if self.version not in {"3.0", "4.0"}:
                if self.precedent_corpus_sha256 is None:
                    raise ValueError("formal SciTasteBench v2 requires a precedent hash")
                if not self.precedent_source_group_ids or len(
                    self.precedent_source_group_ids
                ) != len(set(self.precedent_source_group_ids)):
                    raise ValueError(
                        "formal SciTasteBench v2 requires unique precedent source groups"
                    )
                if {case.source_group_id for case in headline} & set(
                    self.precedent_source_group_ids
                ):
                    raise ValueError("formal case and precedent source groups must be disjoint")
            if any(
                case.source_group_id is None
                or case.source_ref is None
                or case.source_sha256 is None
                or case.primary_label_count is None
                or case.annotation_manifest_sha256 != self.annotation_manifest_sha256
                or case.prompt_version
                != (
                    "scitastebench-v4"
                    if self.version == "4.0"
                    else "scitastebench-v3"
                    if self.version == "3.0"
                    else "scitastebench-v2"
                )
                or case.self_referential
                or case.scripted_selections
                for case in headline
            ):
                raise ValueError(
                    "formal SciTasteBench cases require natural-source, human-label, placebo, "
                    "and versioned protocol bindings"
                )
            if self.version not in {"3.0", "4.0"} and any(
                not case.placebo_taste_principle
                or not case.knowledge_evidence_ids
                or not case.taste_precedent_ids
                or not case.taste_precedent_source_group_ids
                or not case.placebo_precedent_ids
                or not case.placebo_precedent_source_group_ids
                for case in headline
            ):
                raise ValueError("formal SciTasteBench v2 requires legacy context bindings")
            if self.version in {"3.0", "4.0"}:
                mechanism_conditions = {
                    BenchmarkCondition.RAW_SOURCE_RAG,
                    BenchmarkCondition.MATCHED_ABSTRACTED_TASTE,
                    BenchmarkCondition.MISMATCHED_TASTE,
                }
                if not mechanism_conditions.issubset(self.conditions):
                    raise ValueError("formal SciTasteBench v3 requires all mechanism arms")
                if self.reference_treatment_manifest_sha256 is None:
                    raise ValueError("formal SciTasteBench v3 requires a treatment manifest hash")
                expected_contrasts = {
                    (
                        BenchmarkCondition.MATCHED_ABSTRACTED_TASTE,
                        BenchmarkCondition.RAW_SOURCE_RAG,
                        ContrastDifference.REPRESENTATION,
                    ),
                    (
                        BenchmarkCondition.MATCHED_ABSTRACTED_TASTE,
                        BenchmarkCondition.MISMATCHED_TASTE,
                        ContrastDifference.SOURCE_DOMAIN_RELATION,
                    ),
                }
                observed_contrasts = {
                    (item.treatment, item.comparator, item.only_permitted_difference)
                    for item in self.registered_contrasts
                }
                if not expected_contrasts.issubset(observed_contrasts):
                    raise ValueError("formal SciTasteBench v3 requires registered H1/H2 contrasts")
                expected_endpoint = (
                    ContrastPrimaryEndpoint.BUDGETED_DECISION_REGRET
                    if self.version == "4.0"
                    else ContrastPrimaryEndpoint.BLINDED_EXPERT_PREFERENCE
                )
                expected_metric = (
                    "budgeted_decision_regret" if self.version == "4.0" else "pairwise_accuracy"
                )
                expected_role = (
                    RunnerMetricRole.PRIMARY
                    if self.version == "4.0"
                    else RunnerMetricRole.DIAGNOSTIC
                )
                if any(
                    item.primary_endpoint is not expected_endpoint
                    or item.runner_metric != expected_metric
                    or item.runner_metric_role is not expected_role
                    for item in self.registered_contrasts
                    if (item.treatment, item.comparator, item.only_permitted_difference)
                    in expected_contrasts
                ):
                    raise ValueError("formal H1/H2 contrasts require blinded preference endpoints")
                if any(
                    case.mechanism_context is None
                    or case.prompt_version
                    != ("scitastebench-v4" if self.version == "4.0" else "scitastebench-v3")
                    for case in headline
                ):
                    raise ValueError(
                        "formal SciTasteBench v3 cases require qualified mechanism contexts"
                    )
                expected_curation = (
                    "grounded-dual-ai-reviewed"
                    if self.version == "4.0"
                    else "grounded-dual-human-verified"
                )
                if any(
                    context.curation_tier != expected_curation
                    for case in headline
                    for context in (
                        case.mechanism_context.raw_source_rag,
                        case.mechanism_context.matched_abstracted_taste,
                        case.mechanism_context.mismatched_taste,
                    )
                ):
                    raise ValueError(
                        "formal SciTasteBench v4 requires grounded dual-AI Taste curation"
                        if self.version == "4.0"
                        else "formal SciTasteBench v3 requires grounded dual-human Taste curation"
                    )
                if self.version == "4.0" and any(
                    case.label_authority is not BenchmarkLabelAuthority.AI_PANEL_PROXY
                    or not case.action_utilities
                    or case.utility_contract_sha256 is None
                    for case in headline
                ):
                    raise ValueError(
                        "formal SciTasteBench v4 requires AI-panel labels and hidden utilities"
                    )
        return self

    @property
    def sha256(self) -> str:
        payload = self.model_dump(mode="json")
        for case in payload["cases"]:
            observed = set(case["transfer_axes"])
            case["transfer_axes"] = [axis.value for axis in TransferAxis if axis.value in observed]
        if self.version in {"1.0", "2.0"}:
            payload.pop("reference_treatment_manifest_sha256", None)
            payload.pop("registered_contrasts", None)
            for case in payload["cases"]:
                case.pop("mechanism_context", None)
        if self.version in {"1.0", "2.0", "3.0"}:
            for case in payload["cases"]:
                for field in (
                    "decision_context_family",
                    "taste_judgment_family",
                    "label_authority",
                    "action_utilities",
                    "utility_contract_sha256",
                    "abstention_action_ids",
                ):
                    case.pop(field, None)
        if self.version == "1.0":
            for field in (
                "evidence_tier",
                "annotation_manifest_sha256",
                "precedent_corpus_sha256",
                "precedent_source_group_ids",
            ):
                payload.pop(field, None)
            additive_case_fields = (
                "knowledge_evidence_ids",
                "taste_precedent_ids",
                "taste_precedent_source_group_ids",
                "placebo_taste_principle",
                "placebo_precedent_ids",
                "placebo_precedent_source_group_ids",
                "source_group_id",
                "source_ref",
                "source_sha256",
                "primary_label_count",
                "primary_label_agreement",
                "annotation_manifest_sha256",
                "prompt_version",
            )
            for case in payload["cases"]:
                for field in additive_case_fields:
                    case.pop(field, None)
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


class BenchmarkResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    condition: BenchmarkCondition
    candidate_order: CandidateOrder = CandidateOrder.DECLARED
    task: TasteTask
    selected_action_id: str
    selected_role: str
    preferred_action_id: str
    correct: bool
    wrong_level: bool
    confidence: float
    expert_agreement: float
    selected_utility: float | None = Field(default=None, allow_inf_nan=False)
    optimal_utility: float | None = Field(default=None, allow_inf_nan=False)
    budgeted_decision_regret: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    abstained: bool = False
    rationale: str
    backend: str
    model: str
    request_fingerprint: str
    cached: bool
    usage: Usage


class BenchmarkMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    count: int = Field(ge=0)
    pairwise_accuracy: float = Field(ge=0, le=1)
    expert_agreement: float = Field(ge=0, le=1)
    mean_confidence: float = Field(ge=0, le=1)
    brier_score: float = Field(ge=0, le=1)
    expected_calibration_error: float = Field(ge=0, le=1)
    wrong_level_decision_rate: float = Field(ge=0, le=1)
    mean_budgeted_decision_regret: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    abstention_rate: float = Field(default=0.0, ge=0, le=1)


class ConditionReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    condition: BenchmarkCondition
    overall: BenchmarkMetrics
    headline: BenchmarkMetrics
    by_task: dict[TasteTask, BenchmarkMetrics]
    transfer: dict[TransferAxis, BenchmarkMetrics]
    style_invariance: float | None = Field(default=None, ge=0, le=1)
    paraphrase_consistency: float | None = Field(default=None, ge=0, le=1)
    results: list[BenchmarkResult]


class ConditionComparison(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    condition: BenchmarkCondition
    eligible_case_count: int
    accuracy_delta: float
    expert_agreement_delta: float
    wrong_level_rate_delta: float
    budgeted_decision_regret_reduction: float | None = Field(default=None, allow_inf_nan=False)
    abstention_rate_delta: float = Field(default=0.0, ge=-1, le=1)
    paired_improvements: int
    paired_regressions: int
    paired_unchanged: int


class RegisteredContrastReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    contrast_id: str
    hypothesis_id: str
    treatment: BenchmarkCondition
    comparator: BenchmarkCondition
    only_permitted_difference: ContrastDifference
    primary_endpoint: ContrastPrimaryEndpoint
    runner_metric: Literal["pairwise_accuracy", "budgeted_decision_regret"] = "pairwise_accuracy"
    runner_metric_role: RunnerMetricRole
    confirmatory_endpoint_complete: bool
    confirmatory_result: float | None = None
    eligible_case_count: int
    accuracy_delta: float
    expert_agreement_delta: float
    wrong_level_rate_delta: float
    budgeted_decision_regret_reduction: float | None = Field(default=None, allow_inf_nan=False)
    abstention_rate_delta: float = Field(default=0.0, ge=-1, le=1)
    paired_improvements: int
    paired_regressions: int
    paired_unchanged: int


class CapabilityBoundaryReport(BaseModel):
    """Paired evidence separating model-only misses from augmentation effects."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    method: str = "paired-base-full-boundary-v1"
    diagnostic_only: bool = True
    no_observed_limit_case_ids: list[str]
    system_recovery_case_ids: list[str]
    system_regression_case_ids: list[str]
    shared_failure_case_ids: list[str]
    model_capability_conclusion: str
    system_conclusion: str


class BenchmarkReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0"
    suite_id: str
    suite_version: str
    suite_sha256: str
    backend: str
    model: str
    seed: int
    candidate_order: CandidateOrder = CandidateOrder.DECLARED
    conditions: dict[BenchmarkCondition, ConditionReport]
    comparisons_to_base: dict[BenchmarkCondition, ConditionComparison]
    registered_comparisons: dict[str, RegisteredContrastReport] = Field(default_factory=dict)
    excluded_headline_case_ids: list[str]
    unavailable_metrics: dict[str, str]
    capability_boundary: CapabilityBoundaryReport | None = None


class CrossModelCapabilityComparison(BaseModel):
    """Same-suite differential evidence for model-specific versus shared limits."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0"
    method: str = "paired-cross-model-boundary-v1"
    diagnostic_only: bool = True
    suite_id: str
    suite_sha256: str
    seed: int
    candidate_order: CandidateOrder = CandidateOrder.DECLARED
    primary_backend: str
    primary_model: str
    comparator_backend: str
    comparator_model: str
    both_base_correct_case_ids: list[str]
    primary_model_limit_candidate_case_ids: list[str]
    comparator_model_limit_candidate_case_ids: list[str]
    shared_base_failure_case_ids: list[str]
    primary_system_regression_case_ids: list[str]
    comparator_system_regression_case_ids: list[str]
    attribution_rule: str
