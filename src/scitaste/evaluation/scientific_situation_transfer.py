"""Outcome-grounded transfer over typed, pre-decision scientific situations.

This module separates two authorities that earlier SciTaste prototypes mixed:

* a model may abstract only the scientific situation visible before a decision;
* executable counterfactual branches alone supply action utility supervision.

The transfer rule is intentionally small and inspectable.  It normalizes utility
within each source fork, aggregates only cross-task precedents, and abstains when
support, agreement, or the best-action margin is inadequate.
"""

from __future__ import annotations

import math
from collections import Counter
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.project.models import content_sha256, validate_entry_id

_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)
_SHA256 = r"^[0-9a-f]{64}$"


class HypothesisStructure(StrEnum):
    NONE = "none"
    SINGLE_CANDIDATE = "single-candidate"
    COMPETING_CANDIDATES = "competing-candidates"


class EvidenceRelation(StrEnum):
    ABSENT = "absent"
    CONSISTENT = "consistent"
    CONFLICTED = "conflicted"
    UNDERDETERMINED = "underdetermined"


class ScientificBottleneck(StrEnum):
    VARIABLE_DISCOVERY = "variable-discovery"
    FUNCTIONAL_FORM = "functional-form-discrimination"
    PARAMETER_ESTIMATION = "parameter-estimation"
    CONTRADICTION_RESOLUTION = "contradiction-resolution"
    ROBUSTNESS_VALIDATION = "robustness-validation"
    TERMINAL_CALIBRATION = "terminal-calibration"


class IdentifiabilityBand(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class BudgetPressure(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TerminalReadiness(StrEnum):
    NOT_READY = "not-ready"
    AMBIGUOUS = "ambiguous"
    READY = "ready"


class ScientificSituationAxis(StrEnum):
    HYPOTHESIS_STRUCTURE = "hypothesis_structure"
    EVIDENCE_RELATION = "evidence_relation"
    BOTTLENECK = "bottleneck"
    IDENTIFIABILITY = "identifiability"
    BUDGET_PRESSURE = "budget_pressure"
    TERMINAL_READINESS = "terminal_readiness"


class ScientificSituationEvidenceAnchor(BaseModel):
    """A short exact quote from one declared selector-visible field."""

    model_config = _CONFIG

    field_id: str = Field(min_length=1, max_length=100)
    quote: str = Field(min_length=2, max_length=500)
    supports_axes: tuple[ScientificSituationAxis, ...] = Field(
        default=(),
        max_length=6,
        exclude_if=lambda value: not value,
    )

    @model_validator(mode="after")
    def supported_axes_are_unique(self) -> ScientificSituationEvidenceAnchor:
        if len(self.supports_axes) != len(set(self.supports_axes)):
            raise ValueError("scientific-situation anchor axes must be unique")
        return self


class ScientificSituationProposal(BaseModel):
    """Model-produced abstraction before provenance is bound by the runtime."""

    model_config = _CONFIG

    hypothesis_structure: HypothesisStructure
    evidence_relation: EvidenceRelation
    bottleneck: ScientificBottleneck
    identifiability: IdentifiabilityBand
    budget_pressure: BudgetPressure
    terminal_readiness: TerminalReadiness
    anchors: tuple[ScientificSituationEvidenceAnchor, ...] = Field(
        min_length=2,
        max_length=6,
    )
    decision_basis: str = Field(min_length=1, max_length=2_000)
    abstraction_confidence: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)

    @model_validator(mode="after")
    def anchors_are_distinct(self) -> ScientificSituationProposal:
        identities = [(item.field_id, item.quote) for item in self.anchors]
        if len(identities) != len(set(identities)):
            raise ValueError("scientific-situation evidence anchors must be unique")
        return self


class ScientificSituation(BaseModel):
    """Auditable epistemic state derived without target action outcomes."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    contract_id: Literal["predecision-scientific-situation-v1"] = (
        "predecision-scientific-situation-v1"
    )
    study_id: str
    task_cluster_id: str = Field(min_length=1)
    prefix_sha256: str = Field(pattern=_SHA256)
    hypothesis_structure: HypothesisStructure
    evidence_relation: EvidenceRelation
    bottleneck: ScientificBottleneck
    identifiability: IdentifiabilityBand
    budget_pressure: BudgetPressure
    terminal_readiness: TerminalReadiness
    anchors: tuple[ScientificSituationEvidenceAnchor, ...] = Field(
        min_length=2,
        max_length=6,
    )
    anchor_normalization_repairs: tuple[str, ...] = Field(
        default=(),
        max_length=6,
        exclude_if=lambda value: not value,
    )
    decision_basis: str = Field(min_length=1, max_length=2_000)
    abstraction_confidence: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    extractor_provider: str = Field(min_length=1)
    extractor_model: str = Field(min_length=1)
    request_fingerprint: str = Field(pattern=_SHA256)
    response_sha256: str = Field(pattern=_SHA256)
    target_outcomes_visible_to_extractor: Literal[False] = False
    situation_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def situation_is_closed(self) -> ScientificSituation:
        validate_entry_id(self.study_id, field_name="scientific-situation study_id")
        expected = content_sha256(self.model_dump(mode="json", exclude={"situation_sha256"}))
        if self.situation_sha256 != expected:
            raise ValueError("scientific-situation hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> ScientificSituation:
        payload = {
            "schema_version": "1.0",
            "contract_id": "predecision-scientific-situation-v1",
            "target_outcomes_visible_to_extractor": False,
            **values,
        }
        payload.pop("situation_sha256", None)
        if "anchors" in payload:
            payload["anchors"] = tuple(
                ScientificSituationEvidenceAnchor.model_validate(item)
                for item in payload["anchors"]  # type: ignore[union-attr]
            )
        unsigned = cls.model_construct(situation_sha256="0" * 64, **payload)
        return cls(
            **payload,
            situation_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"situation_sha256"})
            ),
        )


def validate_scientific_situation_grounding(
    situation: ScientificSituation,
    *,
    visible_fields: dict[str, str],
    require_all_axes: bool,
) -> tuple[str, ...]:
    """Check exact-span grounding against the outcome-hidden selector view.

    Formal extraction must set ``require_all_axes``. Development artifacts may
    keep older 2--6-anchor proposals, but cannot thereby claim axis-complete
    grounding.
    """

    findings: list[str] = []
    supported_axes: set[ScientificSituationAxis] = set()
    for anchor in situation.anchors:
        source = visible_fields.get(anchor.field_id)
        if source is None:
            findings.append(f"unknown-anchor-field:{anchor.field_id}")
        elif anchor.quote not in source:
            findings.append(f"non-exact-anchor:{anchor.field_id}")
        supported_axes.update(anchor.supports_axes)
    if require_all_axes:
        missing = set(ScientificSituationAxis) - supported_axes
        findings.extend(f"ungrounded-axis:{item.value}" for item in sorted(missing))
    return tuple(sorted(set(findings)))


class ObjectiveForkSituationCase(BaseModel):
    """Legacy development source with one outcome per action.

    These cases remain useful for falsification and interface development, but
    they cannot support a formal effect claim because they contain neither
    replicate-level uncertainty nor an intention-to-treat failure value.
    """

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    study_id: str
    task_cluster_id: str = Field(min_length=1)
    situation: ScientificSituation
    observed_actions: tuple[str, ...] = Field(min_length=1)
    normalized_action_utilities: dict[str, float] = Field(min_length=1)
    result_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def utility_population_is_closed(self) -> ObjectiveForkSituationCase:
        validate_entry_id(self.study_id, field_name="objective-fork situation study_id")
        if self.study_id != self.situation.study_id:
            raise ValueError("objective-fork case and situation study IDs differ")
        if self.task_cluster_id != self.situation.task_cluster_id:
            raise ValueError("objective-fork case and situation task clusters differ")
        if self.observed_actions != tuple(sorted(set(self.observed_actions))):
            raise ValueError("observed actions must be sorted and unique")
        if set(self.normalized_action_utilities) != set(self.observed_actions):
            raise ValueError("normalized utility and observed-action populations differ")
        if any(not 0.0 <= item <= 1.0 for item in self.normalized_action_utilities.values()):
            raise ValueError("normalized objective-fork utilities must lie in [0, 1]")
        return self


class ObjectiveForkReplicateOutcome(BaseModel):
    """One independently seeded branch on a registered common utility scale."""

    model_config = _CONFIG

    action_id: str = Field(min_length=1)
    replicate_id: str = Field(min_length=1)
    executed: bool
    objective_observed: bool
    utility: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    failure_code: str | None = Field(default=None, min_length=1, max_length=500)
    result_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def execution_status_is_closed(self) -> ObjectiveForkReplicateOutcome:
        if self.objective_observed and not self.executed:
            raise ValueError("an unexecuted branch cannot expose an objective outcome")
        if self.objective_observed == (self.failure_code is not None):
            raise ValueError(
                "objective-fork replicate requires a failure code exactly when the "
                "objective is unobserved"
            )
        return self


class FormalObjectiveForkSituationCase(BaseModel):
    """Scorer-owned source case admissible for confirmatory Taste transfer.

    Unlike :class:`ObjectiveForkSituationCase`, this contract retains every
    attempted branch, including failures, and requires repeated continuations
    for every action.  Utilities are means on one registered task-family scale;
    per-fork min--max normalization is forbidden.
    """

    model_config = _CONFIG

    schema_version: Literal["2.0"] = "2.0"
    study_id: str
    task_cluster_id: str = Field(min_length=1)
    situation: ScientificSituation
    available_actions: tuple[str, ...] = Field(min_length=2)
    utility_contract_id: str = Field(min_length=1)
    action_semantics_sha256: str = Field(pattern=_SHA256)
    practical_equivalence_tolerance: float = Field(
        ge=0.0,
        le=1.0,
        allow_inf_nan=False,
    )
    intention_to_treat_failure_utility: float = Field(
        ge=0.0,
        le=1.0,
        allow_inf_nan=False,
    )
    replicate_outcomes: tuple[ObjectiveForkReplicateOutcome, ...] = Field(min_length=6)
    action_utility_estimates: dict[str, float] = Field(min_length=2)
    result_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def formal_population_is_closed(self) -> FormalObjectiveForkSituationCase:
        validate_entry_id(self.study_id, field_name="formal objective-fork study_id")
        if self.study_id != self.situation.study_id:
            raise ValueError("formal objective-fork case and situation study IDs differ")
        if self.task_cluster_id != self.situation.task_cluster_id:
            raise ValueError("formal objective-fork case and situation task clusters differ")
        if self.available_actions != tuple(sorted(set(self.available_actions))):
            raise ValueError("formal objective-fork actions must be sorted and unique")
        if set(self.action_utility_estimates) != set(self.available_actions):
            raise ValueError("formal objective-fork estimates must cover every action")
        replicate_ids = [item.replicate_id for item in self.replicate_outcomes]
        if len(replicate_ids) != len(set(replicate_ids)):
            raise ValueError("formal objective-fork replicate IDs must be unique")
        counts = Counter(item.action_id for item in self.replicate_outcomes)
        if set(counts) != set(self.available_actions) or any(
            count < 3 for count in counts.values()
        ):
            raise ValueError(
                "formal objective-fork cases require at least three replicates per action"
            )
        for outcome in self.replicate_outcomes:
            if outcome.action_id not in self.available_actions:
                raise ValueError("formal objective-fork replicate uses an unknown action")
            if (
                not outcome.objective_observed
                and abs(outcome.utility - self.intention_to_treat_failure_utility) > 1e-9
            ):
                raise ValueError(
                    "failed formal branches must retain the registered intention-to-treat utility"
                )
        for action in self.available_actions:
            utilities = [
                item.utility for item in self.replicate_outcomes if item.action_id == action
            ]
            mean = sum(utilities) / len(utilities)
            if abs(mean - self.action_utility_estimates[action]) > 1e-9:
                raise ValueError(
                    "formal objective-fork action estimate differs from its replicate mean"
                )
        return self

    def action_sampling_variance(self, action_id: str) -> tuple[float, int]:
        """Return the within-case variance and replicate count for one action."""

        values = [item.utility for item in self.replicate_outcomes if item.action_id == action_id]
        if len(values) < 2:
            return 0.0, len(values)
        mean = sum(values) / len(values)
        return sum((value - mean) ** 2 for value in values) / (len(values) - 1), len(values)


ScientificSituationSourceCase = ObjectiveForkSituationCase | FormalObjectiveForkSituationCase


def _source_actions(source: ScientificSituationSourceCase) -> set[str]:
    if isinstance(source, FormalObjectiveForkSituationCase):
        return set(source.available_actions)
    return set(source.normalized_action_utilities)


def _source_utility(source: ScientificSituationSourceCase, action_id: str) -> float:
    if isinstance(source, FormalObjectiveForkSituationCase):
        return source.action_utility_estimates[action_id]
    return source.normalized_action_utilities[action_id]


def _source_sampling_variance(
    source: ScientificSituationSourceCase,
    action_id: str,
) -> tuple[float, int]:
    if isinstance(source, FormalObjectiveForkSituationCase):
        return source.action_sampling_variance(action_id)
    return 0.0, 1


class ScientificSituationTransferThresholds(BaseModel):
    """Frozen selective-prediction gate for one development or formal program."""

    model_config = _CONFIG

    minimum_abstraction_confidence: float = Field(
        default=0.6,
        ge=0.0,
        le=1.0,
        allow_inf_nan=False,
    )
    minimum_source_similarity: float = Field(
        default=0.45,
        ge=0.0,
        le=1.0,
        allow_inf_nan=False,
    )
    minimum_effective_support: float = Field(default=2.0, gt=0, allow_inf_nan=False)
    minimum_action_margin: float = Field(
        default=0.08,
        ge=0.0,
        le=1.0,
        allow_inf_nan=False,
    )
    maximum_standard_error: float = Field(
        default=0.2,
        ge=0.0,
        le=1.0,
        allow_inf_nan=False,
    )
    require_formal_sources: bool = Field(
        default=False,
        exclude_if=lambda value: not value,
    )


class ScientificSituationActionEstimate(BaseModel):
    model_config = _CONFIG

    action_id: str = Field(min_length=1)
    expected_normalized_utility: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    weighted_standard_deviation: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    standard_error: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    effective_support: float = Field(gt=0, allow_inf_nan=False)
    maximum_source_similarity: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    contributing_case_ids: tuple[str, ...] = Field(min_length=1)
    contributing_task_cluster_count: int = Field(
        default=1,
        ge=1,
        exclude_if=lambda value: value == 1,
    )
    minimum_replicates_per_case: int = Field(
        default=1,
        ge=1,
        exclude_if=lambda value: value == 1,
    )
    replicate_aware_uncertainty: bool = Field(
        default=False,
        exclude_if=lambda value: not value,
    )


class ScientificSituationBoundaryAssessment(BaseModel):
    """Explicit transfer boundary between one source and the target situation."""

    model_config = _CONFIG

    source_case_id: str
    source_task_cluster_id: str = Field(min_length=1)
    similarity: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    satisfied_dimensions: tuple[str, ...] = Field(max_length=6)
    violated_dimensions: tuple[str, ...] = Field(max_length=6)

    @model_validator(mode="after")
    def dimensions_partition_the_contract(self) -> ScientificSituationBoundaryAssessment:
        expected = {
            "hypothesis_structure",
            "evidence_relation",
            "bottleneck",
            "identifiability",
            "budget_pressure",
            "terminal_readiness",
        }
        satisfied = set(self.satisfied_dimensions)
        violated = set(self.violated_dimensions)
        if satisfied & violated or satisfied | violated != expected:
            raise ValueError("scientific-situation boundary dimensions must form a partition")
        if self.satisfied_dimensions != tuple(sorted(satisfied)):
            raise ValueError("satisfied boundary dimensions must be sorted and unique")
        if self.violated_dimensions != tuple(sorted(violated)):
            raise ValueError("violated boundary dimensions must be sorted and unique")
        return self


class ScientificSituationTransferDecision(BaseModel):
    """One selective action decision with all support and abstention evidence."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    target_study_id: str
    target_situation_sha256: str = Field(pattern=_SHA256)
    excluded_same_cluster_case_ids: tuple[str, ...] = ()
    estimates: tuple[ScientificSituationActionEstimate, ...] = ()
    source_boundary_assessments: tuple[ScientificSituationBoundaryAssessment, ...] = Field(
        default=(),
        exclude_if=lambda value: not value,
    )
    selected_action: str | None = Field(default=None, min_length=1)
    abstained: bool
    abstention_reasons: tuple[str, ...] = ()
    best_action_margin: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    outcome_grounded_source_count: int = Field(ge=0)
    target_outcomes_used_for_selection: Literal[False] = False
    decision_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def decision_is_closed(self) -> ScientificSituationTransferDecision:
        validate_entry_id(
            self.target_study_id,
            field_name="scientific-situation target study_id",
        )
        if self.abstained == (self.selected_action is not None):
            raise ValueError("transfer decision must select one action xor abstain")
        if self.abstained != bool(self.abstention_reasons):
            raise ValueError("abstention reasons must be present exactly when abstaining")
        if self.estimates != tuple(
            sorted(
                self.estimates,
                key=lambda item: (-item.expected_normalized_utility, item.action_id),
            )
        ):
            raise ValueError("action estimates must be ordered by utility then action ID")
        boundary_ids = [item.source_case_id for item in self.source_boundary_assessments]
        if len(boundary_ids) != len(set(boundary_ids)):
            raise ValueError("source boundary assessments must cover unique cases")
        if self.source_boundary_assessments != tuple(
            sorted(self.source_boundary_assessments, key=lambda item: item.source_case_id)
        ):
            raise ValueError("source boundary assessments must be ordered by case ID")
        if not self.estimates and not self.abstained:
            raise ValueError("a transfer decision without estimates must abstain")
        if self.selected_action is not None and self.selected_action != self.estimates[0].action_id:
            raise ValueError("selected action differs from the highest transfer estimate")
        expected = content_sha256(self.model_dump(mode="json", exclude={"decision_sha256"}))
        if self.decision_sha256 != expected:
            raise ValueError("scientific-situation transfer decision hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> ScientificSituationTransferDecision:
        payload = {
            "schema_version": "1.0",
            "target_outcomes_used_for_selection": False,
            **values,
        }
        payload.pop("decision_sha256", None)
        unsigned = cls.model_construct(decision_sha256="0" * 64, **payload)
        return cls(
            **payload,
            decision_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"decision_sha256"})
            ),
        )


class ScientificSituationModelActionScore(BaseModel):
    """One model-estimated action value before deterministic admission."""

    model_config = _CONFIG

    action_id: str = Field(min_length=1)
    estimated_normalized_utility: float = Field(
        ge=0.0,
        le=1.0,
        allow_inf_nan=False,
    )


class ScientificSituationModelTransferProposal(BaseModel):
    """Bounded model synthesis of typed, outcome-grounded source precedents."""

    model_config = _CONFIG

    target_study_id: str
    action_scores: tuple[ScientificSituationModelActionScore, ...] = Field(min_length=2)
    selected_action: str | None = Field(default=None, min_length=1)
    should_abstain: bool
    used_precedent_ids: tuple[str, ...] = Field(default=(), max_length=6)
    confidence: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    rationale: str = Field(min_length=1, max_length=3_000)

    @model_validator(mode="after")
    def proposal_is_atomic(self) -> ScientificSituationModelTransferProposal:
        validate_entry_id(
            self.target_study_id,
            field_name="scientific-situation model target study_id",
        )
        if self.should_abstain and self.selected_action is not None:
            raise ValueError("an abstaining model transfer proposal cannot select an action")
        action_ids = [item.action_id for item in self.action_scores]
        if len(action_ids) != len(set(action_ids)):
            raise ValueError("model transfer action scores must be unique")
        if self.selected_action is not None and self.selected_action not in action_ids:
            raise ValueError("model transfer selection lacks an action score")
        if len(self.used_precedent_ids) != len(set(self.used_precedent_ids)):
            raise ValueError("model transfer precedent IDs must be unique")
        return self


class ScientificSituationModelTransferDecision(BaseModel):
    """Model proposal after deterministic support and uncertainty checks."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    target_study_id: str
    target_situation_sha256: str = Field(pattern=_SHA256)
    candidate_precedent_ids: tuple[str, ...] = Field(min_length=2, max_length=6)
    used_precedent_ids: tuple[str, ...] = Field(default=(), max_length=6)
    normalization_repairs: tuple[str, ...] = Field(
        default=(),
        max_length=4,
        exclude_if=lambda value: not value,
    )
    action_scores: tuple[ScientificSituationModelActionScore, ...] = Field(min_length=2)
    proposed_action: str | None = Field(default=None, min_length=1)
    selected_action: str | None = Field(default=None, min_length=1)
    abstained: bool
    abstention_reasons: tuple[str, ...] = ()
    best_action_margin: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    model_confidence: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    request_fingerprint: str = Field(pattern=_SHA256)
    response_sha256: str = Field(pattern=_SHA256)
    target_outcomes_visible_to_model: Literal[False] = False
    target_outcomes_used_for_selection: Literal[False] = False
    decision_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def model_decision_is_closed(self) -> ScientificSituationModelTransferDecision:
        validate_entry_id(
            self.target_study_id,
            field_name="scientific-situation model decision study_id",
        )
        if self.candidate_precedent_ids != tuple(sorted(set(self.candidate_precedent_ids))):
            raise ValueError("candidate precedent IDs must be sorted and unique")
        if self.used_precedent_ids != tuple(sorted(set(self.used_precedent_ids))):
            raise ValueError("used precedent IDs must be sorted and unique")
        if set(self.used_precedent_ids) - set(self.candidate_precedent_ids):
            raise ValueError("model used a precedent outside its candidate set")
        if self.abstained == (self.selected_action is not None):
            raise ValueError("admitted model decision must select one action xor abstain")
        if self.abstained != bool(self.abstention_reasons):
            raise ValueError("model decision abstention reasons are inconsistent")
        expected = content_sha256(self.model_dump(mode="json", exclude={"decision_sha256"}))
        if self.decision_sha256 != expected:
            raise ValueError("scientific-situation model decision hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> ScientificSituationModelTransferDecision:
        payload = {
            "schema_version": "1.0",
            "target_outcomes_visible_to_model": False,
            "target_outcomes_used_for_selection": False,
            **values,
        }
        payload.pop("decision_sha256", None)
        if "action_scores" in payload:
            payload["action_scores"] = tuple(
                ScientificSituationModelActionScore.model_validate(item)
                for item in payload["action_scores"]  # type: ignore[union-attr]
            )
        unsigned = cls.model_construct(decision_sha256="0" * 64, **payload)
        return cls(
            **payload,
            decision_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"decision_sha256"})
            ),
        )


def normalize_objective_fork_utilities(
    values: dict[str, float],
    observed: dict[str, bool],
    *,
    metric_direction: Literal["higher", "lower"] = "higher",
) -> dict[str, float]:
    """Normalize scorer-observed actions for consumed development diagnostics.

    Per-fork min--max values are not a common scientific utility scale. They must
    not be used to admit a formal benchmark item or to claim an effect unless the
    source contract separately establishes practical separation.
    """

    if set(values) != set(observed):
        raise ValueError("objective values and observation maps differ")
    eligible = {
        action: float(value)
        for action, value in values.items()
        if observed[action] and math.isfinite(value)
    }
    if not eligible:
        raise ValueError("objective fork has no observed finite action utility")
    minimum = min(eligible.values())
    maximum = max(eligible.values())
    spread = maximum - minimum
    if spread <= 1e-12:
        return {action: 1.0 for action in sorted(eligible)}
    return {
        action: (
            (eligible[action] - minimum) / spread
            if metric_direction == "higher"
            else (maximum - eligible[action]) / spread
        )
        for action in sorted(eligible)
    }


def scientific_situation_similarity(
    source: ScientificSituation,
    target: ScientificSituation,
) -> float:
    """Return a typed, outcome-independent similarity in [0, 1]."""

    components = (
        (source.bottleneck == target.bottleneck, 0.30),
        (source.hypothesis_structure == target.hypothesis_structure, 0.18),
        (source.evidence_relation == target.evidence_relation, 0.17),
        (source.identifiability == target.identifiability, 0.14),
        (source.terminal_readiness == target.terminal_readiness, 0.11),
        (source.budget_pressure == target.budget_pressure, 0.10),
    )
    return sum(weight for matched, weight in components if matched)


def assess_scientific_situation_boundary(
    source: ScientificSituationSourceCase,
    target: ScientificSituation,
) -> ScientificSituationBoundaryAssessment:
    """Expose the exact matched and violated axes behind one transfer weight."""

    dimensions = {
        "hypothesis_structure": source.situation.hypothesis_structure
        == target.hypothesis_structure,
        "evidence_relation": source.situation.evidence_relation == target.evidence_relation,
        "bottleneck": source.situation.bottleneck == target.bottleneck,
        "identifiability": source.situation.identifiability == target.identifiability,
        "budget_pressure": source.situation.budget_pressure == target.budget_pressure,
        "terminal_readiness": source.situation.terminal_readiness == target.terminal_readiness,
    }
    return ScientificSituationBoundaryAssessment(
        source_case_id=source.study_id,
        source_task_cluster_id=source.task_cluster_id,
        similarity=scientific_situation_similarity(source.situation, target),
        satisfied_dimensions=tuple(sorted(key for key, matched in dimensions.items() if matched)),
        violated_dimensions=tuple(
            sorted(key for key, matched in dimensions.items() if not matched)
        ),
    )


def scientific_situation_candidate_precedents(
    *,
    target: ScientificSituation,
    sources: tuple[ScientificSituationSourceCase, ...],
    maximum_precedents: int = 6,
) -> tuple[ScientificSituationSourceCase, ...]:
    """Select the most similar cross-task cases without consulting target outcomes."""

    if not 2 <= maximum_precedents <= 12:
        raise ValueError("maximum scientific-situation precedents must be in [2, 12]")
    eligible = [item for item in sources if item.task_cluster_id != target.task_cluster_id]
    if len({item.task_cluster_id for item in eligible}) < 2:
        raise ValueError("model transfer requires precedents from at least two source tasks")
    return tuple(
        sorted(
            eligible,
            key=lambda item: (
                -scientific_situation_similarity(item.situation, target),
                item.study_id,
            ),
        )[:maximum_precedents]
    )


def admit_scientific_situation_model_proposal(
    *,
    target: ScientificSituation,
    candidates: tuple[ScientificSituationSourceCase, ...],
    proposal: ScientificSituationModelTransferProposal,
    available_actions: set[str],
    request_fingerprint: str,
    response_sha256: str,
    minimum_confidence: float = 0.7,
    minimum_action_margin: float = 0.1,
    minimum_used_task_clusters: int = 2,
    minimum_used_precedent_similarity: float = 0.45,
) -> ScientificSituationModelTransferDecision:
    """Apply non-model support gates to one outcome-hidden synthesis proposal."""

    if proposal.target_study_id != target.study_id:
        raise ValueError("model transfer proposal targets another scientific situation")
    scores = {item.action_id: item.estimated_normalized_utility for item in proposal.action_scores}
    if set(scores) != available_actions:
        raise ValueError("model transfer action-score population differs from action menu")
    candidate_by_id = {item.study_id: item for item in candidates}
    ranked = sorted(scores, key=lambda action: (-scores[action], action))
    best = ranked[0]
    margin = scores[best] - scores[ranked[1]]
    reasons: list[str] = []
    repairs: list[str] = []
    proposed_action = proposal.selected_action
    if proposed_action is None and not proposal.should_abstain:
        proposed_action = best
        repairs.append("selected-action-filled-from-unique-highest-score")
    if proposal.should_abstain:
        reasons.append("model-requested-abstention")
    if proposed_action is not None and proposed_action != best:
        reasons.append("selection-score-disagreement")
    if proposal.confidence < minimum_confidence:
        reasons.append("low-model-confidence")
    unknown_precedents = set(proposal.used_precedent_ids) - set(candidate_by_id)
    if unknown_precedents:
        reasons.append("unknown-precedent-citation")
    used_ids = tuple(item for item in proposal.used_precedent_ids if item in candidate_by_id)
    used = [candidate_by_id[item] for item in used_ids]
    if len({item.task_cluster_id for item in used}) < minimum_used_task_clusters:
        reasons.append("insufficient-source-task-diversity")
    if (
        used
        and min(scientific_situation_similarity(item.situation, target) for item in used)
        < minimum_used_precedent_similarity
    ):
        reasons.append("cited-precedent-outside-transfer-boundary")
    if not used:
        reasons.append("no-outcome-grounded-precedent-cited")
    if margin < minimum_action_margin:
        reasons.append("insufficient-action-margin")
    return ScientificSituationModelTransferDecision.create(
        target_study_id=target.study_id,
        target_situation_sha256=target.situation_sha256,
        candidate_precedent_ids=tuple(sorted(candidate_by_id)),
        used_precedent_ids=tuple(sorted(used_ids)),
        normalization_repairs=tuple(repairs),
        action_scores=tuple(proposal.action_scores),
        proposed_action=proposed_action,
        selected_action=None if reasons else proposed_action,
        abstained=bool(reasons),
        abstention_reasons=tuple(reasons),
        best_action_margin=margin,
        model_confidence=proposal.confidence,
        request_fingerprint=request_fingerprint,
        response_sha256=response_sha256,
    )


def select_by_scientific_situation(
    *,
    target: ScientificSituation,
    sources: tuple[ScientificSituationSourceCase, ...],
    available_actions: set[str],
    thresholds: ScientificSituationTransferThresholds,
) -> ScientificSituationTransferDecision:
    """Choose from cross-task objective precedents or explicitly abstain."""

    if not available_actions:
        raise ValueError("scientific-situation transfer requires available actions")
    same_cluster = tuple(
        sorted(item.study_id for item in sources if item.task_cluster_id == target.task_cluster_id)
    )
    eligible = tuple(item for item in sources if item.task_cluster_id != target.task_cluster_id)
    if not eligible:
        raise ValueError("scientific-situation transfer requires cross-task precedents")

    # Compare every candidate action on the same source population. Otherwise an
    # action can appear strongest merely because its failed/missing branches were
    # silently omitted, while another action is averaged over a harder subset.
    common_support = tuple(
        item for item in eligible if available_actions.issubset(_source_actions(item))
    )
    if thresholds.require_formal_sources:
        common_support = tuple(
            item for item in common_support if isinstance(item, FormalObjectiveForkSituationCase)
        )
        utility_contract_ids = {item.utility_contract_id for item in common_support}
        action_semantics = {item.action_semantics_sha256 for item in common_support}
        if len(utility_contract_ids) > 1 or len(action_semantics) > 1:
            boundaries = tuple(
                sorted(
                    (assess_scientific_situation_boundary(item, target) for item in common_support),
                    key=lambda item: item.source_case_id,
                )
            )
            return ScientificSituationTransferDecision.create(
                target_study_id=target.study_id,
                target_situation_sha256=target.situation_sha256,
                excluded_same_cluster_case_ids=same_cluster,
                estimates=(),
                source_boundary_assessments=boundaries,
                selected_action=None,
                abstained=True,
                abstention_reasons=("incompatible-formal-utility-or-action-contracts",),
                best_action_margin=0.0,
                outcome_grounded_source_count=len(common_support),
            )
    if not common_support:
        return ScientificSituationTransferDecision.create(
            target_study_id=target.study_id,
            target_situation_sha256=target.situation_sha256,
            excluded_same_cluster_case_ids=same_cluster,
            estimates=(),
            source_boundary_assessments=(),
            selected_action=None,
            abstained=True,
            abstention_reasons=("no-common-action-support",),
            best_action_margin=0.0,
            outcome_grounded_source_count=0,
        )

    boundary_assessments = tuple(
        sorted(
            (assess_scientific_situation_boundary(item, target) for item in common_support),
            key=lambda item: item.source_case_id,
        )
    )

    estimates: list[ScientificSituationActionEstimate] = []
    for action in sorted(available_actions):
        weighted_by_cluster: dict[
            str,
            list[tuple[float, float, str, float, float, int]],
        ] = {}
        for source in common_support:
            similarity = scientific_situation_similarity(source.situation, target)
            if similarity < thresholds.minimum_source_similarity:
                continue
            weight = similarity * similarity
            sampling_variance, replicate_count = _source_sampling_variance(source, action)
            weighted_by_cluster.setdefault(source.task_cluster_id, []).append(
                (
                    weight,
                    _source_utility(source, action),
                    source.study_id,
                    similarity,
                    sampling_variance,
                    replicate_count,
                )
            )
        contributing_case_ids = tuple(
            sorted(
                case_id for rows in weighted_by_cluster.values() for _, _, case_id, _, _, _ in rows
            )
        )
        # Repeated prefixes from one task are correlated. Collapse them to one
        # task-cluster contribution before estimating transfer uncertainty.
        weighted: list[tuple[float, float, str, float, float, int]] = []
        for task_cluster_id, rows in sorted(weighted_by_cluster.items()):
            cluster_weight = sum(item[0] for item in rows)
            cluster_value = sum(item[0] * item[1] for item in rows) / cluster_weight
            cluster_sampling_variance = sum(
                item[0] * item[0] * item[4] / item[5] for item in rows
            ) / (cluster_weight * cluster_weight)
            weighted.append(
                (
                    max(item[0] for item in rows),
                    cluster_value,
                    task_cluster_id,
                    max(item[3] for item in rows),
                    cluster_sampling_variance,
                    min(item[5] for item in rows),
                )
            )
        if not weighted:
            continue
        total_weight = sum(item[0] for item in weighted)
        mean = sum(weight * value for weight, value, _, _, _, _ in weighted) / total_weight
        variance = (
            sum(weight * (value - mean) ** 2 for weight, value, _, _, _, _ in weighted)
            / total_weight
        )
        effective = total_weight * total_weight / sum(item[0] ** 2 for item in weighted)
        deviation = math.sqrt(max(variance, 0.0))
        sampling_variance_of_mean = sum(
            weight * weight * within_variance for weight, _, _, _, within_variance, _ in weighted
        ) / (total_weight * total_weight)
        standard_error = math.sqrt(max(variance / effective + sampling_variance_of_mean, 0.0))
        estimates.append(
            ScientificSituationActionEstimate(
                action_id=action,
                expected_normalized_utility=min(max(mean, 0.0), 1.0),
                weighted_standard_deviation=min(max(deviation, 0.0), 1.0),
                standard_error=min(max(standard_error, 0.0), 1.0),
                effective_support=effective,
                maximum_source_similarity=max(item[3] for item in weighted),
                contributing_case_ids=contributing_case_ids,
                contributing_task_cluster_count=len(weighted),
                minimum_replicates_per_case=min(item[5] for item in weighted),
                replicate_aware_uncertainty=all(item[5] >= 3 for item in weighted),
            )
        )
    if not estimates:
        return ScientificSituationTransferDecision.create(
            target_study_id=target.study_id,
            target_situation_sha256=target.situation_sha256,
            excluded_same_cluster_case_ids=same_cluster,
            estimates=(),
            source_boundary_assessments=boundary_assessments,
            selected_action=None,
            abstained=True,
            abstention_reasons=("no-similar-common-action-support",),
            best_action_margin=0.0,
            outcome_grounded_source_count=len(common_support),
        )
    ordered = tuple(
        sorted(estimates, key=lambda item: (-item.expected_normalized_utility, item.action_id))
    )
    best = ordered[0]
    runner_up = ordered[1] if len(ordered) > 1 else None
    margin = (
        best.expected_normalized_utility
        if runner_up is None
        else best.expected_normalized_utility - runner_up.expected_normalized_utility
    )
    reasons: list[str] = []
    if target.abstraction_confidence < thresholds.minimum_abstraction_confidence:
        reasons.append("low-abstraction-confidence")
    if best.maximum_source_similarity < thresholds.minimum_source_similarity:
        reasons.append("no-sufficiently-similar-precedent")
    if best.effective_support < thresholds.minimum_effective_support:
        reasons.append("insufficient-effective-support")
    if margin < thresholds.minimum_action_margin:
        reasons.append("insufficient-action-margin")
    if thresholds.require_formal_sources:
        formal_tolerance = max(
            item.practical_equivalence_tolerance
            for item in common_support
            if isinstance(item, FormalObjectiveForkSituationCase)
        )
        if margin <= formal_tolerance:
            reasons.append("margin-within-practical-equivalence")
        if not best.replicate_aware_uncertainty:
            reasons.append("non-replicate-aware-uncertainty")
    if best.standard_error > thresholds.maximum_standard_error:
        reasons.append("excessive-transfer-uncertainty")
    return ScientificSituationTransferDecision.create(
        target_study_id=target.study_id,
        target_situation_sha256=target.situation_sha256,
        excluded_same_cluster_case_ids=same_cluster,
        estimates=ordered,
        source_boundary_assessments=boundary_assessments,
        selected_action=None if reasons else best.action_id,
        abstained=bool(reasons),
        abstention_reasons=tuple(reasons),
        best_action_margin=margin,
        outcome_grounded_source_count=len(common_support),
    )


__all__ = [
    "BudgetPressure",
    "EvidenceRelation",
    "FormalObjectiveForkSituationCase",
    "HypothesisStructure",
    "IdentifiabilityBand",
    "ObjectiveForkReplicateOutcome",
    "ObjectiveForkSituationCase",
    "ScientificBottleneck",
    "ScientificSituation",
    "ScientificSituationActionEstimate",
    "ScientificSituationAxis",
    "ScientificSituationBoundaryAssessment",
    "ScientificSituationEvidenceAnchor",
    "ScientificSituationModelActionScore",
    "ScientificSituationModelTransferDecision",
    "ScientificSituationModelTransferProposal",
    "ScientificSituationProposal",
    "ScientificSituationTransferDecision",
    "ScientificSituationTransferThresholds",
    "TerminalReadiness",
    "admit_scientific_situation_model_proposal",
    "assess_scientific_situation_boundary",
    "normalize_objective_fork_utilities",
    "scientific_situation_candidate_precedents",
    "scientific_situation_similarity",
    "select_by_scientific_situation",
    "validate_scientific_situation_grounding",
]
