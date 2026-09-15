"""Family-conditioned scientific Taste policies over admitted research episodes."""

from __future__ import annotations

import json
import os
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.project.idea_revision import (
    ProjectIdeaRevisionBinding,
    idea_binding_matches_current,
)
from scitaste.project.models import content_sha256, validate_entry_id
from scitaste.schema.actions import ResearchAction
from scitaste.state.research_state import ResearchState
from scitaste.taste.episode_learning import (
    AdmittedTasteEpisode,
    LifecycleTastePolicyAssessment,
    LifecycleTastePolicyConfig,
    LifecycleTastePolicyModel,
    assess_lifecycle_taste_policy,
    fit_lifecycle_taste_policy,
)
from scitaste.taste.episodes import TasteOutcomeFamily

_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_ARTIFACT_BYTES = 64 * 1024 * 1024


class ScientificTasteDecisionFamily(StrEnum):
    """Orthogonal scientific judgments that should not share one pooled score."""

    SCIENTIFIC_VALUE = "scientific-value"
    EPISTEMIC_DISCRIMINATION = "epistemic-discrimination"
    EMPIRICAL_DIAGNOSTICITY = "empirical-diagnosticity"
    ADAPTIVE_ALLOCATION = "adaptive-allocation"
    INFERENTIAL_DISCIPLINE = "inferential-discipline"
    TRANSFER_AND_CORRECTION = "transfer-and-correction"
    SCIENTIFIC_COMMUNICATION = "scientific-communication"


SCIENTIFIC_TASTE_DECISION_ONTOLOGY_VERSION = "scientific-taste-decision-families-v1"
SCIENTIFIC_TASTE_DECISION_FAMILY_DESCRIPTIONS = {
    ScientificTasteDecisionFamily.SCIENTIFIC_VALUE: (
        "select questions, hypotheses, and contributions whose expected scientific value "
        "justifies their opportunity cost"
    ),
    ScientificTasteDecisionFamily.EPISTEMIC_DISCRIMINATION: (
        "prefer decisions that separate plausible explanations and reduce consequential uncertainty"
    ),
    ScientificTasteDecisionFamily.EMPIRICAL_DIAGNOSTICITY: (
        "design measurements, controls, and ablations that diagnose mechanisms rather than "
        "only improve a score"
    ),
    ScientificTasteDecisionFamily.ADAPTIVE_ALLOCATION: (
        "allocate remaining experiments, model calls, and time from observed trajectory state"
    ),
    ScientificTasteDecisionFamily.INFERENTIAL_DISCIPLINE: (
        "calibrate claims to evidence, account for confounding, and stop unsupported inference"
    ),
    ScientificTasteDecisionFamily.TRANSFER_AND_CORRECTION: (
        "transfer precedents only under matching conditions and reverse course when evidence "
        "invalidates the analogy"
    ),
    ScientificTasteDecisionFamily.SCIENTIFIC_COMMUNICATION: (
        "organize and express a scientific argument without changing its evidential strength"
    ),
}
SCIENTIFIC_TASTE_DECISION_ONTOLOGY_SHA256 = content_sha256(
    {
        "version": SCIENTIFIC_TASTE_DECISION_ONTOLOGY_VERSION,
        "families": {
            family.value: description
            for family, description in SCIENTIFIC_TASTE_DECISION_FAMILY_DESCRIPTIONS.items()
        },
    }
)


class ScientificDecisionFamilyReview(BaseModel):
    """One isolated AI judgment over the fixed scientific-decision ontology."""

    model_config = _CONFIG

    reviewer_id: str = Field(pattern=_ID)
    invocation_id: str = Field(pattern=_ID)
    model_identifier: str = Field(min_length=1, max_length=500)
    role: Literal["primary", "adjudicator"]
    decision_family: ScientificTasteDecisionFamily
    rationale: str = Field(min_length=1, max_length=10_000)
    raw_response_sha256: str = Field(pattern=_SHA256)
    runtime_bound: bool = False
    admission_id: str | None = Field(default=None, pattern=_ID)
    admission_sha256: str | None = Field(default=None, pattern=_SHA256)
    packet_sha256: str | None = Field(default=None, pattern=_SHA256)
    provider_id: str | None = Field(default=None, max_length=300)
    model_id: str | None = Field(default=None, max_length=500)
    project_run_id: str | None = Field(default=None, pattern=_ID)
    ledger_entry_sha256: str | None = Field(default=None, pattern=_SHA256)
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True

    @model_validator(mode="after")
    def runtime_binding_is_atomic(self) -> ScientificDecisionFamilyReview:
        bindings = (
            self.admission_id,
            self.admission_sha256,
            self.packet_sha256,
            self.provider_id,
            self.model_id,
            self.project_run_id,
            self.ledger_entry_sha256,
        )
        if self.runtime_bound != all(item is not None for item in bindings):
            raise ValueError("decision-family runtime evidence binding must be complete")
        if not self.runtime_bound and any(item is not None for item in bindings):
            raise ValueError("legacy decision-family review cannot carry partial runtime evidence")
        if self.runtime_bound and self.model_identifier != f"{self.provider_id}:{self.model_id}":
            raise ValueError("decision-family model identifier differs from runtime evidence")
        return self


class ScientificDecisionFamilyAssignment(BaseModel):
    """AI-reviewed, outcome-blind assignment of one episode to one decision family."""

    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1"] = "1.1"
    assignment_id: str = Field(pattern=_ID)
    admission_id: str = Field(pattern=_ID)
    admission_sha256: str = Field(pattern=_SHA256)
    decision_family: ScientificTasteDecisionFamily
    ontology_sha256: str = Field(pattern=_SHA256)
    observed_outcome_families: tuple[TasteOutcomeFamily, ...] = Field(
        min_length=1,
        max_length=20,
    )
    rationale: str = Field(min_length=1, max_length=10_000)
    assignment_method: Literal["ai-review"] = "ai-review"
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    runtime_review_evidence_bound: bool = False
    reviews: tuple[ScientificDecisionFamilyReview, ...] = Field(
        min_length=2,
        max_length=3,
    )
    assignment_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def assignment_is_closed(self) -> ScientificDecisionFamilyAssignment:
        validate_entry_id(self.assignment_id, field_name="decision-family assignment_id")
        validate_entry_id(self.admission_id, field_name="decision-family admission_id")
        if self.ontology_sha256 != SCIENTIFIC_TASTE_DECISION_ONTOLOGY_SHA256:
            raise ValueError("decision-family assignment uses another ontology")
        if self.observed_outcome_families != tuple(
            sorted(set(self.observed_outcome_families), key=lambda item: item.value)
        ):
            raise ValueError("decision-family outcome families must be sorted and unique")
        primary = tuple(item for item in self.reviews if item.role == "primary")
        adjudicators = tuple(item for item in self.reviews if item.role == "adjudicator")
        if len(primary) != 2:
            raise ValueError("decision-family assignment requires two primary AI reviews")
        if len({item.reviewer_id for item in self.reviews}) != len(self.reviews):
            raise ValueError("decision-family assignment reviewers must be distinct")
        if len({item.invocation_id for item in self.reviews}) != len(self.reviews):
            raise ValueError("decision-family review invocations must be distinct")
        if len({item.raw_response_sha256 for item in self.reviews}) != len(self.reviews):
            raise ValueError("decision-family raw review responses must be distinct")
        if len({item.model_identifier for item in self.reviews}) != len(self.reviews):
            raise ValueError("decision-family AI reviewers must use distinct models")
        if self.runtime_review_evidence_bound != all(item.runtime_bound for item in self.reviews):
            raise ValueError("decision-family runtime-review binding summary differs")
        if (
            any(item.runtime_bound for item in self.reviews)
            and not self.runtime_review_evidence_bound
        ):
            raise ValueError(
                "decision-family review panel cannot mix runtime-bound and legacy records"
            )
        if self.runtime_review_evidence_bound:
            if any(
                item.admission_id != self.admission_id
                or item.admission_sha256 != self.admission_sha256
                for item in self.reviews
            ):
                raise ValueError("decision-family runtime review binds another episode")
            if len({item.packet_sha256 for item in primary}) != 1:
                raise ValueError("decision-family primaries did not receive the same packet")
        primary_families = {item.decision_family for item in primary}
        if len(primary_families) == 1:
            if adjudicators or primary[0].decision_family is not self.decision_family:
                raise ValueError("unanimous family reviews require no adjudicator")
        elif len(adjudicators) != 1 or adjudicators[0].decision_family is not self.decision_family:
            raise ValueError("split family reviews require one decisive adjudicator")
        payload = self.model_dump(mode="json", exclude={"assignment_sha256"})
        accepted_hashes = {content_sha256(payload)}
        if self.schema_version == "1.0":
            payload.pop("runtime_review_evidence_bound", None)
            for review in payload["reviews"]:
                for name in (
                    "runtime_bound",
                    "admission_id",
                    "admission_sha256",
                    "packet_sha256",
                    "provider_id",
                    "model_id",
                    "project_run_id",
                    "ledger_entry_sha256",
                ):
                    review.pop(name, None)
            accepted_hashes.add(content_sha256(payload))
        if self.assignment_sha256 not in accepted_hashes:
            raise ValueError("decision-family assignment hash differs")
        return self

    @classmethod
    def create(cls, **values: object) -> ScientificDecisionFamilyAssignment:
        payload = {
            "schema_version": "1.1",
            "ontology_sha256": SCIENTIFIC_TASTE_DECISION_ONTOLOGY_SHA256,
            "assignment_method": "ai-review",
            "reviewer_kind": "ai",
            "not_human_review": True,
            **values,
        }
        payload.pop("assignment_sha256", None)
        outcomes = payload.get("observed_outcome_families")
        if outcomes is not None:
            payload["observed_outcome_families"] = tuple(
                sorted(
                    {TasteOutcomeFamily(item) for item in outcomes},  # type: ignore[union-attr]
                    key=lambda item: item.value,
                )
            )
        reviews = payload.get("reviews")
        if reviews is not None:
            payload["runtime_review_evidence_bound"] = all(
                item.runtime_bound
                for item in reviews  # type: ignore[union-attr]
            )
        unsigned = cls.model_construct(assignment_sha256="0" * 64, **payload)
        return cls(
            **payload,
            assignment_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"assignment_sha256"})
            ),
        )


class FamilyConditionedLifecycleTastePolicy(BaseModel):
    """Independent lifecycle-policy heads selected by a bound decision-family ledger."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    policy_id: str = Field(pattern=_ID)
    idea_revision: ProjectIdeaRevisionBinding
    ontology_sha256: str = Field(pattern=_SHA256)
    source_episode_ids: tuple[str, ...] = Field(min_length=1)
    source_episode_sha256: tuple[str, ...] = Field(min_length=1)
    assignments: tuple[ScientificDecisionFamilyAssignment, ...] = Field(min_length=1)
    assignment_population_sha256: str = Field(pattern=_SHA256)
    family_heads: dict[ScientificTasteDecisionFamily, LifecycleTastePolicyModel]
    empty_families: tuple[ScientificTasteDecisionFamily, ...]
    conditioning_method: Literal["independent-family-heads-v1"] = "independent-family-heads-v1"
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    human_validity_claim_allowed: Literal[False] = False
    policy_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def policy_is_closed(self) -> FamilyConditionedLifecycleTastePolicy:
        validate_entry_id(self.policy_id, field_name="family-conditioned policy_id")
        if self.ontology_sha256 != SCIENTIFIC_TASTE_DECISION_ONTOLOGY_SHA256:
            raise ValueError("family-conditioned policy uses another ontology")
        if self.source_episode_ids != tuple(sorted(set(self.source_episode_ids))):
            raise ValueError("family-conditioned source episode IDs are not canonical")
        if len(self.source_episode_ids) != len(self.source_episode_sha256):
            raise ValueError("family-conditioned source episode hashes do not close")
        assignments = tuple(sorted(self.assignments, key=lambda item: item.admission_id))
        if self.assignments != assignments:
            raise ValueError("decision-family assignments must be sorted by admission ID")
        if tuple(item.admission_id for item in assignments) != self.source_episode_ids:
            raise ValueError("decision-family assignments do not cover the source population")
        if tuple(item.admission_sha256 for item in assignments) != self.source_episode_sha256:
            raise ValueError("decision-family assignments bind another source population")
        expected_assignment_hash = content_sha256(
            tuple(item.model_dump(mode="json") for item in assignments)
        )
        if self.assignment_population_sha256 != expected_assignment_hash:
            raise ValueError("decision-family assignment population hash differs")
        assigned_families = {item.decision_family for item in assignments}
        if set(self.family_heads) != assigned_families:
            raise ValueError("family-conditioned policy heads differ from assigned families")
        if list(self.family_heads) != sorted(self.family_heads, key=lambda item: item.value):
            raise ValueError("family-conditioned policy heads are not canonical")
        all_families = set(ScientificTasteDecisionFamily)
        expected_empty = tuple(
            sorted(all_families - assigned_families, key=lambda item: item.value)
        )
        if self.empty_families != expected_empty:
            raise ValueError("family-conditioned empty-family ledger differs")
        source = dict(zip(self.source_episode_ids, self.source_episode_sha256, strict=True))
        assignments_by_family = {
            family: tuple(item for item in assignments if item.decision_family is family)
            for family in assigned_families
        }
        for family, head in self.family_heads.items():
            expected = assignments_by_family[family]
            if head.policy_id != f"{self.policy_id}-{family.value}":
                raise ValueError("family-conditioned head ID differs")
            if not idea_binding_matches_current(head.config.idea_revision, self.idea_revision):
                raise ValueError("family-conditioned head belongs to another Idea revision")
            if head.source_episode_ids != tuple(item.admission_id for item in expected):
                raise ValueError("family-conditioned head uses another episode partition")
            if head.source_episode_sha256 != tuple(source[item.admission_id] for item in expected):
                raise ValueError("family-conditioned head episode hashes differ")
        expected_policy_hash = content_sha256(
            self.model_dump(mode="json", exclude={"policy_sha256"})
        )
        if self.policy_sha256 != expected_policy_hash:
            raise ValueError("family-conditioned policy hash differs")
        return self

    @classmethod
    def create(cls, **values: object) -> FamilyConditionedLifecycleTastePolicy:
        payload = {
            "schema_version": "1.0",
            "ontology_sha256": SCIENTIFIC_TASTE_DECISION_ONTOLOGY_SHA256,
            "conditioning_method": "independent-family-heads-v1",
            "reviewer_kind": "ai",
            "not_human_review": True,
            "human_validity_claim_allowed": False,
            **values,
        }
        payload.pop("policy_sha256", None)
        unsigned = cls.model_construct(policy_sha256="0" * 64, **payload)
        return cls(
            **payload,
            policy_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"policy_sha256"})
            ),
        )

    def require_head(
        self,
        family: ScientificTasteDecisionFamily,
    ) -> LifecycleTastePolicyModel:
        """Return one isolated head, refusing an unobserved scientific judgment."""

        head = self.family_heads.get(family)
        if head is None:
            raise ValueError(f"no learned Taste head for decision family: {family.value}")
        return head


class FamilyConditionedTasteAssessment(BaseModel):
    """Decision-family routing evidence around an existing lifecycle assessment."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    policy_id: str
    policy_sha256: str = Field(pattern=_SHA256)
    decision_family: ScientificTasteDecisionFamily
    family_head_sha256: str | None = Field(default=None, pattern=_SHA256)
    candidate_set_sha256: str = Field(pattern=_SHA256)
    assessment: LifecycleTastePolicyAssessment | None = None
    recommended_action_id: str | None = None
    abstained: bool
    reason_codes: tuple[str, ...] = Field(min_length=1)
    assessment_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def assessment_is_closed(self) -> FamilyConditionedTasteAssessment:
        if self.assessment is None:
            if (
                self.family_head_sha256 is not None
                or not self.abstained
                or self.recommended_action_id is not None
                or self.reason_codes != ("unobserved-decision-family",)
            ):
                raise ValueError("unobserved decision family must abstain without a head")
        elif (
            self.family_head_sha256 != self.assessment.policy_sha256
            or self.candidate_set_sha256 != self.assessment.candidate_set_sha256
            or self.recommended_action_id != self.assessment.recommended_action_id
            or self.abstained != self.assessment.abstained
            or self.reason_codes != self.assessment.reason_codes
        ):
            raise ValueError("family-conditioned and head assessments differ")
        expected = content_sha256(self.model_dump(mode="json", exclude={"assessment_sha256"}))
        if self.assessment_sha256 != expected:
            raise ValueError("family-conditioned assessment hash differs")
        return self

    @classmethod
    def create(cls, **values: object) -> FamilyConditionedTasteAssessment:
        payload = {"schema_version": "1.0", **values}
        payload.pop("assessment_sha256", None)
        unsigned = cls.model_construct(assessment_sha256="0" * 64, **payload)
        return cls(
            **payload,
            assessment_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"assessment_sha256"})
            ),
        )


def fit_family_conditioned_lifecycle_taste_policy(
    episodes: tuple[AdmittedTasteEpisode, ...],
    assignments: tuple[ScientificDecisionFamilyAssignment, ...],
    config: LifecycleTastePolicyConfig,
    *,
    policy_id: str,
) -> FamilyConditionedLifecycleTastePolicy:
    """Fit isolated heads after requiring complete AI-reviewed family assignment."""

    validate_entry_id(policy_id, field_name="family-conditioned policy_id")
    episodes = tuple(sorted(episodes, key=lambda item: item.admission_id))
    assignments = tuple(sorted(assignments, key=lambda item: item.admission_id))
    if not episodes:
        raise ValueError("family-conditioned Taste fitting requires admitted episodes")
    if len({item.admission_id for item in episodes}) != len(episodes):
        raise ValueError("family-conditioned Taste fitting received duplicate episodes")
    if tuple(item.admission_id for item in assignments) != tuple(
        item.admission_id for item in episodes
    ):
        raise ValueError("decision-family assignments must exactly cover admitted episodes")
    if tuple(item.admission_sha256 for item in assignments) != tuple(
        item.admission_sha256 for item in episodes
    ):
        raise ValueError("decision-family assignments bind different episode bytes")

    heads: dict[ScientificTasteDecisionFamily, LifecycleTastePolicyModel] = {}
    assigned_families = sorted(
        {item.decision_family for item in assignments},
        key=lambda item: item.value,
    )
    for family in assigned_families:
        family_ids = {item.admission_id for item in assignments if item.decision_family is family}
        family_episodes = tuple(item for item in episodes if item.admission_id in family_ids)
        head_config = LifecycleTastePolicyConfig.model_validate(
            {
                **config.model_dump(mode="python"),
                "policy_id": f"{policy_id}-{family.value}",
            }
        )
        heads[family] = fit_lifecycle_taste_policy(family_episodes, head_config)

    all_families = set(ScientificTasteDecisionFamily)
    return FamilyConditionedLifecycleTastePolicy.create(
        policy_id=policy_id,
        idea_revision=config.idea_revision,
        source_episode_ids=tuple(item.admission_id for item in episodes),
        source_episode_sha256=tuple(item.admission_sha256 for item in episodes),
        assignments=assignments,
        assignment_population_sha256=content_sha256(
            tuple(item.model_dump(mode="json") for item in assignments)
        ),
        family_heads=heads,
        empty_families=tuple(
            sorted(all_families - set(assigned_families), key=lambda item: item.value)
        ),
    )


def assess_family_conditioned_lifecycle_taste_policy(
    model: FamilyConditionedLifecycleTastePolicy,
    *,
    decision_family: ScientificTasteDecisionFamily,
    state: ResearchState,
    actions: tuple[ResearchAction, ...],
    current_idea_revision: ProjectIdeaRevisionBinding | None = None,
) -> FamilyConditionedTasteAssessment:
    """Route a decision only to its family head and preserve head-level abstention."""

    if not actions:
        raise ValueError("family-conditioned Taste assessment requires candidate actions")
    candidate_set_sha256 = content_sha256([item.model_dump(mode="json") for item in actions])
    head = model.family_heads.get(decision_family)
    if head is None:
        return FamilyConditionedTasteAssessment.create(
            policy_id=model.policy_id,
            policy_sha256=model.policy_sha256,
            decision_family=decision_family,
            family_head_sha256=None,
            candidate_set_sha256=candidate_set_sha256,
            assessment=None,
            recommended_action_id=None,
            abstained=True,
            reason_codes=("unobserved-decision-family",),
        )
    assessment = assess_lifecycle_taste_policy(
        head,
        state=state,
        actions=actions,
        current_idea_revision=current_idea_revision,
    )
    return FamilyConditionedTasteAssessment.create(
        policy_id=model.policy_id,
        policy_sha256=model.policy_sha256,
        decision_family=decision_family,
        family_head_sha256=head.policy_sha256,
        candidate_set_sha256=candidate_set_sha256,
        assessment=assessment,
        recommended_action_id=assessment.recommended_action_id,
        abstained=assessment.abstained,
        reason_codes=assessment.reason_codes,
    )


def load_family_conditioned_lifecycle_taste_policy(
    path: str | Path,
) -> FamilyConditionedLifecycleTastePolicy:
    """Load a bounded immutable family-conditioned policy artifact."""

    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError("family-conditioned Taste policy must be a regular file")
    raw = source.read_bytes()
    if not 1 <= len(raw) <= _MAX_ARTIFACT_BYTES:
        raise ValueError("family-conditioned Taste policy has an invalid size")
    return FamilyConditionedLifecycleTastePolicy.model_validate_json(raw, strict=True)


def load_scientific_decision_family_assignment(
    path: str | Path,
) -> ScientificDecisionFamilyAssignment:
    """Load one bounded AI-reviewed family assignment."""

    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError("scientific decision-family assignment must be a regular file")
    raw = source.read_bytes()
    if not 1 <= len(raw) <= _MAX_ARTIFACT_BYTES:
        raise ValueError("scientific decision-family assignment has an invalid size")
    return ScientificDecisionFamilyAssignment.model_validate_json(raw, strict=True)


def save_family_conditioned_lifecycle_taste_policy(
    model: FamilyConditionedLifecycleTastePolicy,
    path: str | Path,
) -> Path:
    """Persist a new policy without replacing an earlier scientific artifact."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    payload = (
        json.dumps(
            model.model_dump(mode="json"),
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    with target.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    directory_descriptor = os.open(target.parent, os.O_RDONLY)
    try:
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)
    return target


def save_scientific_decision_family_assignment(
    assignment: ScientificDecisionFamilyAssignment,
    path: str | Path,
) -> Path:
    """Persist one immutable AI-reviewed family assignment."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    payload = (
        json.dumps(
            assignment.model_dump(mode="json"),
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    with target.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    directory_descriptor = os.open(target.parent, os.O_RDONLY)
    try:
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)
    return target


__all__ = [
    "SCIENTIFIC_TASTE_DECISION_FAMILY_DESCRIPTIONS",
    "SCIENTIFIC_TASTE_DECISION_ONTOLOGY_SHA256",
    "SCIENTIFIC_TASTE_DECISION_ONTOLOGY_VERSION",
    "FamilyConditionedLifecycleTastePolicy",
    "FamilyConditionedTasteAssessment",
    "ScientificDecisionFamilyAssignment",
    "ScientificDecisionFamilyReview",
    "ScientificTasteDecisionFamily",
    "assess_family_conditioned_lifecycle_taste_policy",
    "fit_family_conditioned_lifecycle_taste_policy",
    "load_family_conditioned_lifecycle_taste_policy",
    "load_scientific_decision_family_assignment",
    "save_family_conditioned_lifecycle_taste_policy",
    "save_scientific_decision_family_assignment",
]
