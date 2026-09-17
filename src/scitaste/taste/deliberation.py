"""Decision-grounded selection of transferable Scientific Taste precedents."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.schema.actions import ResearchAction
from scitaste.state.persistence import snapshot_id
from scitaste.state.research_state import ResearchState
from scitaste.taste.retriever import RetrievedTasteCase

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[A-Za-z0-9]+(?:[A-Za-z0-9._:-]*[A-Za-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"

TASTE_APPLICABILITY_NODE = "taste-applicability"
TASTE_DELIBERATION_NODE = "taste-deliberation"


class TasteTransferVerdict(StrEnum):
    APPLICABLE = "applicable"
    INAPPLICABLE = "inapplicable"
    UNCERTAIN = "uncertain"


class TasteDeliberationRole(StrEnum):
    SUPPORT = "support"
    CHALLENGE = "challenge"
    BOUNDARY = "boundary"


class TasteCounterfactualStatus(StrEnum):
    NOT_TRIGGERED = "not-triggered"
    TRIGGERED = "triggered"
    UNKNOWN = "unknown"


class TasteDecisionFact(BaseModel):
    """One current-state fact that an applicability judgment may cite."""

    model_config = _CONFIG

    fact_id: str = Field(pattern=_ID)
    kind: Literal[
        "direction",
        "domain",
        "venue",
        "stage",
        "hypothesis",
        "observation",
        "claim",
        "obligation",
    ]
    text: str = Field(min_length=1, max_length=10_000)
    boundary_candidate: bool = False


class TasteDeliberationCandidate(BaseModel):
    """Outcome-hidden projection of one broadly retrieved grounded Taste case."""

    model_config = _CONFIG

    case_id: str = Field(pattern=_ID)
    case_sha256: str = Field(pattern=_SHA256)
    taste_grounding_sha256: str = Field(pattern=_SHA256)
    source_identities: tuple[str, ...] = Field(min_length=1, max_length=20)
    stage: str = Field(min_length=1, max_length=100)
    context_summary: str = Field(min_length=1, max_length=20_000)
    problem_pattern: str | None = Field(default=None, max_length=4_000)
    evidence_state: str | None = Field(default=None, max_length=10_000)
    candidate_actions: tuple[str, ...] = Field(min_length=2, max_length=20)
    preferred_action: str = Field(min_length=1, max_length=500)
    rejected_actions: tuple[str, ...] = Field(min_length=1, max_length=19)
    decision_principle: str = Field(min_length=1, max_length=10_000)
    why_preferred: str = Field(min_length=1, max_length=10_000)
    applies_when: tuple[str, ...] = Field(min_length=2, max_length=20)
    fails_when: tuple[str, ...] = Field(min_length=2, max_length=20)
    counterfactual_probe: str = Field(min_length=1, max_length=4_000)
    confidence: float = Field(ge=0.0, le=1.0)
    broad_retrieval_score: float = Field(ge=0.0)
    broad_matched_fields: tuple[str, ...] = Field(default_factory=tuple, max_length=30)
    hard_applicability_satisfied: bool | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    hard_applicability_mismatches: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=10,
        exclude_if=lambda value: not value,
    )

    @model_validator(mode="after")
    def identities_and_boundaries_are_unique(self) -> TasteDeliberationCandidate:
        for label, values in (
            ("source identities", self.source_identities),
            ("candidate actions", self.candidate_actions),
            ("rejected actions", self.rejected_actions),
            ("applicability conditions", self.applies_when),
            ("failure conditions", self.fails_when),
            ("broad matched fields", self.broad_matched_fields),
            ("hard applicability mismatches", self.hard_applicability_mismatches),
        ):
            folded = [item.casefold() for item in values]
            if len(folded) != len(set(folded)):
                raise ValueError(f"Taste deliberation candidate {label} must be unique")
        if self.preferred_action not in self.candidate_actions:
            raise ValueError("Taste deliberation preferred action must be a candidate")
        expected_rejected = set(self.candidate_actions) - {self.preferred_action}
        if set(self.rejected_actions) != expected_rejected:
            raise ValueError("Taste deliberation must expose every rejected source action")
        if self.hard_applicability_satisfied is False and not self.hard_applicability_mismatches:
            raise ValueError("failed hard applicability requires at least one mismatch")
        if self.hard_applicability_satisfied is True and self.hard_applicability_mismatches:
            raise ValueError("satisfied hard applicability cannot carry mismatches")
        return self


class TasteDeliberationInput(BaseModel):
    """Closed candidate pool and current facts visible to the selector node."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    decision_id: str = Field(pattern=_ID)
    state_snapshot_id: str = Field(min_length=1)
    stage: str = Field(min_length=1, max_length=100)
    current_actions: tuple[ResearchAction, ...] = Field(min_length=2, max_length=12)
    decision_facts: tuple[TasteDecisionFact, ...] = Field(min_length=3, max_length=80)
    candidates: tuple[TasteDeliberationCandidate, ...] = Field(min_length=2, max_length=20)
    maximum_selected_cases: int = Field(default=3, ge=1, le=5)
    relation_label_hidden: Literal[True] = True
    source_outcomes_hidden_from_selector: Literal[True] = True
    held_out_task_content_excluded: Literal[True] = True

    @model_validator(mode="after")
    def pool_is_closed(self) -> TasteDeliberationInput:
        for label, identities in (
            ("current action", [item.action_id for item in self.current_actions]),
            ("decision fact", [item.fact_id for item in self.decision_facts]),
            ("candidate case", [item.case_id for item in self.candidates]),
        ):
            if len(identities) != len(set(identities)):
                raise ValueError(f"Taste deliberation {label} identities must be unique")
        if self.maximum_selected_cases > len(self.candidates):
            raise ValueError("Taste selection ceiling cannot exceed the candidate pool")
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json"))


class TasteBoundarySupport(BaseModel):
    """Bind one transfer-boundary judgment to exact current-state facts."""

    model_config = _CONFIG

    boundary_condition: str = Field(min_length=1, max_length=4_000)
    decision_fact_ids: tuple[str, ...] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def fact_references_are_unique(self) -> TasteBoundarySupport:
        if len(self.decision_fact_ids) != len(set(self.decision_fact_ids)):
            raise ValueError("Taste boundary-support fact IDs must be unique")
        return self


class TasteCaseTransferAssessment(BaseModel):
    """A proposal about whether one precedent transfers to this decision."""

    model_config = _CONFIG

    case_id: str = Field(pattern=_ID)
    verdict: TasteTransferVerdict
    applicability_supports: tuple[TasteBoundarySupport, ...] = Field(
        default_factory=tuple,
        max_length=20,
    )
    triggered_failure_supports: tuple[TasteBoundarySupport, ...] = Field(
        default_factory=tuple,
        max_length=20,
    )
    aligned_current_action_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=12)
    opposed_current_action_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=12)
    role: TasteDeliberationRole
    counterfactual_status: TasteCounterfactualStatus
    relevance_confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=1, max_length=8_000)

    @model_validator(mode="after")
    def references_are_internally_consistent(self) -> TasteCaseTransferAssessment:
        for label, values in (
            ("aligned actions", self.aligned_current_action_ids),
            ("opposed actions", self.opposed_current_action_ids),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"Taste assessment {label} must be unique")
        if set(self.aligned_current_action_ids) & set(self.opposed_current_action_ids):
            raise ValueError("Taste assessment cannot align and oppose the same action")
        if self.verdict is TasteTransferVerdict.APPLICABLE:
            if len(self.applicability_supports) < 2:
                raise ValueError("an applicable Taste case requires two boundary supports")
            if self.triggered_failure_supports:
                raise ValueError("an applicable Taste case cannot trigger a failure condition")
            if not self.aligned_current_action_ids:
                raise ValueError("an applicable Taste case must align to a current action")
        return self


class TasteApplicabilityProposal(BaseModel):
    """Per-case transfer judgments before controller-owned selection."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    decision_id: str = Field(pattern=_ID)
    assessments: tuple[TasteCaseTransferAssessment, ...] = Field(min_length=2, max_length=20)

    @model_validator(mode="after")
    def identities_are_unique(self) -> TasteApplicabilityProposal:
        assessed = [item.case_id for item in self.assessments]
        if len(assessed) != len(set(assessed)):
            raise ValueError("Taste applicability assessments must cover unique cases")
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json"))


class TasteDeliberationProposal(BaseModel):
    """Untrusted, bounded proposal for a diverse decision-precedent set."""

    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1"] = "1.1"
    decision_id: str = Field(pattern=_ID)
    assessments: tuple[TasteCaseTransferAssessment, ...] = Field(min_length=2, max_length=20)
    selected_case_ids: tuple[str, ...] = Field(max_length=5)
    recommended_action_id: str | None = Field(
        default=None,
        max_length=500,
        exclude_if=lambda value: value is None,
    )
    selection_rationale: str = Field(min_length=1, max_length=10_000)

    @model_validator(mode="after")
    def identities_are_unique(self) -> TasteDeliberationProposal:
        assessed = [item.case_id for item in self.assessments]
        if len(assessed) != len(set(assessed)):
            raise ValueError("Taste deliberation assessments must cover unique cases")
        if len(self.selected_case_ids) != len(set(self.selected_case_ids)):
            raise ValueError("Taste deliberation selected cases must be unique")
        if self.schema_version == "1.0":
            if self.recommended_action_id is not None:
                raise ValueError("Taste deliberation schema 1.0 cannot recommend an action")
        elif bool(self.selected_case_ids) != (self.recommended_action_id is not None):
            raise ValueError(
                "Taste deliberation schema 1.1 requires exactly one recommendation when "
                "precedents are selected and abstention otherwise"
            )
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json"))


class VerifiedTasteDeliberation(BaseModel):
    """Accepted project-ledger proposal supplied to deterministic selection."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    invocation_id: str = Field(min_length=1)
    backend: str = Field(min_length=1)
    model: str = Field(min_length=1)
    ledger_locator: str = Field(min_length=1)
    ledger_sha256: str = Field(pattern=_SHA256)
    input: TasteDeliberationInput
    proposal: TasteDeliberationProposal
    ledger_verified: Literal[True] = True

    @property
    def fingerprint(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json"))


def build_taste_deliberation_input(
    *,
    state: ResearchState,
    actions: list[ResearchAction],
    broad_candidates: list[RetrievedTasteCase],
    maximum_selected_cases: int = 3,
) -> TasteDeliberationInput:
    """Project state and grounded broad-retrieval results into a closed selector input."""

    if len(actions) < 2:
        raise ValueError("Taste deliberation requires at least two current actions")
    candidates: list[TasteDeliberationCandidate] = []
    for result in broad_candidates:
        case = result.case
        if (
            case.taste_grounding_sha256 is None
            or len(case.applicability_conditions) < 2
            or len(case.failure_conditions) < 2
            or not case.counterfactual_probe
        ):
            continue
        candidates.append(_candidate_projection(result))
    if len(candidates) < 2:
        raise ValueError(
            "Taste deliberation requires at least two grounded transfer-bounded candidates"
        )
    facts = _decision_facts(state)
    identity = {
        "state_snapshot_id": snapshot_id(state),
        "action_ids": [item.action_id for item in actions],
        "candidate_ids": [item.case_id for item in candidates],
    }
    return TasteDeliberationInput(
        decision_id=f"taste-{_canonical_sha256(identity)[:24]}",
        state_snapshot_id=snapshot_id(state),
        stage=state.current_stage.value,
        current_actions=tuple(actions),
        decision_facts=facts,
        candidates=tuple(candidates),
        maximum_selected_cases=min(maximum_selected_cases, len(candidates)),
    )


def validate_taste_deliberation(
    input_data: TasteDeliberationInput,
    proposal: TasteDeliberationProposal,
) -> tuple[str, ...]:
    """Reject identity drift, ungrounded transfer claims, and one-sided selection."""

    findings: list[str] = []
    if proposal.decision_id != input_data.decision_id:
        findings.append("Taste deliberation changed the decision identity")
    candidate_by_id = {item.case_id: item for item in input_data.candidates}
    assessment_by_id = {item.case_id: item for item in proposal.assessments}
    if set(assessment_by_id) != set(candidate_by_id):
        findings.append("Taste deliberation assessment coverage differs from the closed pool")
    if len(proposal.selected_case_ids) > input_data.maximum_selected_cases:
        findings.append("Taste deliberation exceeds the selected-case ceiling")
    fact_ids = {item.fact_id for item in input_data.decision_facts}
    boundary_fact_ids = {
        item.fact_id for item in input_data.decision_facts if item.boundary_candidate
    }
    action_ids = {item.action_id for item in input_data.current_actions}
    eligible: dict[str, TasteCaseTransferAssessment] = {}
    for case_id, assessment in assessment_by_id.items():
        candidate = candidate_by_id.get(case_id)
        if candidate is None:
            continue
        if not set(assessment.aligned_current_action_ids).issubset(action_ids):
            findings.append(f"Taste assessment {case_id!r} aligns an unknown current action")
        if not set(assessment.opposed_current_action_ids).issubset(action_ids):
            findings.append(f"Taste assessment {case_id!r} opposes an unknown current action")
        for label, supports, allowed in (
            ("applicability", assessment.applicability_supports, set(candidate.applies_when)),
            ("failure", assessment.triggered_failure_supports, set(candidate.fails_when)),
        ):
            conditions = [item.boundary_condition for item in supports]
            if len(conditions) != len(set(conditions)):
                findings.append(f"Taste assessment {case_id!r} repeats a {label} condition")
            for support in supports:
                if support.boundary_condition not in allowed:
                    findings.append(
                        f"Taste assessment {case_id!r} cites an unknown {label} condition"
                    )
                if not set(support.decision_fact_ids).issubset(fact_ids):
                    findings.append(f"Taste assessment {case_id!r} cites an unknown decision fact")
        if (
            assessment.verdict is TasteTransferVerdict.APPLICABLE
            and candidate.hard_applicability_satisfied is not False
            and len(assessment.applicability_supports) >= 2
            and not assessment.triggered_failure_supports
            and assessment.counterfactual_status is TasteCounterfactualStatus.NOT_TRIGGERED
            and (
                not boundary_fact_ids
                or any(
                    boundary_fact_ids.intersection(support.decision_fact_ids)
                    for support in assessment.applicability_supports
                )
            )
            and assessment.aligned_current_action_ids
            and (
                set(assessment.aligned_current_action_ids) != action_ids
                or bool(assessment.opposed_current_action_ids)
            )
        ):
            eligible[case_id] = assessment
        if (
            candidate.hard_applicability_satisfied is False
            and assessment.verdict is TasteTransferVerdict.APPLICABLE
        ):
            findings.append(
                f"Taste assessment {case_id!r} overrode deterministic hard applicability"
            )
    selected = set(proposal.selected_case_ids)
    if not selected.issubset(candidate_by_id):
        findings.append("Taste deliberation selected a case outside the closed pool")
    if not selected.issubset(eligible):
        findings.append("Taste deliberation selected an inapplicable or unsupported case")
    if proposal.schema_version == "1.1" and proposal.recommended_action_id is not None:
        if proposal.recommended_action_id not in action_ids:
            findings.append("Taste deliberation recommended an unknown current action")
        supported_recommendations = {
            action_id
            for case_id in selected
            if case_id in eligible
            for action_id in eligible[case_id].aligned_current_action_ids
        }
        if proposal.recommended_action_id not in supported_recommendations:
            findings.append(
                "Taste deliberation recommendation lacks selected applicable precedent support"
            )

    selected_candidates = [
        candidate_by_id[item] for item in proposal.selected_case_ids if item in candidate_by_id
    ]
    for index, left in enumerate(selected_candidates):
        for right in selected_candidates[index + 1 :]:
            if set(left.source_identities) & set(right.source_identities):
                findings.append("Taste deliberation selected duplicate-source precedents")

    eligible_action_ids = {
        action_id for item in eligible.values() for action_id in item.aligned_current_action_ids
    }
    selected_action_ids = {
        action_id
        for case_id in selected
        if case_id in eligible
        for action_id in eligible[case_id].aligned_current_action_ids
    }
    if (
        proposal.schema_version == "1.0"
        and len(eligible_action_ids) >= 2
        and input_data.maximum_selected_cases >= 2
        and len(selected_action_ids) < 2
    ):
        findings.append("Taste deliberation omitted available current-action tension")
    eligible_non_support = {
        case_id
        for case_id, item in eligible.items()
        if item.role in {TasteDeliberationRole.CHALLENGE, TasteDeliberationRole.BOUNDARY}
    }
    if (
        eligible_non_support
        and len(proposal.selected_case_ids) >= 2
        and not selected.intersection(eligible_non_support)
    ):
        findings.append("Taste deliberation omitted available challenge or boundary evidence")
    return tuple(sorted(set(findings)))


def validate_taste_applicability(
    input_data: TasteDeliberationInput,
    proposal: TasteApplicabilityProposal,
) -> tuple[str, ...]:
    """Validate transfer judgments without asking the model to select an action."""

    synthetic = TasteDeliberationProposal(
        schema_version="1.1",
        decision_id=proposal.decision_id,
        assessments=proposal.assessments,
        selected_case_ids=(),
        recommended_action_id=None,
        selection_rationale="Applicability-only proposal; controller selection is pending.",
    )
    return validate_taste_deliberation(input_data, synthetic)


def shard_taste_deliberation_input(
    input_data: TasteDeliberationInput,
    *,
    maximum_candidates_per_shard: int = 3,
) -> tuple[TasteDeliberationInput, ...]:
    """Partition one closed pool into model-sized shards without changing its state.

    Deliberating over many long precedents in one structured generation creates an
    avoidable interface confound: a model may omit an assessment even when its
    scientific judgment is sound.  Every shard therefore retains the exact decision
    facts and action menu while exposing two or more candidates.  The companion merge
    function restores one proposal over the original closed pool.
    """

    if maximum_candidates_per_shard < 2:
        raise ValueError("Taste deliberation shards require at least two candidates")
    candidates = list(input_data.candidates)
    if len(candidates) <= maximum_candidates_per_shard:
        return (input_data,)
    shards = [
        candidates[index : index + maximum_candidates_per_shard]
        for index in range(0, len(candidates), maximum_candidates_per_shard)
    ]
    if len(shards[-1]) == 1:
        shards[-1].insert(0, shards[-2].pop())
    return tuple(
        input_data.model_copy(
            update={
                "decision_id": f"{input_data.decision_id}-shard-{index:02d}",
                "candidates": tuple(shard),
                "maximum_selected_cases": min(
                    input_data.maximum_selected_cases,
                    len(shard),
                ),
            }
        )
        for index, shard in enumerate(shards, 1)
    )


def merge_taste_deliberation_proposals(
    input_data: TasteDeliberationInput,
    *,
    shard_inputs: Sequence[TasteDeliberationInput],
    shard_proposals: Sequence[TasteDeliberationProposal],
) -> TasteDeliberationProposal:
    """Merge validated shard assessments through a deterministic Taste policy.

    Models judge transfer boundaries; the controller owns population coverage,
    source de-duplication, the selection ceiling, and the final action aggregation.
    This separation keeps recommendation invariant to shard and presentation order.
    """

    if not shard_inputs or len(shard_inputs) != len(shard_proposals):
        raise ValueError("Taste deliberation merge requires one proposal per shard")
    expected_candidates = {item.case_id: item for item in input_data.candidates}
    observed_candidates: dict[str, TasteDeliberationCandidate] = {}
    assessments: list[TasteCaseTransferAssessment] = []
    for shard_input, proposal in zip(shard_inputs, shard_proposals, strict=True):
        if (
            shard_input.state_snapshot_id != input_data.state_snapshot_id
            or shard_input.stage != input_data.stage
            or shard_input.current_actions != input_data.current_actions
            or shard_input.decision_facts != input_data.decision_facts
        ):
            raise ValueError("Taste deliberation shard changed the decision state")
        findings = validate_taste_deliberation(shard_input, proposal)
        if findings:
            raise ValueError("invalid Taste deliberation shard: " + "; ".join(findings))
        for candidate in shard_input.candidates:
            if candidate.case_id in observed_candidates:
                raise ValueError("Taste deliberation shards overlap")
            observed_candidates[candidate.case_id] = candidate
        assessments.extend(proposal.assessments)
    if observed_candidates != expected_candidates:
        raise ValueError("Taste deliberation shards do not partition the closed pool")

    assessment_by_id = {item.case_id: item for item in assessments}
    boundary_fact_ids = {
        item.fact_id for item in input_data.decision_facts if item.boundary_candidate
    }
    eligible = [
        candidate
        for candidate in input_data.candidates
        if _assessment_is_eligible(
            candidate,
            assessment_by_id[candidate.case_id],
            current_action_ids={item.action_id for item in input_data.current_actions},
            required_boundary_fact_ids=boundary_fact_ids,
        )
    ]
    eligible.sort(
        key=lambda candidate: (
            -assessment_by_id[candidate.case_id].relevance_confidence,
            -candidate.confidence,
            -candidate.broad_retrieval_score,
            candidate.case_id,
        )
    )
    selected: list[TasteDeliberationCandidate] = []
    selected_sources: set[str] = set()
    for candidate in eligible:
        if selected_sources.intersection(candidate.source_identities):
            continue
        selected.append(candidate)
        selected_sources.update(candidate.source_identities)
        if len(selected) == input_data.maximum_selected_cases:
            break

    action_scores = {item.action_id: 0.0 for item in input_data.current_actions}
    for candidate in selected:
        assessment = assessment_by_id[candidate.case_id]
        weight = assessment.relevance_confidence * (0.5 + 0.5 * candidate.confidence)
        for action_id in assessment.aligned_current_action_ids:
            action_scores[action_id] += weight
        for action_id in assessment.opposed_current_action_ids:
            action_scores[action_id] -= weight
    recommended_action_id = None
    if selected:
        recommended_action_id = min(
            action_scores,
            key=lambda action_id: (-action_scores[action_id], action_id),
        )
        if not any(
            recommended_action_id in assessment_by_id[candidate.case_id].aligned_current_action_ids
            for candidate in selected
        ):
            selected = []
            recommended_action_id = None

    selected_ids = tuple(item.case_id for item in selected)
    rationale = (
        "No precedent satisfied two applicability boundaries without triggering a "
        "failure boundary; the selector abstained."
        if not selected_ids
        else (
            "The controller selected the highest-confidence source-disjoint applicable "
            f"precedents ({', '.join(selected_ids)}) and recommended "
            f"{recommended_action_id} by confidence-weighted aligned-minus-opposed support."
        )
    )
    proposal = TasteDeliberationProposal(
        schema_version="1.1",
        decision_id=input_data.decision_id,
        assessments=tuple(sorted(assessments, key=lambda item: item.case_id)),
        selected_case_ids=selected_ids,
        recommended_action_id=recommended_action_id,
        selection_rationale=rationale,
    )
    findings = validate_taste_deliberation(input_data, proposal)
    if findings:
        raise ValueError("merged Taste deliberation is invalid: " + "; ".join(findings))
    return proposal


def merge_taste_applicability_proposals(
    input_data: TasteDeliberationInput,
    *,
    shard_inputs: Sequence[TasteDeliberationInput],
    shard_proposals: Sequence[TasteApplicabilityProposal],
) -> TasteDeliberationProposal:
    """Compile applicability-only shard outputs into one controller proposal."""

    deliberation_proposals: list[TasteDeliberationProposal] = []
    for shard_input, proposal in zip(shard_inputs, shard_proposals, strict=True):
        findings = validate_taste_applicability(shard_input, proposal)
        if findings:
            raise ValueError("invalid Taste applicability shard: " + "; ".join(findings))
        deliberation_proposals.append(
            TasteDeliberationProposal(
                schema_version="1.1",
                decision_id=proposal.decision_id,
                assessments=proposal.assessments,
                selected_case_ids=(),
                recommended_action_id=None,
                selection_rationale=("Applicability-only shard; controller selection is pending."),
            )
        )
    return merge_taste_deliberation_proposals(
        input_data,
        shard_inputs=shard_inputs,
        shard_proposals=deliberation_proposals,
    )


def _assessment_is_eligible(
    candidate: TasteDeliberationCandidate,
    assessment: TasteCaseTransferAssessment,
    *,
    current_action_ids: set[str],
    required_boundary_fact_ids: set[str] | None = None,
) -> bool:
    aligned = set(assessment.aligned_current_action_ids)
    opposed = set(assessment.opposed_current_action_ids)
    discriminates = bool(aligned) and (aligned != current_action_ids or bool(opposed))
    boundary_grounded = not required_boundary_fact_ids or any(
        required_boundary_fact_ids.intersection(support.decision_fact_ids)
        for support in assessment.applicability_supports
    )
    return (
        assessment.verdict is TasteTransferVerdict.APPLICABLE
        and candidate.hard_applicability_satisfied is not False
        and len(assessment.applicability_supports) >= 2
        and not assessment.triggered_failure_supports
        and assessment.counterfactual_status is TasteCounterfactualStatus.NOT_TRIGGERED
        and boundary_grounded
        and discriminates
    )


def select_deliberated_taste_cases(
    *,
    input_data: TasteDeliberationInput,
    proposal: TasteDeliberationProposal,
    broad_candidates: list[RetrievedTasteCase],
) -> list[RetrievedTasteCase]:
    """Apply an accepted proposal without silently falling back to lexical ranking."""

    findings = validate_taste_deliberation(input_data, proposal)
    if findings:
        raise ValueError("invalid Taste deliberation: " + "; ".join(findings))
    by_id = {item.case.case_id: item for item in broad_candidates}
    assessments = {item.case_id: item for item in proposal.assessments}
    result: list[RetrievedTasteCase] = []
    for case_id in proposal.selected_case_ids:
        retrieved = by_id.get(case_id)
        if retrieved is None:
            raise ValueError("Taste deliberation result is absent from broad retrieval")
        assessment = assessments[case_id]
        fact_ids = sorted(
            {
                fact_id
                for support in (
                    *assessment.applicability_supports,
                    *assessment.triggered_failure_supports,
                )
                for fact_id in support.decision_fact_ids
            }
        )
        result.append(
            retrieved.model_copy(
                update={
                    "selection_role": assessment.role.value,
                    "applicability_confidence": assessment.relevance_confidence,
                    "selection_fact_ids": fact_ids,
                    "deliberation_sha256": proposal.fingerprint,
                }
            )
        )
    return result


def _candidate_projection(result: RetrievedTasteCase) -> TasteDeliberationCandidate:
    case = result.case
    return TasteDeliberationCandidate(
        case_id=case.case_id,
        case_sha256=_canonical_sha256(case.model_dump(mode="json")),
        taste_grounding_sha256=case.taste_grounding_sha256,
        source_identities=tuple(sorted({_source_identity(item) for item in case.provenance})),
        stage=case.stage,
        context_summary=case.context_summary,
        problem_pattern=case.problem_pattern,
        evidence_state=case.evidence_state,
        candidate_actions=tuple(case.candidate_actions),
        preferred_action=case.preferred_action,
        rejected_actions=tuple(case.rejected_actions),
        decision_principle=case.decision_principle,
        why_preferred=case.why_preferred,
        applies_when=tuple(case.applicability_conditions),
        fails_when=tuple(case.failure_conditions),
        counterfactual_probe=case.counterfactual_probe,
        confidence=case.confidence,
        broad_retrieval_score=result.score,
        broad_matched_fields=tuple(result.matched_fields),
    )


def _decision_facts(state: ResearchState) -> tuple[TasteDecisionFact, ...]:
    raw: list[tuple[str, str]] = [
        ("direction", state.research_direction),
        ("domain", state.target_domain),
        ("stage", state.current_stage.value),
    ]
    if state.target_venue:
        raw.append(("venue", state.target_venue))
    raw.extend(
        ("hypothesis", f"{item.statement} [status={item.status}]")
        for item in state.hypotheses[-12:]
    )
    raw.extend(
        (
            "observation",
            f"{item.statement} [reproducible={item.reproducible}; stability={item.stability}]",
        )
        for item in state.observations[-12:]
    )
    raw.extend(("claim", f"{item.text} [status={item.status}]") for item in state.claims[-12:])
    raw.extend(
        (
            "obligation",
            f"{item.required_action} [action={item.action_type}; status={item.status}]",
        )
        for item in state.open_research_obligations[-12:]
    )
    facts: list[TasteDecisionFact] = []
    seen: set[str] = set()
    for kind, value in raw:
        text = value.strip()
        identity = f"fact-{hashlib.sha256(f'{kind}:{text}'.encode()).hexdigest()[:20]}"
        if identity in seen:
            continue
        seen.add(identity)
        facts.append(TasteDecisionFact(fact_id=identity, kind=kind, text=text))
    return tuple(facts)


def _source_identity(provenance: object) -> str:
    payload = {
        "source_type": provenance.source_type,
        "locator": provenance.locator,
        "content_hash": provenance.content_hash,
        "version": provenance.version,
    }
    return "source-" + _canonical_sha256(payload)


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "TASTE_APPLICABILITY_NODE",
    "TASTE_DELIBERATION_NODE",
    "TasteApplicabilityProposal",
    "TasteBoundarySupport",
    "TasteCaseTransferAssessment",
    "TasteCounterfactualStatus",
    "TasteDecisionFact",
    "TasteDeliberationCandidate",
    "TasteDeliberationInput",
    "TasteDeliberationProposal",
    "TasteDeliberationRole",
    "TasteTransferVerdict",
    "VerifiedTasteDeliberation",
    "build_taste_deliberation_input",
    "merge_taste_applicability_proposals",
    "merge_taste_deliberation_proposals",
    "select_deliberated_taste_cases",
    "shard_taste_deliberation_input",
    "validate_taste_applicability",
    "validate_taste_deliberation",
]
