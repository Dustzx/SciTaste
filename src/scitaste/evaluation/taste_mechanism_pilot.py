"""Prepare the natural-source, AI-only SciTasteBench Track-A pilot.

The planner is deliberately local.  It turns two already sealed AI-D inventories
into outcome-hidden decision targets and source-disjoint precedent treatments;
it never calls a model and it does not claim human or formal evidence.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.evaluation.natural_taste_review import (
    PrivacyTasteSourceReviewItem,
    ScientificTasteSourceReviewItem,
    TasteSourcePrivateMapItem,
    TasteSourceReviewCampaign,
)
from scitaste.evaluation.taste_source_segmentation import (
    TasteSourceDecisionSegment,
    load_taste_source_segmentation_sample_manifest,
)
from scitaste.evaluation.taste_source_segmentation_post_audit import (
    load_taste_source_integrity_inventory,
)
from scitaste.taste.intrinsic import TasteTask
from scitaste.taste.semantic_models import TasteAbstractionInput

_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)
_EXACT_CONFIG = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_CONTROL_BYTES = 32 * 1_048_576
_MAX_SOURCE_BYTES = 256 * 1_048_576
_DOMAINS = ("computing", "ecology", "public-health")
_SELECTION_ALGORITHM = "sha256-content-ranked-domain-balanced-v1"
_PAIRING_ALGORITHM = "sha256-family-first-source-disjoint-v1"


class PilotFileBinding(BaseModel):
    """One immutable file below the declared locator root."""

    model_config = _CONFIG

    locator: str = Field(min_length=1, max_length=2_000)
    file_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def locator_is_safe(self) -> PilotFileBinding:
        _safe_locator(self.locator)
        return self


class PilotSemanticBinding(PilotFileBinding):
    semantic_sha256: str = Field(pattern=_SHA256)


class PilotInventoryBinding(BaseModel):
    model_config = _CONFIG

    cohort_id: str = Field(pattern=_ID)
    inventory: PilotSemanticBinding
    sample_manifest: PilotSemanticBinding


class PilotCampaignBinding(BaseModel):
    model_config = _CONFIG

    cohort_id: str = Field(pattern=_ID)
    campaign_id: str = Field(pattern=_ID)
    campaign: PilotSemanticBinding
    scientific_items: PilotFileBinding
    privacy_items: PilotFileBinding
    private_item_map: PilotFileBinding


class TasteMechanismPilotConfig(BaseModel):
    """Tracked, self-hashed inputs and non-authority boundary for the pilot."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    pilot_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    pilot_kind: Literal["natural-source-track-a-ai-pilot"]
    hypotheses: tuple[Literal["H1_taste_abstraction", "H2_taste_specificity"], ...]
    selection_seed: str = Field(min_length=1, max_length=200)
    selection_algorithm: Literal["sha256-content-ranked-domain-balanced-v1"]
    pairing_algorithm: Literal["sha256-family-first-source-disjoint-v1"]
    planner_implementation: PilotFileBinding
    target_counts_by_domain: dict[str, int]
    target_count: Literal[24] = 24
    precedent_pool_count: Literal[16] = 16
    inventory_sources: tuple[PilotInventoryBinding, PilotInventoryBinding]
    campaigns: tuple[PilotCampaignBinding, ...] = Field(min_length=4, max_length=4)
    target_outcomes_hidden: Literal[True] = True
    precedent_outcomes_available_to_both_h1_arms: Literal[True] = True
    raw_and_taste_share_exact_projection_bytes: Literal[True] = True
    target_and_precedent_source_groups_disjoint: Literal[True] = True
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    human_validity_claim_allowed: Literal[False] = False
    objective_correctness_claim_allowed: Literal[False] = False
    permitted_diagnostic: Literal["observed-action-agreement-and-natural-outcome-proxy"] = (
        "observed-action-agreement-and-natural-outcome-proxy"
    )
    natural_pilot: Literal[True] = True
    formal_evidence_eligible: Literal[False] = False
    authorizes_api_calls: Literal[False] = False
    authorizes_model_calls: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False
    authorizes_experiment_execution: Literal[False] = False
    config_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def config_is_closed(self) -> TasteMechanismPilotConfig:
        if self.hypotheses != ("H1_taste_abstraction", "H2_taste_specificity"):
            raise ValueError("Track-A pilot must bind H1 and H2 exactly once")
        if self.target_counts_by_domain != {domain: 8 for domain in _DOMAINS}:
            raise ValueError("Track-A pilot target geometry must be 8/8/8")
        cohorts = tuple(item.cohort_id for item in self.inventory_sources)
        if cohorts != tuple(sorted(set(cohorts))) or len(cohorts) != 2:
            raise ValueError("Track-A pilot inventory cohorts must be sorted and unique")
        campaign_keys = tuple((item.cohort_id, item.campaign_id) for item in self.campaigns)
        if campaign_keys != tuple(sorted(set(campaign_keys))):
            raise ValueError("Track-A pilot campaigns must be sorted and unique")
        if {item.cohort_id for item in self.campaigns} != set(cohorts):
            raise ValueError("Track-A pilot campaign cohorts differ from inventories")
        expected = _canonical_sha256(self.model_dump(mode="json", exclude={"config_sha256"}))
        if self.config_sha256 != expected:
            raise ValueError("Track-A pilot config hash mismatch")
        return self


class PilotSourceItem(BaseModel):
    """Owner-side provenance for one inventoried item, without its outcome."""

    model_config = _CONFIG

    cohort_id: str = Field(pattern=_ID)
    campaign_id: str = Field(pattern=_ID)
    review_item_id: str = Field(pattern=_ID)
    source_group_id: str = Field(pattern=_ID)
    domain: Literal["computing", "ecology", "public-health"]
    source_comment_sha256: str = Field(pattern=_SHA256)
    inventory_item_sha256: str = Field(pattern=_SHA256)
    scientific_item_sha256: str = Field(pattern=_SHA256)
    privacy_item_sha256: str = Field(pattern=_SHA256)
    private_map_item_sha256: str = Field(pattern=_SHA256)
    content_rank_sha256: str = Field(pattern=_SHA256)
    decision_count: int = Field(gt=0, le=128)
    role: Literal["target", "precedent-only"]
    target_outcome_included: Literal[False] = False


class PilotDecisionContext(BaseModel):
    """Only outcome-hidden target facts; action text lives outside this object."""

    model_config = _EXACT_CONFIG

    reviewed_abstract: str = Field(min_length=1, max_length=8_000)
    predecision_review_context: str | None = Field(default=None, max_length=8_000)
    context_sha256: str = Field(pattern=_SHA256)
    verbatim_trigger_included: Literal[False] = False
    atomic_decision_statement_included: Literal[False] = False
    author_response_included: Literal[False] = False
    revision_included: Literal[False] = False
    recommendation_included: Literal[False] = False

    @model_validator(mode="after")
    def context_hash_is_exact(self) -> PilotDecisionContext:
        expected = _canonical_sha256(
            {
                "reviewed_abstract": self.reviewed_abstract,
                "predecision_review_context": self.predecision_review_context,
            }
        )
        if self.context_sha256 != expected:
            raise ValueError("Track-A target context hash mismatch")
        return self


class PilotAction(BaseModel):
    model_config = _EXACT_CONFIG

    source_target_id: str = Field(pattern=_ID)
    source_segment_id: str = Field(pattern=_ID)
    decision_family: TasteTask
    action_text: str = Field(min_length=1, max_length=2_000)
    action_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def action_hash_is_exact(self) -> PilotAction:
        if self.action_sha256 != hashlib.sha256(self.action_text.encode()).hexdigest():
            raise ValueError("Track-A action hash mismatch")
        return self


class PilotAbstractionReference(BaseModel):
    model_config = _CONFIG

    relation: Literal["matched", "mismatched"]
    source_review_item_id: str = Field(pattern=_ID)
    source_group_id: str = Field(pattern=_ID)
    source_domain: Literal["computing", "ecology", "public-health"]
    source_segment_id: str = Field(pattern=_ID)
    source_decision_family: TasteTask
    abstraction_input: PilotFileBinding
    source_projection_sha256: str = Field(pattern=_SHA256)
    source_projection_bytes: int = Field(gt=0, le=800_000)
    precedent_outcome_included: Literal[True] = True
    target_outcome_included: Literal[False] = False


class PilotArmBinding(BaseModel):
    model_config = _CONFIG

    condition: Literal["raw-source-rag", "abstracted-matched-taste", "abstracted-mismatched-taste"]
    reference: PilotAbstractionReference


class TasteMechanismPilotTarget(BaseModel):
    """One target and its exact H1/H2 treatment sources, before generation."""

    model_config = _EXACT_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    target_id: str = Field(pattern=_ID)
    source_review_item_id: str = Field(pattern=_ID)
    source_group_id: str = Field(pattern=_ID)
    domain: Literal["computing", "ecology", "public-health"]
    decision_family: TasteTask
    decision_context: PilotDecisionContext
    source_observed_action: PilotAction
    distractor_action: PilotAction
    raw_source_rag: PilotArmBinding
    abstracted_matched_taste: PilotArmBinding
    abstracted_mismatched_taste: PilotArmBinding
    action_order_not_assigned: Literal[True] = True
    natural_pilot: Literal[True] = True
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    human_validity_claim_allowed: Literal[False] = False
    objective_correctness_claim_allowed: Literal[False] = False
    formal_evidence_eligible: Literal[False] = False
    model_output_not_generated: Literal[True] = True
    api_calls_performed: Literal[False] = False
    target_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def target_is_leakage_safe_and_paired(self) -> TasteMechanismPilotTarget:
        if self.source_observed_action.source_target_id != self.target_id:
            raise ValueError("Track-A observed source action comes from another target")
        if self.distractor_action.source_target_id == self.target_id:
            raise ValueError("Track-A distractor must come from another target")
        if self.source_observed_action.action_sha256 == self.distractor_action.action_sha256:
            raise ValueError("Track-A action options are not unique")
        if self.source_observed_action.decision_family != self.decision_family:
            raise ValueError("Track-A observed source action family differs from target")
        if self.distractor_action.decision_family != self.decision_family:
            raise ValueError("Track-A distractor failed same-family matching")
        raw = self.raw_source_rag
        matched = self.abstracted_matched_taste
        mismatched = self.abstracted_mismatched_taste
        if (
            raw.condition != "raw-source-rag"
            or matched.condition != "abstracted-matched-taste"
            or mismatched.condition != "abstracted-mismatched-taste"
        ):
            raise ValueError("Track-A treatment labels drifted")
        if raw.reference != matched.reference.model_copy(update={"relation": "matched"}):
            raise ValueError("H1 raw and Taste arms do not bind the same projection bytes")
        if raw.reference.relation != "matched" or matched.reference.relation != "matched":
            raise ValueError("H1 arms must use the matched precedent")
        if matched.reference.source_domain != self.domain:
            raise ValueError("Track-A matched precedent comes from another domain")
        if mismatched.reference.source_domain == self.domain:
            raise ValueError("Track-A mismatched precedent comes from the target domain")
        if (
            len(
                {
                    self.source_group_id,
                    matched.reference.source_group_id,
                    mismatched.reference.source_group_id,
                }
            )
            != 3
        ):
            raise ValueError("Track-A target and precedents must be source-group disjoint")
        context_text = "\n".join(
            item
            for item in (
                self.decision_context.reviewed_abstract,
                self.decision_context.predecision_review_context,
            )
            if item
        ).casefold()
        if self.source_observed_action.action_text.casefold() in context_text:
            raise ValueError("Track-A target context leaks the observed source action")
        expected = _canonical_sha256(self.model_dump(mode="json", exclude={"target_sha256"}))
        if self.target_sha256 != expected:
            raise ValueError("Track-A target hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> TasteMechanismPilotTarget:
        payload = {"schema_version": "1.0", **values}
        payload.pop("target_sha256", None)
        unsigned = cls.model_construct(target_sha256="0" * 64, **payload)
        return cls(
            **payload,
            target_sha256=_canonical_sha256(
                unsigned.model_dump(mode="json", exclude={"target_sha256"})
            ),
        )


class PilotTargetRecord(BaseModel):
    model_config = _CONFIG

    target_id: str = Field(pattern=_ID)
    source_review_item_id: str = Field(pattern=_ID)
    source_group_id: str = Field(pattern=_ID)
    domain: Literal["computing", "ecology", "public-health"]
    decision_family: TasteTask
    target_file: PilotSemanticBinding


class PilotAbstractionInputRecord(BaseModel):
    """One canonical precedent episode, reusable across held-out targets."""

    model_config = _CONFIG

    input_id: str = Field(pattern=_ID)
    source_review_item_id: str = Field(pattern=_ID)
    source_group_id: str = Field(pattern=_ID)
    source_domain: Literal["computing", "ecology", "public-health"]
    source_segment_id: str = Field(pattern=_ID)
    decision_family: TasteTask
    input_file: PilotFileBinding
    source_projection_sha256: str = Field(pattern=_SHA256)
    source_projection_bytes: int = Field(gt=0, le=800_000)
    target_reference_count: int = Field(ge=0, le=48)
    target_specific_content_included: Literal[False] = False
    relation_label_included: Literal[False] = False


class TasteMechanismPilotPlan(BaseModel):
    """Self-hashed no-call materialization plan for 24 natural decisions."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    plan_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    pilot_kind: Literal["natural-source-track-a-ai-pilot"]
    config: PilotSemanticBinding
    prepared_at: datetime
    selection_algorithm: Literal["sha256-content-ranked-domain-balanced-v1"]
    pairing_algorithm: Literal["sha256-family-first-source-disjoint-v1"]
    source_items: tuple[PilotSourceItem, ...] = Field(min_length=40, max_length=40)
    targets: tuple[PilotTargetRecord, ...] = Field(min_length=24, max_length=24)
    abstraction_inputs: tuple[PilotAbstractionInputRecord, ...] = Field(
        min_length=16, max_length=16
    )
    source_item_count: Literal[40] = 40
    target_counts_by_domain: dict[str, int]
    precedent_pool_counts_by_domain: dict[str, int]
    target_count: Literal[24] = 24
    precedent_pool_count: Literal[16] = 16
    unique_abstraction_invocation_count: Literal[16] = 16
    unique_abstraction_invocation_ceiling: Literal[16] = 16
    target_precedent_reference_count: Literal[48] = 48
    raw_and_matched_projection_parity_count: Literal[24] = 24
    target_outcomes_hidden: Literal[True] = True
    precedent_outcomes_available_to_raw_and_taste: Literal[True] = True
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    human_validity_claim_allowed: Literal[False] = False
    objective_correctness_claim_allowed: Literal[False] = False
    permitted_diagnostic: Literal["observed-action-agreement-and-natural-outcome-proxy"] = (
        "observed-action-agreement-and-natural-outcome-proxy"
    )
    natural_pilot: Literal[True] = True
    formal_evidence_eligible: Literal[False] = False
    final_suite_generated: Literal[False] = False
    model_calls_performed: Literal[False] = False
    api_calls_performed: Literal[False] = False
    gpu_work_performed: Literal[False] = False
    experiment_performed: Literal[False] = False
    plan_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def plan_is_closed(self) -> TasteMechanismPilotPlan:
        if self.prepared_at.utcoffset() is None:
            raise ValueError("Track-A pilot plan timestamp must include a timezone")
        if tuple(item.target_id for item in self.targets) != tuple(
            sorted({item.target_id for item in self.targets})
        ):
            raise ValueError("Track-A targets must be sorted and unique")
        if tuple(item.input_id for item in self.abstraction_inputs) != tuple(
            sorted({item.input_id for item in self.abstraction_inputs})
        ):
            raise ValueError("Track-A abstraction inputs must be sorted and unique")
        if sum(item.target_reference_count for item in self.abstraction_inputs) != 48:
            raise ValueError("Track-A abstraction-input reuse counts do not sum to 48")
        if len({item.source_group_id for item in self.source_items}) != 40:
            raise ValueError("Track-A inventoried items are not source-group disjoint")
        role_counts = Counter(item.role for item in self.source_items)
        if role_counts != {"target": 24, "precedent-only": 16}:
            raise ValueError("Track-A target/precedent roles differ from 24/16")
        target_counts = Counter(item.domain for item in self.source_items if item.role == "target")
        pool_counts = Counter(
            item.domain for item in self.source_items if item.role == "precedent-only"
        )
        if dict(target_counts) != self.target_counts_by_domain:
            raise ValueError("Track-A target domain counts drifted")
        if dict(pool_counts) != self.precedent_pool_counts_by_domain:
            raise ValueError("Track-A precedent-pool domain counts drifted")
        if self.target_counts_by_domain != {domain: 8 for domain in _DOMAINS}:
            raise ValueError("Track-A target domain geometry must remain 8/8/8")
        target_ids = {item.review_item_id for item in self.source_items if item.role == "target"}
        pool_ids = {
            item.review_item_id for item in self.source_items if item.role == "precedent-only"
        }
        if (
            target_ids & pool_ids
            or {item.source_review_item_id for item in self.targets} != target_ids
        ):
            raise ValueError("Track-A target and precedent pool are not disjoint")
        expected = _canonical_sha256(self.model_dump(mode="json", exclude={"plan_sha256"}))
        if self.plan_sha256 != expected:
            raise ValueError("Track-A pilot plan hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> TasteMechanismPilotPlan:
        payload = {"schema_version": "1.0", **values}
        payload.pop("plan_sha256", None)
        unsigned = cls.model_construct(plan_sha256="0" * 64, **payload)
        return cls(
            **payload,
            plan_sha256=_canonical_sha256(
                unsigned.model_dump(mode="json", exclude={"plan_sha256"})
            ),
        )


class TasteMechanismPilotPlanInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    plan: TasteMechanismPilotPlan
    target_files_verified: Literal[True] = True
    abstraction_inputs_verified: Literal[True] = True
    deterministic_selection_verified: Literal[True] = True
    leakage_boundary_verified: Literal[True] = True


class _LoadedSource:
    def __init__(
        self,
        *,
        receipt: PilotSourceItem,
        scientific: ScientificTasteSourceReviewItem,
        privacy: PrivacyTasteSourceReviewItem,
        private: TasteSourcePrivateMapItem,
        decisions: tuple[TasteSourceDecisionSegment, ...],
    ) -> None:
        self.receipt = receipt
        self.scientific = scientific
        self.privacy = privacy
        self.private = private
        self.decisions = decisions


def prepare_taste_mechanism_pilot(
    *,
    config_path: str | Path,
    locator_root: str | Path,
    output_dir: str | Path,
    prepared_at: datetime | None = None,
) -> TasteMechanismPilotPlan:
    """Atomically materialize PLAN, 24 targets, and 16 reusable abstraction inputs."""

    root = Path(locator_root).resolve(strict=True)
    config_file, config = _load_config(Path(config_path), root=root)
    sources, targets, abstraction_inputs = _compile(config, root=root)
    target = Path(output_dir)
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{target.name}.", suffix=".staging", dir=target.parent)
    )
    try:
        input_bindings: dict[str, PilotFileBinding] = {}
        input_records: list[PilotAbstractionInputRecord] = []
        reuse_counts = Counter(
            input_id
            for compiled in targets
            for input_id in (compiled["matched_input_id"], compiled["mismatched_input_id"])
        )
        for input_id, compiled_input in sorted(abstraction_inputs.items()):
            input_data = compiled_input["input"]
            precedent = compiled_input["source"]
            decision = compiled_input["decision"]
            assert isinstance(input_data, TasteAbstractionInput)
            assert isinstance(precedent, _LoadedSource)
            assert isinstance(decision, TasteSourceDecisionSegment)
            relative = PurePosixPath("abstraction-inputs") / f"{input_id}.json"
            payload = _canonical_json(input_data.model_dump(mode="json")) + b"\n"
            _write_new(staging.joinpath(*relative.parts), payload)
            binding = PilotFileBinding(
                locator=relative.as_posix(),
                file_sha256=hashlib.sha256(payload).hexdigest(),
            )
            input_bindings[input_id] = binding
            family = decision.primary_decision_family
            assert isinstance(family, TasteTask)
            input_records.append(
                PilotAbstractionInputRecord(
                    input_id=input_id,
                    source_review_item_id=precedent.receipt.review_item_id,
                    source_group_id=precedent.receipt.source_group_id,
                    source_domain=precedent.receipt.domain,
                    source_segment_id=decision.segment_id,
                    decision_family=family,
                    input_file=binding,
                    source_projection_sha256=input_data.source_projection_sha256,
                    source_projection_bytes=len(input_data.source_projection.encode()),
                    target_reference_count=reuse_counts[input_id],
                )
            )
        records: list[PilotTargetRecord] = []
        for compiled in targets:
            target_model = _build_target(compiled, input_bindings)
            target_relative = PurePosixPath("targets") / f"{target_model.target_id}.json"
            target_payload = _canonical_json(target_model.model_dump(mode="json")) + b"\n"
            _write_new(staging.joinpath(*target_relative.parts), target_payload)
            records.append(
                PilotTargetRecord(
                    target_id=target_model.target_id,
                    source_review_item_id=target_model.source_review_item_id,
                    source_group_id=target_model.source_group_id,
                    domain=target_model.domain,
                    decision_family=target_model.decision_family,
                    target_file=PilotSemanticBinding(
                        locator=target_relative.as_posix(),
                        file_sha256=hashlib.sha256(target_payload).hexdigest(),
                        semantic_sha256=target_model.target_sha256,
                    ),
                )
            )
        config_raw = config_file.read_bytes()
        plan = TasteMechanismPilotPlan.create(
            plan_id=f"{config.pilot_id}-plan",
            project_id=config.project_id,
            pilot_kind=config.pilot_kind,
            config=PilotSemanticBinding(
                locator=_relative(config_file, root),
                file_sha256=hashlib.sha256(config_raw).hexdigest(),
                semantic_sha256=config.config_sha256,
            ),
            prepared_at=prepared_at or datetime.now(UTC),
            selection_algorithm=config.selection_algorithm,
            pairing_algorithm=config.pairing_algorithm,
            source_items=tuple(source.receipt for source in sources),
            targets=tuple(sorted(records, key=lambda item: item.target_id)),
            abstraction_inputs=tuple(input_records),
            target_counts_by_domain={domain: 8 for domain in _DOMAINS},
            precedent_pool_counts_by_domain=dict(
                sorted(
                    Counter(
                        source.receipt.domain
                        for source in sources
                        if source.receipt.role == "precedent-only"
                    ).items()
                )
            ),
        )
        _write_new(staging / "PLAN.json", _canonical_json(plan.model_dump(mode="json")) + b"\n")
        os.rename(staging, target)
        return plan
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def load_taste_mechanism_pilot_plan(
    path: str | Path,
    *,
    locator_root: str | Path,
) -> TasteMechanismPilotPlanInspection:
    """Replay every upstream hash, selection, target, and projection invariant."""

    source = _bounded_file(Path(path), maximum_bytes=_MAX_CONTROL_BYTES)
    plan = TasteMechanismPilotPlan.model_validate_json(source.read_bytes())
    root = Path(locator_root).resolve(strict=True)
    config_file = _bound_file(root, plan.config, maximum_bytes=_MAX_CONTROL_BYTES)
    if _relative(config_file, root) != plan.config.locator:
        raise ValueError("Track-A plan config locator drifted")
    _, config = _load_config(config_file, root=root)
    if config.config_sha256 != plan.config.semantic_sha256:
        raise ValueError("Track-A plan config semantic hash drifted")
    sources, compiled_targets, compiled_inputs = _compile(config, root=root)
    if tuple(item.receipt for item in sources) != plan.source_items:
        raise ValueError("Track-A plan source receipts differ from deterministic replay")
    if len(compiled_targets) != len(plan.targets):
        raise ValueError("Track-A plan target count differs from deterministic replay")
    output_root = source.parent.resolve(strict=True)
    records_by_id = {item.target_id: item for item in plan.targets}
    compiled_by_id = {item["target_id"]: item for item in compiled_targets}
    if set(records_by_id) != set(compiled_by_id):
        raise ValueError("Track-A plan target identities differ from deterministic replay")
    input_records = {item.input_id: item for item in plan.abstraction_inputs}
    if set(input_records) != set(compiled_inputs):
        raise ValueError("Track-A abstraction-input identities differ from replay")
    input_bindings: dict[str, PilotFileBinding] = {}
    for input_id, record in input_records.items():
        input_path = _bound_file(output_root, record.input_file, maximum_bytes=_MAX_SOURCE_BYTES)
        observed = TasteAbstractionInput.model_validate_json(input_path.read_bytes())
        expected = compiled_inputs[input_id]["input"]
        if observed != expected or observed.source_projection_sha256 != (
            record.source_projection_sha256
        ):
            raise ValueError("Track-A abstraction input differs from deterministic replay")
        input_bindings[input_id] = record.input_file
    expected_reuse = Counter(
        input_id
        for compiled in compiled_targets
        for input_id in (compiled["matched_input_id"], compiled["mismatched_input_id"])
    )
    if any(
        record.target_reference_count != expected_reuse[input_id]
        for input_id, record in input_records.items()
    ):
        raise ValueError("Track-A abstraction-input reuse count differs from replay")
    for target_id, record in records_by_id.items():
        compiled = compiled_by_id[target_id]
        expected_target = _build_target(compiled, input_bindings)
        target_path = _bound_file(output_root, record.target_file, maximum_bytes=_MAX_SOURCE_BYTES)
        observed_target = TasteMechanismPilotTarget.model_validate_json(target_path.read_bytes())
        if observed_target != expected_target or observed_target.target_sha256 != (
            record.target_file.semantic_sha256
        ):
            raise ValueError("Track-A target differs from deterministic replay")
    return TasteMechanismPilotPlanInspection(
        path=source,
        file_sha256=_sha256_file(source),
        plan=plan,
    )


def _load_config(path: Path, *, root: Path) -> tuple[Path, TasteMechanismPilotConfig]:
    source = _bounded_file(path, maximum_bytes=_MAX_CONTROL_BYTES)
    _relative(source, root)
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Track-A pilot config must contain a mapping")
    config = TasteMechanismPilotConfig.model_validate(payload)
    _bound_file(root, config.planner_implementation, maximum_bytes=_MAX_CONTROL_BYTES)
    return source, config


def _compile(
    config: TasteMechanismPilotConfig, *, root: Path
) -> tuple[
    tuple[_LoadedSource, ...],
    tuple[dict[str, object], ...],
    dict[str, dict[str, object]],
]:
    campaign_configs = {(item.cohort_id, item.campaign_id): item for item in config.campaigns}
    loaded: list[_LoadedSource] = []
    observed_ids: set[str] = set()
    for inventory_binding in config.inventory_sources:
        inventory_path = _bound_file(
            root, inventory_binding.inventory, maximum_bytes=_MAX_SOURCE_BYTES
        )
        inventory = load_taste_source_integrity_inventory(inventory_path)
        if inventory.inventory_sha256 != inventory_binding.inventory.semantic_sha256:
            raise ValueError("Track-A inventory semantic hash drifted")
        sample_path = _bound_file(
            root, inventory_binding.sample_manifest, maximum_bytes=_MAX_CONTROL_BYTES
        )
        sample_inspection = load_taste_source_segmentation_sample_manifest(sample_path)
        if sample_inspection.sample.sample_sha256 != (
            inventory_binding.sample_manifest.semantic_sha256
        ):
            raise ValueError("Track-A sample semantic hash drifted")
        sample = sample_inspection.sample
        if (
            sample.project_id != config.project_id
            or inventory.project_id != config.project_id
            or sample.item_count != inventory.item_count
        ):
            raise ValueError("Track-A sample and AI-D inventory counts differ")
        campaign_by_item = {item.review_item_id: item.campaign_id for item in sample.items}
        if set(campaign_by_item) != {item.review_item_id for item in inventory.items}:
            raise ValueError("Track-A sample and AI-D inventory items differ")
        loaded_campaigns: dict[
            str,
            tuple[
                PilotCampaignBinding,
                TasteSourceReviewCampaign,
                dict[str, ScientificTasteSourceReviewItem],
                dict[str, PrivacyTasteSourceReviewItem],
                dict[str, TasteSourcePrivateMapItem],
            ],
        ] = {}
        for campaign_id in sorted(set(campaign_by_item.values())):
            binding = campaign_configs[(inventory_binding.cohort_id, campaign_id)]
            if (
                (sample.source_campaign_locators or {}).get(campaign_id) != binding.campaign.locator
                or (sample.source_campaign_file_sha256s or {}).get(campaign_id)
                != binding.campaign.file_sha256
                or (sample.source_campaign_sha256s or {}).get(campaign_id)
                != binding.campaign.semantic_sha256
                or (sample.source_scientific_items_sha256s or {}).get(campaign_id)
                != binding.scientific_items.file_sha256
                or (sample.source_private_map_file_sha256s or {}).get(campaign_id)
                != binding.private_item_map.file_sha256
            ):
                raise ValueError("Track-A campaign binding differs from the sample manifest")
            campaign_path = _bound_file(root, binding.campaign, maximum_bytes=_MAX_CONTROL_BYTES)
            campaign = TasteSourceReviewCampaign.model_validate_json(campaign_path.read_bytes())
            if campaign.campaign_id != campaign_id or campaign.campaign_sha256 != (
                binding.campaign.semantic_sha256
            ):
                raise ValueError("Track-A campaign identity drifted")
            campaign_root = campaign_path.parent.resolve(strict=True)
            for declared, actual in (
                (binding.scientific_items, campaign.scientific_items),
                (binding.privacy_items, campaign.privacy_items),
                (binding.private_item_map, campaign.private_item_map),
            ):
                if (
                    declared.locator
                    != _relative(campaign_root.joinpath(*PurePosixPath(actual.locator).parts), root)
                    or declared.file_sha256 != actual.sha256
                ):
                    raise ValueError("Track-A campaign child binding drifted")
            scientific = _load_jsonl(
                _bound_file(root, binding.scientific_items, maximum_bytes=_MAX_SOURCE_BYTES),
                ScientificTasteSourceReviewItem,
            )
            privacy = _load_jsonl(
                _bound_file(root, binding.privacy_items, maximum_bytes=_MAX_SOURCE_BYTES),
                PrivacyTasteSourceReviewItem,
            )
            private = _load_private_map(
                _bound_file(root, binding.private_item_map, maximum_bytes=_MAX_SOURCE_BYTES)
            )
            loaded_campaigns[campaign_id] = (
                binding,
                campaign,
                {item.review_item_id: item for item in scientific},
                {item.review_item_id: item for item in privacy},
                {item.review_item_id: item for item in private},
            )
        for inventory_item in inventory.items:
            item_id = inventory_item.review_item_id
            if item_id in observed_ids:
                raise ValueError("Track-A review item is repeated across inventories")
            observed_ids.add(item_id)
            campaign_id = campaign_by_item[item_id]
            _, _, scientific_by_id, privacy_by_id, private_by_id = loaded_campaigns[campaign_id]
            scientific = scientific_by_id[item_id]
            privacy = privacy_by_id[item_id]
            private = private_by_id[item_id]
            if (
                scientific.reviewed_abstract != privacy.reviewed_abstract
                or scientific.review_comment != privacy.review_comment
                or hashlib.sha256(scientific.review_comment.encode()).hexdigest()
                != inventory_item.source_comment_sha256
            ):
                raise ValueError("Track-A inventoried text differs from campaign projection")
            if private.publisher_subject not in _DOMAINS:
                raise ValueError("Track-A item has an unsupported domain")
            if not inventory_item.decisions or any(
                item.primary_decision_family == "cannot-assess" for item in inventory_item.decisions
            ):
                raise ValueError("Track-A item lacks an actionable AI-D decision")
            content_rank = _selection_rank(
                config.selection_seed,
                private.publisher_subject,
                inventory_item.source_comment_sha256,
            )
            receipt = PilotSourceItem(
                cohort_id=inventory_binding.cohort_id,
                campaign_id=campaign_id,
                review_item_id=item_id,
                source_group_id=private.source_group_id,
                domain=private.publisher_subject,
                source_comment_sha256=inventory_item.source_comment_sha256,
                inventory_item_sha256=_canonical_sha256(inventory_item.model_dump(mode="json")),
                scientific_item_sha256=_canonical_sha256(scientific.model_dump(mode="json")),
                privacy_item_sha256=_canonical_sha256(privacy.model_dump(mode="json")),
                private_map_item_sha256=_canonical_sha256(private.model_dump(mode="json")),
                content_rank_sha256=content_rank,
                decision_count=len(inventory_item.decisions),
                role="precedent-only",
            )
            loaded.append(
                _LoadedSource(
                    receipt=receipt,
                    scientific=scientific,
                    privacy=privacy,
                    private=private,
                    decisions=inventory_item.decisions,
                )
            )
    if len(loaded) != 40 or len({item.receipt.source_group_id for item in loaded}) != 40:
        raise ValueError("Track-A pilot requires 40 source-group-disjoint inventoried items")
    targets: list[_LoadedSource] = []
    for domain in _DOMAINS:
        candidates = sorted(
            (item for item in loaded if item.receipt.domain == domain),
            key=lambda item: (
                item.receipt.content_rank_sha256,
                item.receipt.review_item_id,
            ),
        )
        if len(candidates) < config.target_counts_by_domain[domain]:
            raise ValueError("Track-A pilot lacks its domain target quota")
        targets.extend(candidates[: config.target_counts_by_domain[domain]])
    target_ids = {item.receipt.review_item_id for item in targets}
    reclassified = []
    for source in loaded:
        role = "target" if source.receipt.review_item_id in target_ids else "precedent-only"
        source.receipt = source.receipt.model_copy(update={"role": role})
        reclassified.append(source)
    sources = tuple(sorted(reclassified, key=lambda item: item.receipt.review_item_id))
    targets = sorted(
        (item for item in sources if item.receipt.role == "target"),
        key=lambda item: item.receipt.review_item_id,
    )
    pool = tuple(item for item in sources if item.receipt.role == "precedent-only")
    pool_decisions = {
        item.receipt.review_item_id: _select_canonical_precedent_decision(config, item)
        for item in pool
    }
    abstraction_inputs: dict[str, dict[str, object]] = {}
    input_id_by_item: dict[str, str] = {}
    for precedent in pool:
        decision = pool_decisions[precedent.receipt.review_item_id]
        input_id = f"pilot-input-{precedent.receipt.source_comment_sha256[:20]}"
        input_id_by_item[precedent.receipt.review_item_id] = input_id
        abstraction_inputs[input_id] = {
            "source": precedent,
            "decision": decision,
            "input": _abstraction_input(
                input_id=input_id,
                source=precedent,
                decision=decision,
            ),
        }
    selected_decisions = {
        item.receipt.review_item_id: _select_target_decision(config, item) for item in targets
    }
    target_id_by_item = {
        item.receipt.review_item_id: f"track-a-target-{item.receipt.source_comment_sha256[:20]}"
        for item in targets
    }
    distractors = _assign_distractors(targets, selected_decisions, target_id_by_item)
    compiled: list[dict[str, object]] = []
    usage: Counter[str] = Counter()
    for source in sorted(targets, key=lambda item: target_id_by_item[item.receipt.review_item_id]):
        decision = selected_decisions[source.receipt.review_item_id]
        target_id = target_id_by_item[source.receipt.review_item_id]
        matched = _select_precedent(
            config,
            source,
            decision,
            pool,
            pool_decisions,
            relation="matched",
            usage=usage,
        )
        usage[matched.receipt.review_item_id] += 1
        mismatched = _select_precedent(
            config,
            source,
            decision,
            pool,
            pool_decisions,
            relation="mismatched",
            usage=usage,
        )
        usage[mismatched.receipt.review_item_id] += 1
        matched_decision = pool_decisions[matched.receipt.review_item_id]
        mismatched_decision = pool_decisions[mismatched.receipt.review_item_id]
        context = _target_context(source, decision)
        matched_input_id = input_id_by_item[matched.receipt.review_item_id]
        mismatched_input_id = input_id_by_item[mismatched.receipt.review_item_id]
        compiled.append(
            {
                "target_id": target_id,
                "source": source,
                "decision": decision,
                "context": context,
                "distractor": distractors[source.receipt.review_item_id],
                "matched": (matched, matched_decision),
                "mismatched": (mismatched, mismatched_decision),
                "matched_input_id": matched_input_id,
                "mismatched_input_id": mismatched_input_id,
                "inputs": {
                    "matched": abstraction_inputs[matched_input_id]["input"],
                    "mismatched": abstraction_inputs[mismatched_input_id]["input"],
                },
            }
        )
    return sources, tuple(compiled), abstraction_inputs


def _build_target(
    compiled: dict[str, object], input_bindings: dict[str, PilotFileBinding]
) -> TasteMechanismPilotTarget:
    source = compiled["source"]
    decision = compiled["decision"]
    distractor_source, distractor_decision, distractor_target_id = compiled["distractor"]
    matched, matched_decision = compiled["matched"]
    mismatched, mismatched_decision = compiled["mismatched"]
    inputs = compiled["inputs"]
    assert isinstance(source, _LoadedSource)
    assert isinstance(decision, TasteSourceDecisionSegment)
    assert isinstance(distractor_source, _LoadedSource)
    assert isinstance(distractor_decision, TasteSourceDecisionSegment)
    assert isinstance(distractor_target_id, str)
    assert isinstance(matched, _LoadedSource)
    assert isinstance(matched_decision, TasteSourceDecisionSegment)
    assert isinstance(mismatched, _LoadedSource)
    assert isinstance(mismatched_decision, TasteSourceDecisionSegment)
    matched_input = inputs["matched"]
    mismatched_input = inputs["mismatched"]
    assert isinstance(matched_input, TasteAbstractionInput)
    assert isinstance(mismatched_input, TasteAbstractionInput)
    matched_input_id = compiled["matched_input_id"]
    mismatched_input_id = compiled["mismatched_input_id"]
    assert isinstance(matched_input_id, str)
    assert isinstance(mismatched_input_id, str)
    matched_reference = _reference(
        "matched", matched, matched_decision, matched_input, input_bindings[matched_input_id]
    )
    mismatched_reference = _reference(
        "mismatched",
        mismatched,
        mismatched_decision,
        mismatched_input,
        input_bindings[mismatched_input_id],
    )
    target_id = compiled["target_id"]
    assert isinstance(target_id, str)
    context = compiled["context"]
    assert isinstance(context, PilotDecisionContext)
    return TasteMechanismPilotTarget.create(
        target_id=target_id,
        source_review_item_id=source.receipt.review_item_id,
        source_group_id=source.receipt.source_group_id,
        domain=source.receipt.domain,
        decision_family=decision.primary_decision_family,
        decision_context=context,
        source_observed_action=_action(target_id, decision),
        distractor_action=_action(distractor_target_id, distractor_decision),
        raw_source_rag=PilotArmBinding(condition="raw-source-rag", reference=matched_reference),
        abstracted_matched_taste=PilotArmBinding(
            condition="abstracted-matched-taste", reference=matched_reference
        ),
        abstracted_mismatched_taste=PilotArmBinding(
            condition="abstracted-mismatched-taste", reference=mismatched_reference
        ),
    )


def _selection_rank(seed: str, domain: str, content_sha256: str) -> str:
    return _canonical_sha256([_SELECTION_ALGORITHM, seed, domain, content_sha256])


def _select_target_decision(
    config: TasteMechanismPilotConfig, source: _LoadedSource
) -> TasteSourceDecisionSegment:
    safe = []
    for decision in source.decisions:
        context = _target_context(source, decision)
        visible = "\n".join(
            item for item in (context.reviewed_abstract, context.predecision_review_context) if item
        ).casefold()
        if (
            decision.verbatim_decision_text.casefold() not in visible
            and decision.atomic_decision_statement.casefold() not in visible
        ):
            safe.append(decision)
    if not safe:
        raise ValueError("Track-A target has no decision that satisfies the leakage boundary")
    return min(
        safe,
        key=lambda item: _canonical_sha256(
            [
                config.selection_seed,
                source.receipt.source_comment_sha256,
                item.segment_id,
                hashlib.sha256(item.atomic_decision_statement.encode()).hexdigest(),
            ]
        ),
    )


def _target_context(
    source: _LoadedSource, decision: TasteSourceDecisionSegment
) -> PilotDecisionContext:
    comment = source.scientific.review_comment
    fragments: list[str] = []
    for span in decision.context_ranges:
        if comment[span.start_char : span.end_char] != span.verbatim_context_text:
            raise ValueError("Track-A AI-D context span differs from the review comment")
        for start, end in _subtract_interval(
            span.start_char, span.end_char, decision.start_char, decision.end_char
        ):
            fragment = comment[start:end].strip()
            if fragment:
                fragments.append(fragment)
    if not fragments and decision.start_char:
        prefix = comment[max(0, decision.start_char - 1_200) : decision.start_char].strip()
        if prefix:
            fragments.append(prefix)
    predecision = "\n\n".join(fragments) or None
    if comment[decision.start_char : decision.end_char] != decision.verbatim_decision_text:
        raise ValueError("Track-A AI-D trigger span differs from the review comment")
    visible = "\n".join(
        item for item in (source.scientific.reviewed_abstract, predecision) if item
    ).casefold()
    if (
        decision.verbatim_decision_text.casefold() in visible
        or decision.atomic_decision_statement.casefold() in visible
    ):
        raise ValueError("Track-A target context leaks its action")
    return PilotDecisionContext(
        reviewed_abstract=source.scientific.reviewed_abstract,
        predecision_review_context=predecision,
        context_sha256=_canonical_sha256(
            {
                "reviewed_abstract": source.scientific.reviewed_abstract,
                "predecision_review_context": predecision,
            }
        ),
    )


def _subtract_interval(
    start: int, end: int, cut_start: int, cut_end: int
) -> tuple[tuple[int, int], ...]:
    if end <= cut_start or start >= cut_end:
        return ((start, end),)
    parts = []
    if start < cut_start:
        parts.append((start, cut_start))
    if end > cut_end:
        parts.append((cut_end, end))
    return tuple(parts)


def _assign_distractors(
    targets: list[_LoadedSource],
    decisions: dict[str, TasteSourceDecisionSegment],
    target_ids: dict[str, str],
) -> dict[str, tuple[_LoadedSource, TasteSourceDecisionSegment, str]]:
    by_family: dict[TasteTask, list[_LoadedSource]] = defaultdict(list)
    for source in targets:
        family = decisions[source.receipt.review_item_id].primary_decision_family
        assert isinstance(family, TasteTask)
        by_family[family].append(source)
    result = {}
    for family, members in sorted(by_family.items(), key=lambda item: item[0].value):
        ordered = sorted(members, key=lambda item: target_ids[item.receipt.review_item_id])
        if len(ordered) < 2:
            raise ValueError(f"Track-A cannot construct a same-family distractor for {family}")
        for index, source in enumerate(ordered):
            other = ordered[(index + 1) % len(ordered)]
            other_id = other.receipt.review_item_id
            result[source.receipt.review_item_id] = (
                other,
                decisions[other_id],
                target_ids[other_id],
            )
    if len({value[2] for value in result.values()}) != len(targets):
        raise ValueError("Track-A distractor assignment is not one-to-one")
    return result


def _select_precedent(
    config: TasteMechanismPilotConfig,
    target: _LoadedSource,
    target_decision: TasteSourceDecisionSegment,
    pool: tuple[_LoadedSource, ...],
    pool_decisions: dict[str, TasteSourceDecisionSegment],
    *,
    relation: Literal["matched", "mismatched"],
    usage: Counter[str],
) -> _LoadedSource:
    candidates = [
        item
        for item in pool
        if (
            (item.receipt.domain == target.receipt.domain)
            if relation == "matched"
            else (item.receipt.domain != target.receipt.domain)
        )
        and item.receipt.source_group_id != target.receipt.source_group_id
    ]
    if not candidates:
        raise ValueError(f"Track-A lacks a source-disjoint {relation} precedent")
    family = target_decision.primary_decision_family
    return min(
        candidates,
        key=lambda item: (
            pool_decisions[item.receipt.review_item_id].primary_decision_family != family,
            usage[item.receipt.review_item_id],
            _canonical_sha256(
                [
                    _PAIRING_ALGORITHM,
                    config.selection_seed,
                    relation,
                    target.receipt.source_comment_sha256,
                    item.receipt.source_comment_sha256,
                ]
            ),
        ),
    )


def _select_canonical_precedent_decision(
    config: TasteMechanismPilotConfig, source: _LoadedSource
) -> TasteSourceDecisionSegment:
    return min(
        source.decisions,
        key=lambda item: _canonical_sha256(
            [config.selection_seed, source.receipt.source_comment_sha256, item.segment_id]
        ),
    )


def _abstraction_input(
    *,
    input_id: str,
    source: _LoadedSource,
    decision: TasteSourceDecisionSegment,
) -> TasteAbstractionInput:
    projection = _precedent_projection(source, decision)
    digest = _canonical_sha256(
        [input_id, source.receipt.source_comment_sha256, decision.segment_id]
    )[:20]
    family = decision.primary_decision_family
    assert isinstance(family, TasteTask)
    return TasteAbstractionInput(
        source_id=f"pilot-source-{source.receipt.source_comment_sha256[:20]}",
        candidate_id=f"pilot-abstraction-{digest}",
        case_id=f"pilot-case-{digest}",
        stage=family.value,
        decision_role=f"derive a transferable {family.value} decision precedent",
        source_projection=projection,
        source_projection_sha256=hashlib.sha256(projection.encode()).hexdigest(),
        domain_tags=(source.receipt.domain,),
        outcome_information_availability="available",
    )


def _precedent_projection(source: _LoadedSource, decision: TasteSourceDecisionSegment) -> str:
    context = _target_context(source, decision)
    fields: dict[str, dict[str, object]] = {
        "reviewed_abstract": {
            "semantic_roles": ["problem_context", "evidence"],
            "value": context.reviewed_abstract,
        },
        "verbatim_scientific_action": {
            "semantic_roles": ["alternative", "scientific_action"],
            "value": decision.verbatim_decision_text,
        },
        "observed_natural_outcome": {
            "semantic_role": "outcome",
            "value": source.private.observed_recommendation,
        },
    }
    if context.predecision_review_context:
        fields["predecision_review_context"] = {
            "semantic_roles": ["alternative", "evidence", "limitation"],
            "value": context.predecision_review_context,
        }
    return _canonical_json(
        {
            "schema_version": "1.0",
            "outcome_information_availability": "available",
            "fields": fields,
        }
    ).decode()


def _reference(
    relation: Literal["matched", "mismatched"],
    source: _LoadedSource,
    decision: TasteSourceDecisionSegment,
    input_data: TasteAbstractionInput,
    binding: PilotFileBinding,
) -> PilotAbstractionReference:
    family = decision.primary_decision_family
    assert isinstance(family, TasteTask)
    return PilotAbstractionReference(
        relation=relation,
        source_review_item_id=source.receipt.review_item_id,
        source_group_id=source.receipt.source_group_id,
        source_domain=source.receipt.domain,
        source_segment_id=decision.segment_id,
        source_decision_family=family,
        abstraction_input=binding,
        source_projection_sha256=input_data.source_projection_sha256,
        source_projection_bytes=len(input_data.source_projection.encode()),
    )


def _action(target_id: str, decision: TasteSourceDecisionSegment) -> PilotAction:
    family = decision.primary_decision_family
    assert isinstance(family, TasteTask)
    return PilotAction(
        source_target_id=target_id,
        source_segment_id=decision.segment_id,
        decision_family=family,
        action_text=decision.atomic_decision_statement,
        action_sha256=hashlib.sha256(decision.atomic_decision_statement.encode()).hexdigest(),
    )


def _load_jsonl(path: Path, model: type[BaseModel]) -> tuple[BaseModel, ...]:
    items = []
    for line_number, line in enumerate(path.read_bytes().splitlines(), 1):
        if not line.strip():
            continue
        try:
            items.append(model.model_validate_json(line))
        except ValueError as error:
            raise ValueError(f"Track-A JSONL line {line_number} is invalid") from error
    if not items:
        raise ValueError("Track-A bound JSONL file is empty")
    return tuple(items)


def _load_private_map(path: Path) -> tuple[TasteSourcePrivateMapItem, ...]:
    payload = json.loads(path.read_bytes())
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0":
        raise ValueError("Track-A private map has an unsupported schema")
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("Track-A private map is empty")
    return tuple(TasteSourcePrivateMapItem.model_validate(item) for item in items)


def _bound_file(root: Path, binding: PilotFileBinding, *, maximum_bytes: int) -> Path:
    candidate = root.joinpath(*_safe_locator(binding.locator).parts)
    source = _bounded_file(candidate, maximum_bytes=maximum_bytes)
    try:
        source.relative_to(root)
    except ValueError as error:
        raise ValueError("Track-A bound file escapes the locator root") from error
    if _sha256_file(source) != binding.file_sha256:
        raise ValueError(f"Track-A bound file hash drifted: {binding.locator}")
    return source


def _bounded_file(path: Path, *, maximum_bytes: int) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Track-A file must be a regular non-symlink: {path}")
    if path.stat().st_size > maximum_bytes:
        raise ValueError(f"Track-A file exceeds its byte ceiling: {path}")
    return path.resolve(strict=True)


def _safe_locator(locator: str) -> PurePosixPath:
    path = PurePosixPath(locator)
    if "\\" in locator or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("Track-A artifact locator is unsafe")
    return path


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve(strict=True).relative_to(root).as_posix()
    except ValueError as error:
        raise ValueError("Track-A file lies outside the locator root") from error


def _write_new(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1_048_576):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


__all__ = [
    "TasteMechanismPilotConfig",
    "TasteMechanismPilotPlan",
    "TasteMechanismPilotPlanInspection",
    "TasteMechanismPilotTarget",
    "load_taste_mechanism_pilot_plan",
    "prepare_taste_mechanism_pilot",
]
