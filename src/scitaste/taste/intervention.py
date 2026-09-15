"""Single-variable intervention contracts for formal Scientific Taste studies."""

from __future__ import annotations

import json
from collections.abc import Sequence
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.project.idea_revision import ProjectIdeaRevisionBinding
from scitaste.project.models import content_sha256, validate_entry_id
from scitaste.schema.actions import ResearchAction
from scitaste.schema.decisions import TasteInterventionTrace
from scitaste.state.persistence import snapshot_id
from scitaste.state.research_state import ResearchState, ResourceBudget
from scitaste.taste.deliberation import VerifiedTasteDeliberation
from scitaste.taste.episode_learning import (
    LifecycleTastePolicyModel,
    LifecycleTastePolicyUpdateMode,
)
from scitaste.taste.retriever import RetrievedTasteCase

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_CONTRACT_BYTES = 4 * 1024 * 1024


class TasteInterventionHypothesis(StrEnum):
    TASTE_SELECTION = "H2b_taste_selection"
    LIFECYCLE_CREDIT = "H3_lifecycle_credit"
    OBJECTIVE_PROGRESS = "H4_native_effect"


class TasteInterventionDimension(StrEnum):
    SELECTOR = "selector-mode"
    CREDIT_UPDATE = "credit-update"
    POLICY_WEIGHT = "policy-weight"


class TasteSelectorMode(StrEnum):
    DISABLED = "disabled"
    LEXICAL = "lexical"
    DELIBERATIVE = "deliberative"


class TasteInterventionCondition(StrEnum):
    DELIBERATIVE_SELECTION = "deliberative-taste-selection"
    LEXICAL_RETRIEVAL = "lexical-taste-retrieval"
    OUTCOME_UPDATED = "outcome-updated-policy"
    NO_UPDATE = "no-update-policy"
    SHUFFLED_CREDIT = "shuffled-credit-policy"
    SUCCESS_ONLY = "success-only-policy"
    FAILURE_ONLY = "failure-only-policy"
    LEARNED_POLICY_ON = "full-scitaste-learned-policy"
    LEARNED_POLICY_OFF = "native-base-without-learned-taste"


_H2B_CONDITIONS = {
    TasteInterventionCondition.DELIBERATIVE_SELECTION: TasteSelectorMode.DELIBERATIVE,
    TasteInterventionCondition.LEXICAL_RETRIEVAL: TasteSelectorMode.LEXICAL,
}
_H3_CONDITIONS = {
    TasteInterventionCondition.OUTCOME_UPDATED: LifecycleTastePolicyUpdateMode.OUTCOME_UPDATED,
    TasteInterventionCondition.NO_UPDATE: LifecycleTastePolicyUpdateMode.NO_UPDATE,
    TasteInterventionCondition.SHUFFLED_CREDIT: (
        LifecycleTastePolicyUpdateMode.SHUFFLED_CREDIT
    ),
    TasteInterventionCondition.SUCCESS_ONLY: LifecycleTastePolicyUpdateMode.SUCCESS_ONLY,
    TasteInterventionCondition.FAILURE_ONLY: LifecycleTastePolicyUpdateMode.FAILURE_ONLY,
}
_H4_WEIGHTS = {
    TasteInterventionCondition.LEARNED_POLICY_ON: 1.0,
    TasteInterventionCondition.LEARNED_POLICY_OFF: 0.0,
}


class TasteInterventionActionBinding(BaseModel):
    """Exact candidate identity before any condition-specific decision."""

    model_config = _CONFIG

    action_id: str = Field(min_length=1, max_length=300)
    action_type: str = Field(min_length=1, max_length=200)
    action_sha256: str = Field(pattern=_SHA256)

    @classmethod
    def from_action(cls, action: ResearchAction) -> TasteInterventionActionBinding:
        return cls(
            action_id=action.action_id,
            action_type=action.type.value,
            action_sha256=content_sha256(action),
        )


class TasteInterventionContract(BaseModel):
    """Hash-bound execution contract for the H2b, H3, and H4 causal contrasts.

    The contract carries every factor that must remain fixed across a comparison.
    Its validator closes condition semantics; :class:`TasteInterventionComparison`
    then rejects any pair that changes more than the registered dimension.
    """

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    contract_id: str
    hypothesis: TasteInterventionHypothesis
    condition: TasteInterventionCondition
    changed_dimension: TasteInterventionDimension
    benchmark_id: str
    task_id: str
    benchmark_local_state_sha256: str = Field(pattern=_SHA256)
    action_menu: tuple[TasteInterventionActionBinding, ...] = Field(
        min_length=2,
        max_length=20,
    )
    action_menu_sha256: str = Field(pattern=_SHA256)
    precedent_pool_sha256: str = Field(pattern=_SHA256)
    selector_runtime_sha256: str = Field(pattern=_SHA256)
    controller_backbone_sha256: str = Field(pattern=_SHA256)
    source_identity_registry_sha256: str = Field(pattern=_SHA256)
    canonical_source_group_ids: tuple[str, ...] = Field(min_length=1, max_length=10_000)
    policy_source_group_ids: tuple[str, ...] = Field(default=(), max_length=10_000)
    precedent_source_group_ids: tuple[str, ...] = Field(default=(), max_length=10_000)
    heldout_source_group_ids: tuple[str, ...] = Field(min_length=1, max_length=10_000)
    selector_mode: TasteSelectorMode
    lifecycle_update_mode: LifecycleTastePolicyUpdateMode | None = None
    lifecycle_policy_sha256: str | None = Field(default=None, pattern=_SHA256)
    policy_training_corpus_sha256: str | None = Field(default=None, pattern=_SHA256)
    credit_assignment_schedule_sha256: str | None = Field(default=None, pattern=_SHA256)
    lifecycle_policy_weight: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    decision_provider: str = Field(min_length=1, max_length=300)
    decision_model: str = Field(min_length=1, max_length=500)
    prompt_version: str = Field(min_length=1, max_length=300)
    seed: int = Field(ge=0)
    resource_budget_sha256: str = Field(pattern=_SHA256)
    tool_policy_sha256: str = Field(pattern=_SHA256)
    repair_policy_sha256: str = Field(pattern=_SHA256)
    executor_sha256: str = Field(pattern=_SHA256)
    task_sha256: str = Field(pattern=_SHA256)
    idea_revision_binding_sha256: str = Field(pattern=_SHA256)
    contract_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def intervention_is_closed(self) -> TasteInterventionContract:
        for value, label in (
            (self.contract_id, "contract_id"),
            (self.benchmark_id, "benchmark_id"),
            (self.task_id, "task_id"),
        ):
            validate_entry_id(value, field_name=label)
        action_ids = [item.action_id for item in self.action_menu]
        if len(action_ids) != len(set(action_ids)):
            raise ValueError("Taste intervention action identities must be unique")
        if self.action_menu_sha256 != _action_menu_sha256(self.action_menu):
            raise ValueError("Taste intervention action-menu hash differs")
        for label, groups in (
            ("canonical", self.canonical_source_group_ids),
            ("policy", self.policy_source_group_ids),
            ("precedent", self.precedent_source_group_ids),
            ("heldout", self.heldout_source_group_ids),
        ):
            if groups != tuple(sorted(set(groups))):
                raise ValueError(
                    f"Taste intervention {label} source groups must be sorted and unique"
                )
        source_partitions = (
            set(self.policy_source_group_ids),
            set(self.precedent_source_group_ids),
            set(self.heldout_source_group_ids),
        )
        if any(
            left & right
            for index, left in enumerate(source_partitions)
            for right in source_partitions[index + 1 :]
        ):
            raise ValueError("Taste intervention source-group partitions overlap")
        if set(self.canonical_source_group_ids) != (
            set().union(*source_partitions)
        ):
            raise ValueError("Taste intervention canonical source-group coverage differs")
        if (self.selector_mode is TasteSelectorMode.DISABLED) != (
            not self.precedent_source_group_ids
        ):
            raise ValueError("Taste selector mode and precedent source groups differ")
        self._validate_condition_semantics()
        expected = content_sha256(self.model_dump(mode="json", exclude={"contract_sha256"}))
        if self.contract_sha256 != expected:
            raise ValueError("Taste intervention contract hash differs")
        return self

    def _validate_condition_semantics(self) -> None:
        if self.hypothesis is TasteInterventionHypothesis.TASTE_SELECTION:
            if self.changed_dimension is not TasteInterventionDimension.SELECTOR:
                raise ValueError("H2b may change only selector mode")
            expected_selector = _H2B_CONDITIONS.get(self.condition)
            if expected_selector is None or self.selector_mode is not expected_selector:
                raise ValueError("H2b condition and selector mode differ")
            if any(
                value is not None
                for value in (
                    self.lifecycle_update_mode,
                    self.lifecycle_policy_sha256,
                    self.policy_training_corpus_sha256,
                    self.credit_assignment_schedule_sha256,
                )
            ) or self.lifecycle_policy_weight != 0:
                raise ValueError("H2b cannot carry a lifecycle policy intervention")
            if not self.precedent_source_group_ids:
                raise ValueError("H2b requires a source-identified precedent pool")
            return
        if self.hypothesis is TasteInterventionHypothesis.LIFECYCLE_CREDIT:
            if self.changed_dimension is not TasteInterventionDimension.CREDIT_UPDATE:
                raise ValueError("H3 may change only delayed-credit update mode")
            expected_update = _H3_CONDITIONS.get(self.condition)
            if expected_update is None or self.lifecycle_update_mode is not expected_update:
                raise ValueError("H3 condition and delayed-credit update mode differ")
            if (
                self.lifecycle_policy_sha256 is None
                or self.policy_training_corpus_sha256 is None
                or self.lifecycle_policy_weight != 1
                or not self.policy_source_group_ids
            ):
                raise ValueError("H3 requires one fully weighted fitted policy")
            shuffled = expected_update is LifecycleTastePolicyUpdateMode.SHUFFLED_CREDIT
            if shuffled != (self.credit_assignment_schedule_sha256 is not None):
                raise ValueError("H3 shuffled-credit schedule binding differs")
            return
        if self.changed_dimension is not TasteInterventionDimension.POLICY_WEIGHT:
            raise ValueError("H4 may change only learned-policy weight")
        expected_weight = _H4_WEIGHTS.get(self.condition)
        if expected_weight is None or self.lifecycle_policy_weight != expected_weight:
            raise ValueError("H4 condition and learned-policy weight differ")
        if (
            self.lifecycle_update_mode is not LifecycleTastePolicyUpdateMode.OUTCOME_UPDATED
            or self.lifecycle_policy_sha256 is None
            or self.policy_training_corpus_sha256 is None
            or not self.policy_source_group_ids
        ):
            raise ValueError("H4 requires the identical outcome-updated policy in both arms")
        if self.credit_assignment_schedule_sha256 is not None:
            raise ValueError("H4 cannot change a delayed-credit assignment schedule")

    @classmethod
    def create(cls, **values: object) -> TasteInterventionContract:
        payload = {"schema_version": "1.0", **values}
        payload.pop("contract_sha256", None)
        actions = tuple(payload["action_menu"])  # type: ignore[arg-type]
        payload["action_menu"] = actions
        payload["action_menu_sha256"] = _action_menu_sha256(actions)
        payload["canonical_source_group_ids"] = tuple(
            sorted(set(payload["canonical_source_group_ids"]))  # type: ignore[arg-type]
        )
        payload["policy_source_group_ids"] = tuple(
            sorted(set(payload.get("policy_source_group_ids", ())))  # type: ignore[arg-type]
        )
        payload["precedent_source_group_ids"] = tuple(
            sorted(set(payload.get("precedent_source_group_ids", ())))  # type: ignore[arg-type]
        )
        payload["heldout_source_group_ids"] = tuple(
            sorted(set(payload["heldout_source_group_ids"]))  # type: ignore[arg-type]
        )
        unsigned = cls.model_construct(contract_sha256="0" * 64, **payload)
        return cls(
            **payload,
            contract_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"contract_sha256"})
            ),
        )

    def validate_runtime(
        self,
        *,
        state: ResearchState,
        actions: tuple[ResearchAction, ...],
        budget: ResourceBudget,
        taste_deliberation: VerifiedTasteDeliberation | None,
        selector_mode: TasteSelectorMode,
        precedent_pool_sha256: str,
        precedent_source_group_ids: tuple[str, ...],
        selector_runtime_sha256: str,
        controller_backbone_sha256: str,
        lifecycle_policy: LifecycleTastePolicyModel | None,
        lifecycle_policy_weight: float,
        idea_revision: ProjectIdeaRevisionBinding | None,
        decision_provider: str,
        decision_model: str,
        prompt_version: str,
        seed: int,
    ) -> TasteInterventionTrace:
        """Validate the live controller inputs and return a durable trace."""

        observed_actions = tuple(
            TasteInterventionActionBinding.from_action(action) for action in actions
        )
        checks = {
            "benchmark-local state": self.benchmark_local_state_sha256
            == snapshot_id(state).removeprefix("state-"),
            "action menu": self.action_menu == observed_actions,
            "resource budget": self.resource_budget_sha256 == content_sha256(budget),
            "precedent pool": self.precedent_pool_sha256 == precedent_pool_sha256,
            "precedent source groups": (
                self.precedent_source_group_ids == precedent_source_group_ids
            ),
            "selector runtime": self.selector_runtime_sha256 == selector_runtime_sha256,
            "controller backbone": (
                self.controller_backbone_sha256 == controller_backbone_sha256
            ),
            "decision provider": self.decision_provider == decision_provider,
            "decision model": self.decision_model == decision_model,
            "prompt version": self.prompt_version == prompt_version,
            "seed": self.seed == seed,
            "Idea revision": idea_revision is not None
            and self.idea_revision_binding_sha256 == idea_revision.binding_sha256,
            "lifecycle policy weight": self.lifecycle_policy_weight
            == lifecycle_policy_weight,
        }
        observed_policy_sha = lifecycle_policy.policy_sha256 if lifecycle_policy else None
        observed_update = lifecycle_policy.config.update_mode if lifecycle_policy else None
        checks["lifecycle policy"] = self.lifecycle_policy_sha256 == observed_policy_sha
        checks["lifecycle update mode"] = self.lifecycle_update_mode == observed_update
        checks["lifecycle training corpus"] = self.policy_training_corpus_sha256 == (
            lifecycle_policy_training_corpus_sha256(lifecycle_policy)
            if lifecycle_policy is not None
            else None
        )
        if lifecycle_policy is not None:
            checks["policy source groups"] = (
                lifecycle_policy.schema_version == "1.4"
                and lifecycle_policy.source_group_ids == self.policy_source_group_ids
            )
            checks["credit assignment schedule"] = (
                self.credit_assignment_schedule_sha256
                == lifecycle_policy.shuffle_assignment_sha256
            )
            checks["policy Idea revision"] = (
                idea_revision is not None
                and lifecycle_policy.config.idea_revision.binding_sha256
                == idea_revision.binding_sha256
            )
            diagnostic_h3 = self.condition in {
                TasteInterventionCondition.SUCCESS_ONLY,
                TasteInterventionCondition.FAILURE_ONLY,
            }
            checks["formal policy eligibility"] = (
                lifecycle_policy.intervention_policy_artifact_eligible
                if diagnostic_h3
                else lifecycle_policy.h3_policy_artifact_eligible
            )
        checks["selector mode"] = self.selector_mode is selector_mode
        if taste_deliberation is not None:
            checks["deliberation action menu"] = tuple(
                item.action_id for item in taste_deliberation.input.current_actions
            ) == tuple(item.action_id for item in self.action_menu)
            checks["deliberation state"] = (
                taste_deliberation.input.state_snapshot_id == snapshot_id(state)
            )
        failed = tuple(label for label, passed in checks.items() if not passed)
        if failed:
            raise ValueError("Taste intervention runtime drift: " + ", ".join(failed))
        return TasteInterventionTrace.create(
            contract_sha256=self.contract_sha256,
            hypothesis=self.hypothesis.value,
            condition_id=self.condition.value,
            changed_dimension=self.changed_dimension.value,
            selector_mode=self.selector_mode.value,
            lifecycle_update_mode=(
                self.lifecycle_update_mode.value if self.lifecycle_update_mode else None
            ),
            lifecycle_policy_sha256=self.lifecycle_policy_sha256,
            policy_training_corpus_sha256=self.policy_training_corpus_sha256,
            lifecycle_policy_weight=self.lifecycle_policy_weight,
            action_menu_sha256=self.action_menu_sha256,
            precedent_pool_sha256=self.precedent_pool_sha256,
            policy_source_groups_sha256=content_sha256(
                self.policy_source_group_ids
            ),
            precedent_source_groups_sha256=content_sha256(
                self.precedent_source_group_ids
            ),
            heldout_source_groups_sha256=content_sha256(
                self.heldout_source_group_ids
            ),
            credit_assignment_schedule_sha256=(
                self.credit_assignment_schedule_sha256
            ),
            selector_runtime_sha256=self.selector_runtime_sha256,
            controller_backbone_sha256=self.controller_backbone_sha256,
            state_snapshot_id=snapshot_id(state),
            resource_budget_sha256=self.resource_budget_sha256,
            decision_provider=self.decision_provider,
            decision_model=self.decision_model,
            prompt_version=self.prompt_version,
            seed=self.seed,
            source_identity_registry_sha256=self.source_identity_registry_sha256,
            tool_policy_sha256=self.tool_policy_sha256,
            repair_policy_sha256=self.repair_policy_sha256,
            executor_sha256=self.executor_sha256,
            task_sha256=self.task_sha256,
            idea_revision_binding_sha256=self.idea_revision_binding_sha256,
        )


def lifecycle_policy_training_corpus_sha256(policy: LifecycleTastePolicyModel) -> str:
    """Identity shared by update-mode controls fitted over the same source episodes."""

    return content_sha256(
        {
            "idea_revision_binding_sha256": policy.config.idea_revision.binding_sha256,
            "source_episode_ids": policy.source_episode_ids,
            "source_episode_sha256": policy.source_episode_sha256,
            "source_group_ids": policy.source_group_ids,
            "training_partitions": tuple(item.value for item in policy.config.training_partitions),
            "eligible_outcome_families": tuple(
                item.value for item in policy.config.eligible_outcome_families
            ),
            "estimator": policy.estimator,
            "prior_alpha": policy.config.prior_alpha,
            "prior_beta": policy.config.prior_beta,
            "minimum_feature_support": policy.config.minimum_feature_support,
            "credible_z": policy.config.credible_z,
            "minimum_pairwise_probability": policy.config.minimum_pairwise_probability,
            "maximum_absolute_adjustment": policy.config.maximum_absolute_adjustment,
            "require_stage_support": policy.config.require_stage_support,
            "allow_cross_domain": policy.config.allow_cross_domain,
        }
    )


def taste_precedent_pool_sha256(cases: Sequence[RetrievedTasteCase]) -> str:
    """Hash the ordered broad pool shared by lexical and deliberative selectors."""

    return content_sha256(tuple(item.model_dump(mode="json") for item in cases))


def taste_precedent_source_group_ids(
    cases: Sequence[RetrievedTasteCase],
) -> tuple[str, ...]:
    """Extract exact canonical source groups; fail when a case lacks the binding."""

    groups: set[str] = set()
    for retrieved in cases:
        case_groups = {
            str(value)
            for provenance in retrieved.case.provenance
            for key in (
                "canonical_source_group_id",
                "source_group_id",
                "source_group",
            )
            if (value := provenance.metadata.get(key)) is not None
        }
        if len(case_groups) != 1:
            raise ValueError(
                f"Taste precedent {retrieved.case.case_id!r} lacks one canonical source group"
            )
        groups.update(case_groups)
    return tuple(sorted(groups))


def _action_menu_sha256(actions: tuple[object, ...]) -> str:
    return content_sha256(
        tuple(
            item.model_dump(mode="json") if isinstance(item, BaseModel) else item
            for item in actions
        )
    )


class TasteInterventionComparison(BaseModel):
    """A two-arm contrast that fails when any non-intervention factor drifts."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    comparison_id: str
    left: TasteInterventionContract
    right: TasteInterventionContract
    comparison_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def pair_changes_exactly_one_dimension(self) -> TasteInterventionComparison:
        validate_entry_id(self.comparison_id, field_name="comparison_id")
        if self.left.hypothesis is not self.right.hypothesis:
            raise ValueError("Taste intervention arms test different hypotheses")
        if self.left.changed_dimension is not self.right.changed_dimension:
            raise ValueError("Taste intervention arms declare different changed dimensions")
        allowed_conditions = {
            TasteInterventionHypothesis.TASTE_SELECTION: set(_H2B_CONDITIONS),
            TasteInterventionHypothesis.LIFECYCLE_CREDIT: set(_H3_CONDITIONS),
            TasteInterventionHypothesis.OBJECTIVE_PROGRESS: set(_H4_WEIGHTS),
        }[self.left.hypothesis]
        if (
            self.left.condition == self.right.condition
            or {self.left.condition, self.right.condition} - allowed_conditions
        ):
            raise ValueError("Taste intervention comparison lacks distinct legal conditions")
        left = self.left.model_dump(mode="json")
        right = self.right.model_dump(mode="json")
        ignored = {"contract_id", "condition", "contract_sha256"}
        if self.left.changed_dimension is TasteInterventionDimension.SELECTOR:
            ignored.add("selector_mode")
        elif self.left.changed_dimension is TasteInterventionDimension.CREDIT_UPDATE:
            ignored.update(
                {
                    "lifecycle_update_mode",
                    "lifecycle_policy_sha256",
                    "credit_assignment_schedule_sha256",
                }
            )
        else:
            ignored.add("lifecycle_policy_weight")
        if self.left.changed_dimension is TasteInterventionDimension.SELECTOR:
            ignored.add("selector_runtime_sha256")
        drift = tuple(key for key in sorted(left) if key not in ignored and left[key] != right[key])
        if drift:
            raise ValueError("Taste intervention changes non-target factors: " + ", ".join(drift))
        expected = content_sha256(
            self.model_dump(mode="json", exclude={"comparison_sha256"})
        )
        if self.comparison_sha256 != expected:
            raise ValueError("Taste intervention comparison hash differs")
        return self

    @classmethod
    def create(cls, **values: object) -> TasteInterventionComparison:
        payload = {"schema_version": "1.0", **values}
        payload.pop("comparison_sha256", None)
        unsigned = cls.model_construct(comparison_sha256="0" * 64, **payload)
        return cls(
            **payload,
            comparison_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"comparison_sha256"})
            ),
        )


def load_taste_intervention_contract(path: str | Path) -> TasteInterventionContract:
    return _load_bounded_model(path, TasteInterventionContract)


def load_taste_intervention_comparison(path: str | Path) -> TasteInterventionComparison:
    return _load_bounded_model(path, TasteInterventionComparison)


def save_taste_intervention_contract(
    contract: TasteInterventionContract,
    path: str | Path,
) -> Path:
    return _save_new_model(contract, path)


def save_taste_intervention_comparison(
    comparison: TasteInterventionComparison,
    path: str | Path,
) -> Path:
    return _save_new_model(comparison, path)


def _load_bounded_model(path: str | Path, model_type):
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError("Taste intervention artifact must be a regular file")
    raw = source.read_bytes()
    if not raw or len(raw) > _MAX_CONTRACT_BYTES:
        raise ValueError("Taste intervention artifact has an invalid byte size")
    return model_type.model_validate_json(raw, strict=True)


def _save_new_model(model: BaseModel, path: str | Path) -> Path:
    target = Path(path)
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(
        model.model_dump(mode="json"),
        ensure_ascii=False,
        allow_nan=False,
        indent=2,
        sort_keys=True,
    )
    target.write_text(rendered + "\n", encoding="utf-8")
    return target


__all__ = [
    "TasteInterventionActionBinding",
    "TasteInterventionComparison",
    "TasteInterventionCondition",
    "TasteInterventionContract",
    "TasteInterventionDimension",
    "TasteInterventionHypothesis",
    "TasteSelectorMode",
    "lifecycle_policy_training_corpus_sha256",
    "load_taste_intervention_comparison",
    "load_taste_intervention_contract",
    "save_taste_intervention_comparison",
    "save_taste_intervention_contract",
    "taste_precedent_pool_sha256",
    "taste_precedent_source_group_ids",
]
