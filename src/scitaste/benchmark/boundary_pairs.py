"""Schemas and readiness checks for SciTasteBench boundary-counterfactual pairs.

The boundary pair is the independent unit of the benchmark.  It keeps the
scientific decision and action menu fixed while changing one registered fact
that should reverse the preferred action or whether the system should abstain.
This is deliberately separate from :mod:`scitaste.benchmark.models`: legacy
development suites must retain their existing content hashes.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.benchmark.models import BenchmarkDecisionContextFamily, BenchmarkLabelAuthority
from scitaste.schema.actions import ResearchAction
from scitaste.taste.decision_families import ScientificTasteDecisionFamily

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"


class BoundaryPairSplit(StrEnum):
    DEVELOPMENT = "development"
    VALIDATION = "validation"
    HIDDEN_TEST = "hidden-test"


class BoundaryFlipKind(StrEnum):
    ACTION_TO_ACTION = "action-to-action"
    ACTION_TO_ABSTENTION = "action-to-abstention"


class BoundaryStateRole(StrEnum):
    BASE = "base"
    TWIN = "twin"


class BoundaryFactChange(BaseModel):
    """The only scientific fact permitted to differ inside a pair."""

    model_config = _CONFIG

    fact_id: str = Field(min_length=1, max_length=160)
    question: str = Field(min_length=1, max_length=1_000)
    base_value: str = Field(min_length=1, max_length=4_000)
    twin_value: str = Field(min_length=1, max_length=4_000)
    why_decisive: str = Field(min_length=1, max_length=4_000)
    base_evidence_refs: tuple[str, ...] = Field(min_length=1, max_length=20)
    twin_construction_refs: tuple[str, ...] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def values_and_refs_differ(self) -> BoundaryFactChange:
        if self.base_value == self.twin_value:
            raise ValueError("a boundary fact must change between base and twin")
        if len(self.base_evidence_refs) != len(set(self.base_evidence_refs)):
            raise ValueError("base evidence references must be unique")
        if len(self.twin_construction_refs) != len(set(self.twin_construction_refs)):
            raise ValueError("twin construction references must be unique")
        return self


class BoundaryUtilityVector(BaseModel):
    """Separately registered benefits and liabilities of one feasible action."""

    model_config = _CONFIG

    evidence_value: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    expected_information_gain: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    resource_cost: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    claim_risk: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)


class BoundaryUtilityContract(BaseModel):
    """Frozen, context-specific aggregation rule for pair-level regret."""

    model_config = _CONFIG

    contract_id: str = Field(min_length=1, max_length=300)
    evidence_value_weight: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    expected_information_gain_weight: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    resource_cost_weight: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    claim_risk_weight: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    minimum_action_utility_for_commitment: float = Field(ge=-1.0, le=1.0, allow_inf_nan=False)
    component_anchors: dict[str, str]
    registered_before_system_outputs: Literal[True] = True

    @model_validator(mode="after")
    def weights_and_anchors_are_complete(self) -> BoundaryUtilityContract:
        weights = (
            self.evidence_value_weight,
            self.expected_information_gain_weight,
            self.resource_cost_weight,
            self.claim_risk_weight,
        )
        if abs(sum(weights) - 1.0) > 1e-9:
            raise ValueError("boundary utility component weights must sum to one")
        expected = {
            "evidence_value",
            "expected_information_gain",
            "resource_cost",
            "claim_risk",
        }
        if set(self.component_anchors) != expected:
            raise ValueError("boundary utility anchors must cover exactly four components")
        if any(not value.strip() for value in self.component_anchors.values()):
            raise ValueError("boundary utility anchors cannot be blank")
        return self

    def aggregate(self, vector: BoundaryUtilityVector) -> float:
        return (
            self.evidence_value_weight * vector.evidence_value
            + self.expected_information_gain_weight * vector.expected_information_gain
            - self.resource_cost_weight * vector.resource_cost
            - self.claim_risk_weight * vector.claim_risk
        )

    @property
    def sha256(self) -> str:
        canonical = json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode()).hexdigest()


class BoundaryPairState(BaseModel):
    """One outcome-hidden decision state in a counterfactual pair."""

    model_config = _CONFIG

    role: BoundaryStateRole
    decision_context: str = Field(min_length=1, max_length=40_000)
    visible_budget: str = Field(min_length=1, max_length=4_000)
    preferred_action_id: str | None = Field(default=None, min_length=1, max_length=300)
    should_abstain: bool = False
    action_utilities: dict[str, float]
    utility_components: dict[str, BoundaryUtilityVector] = Field(default_factory=dict)
    utility_rationale: dict[str, str]

    @model_validator(mode="after")
    def preference_and_utility_agree(self) -> BoundaryPairState:
        if not self.action_utilities:
            raise ValueError("a boundary state requires registered action utilities")
        if set(self.action_utilities) != set(self.utility_rationale):
            raise ValueError("utility rationales must cover every action utility")
        if self.should_abstain:
            if self.preferred_action_id is not None:
                raise ValueError("an abstention state cannot declare a preferred action")
        elif self.preferred_action_id is None:
            raise ValueError("a non-abstention state requires a preferred action")
        elif self.preferred_action_id not in self.action_utilities:
            raise ValueError("preferred action must have a registered utility")
        elif self.action_utilities[self.preferred_action_id] != max(self.action_utilities.values()):
            raise ValueError("preferred action must maximize registered utility")
        return self


class BoundaryPairJudgment(BaseModel):
    """One independent, pair-blinded construct judgment."""

    model_config = _CONFIG

    judgment_id: str = Field(min_length=1, max_length=300)
    reviewer_id: str = Field(min_length=1, max_length=300)
    authority: BenchmarkLabelAuthority
    expertise_scope: str = Field(min_length=1, max_length=1_000)
    base_selection_id: str | None = Field(default=None, min_length=1, max_length=300)
    twin_selection_id: str | None = Field(default=None, min_length=1, max_length=300)
    base_should_abstain: bool = False
    twin_should_abstain: bool = False
    confidence: float = Field(ge=0, le=1)
    pair_order_blinded: bool
    expected_pair_labels_hidden: bool
    conflict_cleared: bool
    evidence_refs: tuple[str, ...] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def selections_match_abstention(self) -> BoundaryPairJudgment:
        for role, selection, abstains in (
            ("base", self.base_selection_id, self.base_should_abstain),
            ("twin", self.twin_selection_id, self.twin_should_abstain),
        ):
            if abstains == (selection is not None):
                raise ValueError(f"{role} judgment must select an action xor abstain")
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("judgment evidence references must be unique")
        return self


class BoundaryConstructAudit(BaseModel):
    """Independent audit of counterfactual-pair construct validity."""

    model_config = _CONFIG

    audit_id: str = Field(min_length=1, max_length=300)
    reviewer_id: str = Field(min_length=1, max_length=300)
    authority: BenchmarkLabelAuthority
    expertise_scope: str = Field(min_length=1, max_length=1_000)
    single_atomic_fact: bool
    shared_context_fact_neutral: bool
    states_internally_noncontradictory: bool
    action_meanings_stable: bool
    actions_feasible_in_both_states: bool
    labels_uniquely_identifiable: bool
    abstention_explicitly_considered: bool
    utility_components_defensible: bool
    cue_shortcut_resistant: bool
    pair_order_blinded: bool
    expected_pair_labels_hidden: bool
    evidence_refs: tuple[str, ...] = Field(min_length=1, max_length=30)
    rejection_codes: tuple[str, ...] = Field(default_factory=tuple, max_length=30)

    @property
    def accepted(self) -> bool:
        checks = (
            self.single_atomic_fact,
            self.shared_context_fact_neutral,
            self.states_internally_noncontradictory,
            self.action_meanings_stable,
            self.actions_feasible_in_both_states,
            self.labels_uniquely_identifiable,
            self.abstention_explicitly_considered,
            self.utility_components_defensible,
            self.cue_shortcut_resistant,
            self.pair_order_blinded,
            self.expected_pair_labels_hidden,
        )
        return all(checks) and not self.rejection_codes

    @model_validator(mode="after")
    def rejection_codes_match_checks(self) -> BoundaryConstructAudit:
        if len(self.rejection_codes) != len(set(self.rejection_codes)):
            raise ValueError("construct-audit rejection codes must be unique")
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("construct-audit evidence references must be unique")
        if all(
            (
                self.single_atomic_fact,
                self.shared_context_fact_neutral,
                self.states_internally_noncontradictory,
                self.action_meanings_stable,
                self.actions_feasible_in_both_states,
                self.labels_uniquely_identifiable,
                self.abstention_explicitly_considered,
                self.utility_components_defensible,
                self.cue_shortcut_resistant,
                self.pair_order_blinded,
                self.expected_pair_labels_hidden,
            )
        ) != (not self.rejection_codes):
            raise ValueError("construct-audit checks and rejection codes disagree")
        return self


class BoundaryCounterfactualPair(BaseModel):
    """A natural decision and its single-fact counterfactual twin."""

    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1"] = "1.0"
    pair_id: str = Field(min_length=1, max_length=300)
    split: BoundaryPairSplit
    source_group_id: str = Field(min_length=1, max_length=300)
    domain: str = Field(min_length=1, max_length=300)
    decision_context_family: BenchmarkDecisionContextFamily
    taste_judgment_family: ScientificTasteDecisionFamily
    source_locator: str = Field(min_length=1, max_length=2_000)
    source_content_sha256: str = Field(pattern=_SHA256)
    license_identifier: str = Field(min_length=1, max_length=200)
    public_reconstruction_allowed: bool
    outcome_hidden_during_construction: bool
    candidate_actions: tuple[ResearchAction, ...] = Field(min_length=2, max_length=5)
    invariant_facts: tuple[str, ...] = Field(min_length=2, max_length=30)
    changed_fact: BoundaryFactChange
    flip_kind: BoundaryFlipKind
    utility_contract: BoundaryUtilityContract | None = None
    base: BoundaryPairState
    twin: BoundaryPairState
    judgments: tuple[BoundaryPairJudgment, ...] = ()
    construct_audits: tuple[BoundaryConstructAudit, ...] = ()
    contamination_probe_refs: tuple[str, ...] = Field(min_length=1, max_length=20)
    construction_manifest_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def pair_is_action_identifiable(self) -> BoundaryCounterfactualPair:
        if self.base.role is not BoundaryStateRole.BASE:
            raise ValueError("base state must use the base role")
        if self.twin.role is not BoundaryStateRole.TWIN:
            raise ValueError("twin state must use the twin role")
        action_ids = [action.action_id for action in self.candidate_actions]
        action_set = set(action_ids)
        if len(action_ids) != len(action_set):
            raise ValueError("candidate action ids must be unique")
        for state in (self.base, self.twin):
            if set(state.action_utilities) != action_set:
                raise ValueError("both states must score the identical action menu")
        if self.utility_contract is None:
            if self.base.utility_components or self.twin.utility_components:
                raise ValueError("utility components require a frozen utility contract")
            if self.schema_version == "1.1":
                raise ValueError("boundary pair schema 1.1 requires a utility contract")
        else:
            if self.schema_version != "1.1":
                raise ValueError("a utility contract requires boundary pair schema 1.1")
            for state in (self.base, self.twin):
                if set(state.utility_components) != action_set:
                    raise ValueError("utility components must cover the identical action menu")
                for action_id, vector in state.utility_components.items():
                    expected = self.utility_contract.aggregate(vector)
                    if abs(state.action_utilities[action_id] - expected) > 1e-6:
                        raise ValueError("scalar utility does not match the frozen contract")
                maximum = max(state.action_utilities.values())
                should_abstain = (
                    maximum <= self.utility_contract.minimum_action_utility_for_commitment
                )
                if state.should_abstain != should_abstain:
                    raise ValueError("abstention label contradicts the frozen utility threshold")
        if self.base.decision_context == self.twin.decision_context:
            raise ValueError("base and twin contexts must expose the registered fact change")
        if self.flip_kind is BoundaryFlipKind.ACTION_TO_ACTION:
            if self.base.should_abstain or self.twin.should_abstain:
                raise ValueError("action-to-action pairs cannot use abstention")
            if self.base.preferred_action_id == self.twin.preferred_action_id:
                raise ValueError("action-to-action pairs require a preferred-action flip")
        elif self.base.should_abstain == self.twin.should_abstain:
            raise ValueError("action-to-abstention pairs require exactly one abstention state")
        if len(self.invariant_facts) != len(set(self.invariant_facts)):
            raise ValueError("invariant facts must be unique")
        if len(self.contamination_probe_refs) != len(set(self.contamination_probe_refs)):
            raise ValueError("contamination probe references must be unique")
        for judgment in self.judgments:
            for selection in (judgment.base_selection_id, judgment.twin_selection_id):
                if selection is not None and selection not in action_set:
                    raise ValueError("judgment selected an action outside the frozen menu")
        audit_ids = [audit.audit_id for audit in self.construct_audits]
        audit_reviewers = [audit.reviewer_id for audit in self.construct_audits]
        if len(audit_ids) != len(set(audit_ids)):
            raise ValueError("construct-audit identities must be unique")
        if len(audit_reviewers) != len(set(audit_reviewers)):
            raise ValueError("construct audits require independent reviewers")
        return self

    @property
    def sha256(self) -> str:
        canonical = json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode()).hexdigest()


class BoundaryPairPackage(BaseModel):
    """Immutable benchmark population divided before model evaluation."""

    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1"] = "1.0"
    package_id: str = Field(min_length=1, max_length=300)
    release_tier: Literal["development", "formal"]
    pairs: tuple[BoundaryCounterfactualPair, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def identities_are_disjoint(self) -> BoundaryPairPackage:
        pair_ids = [pair.pair_id for pair in self.pairs]
        source_groups = [pair.source_group_id for pair in self.pairs]
        source_contents = [pair.source_content_sha256 for pair in self.pairs]
        if len(pair_ids) != len(set(pair_ids)):
            raise ValueError("boundary pair ids must be unique")
        if len(source_groups) != len(set(source_groups)):
            raise ValueError("one source group may contribute at most one boundary pair")
        if len(source_contents) != len(set(source_contents)):
            raise ValueError("duplicate source content cannot cross benchmark pairs")
        return self

    @property
    def sha256(self) -> str:
        canonical = json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode()).hexdigest()


class BoundaryPairReadiness(BaseModel):
    model_config = _CONFIG

    package_id: str
    package_sha256: str = Field(pattern=_SHA256)
    pair_count: int = Field(ge=1)
    item_count: int = Field(ge=2)
    domain_count: int = Field(ge=1)
    split_counts: dict[BoundaryPairSplit, int]
    context_counts: dict[BenchmarkDecisionContextFamily, int]
    action_flip_count: int = Field(ge=0)
    abstention_flip_count: int = Field(ge=0)
    ready_for_development: bool
    ready_for_formal_release: bool
    blocker_codes: tuple[str, ...]


def inspect_boundary_pair_package(package: BoundaryPairPackage) -> BoundaryPairReadiness:
    """Report scientific-release blockers without opening or running a split."""

    blockers: list[str] = []
    pairs = package.pairs
    split_counts = Counter(pair.split for pair in pairs)
    context_counts = Counter(pair.decision_context_family for pair in pairs)
    judgment_counts = defaultdict(int)
    for pair in pairs:
        if not pair.public_reconstruction_allowed and package.release_tier == "formal":
            blockers.append(f"pair:{pair.pair_id}:release-rights-unresolved")
        if not pair.outcome_hidden_during_construction:
            blockers.append(f"pair:{pair.pair_id}:outcome-leakage")
        if len(pair.judgments) < 2:
            blockers.append(f"pair:{pair.pair_id}:fewer-than-two-independent-judgments")
        reviewer_ids = [judgment.reviewer_id for judgment in pair.judgments]
        if len(reviewer_ids) != len(set(reviewer_ids)):
            blockers.append(f"pair:{pair.pair_id}:duplicate-reviewer")
        if any(
            not judgment.pair_order_blinded
            or not judgment.expected_pair_labels_hidden
            or not judgment.conflict_cleared
            for judgment in pair.judgments
        ):
            blockers.append(f"pair:{pair.pair_id}:judgment-protocol-failed")
        for judgment in pair.judgments:
            judgment_counts[judgment.authority] += 1
        if package.release_tier == "formal" and pair.utility_contract is None:
            blockers.append(f"pair:{pair.pair_id}:utility-contract-missing")
        if package.release_tier == "formal":
            if len(pair.construct_audits) < 2:
                blockers.append(f"pair:{pair.pair_id}:construct-audit-incomplete")
            elif any(not audit.accepted for audit in pair.construct_audits):
                blockers.append(f"pair:{pair.pair_id}:construct-audit-failed")
            if (
                sum(
                    audit.authority is BenchmarkLabelAuthority.HUMAN_EXPERT
                    for audit in pair.construct_audits
                )
                < 2
            ):
                blockers.append(f"pair:{pair.pair_id}:expert-construct-audit-incomplete")

    formal = package.release_tier == "formal"
    if formal:
        if len(pairs) < 120:
            blockers.append("formal:fewer-than-120-independent-pairs")
        if len({pair.domain for pair in pairs}) < 3:
            blockers.append("formal:fewer-than-three-domains")
        if set(context_counts) != set(BenchmarkDecisionContextFamily):
            blockers.append("formal:incomplete-decision-context-coverage")
        if any(context_counts[family] < 20 for family in BenchmarkDecisionContextFamily):
            blockers.append("formal:fewer-than-20-pairs-per-context")
        if set(split_counts) != set(BoundaryPairSplit):
            blockers.append("formal:development-validation-test-split-incomplete")
        if split_counts[BoundaryPairSplit.HIDDEN_TEST] < 60:
            blockers.append("formal:fewer-than-60-hidden-test-pairs")
        if judgment_counts[BenchmarkLabelAuthority.HUMAN_EXPERT] < 2 * len(pairs):
            blockers.append("formal:expert-construct-validation-incomplete")
        if sum(pair.flip_kind is BoundaryFlipKind.ACTION_TO_ABSTENTION for pair in pairs) < 12:
            blockers.append("formal:fewer-than-12-abstention-boundary-pairs")

    unique_blockers = tuple(dict.fromkeys(blockers))
    development_blockers = tuple(
        code
        for code in unique_blockers
        if not code.startswith("formal:") and "expert-construct-validation" not in code
    )
    return BoundaryPairReadiness(
        package_id=package.package_id,
        package_sha256=package.sha256,
        pair_count=len(pairs),
        item_count=2 * len(pairs),
        domain_count=len({pair.domain for pair in pairs}),
        split_counts=dict(split_counts),
        context_counts=dict(context_counts),
        action_flip_count=sum(
            pair.flip_kind is BoundaryFlipKind.ACTION_TO_ACTION for pair in pairs
        ),
        abstention_flip_count=sum(
            pair.flip_kind is BoundaryFlipKind.ACTION_TO_ABSTENTION for pair in pairs
        ),
        ready_for_development=not development_blockers,
        ready_for_formal_release=formal and not unique_blockers,
        blocker_codes=unique_blockers,
    )
