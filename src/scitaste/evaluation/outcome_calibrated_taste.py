"""Outcome-calibrated Scientific Taste over grounded research situations.

The policy in this module is trained from development-only counterfactual
branches.  Each training state has a fixed pre-decision prefix and multiple
matched action continuations, so the target is observed downstream utility
rather than an imitation label.  At inference time the policy sees only the
outcome-hidden scientific situation and its exact evidence anchors.

Fitting lives in study scripts because it uses the optional ``study``
dependencies.  The serialized policy and inference path remain pure Python.
"""

from __future__ import annotations

import math
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.evaluation.scientific_situation_transfer import ScientificSituation
from scitaste.project.models import content_sha256, validate_entry_id

_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)
_SHA256 = r"^[0-9a-f]{64}$"
_AXES = (
    "hypothesis_structure",
    "evidence_relation",
    "bottleneck",
    "identifiability",
    "budget_pressure",
    "terminal_readiness",
)
_NAMED_NUMERICS = (
    "turn_count",
    "experiment_count",
    "evidence_confidence",
    "next_experiment_value",
)
_NUMBER = re.compile(r"[-+]?\d+(?:\.\d+)?(?:e[-+]?\d+)?", re.IGNORECASE)
_TOKEN = re.compile(r"[a-z][a-z-]{1,31}")
_STOPWORDS = frozenset(
    {
        "and",
        "count",
        "from",
        "into",
        "that",
        "the",
        "this",
        "turn",
        "where",
        "with",
    }
)


def grounded_situation_action_features(
    situation: ScientificSituation,
    action_id: str,
) -> dict[str, float]:
    """Build the frozen v1 feature map without consulting action outcomes."""

    if not action_id.strip():
        raise ValueError("outcome-calibrated Taste action_id cannot be empty")
    features: dict[str, float] = {"bias": 1.0, f"action={action_id}": 1.0}
    for name in _AXES:
        value = str(getattr(situation, name).value)
        features[f"state:{name}={value}"] = 1.0
        features[f"interaction:{action_id}:{name}={value}"] = 1.0

    anchor_text = ";".join(item.quote for item in situation.anchors)
    for name in _NAMED_NUMERICS:
        match = re.search(rf"{name}=({_NUMBER.pattern})", anchor_text, re.IGNORECASE)
        if match is not None:
            _add_numeric(features, action_id, name, float(match.group(1)))

    observations: list[float] = []
    for anchor in situation.anchors:
        if "observation" in anchor.field_id.casefold():
            observations.extend(float(item) for item in _NUMBER.findall(anchor.quote))
        for token in _TOKEN.findall(anchor.quote.casefold()):
            if token in _STOPWORDS:
                continue
            features[f"anchor-token:{token}"] = features.get(f"anchor-token:{token}", 0.0) + 1.0
            features[f"action-token:{action_id}:{token}"] = (
                features.get(f"action-token:{action_id}:{token}", 0.0) + 1.0
            )
    if observations:
        nonzero = [abs(item) for item in observations if item]
        log_range = 0.0 if not nonzero else math.log10(max(nonzero)) - math.log10(min(nonzero))
        _add_numeric(features, action_id, "observation_log10_range", log_range)
        _add_numeric(features, action_id, "observation_count", float(len(observations)))
        _add_numeric(
            features,
            action_id,
            "observation_sign_count",
            float(len({math.copysign(1.0, item) if item else 0.0 for item in observations})),
        )
    return features


def grounded_situation_axis_action_features(
    situation: ScientificSituation,
    action_id: str,
) -> dict[str, float]:
    """Return the task-invariant categorical subset of the v1 feature map.

    Exact anchors remain necessary evidence for validating each situation, but
    their task-specific words are deliberately excluded from this selector.
    """

    features = grounded_situation_action_features(situation, action_id)
    prefixes = ("action=", "state:", "interaction:")
    return {
        name: value
        for name, value in features.items()
        if name == "bias" or name.startswith(prefixes)
    }


def _add_numeric(
    features: dict[str, float],
    action_id: str,
    name: str,
    value: float,
) -> None:
    if not math.isfinite(value):
        raise ValueError(f"non-finite grounded numeric feature: {name}")
    features[f"numeric:{name}"] = value
    features[f"action-numeric:{action_id}:{name}"] = value


class OutcomeCalibratedTasteModel(BaseModel):
    """A sparse ridge policy fitted to matched counterfactual utility."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    model_family: Literal["grounded-sparse-ridge-v1"] = "grounded-sparse-ridge-v1"
    feature_contract: Literal["grounded-situation-action-v1"] = "grounded-situation-action-v1"
    feature_names: tuple[str, ...] = Field(min_length=1)
    coefficients: tuple[float, ...] = Field(min_length=1)
    intercept: float = Field(allow_inf_nan=False)
    ridge_alpha: float = Field(gt=0.0, allow_inf_nan=False)
    source_case_ids: tuple[str, ...] = Field(min_length=2)
    source_task_cluster_ids: tuple[str, ...] = Field(min_length=2)
    training_population_sha256: str = Field(pattern=_SHA256)
    training_target: Literal["matched-counterfactual-mean-utility"] = (
        "matched-counterfactual-mean-utility"
    )
    target_outcomes_used_for_training: Literal[True] = True
    target_outcomes_visible_at_inference: Literal[False] = False
    development_only: Literal[True] = True
    model_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def model_is_closed(self) -> OutcomeCalibratedTasteModel:
        if self.feature_names != tuple(sorted(set(self.feature_names))):
            raise ValueError("outcome-calibrated Taste features must be sorted and unique")
        if len(self.feature_names) != len(self.coefficients):
            raise ValueError("outcome-calibrated Taste coefficient population differs")
        if any(not math.isfinite(item) for item in self.coefficients):
            raise ValueError("outcome-calibrated Taste coefficients must be finite")
        if self.source_case_ids != tuple(sorted(set(self.source_case_ids))):
            raise ValueError("outcome-calibrated Taste source cases must be canonical")
        if self.source_task_cluster_ids != tuple(sorted(set(self.source_task_cluster_ids))):
            raise ValueError("outcome-calibrated Taste source clusters must be canonical")
        expected = content_sha256(self.model_dump(mode="json", exclude={"model_sha256"}))
        if self.model_sha256 != expected:
            raise ValueError("outcome-calibrated Taste model hash differs")
        return self

    @classmethod
    def create(cls, **values: object) -> OutcomeCalibratedTasteModel:
        payload = {
            "schema_version": "1.0",
            "model_family": "grounded-sparse-ridge-v1",
            "feature_contract": "grounded-situation-action-v1",
            "training_target": "matched-counterfactual-mean-utility",
            "target_outcomes_used_for_training": True,
            "target_outcomes_visible_at_inference": False,
            "development_only": True,
            **values,
        }
        payload.pop("model_sha256", None)
        unsigned = cls.model_construct(model_sha256="0" * 64, **payload)
        return cls(
            **payload,
            model_sha256=content_sha256(unsigned.model_dump(mode="json", exclude={"model_sha256"})),
        )

    def score(self, situation: ScientificSituation, action_id: str) -> float:
        observed = grounded_situation_action_features(situation, action_id)
        return self.intercept + math.fsum(
            coefficient * observed.get(name, 0.0)
            for name, coefficient in zip(
                self.feature_names,
                self.coefficients,
                strict=True,
            )
        )


class OutcomeCalibratedActionScore(BaseModel):
    model_config = _CONFIG

    action_id: str = Field(min_length=1)
    predicted_utility: float = Field(allow_inf_nan=False)


class OutcomeCalibratedTasteDecision(BaseModel):
    """One full-coverage decision made without target action outcomes."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    study_id: str
    situation_sha256: str = Field(pattern=_SHA256)
    model_sha256: str = Field(pattern=_SHA256)
    action_scores: tuple[OutcomeCalibratedActionScore, ...] = Field(min_length=2)
    selected_action_id: str = Field(min_length=1)
    tie_break: Literal["predicted-utility-then-action-id"] = "predicted-utility-then-action-id"
    target_outcomes_used_for_selection: Literal[False] = False
    decision_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def decision_is_closed(self) -> OutcomeCalibratedTasteDecision:
        validate_entry_id(self.study_id, field_name="outcome-calibrated Taste study_id")
        action_ids = tuple(item.action_id for item in self.action_scores)
        if action_ids != tuple(sorted(set(action_ids))):
            raise ValueError("outcome-calibrated Taste action scores must be canonical")
        expected_selected = max(
            self.action_scores,
            key=lambda item: (item.predicted_utility, item.action_id),
        ).action_id
        if self.selected_action_id != expected_selected:
            raise ValueError("outcome-calibrated Taste selected action differs")
        expected = content_sha256(self.model_dump(mode="json", exclude={"decision_sha256"}))
        if self.decision_sha256 != expected:
            raise ValueError("outcome-calibrated Taste decision hash differs")
        return self

    @classmethod
    def create(cls, **values: object) -> OutcomeCalibratedTasteDecision:
        payload = {
            "schema_version": "1.0",
            "tie_break": "predicted-utility-then-action-id",
            "target_outcomes_used_for_selection": False,
            **values,
        }
        payload.pop("decision_sha256", None)
        payload["action_scores"] = tuple(
            sorted(
                (
                    OutcomeCalibratedActionScore.model_validate(item)
                    for item in payload["action_scores"]  # type: ignore[union-attr]
                ),
                key=lambda item: item.action_id,
            )
        )
        unsigned = cls.model_construct(decision_sha256="0" * 64, **payload)
        return cls(
            **payload,
            decision_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"decision_sha256"})
            ),
        )


def decide_outcome_calibrated_taste(
    model: OutcomeCalibratedTasteModel,
    situation: ScientificSituation,
    action_ids: tuple[str, ...],
) -> OutcomeCalibratedTasteDecision:
    if action_ids != tuple(sorted(set(action_ids))) or len(action_ids) < 2:
        raise ValueError("outcome-calibrated Taste requires a canonical action menu")
    scores = tuple(
        OutcomeCalibratedActionScore(
            action_id=action_id,
            predicted_utility=model.score(situation, action_id),
        )
        for action_id in action_ids
    )
    selected = max(scores, key=lambda item: (item.predicted_utility, item.action_id))
    return OutcomeCalibratedTasteDecision.create(
        study_id=situation.study_id,
        situation_sha256=situation.situation_sha256,
        model_sha256=model.model_sha256,
        action_scores=scores,
        selected_action_id=selected.action_id,
    )


class ConservativeTastePolicy(BaseModel):
    """A jackknife committee that intervenes only under transferable support."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    model_family: Literal["axis-jackknife-conservative-ridge-v1"] = (
        "axis-jackknife-conservative-ridge-v1"
    )
    feature_contract: Literal["grounded-situation-axis-action-v1"] = (
        "grounded-situation-axis-action-v1"
    )
    members: tuple[OutcomeCalibratedTasteModel, ...] = Field(min_length=3)
    member_heldout_group_ids: tuple[str, ...] = Field(min_length=3)
    baseline_actions: dict[str, str]
    intervention_margin: float = Field(ge=0.0, allow_inf_nan=False)
    minimum_member_agreement: float = Field(gt=0.5, le=1.0, allow_inf_nan=False)
    source_case_ids: tuple[str, ...] = Field(min_length=3)
    source_group_ids: tuple[str, ...] = Field(min_length=3)
    training_population_sha256: str = Field(pattern=_SHA256)
    target_outcomes_used_for_training: Literal[True] = True
    target_outcomes_visible_at_inference: Literal[False] = False
    policy_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def policy_is_closed(self) -> ConservativeTastePolicy:
        if len(self.members) != len(self.member_heldout_group_ids):
            raise ValueError("conservative Taste members and held-out groups differ")
        if self.member_heldout_group_ids != tuple(sorted(set(self.member_heldout_group_ids))):
            raise ValueError("conservative Taste held-out groups must be canonical")
        if self.source_case_ids != tuple(sorted(set(self.source_case_ids))):
            raise ValueError("conservative Taste source cases must be canonical")
        if self.source_group_ids != tuple(sorted(set(self.source_group_ids))):
            raise ValueError("conservative Taste source groups must be canonical")
        if set(self.baseline_actions) != {"early", "middle", "late"}:
            raise ValueError("conservative Taste requires all three stage baselines")
        if any(
            member.feature_contract != "grounded-situation-action-v1" for member in self.members
        ):
            raise ValueError("conservative Taste member feature contract differs")
        expected = content_sha256(self.model_dump(mode="json", exclude={"policy_sha256"}))
        if self.policy_sha256 != expected:
            raise ValueError("conservative Taste policy hash differs")
        return self

    @classmethod
    def create(cls, **values: object) -> ConservativeTastePolicy:
        payload = {
            "schema_version": "1.0",
            "model_family": "axis-jackknife-conservative-ridge-v1",
            "feature_contract": "grounded-situation-axis-action-v1",
            "target_outcomes_used_for_training": True,
            "target_outcomes_visible_at_inference": False,
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


class ConservativeTasteDecision(BaseModel):
    """One outcome-hidden conservative intervention decision."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    study_id: str
    situation_sha256: str = Field(pattern=_SHA256)
    policy_sha256: str = Field(pattern=_SHA256)
    action_scores: tuple[OutcomeCalibratedActionScore, ...] = Field(min_length=2)
    member_selected_actions: tuple[str, ...] = Field(min_length=3)
    baseline_action_id: str
    candidate_action_id: str
    selected_action_id: str
    member_agreement: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    lower_predicted_advantage: float = Field(allow_inf_nan=False)
    intervention_margin: float = Field(ge=0.0, allow_inf_nan=False)
    intervened: bool
    target_outcomes_used_for_selection: Literal[False] = False
    decision_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def decision_is_closed(self) -> ConservativeTasteDecision:
        validate_entry_id(self.study_id, field_name="conservative Taste study_id")
        action_ids = tuple(item.action_id for item in self.action_scores)
        if action_ids != tuple(sorted(set(action_ids))):
            raise ValueError("conservative Taste action scores must be canonical")
        if self.baseline_action_id not in action_ids or self.candidate_action_id not in action_ids:
            raise ValueError("conservative Taste action is outside the registered menu")
        expected_selected = self.candidate_action_id if self.intervened else self.baseline_action_id
        if self.selected_action_id != expected_selected:
            raise ValueError("conservative Taste selected action differs")
        expected = content_sha256(self.model_dump(mode="json", exclude={"decision_sha256"}))
        if self.decision_sha256 != expected:
            raise ValueError("conservative Taste decision hash differs")
        return self

    @classmethod
    def create(cls, **values: object) -> ConservativeTasteDecision:
        payload = {
            "schema_version": "1.0",
            "target_outcomes_used_for_selection": False,
            **values,
        }
        payload.pop("decision_sha256", None)
        payload["action_scores"] = tuple(
            sorted(
                (
                    OutcomeCalibratedActionScore.model_validate(item)
                    for item in payload["action_scores"]  # type: ignore[union-attr]
                ),
                key=lambda item: item.action_id,
            )
        )
        unsigned = cls.model_construct(decision_sha256="0" * 64, **payload)
        return cls(
            **payload,
            decision_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"decision_sha256"})
            ),
        )


def decide_conservative_taste(
    policy: ConservativeTastePolicy,
    situation: ScientificSituation,
    action_ids: tuple[str, ...],
    *,
    stage: Literal["early", "middle", "late"],
) -> ConservativeTasteDecision:
    """Apply a frozen committee without consulting target action outcomes."""

    if action_ids != tuple(sorted(set(action_ids))) or len(action_ids) < 2:
        raise ValueError("conservative Taste requires a canonical action menu")
    baseline = policy.baseline_actions[stage]
    if baseline not in action_ids:
        raise ValueError("conservative Taste baseline is outside the registered menu")
    member_scores = [
        {action_id: member.score(situation, action_id) for action_id in action_ids}
        for member in policy.members
    ]
    member_selected = tuple(
        max(action_ids, key=lambda action_id: (scores[action_id], action_id))
        for scores in member_scores
    )
    vote_counts = {action_id: member_selected.count(action_id) for action_id in action_ids}
    candidate = max(action_ids, key=lambda action_id: (vote_counts[action_id], action_id))
    agreement = vote_counts[candidate] / len(member_selected)
    lower_advantage = min(scores[candidate] - scores[baseline] for scores in member_scores)
    intervened = (
        candidate != baseline
        and agreement >= policy.minimum_member_agreement
        and lower_advantage > policy.intervention_margin
    )
    means = tuple(
        OutcomeCalibratedActionScore(
            action_id=action_id,
            predicted_utility=math.fsum(scores[action_id] for scores in member_scores)
            / len(member_scores),
        )
        for action_id in action_ids
    )
    return ConservativeTasteDecision.create(
        study_id=situation.study_id,
        situation_sha256=situation.situation_sha256,
        policy_sha256=policy.policy_sha256,
        action_scores=means,
        member_selected_actions=member_selected,
        baseline_action_id=baseline,
        candidate_action_id=candidate,
        selected_action_id=candidate if intervened else baseline,
        member_agreement=agreement,
        lower_predicted_advantage=lower_advantage,
        intervention_margin=policy.intervention_margin,
        intervened=intervened,
    )


__all__ = [
    "ConservativeTasteDecision",
    "ConservativeTastePolicy",
    "OutcomeCalibratedActionScore",
    "OutcomeCalibratedTasteDecision",
    "OutcomeCalibratedTasteModel",
    "decide_conservative_taste",
    "decide_outcome_calibrated_taste",
    "grounded_situation_action_features",
    "grounded_situation_axis_action_features",
]
