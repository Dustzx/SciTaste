"""Materialize the AI-only natural Track-A pilot into frozen three-arm requests."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, JsonValue, computed_field, model_validator

from scitaste.evaluation.ai_taste_abstraction_review import (
    AIAbstractionAdjudicationRequest,
    AIAbstractionAdjudicationResponse,
    AIAbstractionFileBinding,
    AIAbstractionFinalDisposition,
    AIAbstractionPrimaryRequest,
    AIAbstractionRawReviewItem,
    AIAbstractionRawReviewResponse,
    AIAbstractionRequestPack,
    AIAbstractionReviewDisposition,
    AIAbstractionReviewExecutionReceipt,
    AIAcceptedTasteAbstraction,
    AIAcceptedTasteAbstractionSet,
    AIVisibleGroundedTasteAbstraction,
    LockedAIAbstractionPrimaryReviews,
    load_ai_abstraction_request_pack,
)
from scitaste.evaluation.taste_mechanism_pilot import (
    PilotAbstractionInputRecord,
    TasteMechanismPilotTarget,
    load_taste_mechanism_pilot_plan,
)
from scitaste.model_nodes.models import NodeResult, NodeResultStatus
from scitaste.model_nodes.runtime import RuntimeInvocationReceipt, RuntimeOutcome
from scitaste.taste.reference_quality import (
    ReferenceQualityQualification,
    ReferenceQualityVerdict,
)
from scitaste.taste.semantic_models import (
    GROUNDED_TASTE_ABSTRACTION_NODE,
    GroundedTasteCaseAbstraction,
    TasteAbstractionInput,
    validate_grounded_abstraction_against_projection,
)

_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)
_EXACT_CONFIG = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_CONTROL_BYTES = 64 * 1_048_576
_CONDITIONS = (
    "raw-source-rag",
    "abstracted-matched-taste",
    "abstracted-mismatched-taste",
)


class TrackASuiteFileBinding(BaseModel):
    model_config = _CONFIG

    locator: str = Field(min_length=1, max_length=2_000)
    file_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def locator_is_safe(self) -> TrackASuiteFileBinding:
        _safe_locator(self.locator)
        return self


class TrackASuiteSemanticBinding(TrackASuiteFileBinding):
    semantic_sha256: str = Field(pattern=_SHA256)


class TrackASuiteSampling(BaseModel):
    model_config = _CONFIG

    seed: int
    temperature: float = Field(ge=0, le=2, allow_inf_nan=False)
    top_p: float = Field(gt=0, le=1, allow_inf_nan=False)
    maximum_output_tokens: int = Field(gt=0, le=65_536)
    response_schema: Literal["scitaste-track-a-observed-action-selection-v1"]


class TrackASuiteContextBudget(BaseModel):
    model_config = _CONFIG

    maximum_target_prompt_bytes: int = Field(gt=0)
    maximum_precedent_context_bytes: int = Field(gt=0)
    maximum_request_bytes: int = Field(gt=0)
    maximum_input_tokens: int = Field(gt=0)
    tokenizer_count_required_before_execution: Literal[True] = True
    no_silent_truncation: Literal[True] = True


class TrackAPilotSuiteSpec(BaseModel):
    """Tracked decision-model identity, prompt, sampling, and budget contract."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    spec_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    provider: str = Field(min_length=1, max_length=200)
    model: str = Field(min_length=1, max_length=300)
    model_identity_status: Literal["declared-exact-name-runtime-attestation-required"]
    study_mode: Literal["natural-ai-pilot", "formal-candidate"]
    system_instruction: str = Field(min_length=1, max_length=20_000)
    target_instruction: str = Field(min_length=1, max_length=10_000)
    output_schema: dict[str, JsonValue]
    sampling: TrackASuiteSampling
    context_budget: TrackASuiteContextBudget
    condition_order: tuple[
        Literal[
            "raw-source-rag",
            "abstracted-matched-taste",
            "abstracted-mismatched-taste",
        ],
        ...,
    ]
    tools_allowed: Literal[False] = False
    automatic_retry_allowed: Literal[False] = False
    relation_labels_hidden_from_model: Literal[True] = True
    source_identity_hidden_from_model: Literal[True] = True
    source_observed_action_is_natural_proxy_not_truth: Literal[True] = True
    formal_reference_quality_qualification_required: Literal[True] = True
    natural_pilot_reference_quality_override: bool
    objective_correctness_claim_allowed: Literal[False] = False
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    human_or_expert_validity_claim_allowed: Literal[False] = False
    formal_evidence_eligible: Literal[False] = False
    authorizes_model_calls: Literal[False] = False
    authorizes_api_spend: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False
    authorizes_experiment_execution: Literal[False] = False

    @model_validator(mode="after")
    def spec_is_closed(self) -> TrackAPilotSuiteSpec:
        if self.condition_order != _CONDITIONS:
            raise ValueError("Track-A suite must freeze the three conditions exactly once")
        allowed = self.output_schema.get("properties")
        if not isinstance(allowed, dict) or set(allowed) != {
            "selected_action_id",
            "abstained",
            "confidence",
            "rationale",
        }:
            raise ValueError("Track-A suite output schema drifted")
        if self.natural_pilot_reference_quality_override != (
            self.study_mode == "natural-ai-pilot"
        ):
            raise ValueError(
                "Track-A reference-quality override is allowed only for the natural pilot"
            )
        return self

    @computed_field
    @property
    def spec_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"spec_sha256"}))


class TrackACandidateAction(BaseModel):
    model_config = _EXACT_CONFIG

    action_id: Literal["option-a", "option-b"]
    text: str = Field(min_length=1, max_length=2_000)
    text_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def text_hash_is_exact(self) -> TrackACandidateAction:
        if self.text_sha256 != hashlib.sha256(self.text.encode()).hexdigest():
            raise ValueError("Track-A candidate-action hash mismatch")
        return self


class TrackATargetPrompt(BaseModel):
    """The byte-identical target prompt reused by all three arms."""

    model_config = _EXACT_CONFIG

    instruction: str
    decision_family: str
    reviewed_abstract: str
    predecision_review_context: str | None
    candidate_actions: tuple[TrackACandidateAction, TrackACandidateAction]

    @model_validator(mode="after")
    def actions_are_closed(self) -> TrackATargetPrompt:
        if tuple(item.action_id for item in self.candidate_actions) != ("option-a", "option-b"):
            raise ValueError("Track-A candidate actions must be ordered A/B")
        if len({item.text_sha256 for item in self.candidate_actions}) != 2:
            raise ValueError("Track-A candidate actions must be distinct")
        return self


class TrackAModelVisibleRequest(BaseModel):
    """Only these bytes may be sent to the decision model."""

    model_config = _EXACT_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    request_id: str = Field(pattern=_ID)
    provider: str
    model: str
    system_instruction: str
    target_prompt: TrackATargetPrompt
    precedent_representation: Literal[
        "raw-source-projection", "grounded-taste-abstraction"
    ]
    precedent_content: dict[str, JsonValue]
    output_schema: dict[str, JsonValue]
    sampling: TrackASuiteSampling
    maximum_input_tokens: int = Field(gt=0)
    tools_allowed: Literal[False] = False
    relation_label_absent: Literal[True] = True
    source_identity_absent: Literal[True] = True

    @computed_field
    @property
    def request_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"request_sha256"}))


class TrackAArmExecutionConfig(BaseModel):
    """Controller metadata plus a condition-blind provider request."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    config_id: str = Field(pattern=_ID)
    target_id: str = Field(pattern=_ID)
    condition: Literal[
        "raw-source-rag", "abstracted-matched-taste", "abstracted-mismatched-taste"
    ]
    precedent_input_id: str = Field(pattern=_ID)
    precedent_source_group_id: str = Field(pattern=_ID)
    precedent_domain: Literal["computing", "ecology", "public-health"]
    source_projection_sha256: str = Field(pattern=_SHA256)
    accepted_abstraction_sha256: str | None = Field(default=None, pattern=_SHA256)
    target_prompt_sha256: str = Field(pattern=_SHA256)
    target_prompt_bytes: int = Field(gt=0)
    precedent_context_bytes: int = Field(gt=0)
    model_request_bytes: int = Field(gt=0)
    model_visible_request: TrackAModelVisibleRequest
    source_observed_action_absent_from_model_metadata: Literal[True] = True
    condition_metadata_absent_from_model_request: Literal[True] = True
    model_call_performed: Literal[False] = False
    config_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def config_is_self_hashed(self) -> TrackAArmExecutionConfig:
        if self.model_visible_request.request_sha256 != _canonical_sha256(
            self.model_visible_request.model_dump(mode="json", exclude={"request_sha256"})
        ):
            raise ValueError("Track-A model request hash drifted")
        expected = _canonical_sha256(self.model_dump(mode="json", exclude={"config_sha256"}))
        if self.config_sha256 != expected:
            raise ValueError("Track-A execution config hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> TrackAArmExecutionConfig:
        payload = {"schema_version": "1.0", **values}
        payload.pop("config_sha256", None)
        unsigned = cls.model_construct(config_sha256="0" * 64, **payload)
        return cls(
            **payload,
            config_sha256=_canonical_sha256(
                unsigned.model_dump(mode="json", exclude={"config_sha256"})
            ),
        )


class TrackASuiteArmRecord(BaseModel):
    model_config = _CONFIG

    condition: Literal[
        "raw-source-rag", "abstracted-matched-taste", "abstracted-mismatched-taste"
    ]
    precedent_input_id: str = Field(pattern=_ID)
    precedent_source_group_id: str = Field(pattern=_ID)
    precedent_domain: Literal["computing", "ecology", "public-health"]
    source_projection_sha256: str = Field(pattern=_SHA256)
    accepted_abstraction_sha256: str | None = Field(default=None, pattern=_SHA256)
    execution_config: TrackASuiteSemanticBinding
    model_request_sha256: str = Field(pattern=_SHA256)
    target_prompt_sha256: str = Field(pattern=_SHA256)
    target_prompt_bytes: int = Field(gt=0)
    precedent_context_bytes: int = Field(gt=0)
    model_request_bytes: int = Field(gt=0)
    input_token_count_status: Literal["must-measure-before-execution"]


class TrackASuiteCaseRecord(BaseModel):
    model_config = _CONFIG

    target_id: str = Field(pattern=_ID)
    target_source_group_id: str = Field(pattern=_ID)
    target_domain: Literal["computing", "ecology", "public-health"]
    decision_family: str
    source_observed_action_option_id: Literal["option-a", "option-b"]
    source_observed_action_sha256: str = Field(pattern=_SHA256)
    natural_proxy_not_objective_truth: Literal[True] = True
    arms: tuple[TrackASuiteArmRecord, TrackASuiteArmRecord, TrackASuiteArmRecord]

    @model_validator(mode="after")
    def arms_are_an_identifiable_triplet(self) -> TrackASuiteCaseRecord:
        if tuple(item.condition for item in self.arms) != _CONDITIONS:
            raise ValueError("Track-A case does not contain the frozen three-arm order")
        raw, matched, mismatched = self.arms
        if (
            raw.precedent_input_id != matched.precedent_input_id
            or raw.precedent_source_group_id != matched.precedent_source_group_id
            or raw.source_projection_sha256 != matched.source_projection_sha256
            or matched.accepted_abstraction_sha256 is None
            or raw.accepted_abstraction_sha256 is not None
        ):
            raise ValueError("Track-A H1 arms do not preserve same-source identity")
        if (
            matched.precedent_domain != self.target_domain
            or mismatched.precedent_domain == self.target_domain
            or len(
                {
                    self.target_source_group_id,
                    matched.precedent_source_group_id,
                    mismatched.precedent_source_group_id,
                }
            )
            != 3
        ):
            raise ValueError("Track-A H2 domain or source-group isolation failed")
        if len({item.target_prompt_sha256 for item in self.arms}) != 1:
            raise ValueError("Track-A arms do not share byte-identical target prompts")
        return self


class TrackAAbstractionCoverage(BaseModel):
    """Why one planned precedent is or is not available to the suite."""

    model_config = _CONFIG

    input_id: str = Field(pattern=_ID)
    source_group_id: str = Field(pattern=_ID)
    source_domain: Literal["computing", "ecology", "public-health"]
    status: Literal["accepted", "ai-review-rejected", "not-present-in-accepted-set"]
    review_item_id: str | None = Field(default=None, pattern=_ID)
    reason_code: Literal[
        "operational-ai-review-accepted",
        "operational-ai-review-rejected",
        "runtime-or-review-result-not-present",
    ]
    no_substitute_generated: Literal[True] = True


class TrackATargetCoverage(BaseModel):
    """Per-target coverage; only two accepted precedents make a triplet runnable."""

    model_config = _CONFIG

    target_id: str = Field(pattern=_ID)
    matched_input_id: str = Field(pattern=_ID)
    matched_status: Literal["accepted", "ai-review-rejected", "not-present-in-accepted-set"]
    mismatched_input_id: str = Field(pattern=_ID)
    mismatched_status: Literal[
        "accepted", "ai-review-rejected", "not-present-in-accepted-set"
    ]
    runnable: bool
    blocker_codes: tuple[str, ...]

    @model_validator(mode="after")
    def coverage_is_closed(self) -> TrackATargetCoverage:
        expected = self.matched_status == self.mismatched_status == "accepted"
        if self.runnable != expected:
            raise ValueError("Track-A target runnable status differs from its precedents")
        if self.blocker_codes != tuple(sorted(set(self.blocker_codes))):
            raise ValueError("Track-A target coverage blockers must be sorted and unique")
        if self.runnable != (not self.blocker_codes):
            raise ValueError("Track-A target coverage blockers differ from readiness")
        return self


class TrackAPilotSuiteManifest(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    suite_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    pilot_plan: TrackASuiteSemanticBinding
    suite_spec: TrackASuiteSemanticBinding
    accepted_abstraction_set: TrackASuiteSemanticBinding
    materializer_implementation_sha256: str = Field(pattern=_SHA256)
    provider: str
    model: str
    sampling: TrackASuiteSampling
    context_budget: TrackASuiteContextBudget
    study_mode: Literal["natural-ai-pilot", "formal-candidate"]
    reference_quality_status: Literal[
        "natural-pilot-explicit-override", "all-precedents-qualified"
    ]
    reference_quality_qualifications: tuple[TrackASuiteSemanticBinding, ...]
    cases: tuple[TrackASuiteCaseRecord, ...] = Field(min_length=1, max_length=24)
    case_count: int = Field(ge=1, le=24)
    arm_count: int = Field(ge=3, le=72)
    accepted_abstraction_count: int = Field(ge=1, le=16)
    full_target_coverage: bool
    all_target_prompts_equal_within_case: Literal[True] = True
    all_h1_raw_taste_projections_identical: Literal[True] = True
    all_h2_sources_domain_and_group_disjoint: Literal[True] = True
    source_observed_action_is_natural_proxy_not_truth: Literal[True] = True
    permitted_endpoint: Literal["observed-action-agreement-and-natural-outcome-proxy"] = (
        "observed-action-agreement-and-natural-outcome-proxy"
    )
    objective_accuracy_claim_allowed: Literal[False] = False
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    human_or_expert_validity_claim_allowed: Literal[False] = False
    natural_pilot: bool
    formal_evidence_eligible: Literal[False] = False
    execution_authorized: Literal[False] = False
    model_calls_performed: Literal[False] = False
    api_spend_performed: Literal[False] = False
    gpu_work_performed: Literal[False] = False
    experiment_performed: Literal[False] = False
    manifest_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def manifest_is_closed(self) -> TrackAPilotSuiteManifest:
        if tuple(item.target_id for item in self.cases) != tuple(
            sorted({item.target_id for item in self.cases})
        ):
            raise ValueError("Track-A suite cases must be sorted and unique")
        if sum(len(item.arms) for item in self.cases) != self.arm_count:
            raise ValueError("Track-A suite arm count drifted")
        if self.case_count != len(self.cases) or self.arm_count != 3 * self.case_count:
            raise ValueError("Track-A suite case/arm counts are inconsistent")
        if self.full_target_coverage != (self.case_count == 24):
            raise ValueError("Track-A suite full-coverage flag drifted")
        if self.natural_pilot != (self.study_mode == "natural-ai-pilot"):
            raise ValueError("Track-A suite study-mode flag drifted")
        if self.study_mode == "formal-candidate" and self.reference_quality_status != (
            "all-precedents-qualified"
        ):
            raise ValueError("formal-candidate Track-A suite lacks reference qualification")
        expected_quality_count = 0 if self.study_mode == "natural-ai-pilot" else 16
        if len(self.reference_quality_qualifications) != expected_quality_count:
            raise ValueError("Track-A suite reference-quality binding count drifted")
        expected = _canonical_sha256(self.model_dump(mode="json", exclude={"manifest_sha256"}))
        if self.manifest_sha256 != expected:
            raise ValueError("Track-A suite manifest hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> TrackAPilotSuiteManifest:
        payload = {"schema_version": "1.0", **values}
        payload.pop("manifest_sha256", None)
        unsigned = cls.model_construct(manifest_sha256="0" * 64, **payload)
        return cls(
            **payload,
            manifest_sha256=_canonical_sha256(
                unsigned.model_dump(mode="json", exclude={"manifest_sha256"})
            ),
        )


class TrackAPilotSuitePreparation(BaseModel):
    """Always emitted; blockers are data, not an invitation to fabricate content."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    preparation_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    prepared_at: datetime
    pilot_plan: TrackASuiteSemanticBinding
    suite_spec: TrackASuiteSemanticBinding
    accepted_abstraction_set: TrackASuiteSemanticBinding | None = None
    expected_abstraction_count: Literal[16] = 16
    accepted_abstraction_count: int = Field(ge=0, le=16)
    abstraction_coverage: tuple[TrackAAbstractionCoverage, ...] = Field(
        min_length=16, max_length=16
    )
    missing_abstraction_input_ids: tuple[str, ...]
    target_coverage: tuple[TrackATargetCoverage, ...] = Field(min_length=24, max_length=24)
    runnable_target_count: int = Field(ge=0, le=24)
    reference_quality_qualifications: tuple[TrackASuiteSemanticBinding, ...] = ()
    reference_quality_status: Literal[
        "natural-pilot-explicit-override",
        "all-precedents-qualified",
        "formal-qualification-incomplete",
    ]
    blocker_codes: tuple[str, ...]
    status: Literal["blocked", "partial", "ready"]
    suite_manifest: TrackASuiteSemanticBinding | None = None
    generated_arm_config_count: int = Field(ge=0, le=72)
    source_observed_action_is_natural_proxy_not_truth: Literal[True] = True
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    formal_evidence_eligible: Literal[False] = False
    authorizes_model_calls: Literal[False] = False
    authorizes_api_spend: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False
    authorizes_experiment_execution: Literal[False] = False
    preparation_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def preparation_is_honest(self) -> TrackAPilotSuitePreparation:
        if self.prepared_at.utcoffset() is None:
            raise ValueError("Track-A suite preparation time must include a timezone")
        if self.blocker_codes != tuple(sorted(set(self.blocker_codes))):
            raise ValueError("Track-A suite blocker codes must be sorted and unique")
        if self.missing_abstraction_input_ids != tuple(
            sorted(set(self.missing_abstraction_input_ids))
        ):
            raise ValueError("Track-A missing abstraction IDs must be sorted and unique")
        if tuple(item.input_id for item in self.abstraction_coverage) != tuple(
            sorted({item.input_id for item in self.abstraction_coverage})
        ):
            raise ValueError("Track-A abstraction coverage must be sorted and unique")
        if tuple(item.target_id for item in self.target_coverage) != tuple(
            sorted({item.target_id for item in self.target_coverage})
        ):
            raise ValueError("Track-A target coverage must be sorted and unique")
        if self.accepted_abstraction_count != sum(
            item.status == "accepted" for item in self.abstraction_coverage
        ):
            raise ValueError("Track-A accepted count differs from coverage")
        if self.runnable_target_count != sum(item.runnable for item in self.target_coverage):
            raise ValueError("Track-A runnable target count differs from coverage")
        expected_status = (
            "blocked"
            if self.runnable_target_count == 0
            or self.reference_quality_status == "formal-qualification-incomplete"
            else "ready"
            if self.runnable_target_count == 24 and not self.blocker_codes
            else "partial"
        )
        if self.status != expected_status:
            raise ValueError("Track-A suite readiness differs from its coverage")
        if self.status == "blocked" and (
            self.suite_manifest is not None or self.generated_arm_config_count
        ):
            raise ValueError("blocked Track-A suite cannot expose execution configs")
        if self.status != "blocked" and (
            self.suite_manifest is None
            or self.generated_arm_config_count != 3 * self.runnable_target_count
        ):
            raise ValueError("available Track-A suite has inconsistent config coverage")
        expected = _canonical_sha256(
            self.model_dump(mode="json", exclude={"preparation_sha256"})
        )
        if self.preparation_sha256 != expected:
            raise ValueError("Track-A suite preparation hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> TrackAPilotSuitePreparation:
        payload = {"schema_version": "1.0", **values}
        payload.pop("preparation_sha256", None)
        unsigned = cls.model_construct(preparation_sha256="0" * 64, **payload)
        return cls(
            **payload,
            preparation_sha256=_canonical_sha256(
                unsigned.model_dump(mode="json", exclude={"preparation_sha256"})
            ),
        )


class TrackAPilotSuiteInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    preparation: TrackAPilotSuitePreparation
    manifest_verified: bool
    arm_configs_verified: int = Field(ge=0, le=72)


class _AcceptedAbstraction:
    def __init__(
        self,
        *,
        accepted: AIAcceptedTasteAbstraction,
        node_input: TasteAbstractionInput,
        visible: AIVisibleGroundedTasteAbstraction,
    ) -> None:
        self.accepted = accepted
        self.node_input = node_input
        self.visible = visible


def materialize_track_a_pilot_suite(
    *,
    evidence_root: str | Path,
    pilot_plan_path: str | Path,
    suite_spec_path: str | Path,
    output_dir: str | Path,
    accepted_abstraction_set_path: str | Path | None = None,
    reference_quality_qualification_paths: Sequence[str | Path] = (),
    prepared_at: datetime | None = None,
) -> TrackAPilotSuitePreparation:
    """Compile a blocked status or a complete 24-case/72-arm no-call suite."""

    root = Path(evidence_root).resolve(strict=True)
    plan_file = _regular_file(root, pilot_plan_path)
    plan_inspection = load_taste_mechanism_pilot_plan(plan_file, locator_root=root)
    plan = plan_inspection.plan
    spec_file = _regular_file(root, suite_spec_path)
    spec = load_track_a_pilot_suite_spec(spec_file)
    if plan.project_id != spec.project_id:
        raise ValueError("Track-A suite plan and spec target different projects")
    target = _new_path(root, output_dir)
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{target.name}.", suffix=".staging", dir=target.parent
        )
    )
    try:
        plan_binding = TrackASuiteSemanticBinding(
            locator=_relative(plan_file, root),
            file_sha256=_sha256_file(plan_file),
            semantic_sha256=plan.plan_sha256,
        )
        spec_binding = TrackASuiteSemanticBinding(
            locator=_relative(spec_file, root),
            file_sha256=_sha256_file(spec_file),
            semantic_sha256=spec.spec_sha256,
        )
        accepted_binding: TrackASuiteSemanticBinding | None = None
        accepted_by_input: dict[str, _AcceptedAbstraction] = {}
        coverage_by_input: dict[str, tuple[str, str | None, str]] = {
            item.input_id: (
                "not-present-in-accepted-set",
                None,
                "runtime-or-review-result-not-present",
            )
            for item in plan.abstraction_inputs
        }
        blocker_codes: list[str] = []
        if accepted_abstraction_set_path is None:
            blocker_codes.append("accepted-abstraction-set-missing")
        else:
            accepted_file = _candidate_path(root, accepted_abstraction_set_path)
            if not accepted_file.exists():
                blocker_codes.append("accepted-abstraction-set-file-missing")
            else:
                accepted_file = _regular_file(root, accepted_file)
                accepted_set = _load_accepted_set(accepted_file)
                accepted_binding = TrackASuiteSemanticBinding(
                    locator=_relative(accepted_file, root),
                    file_sha256=_sha256_file(accepted_file),
                    semantic_sha256=accepted_set.accepted_set_sha256,
                )
                accepted_by_input, coverage_by_input, accepted_pack = _verify_accepted_set(
                    root=root,
                    plan_file=plan_file,
                    plan_inputs=plan.abstraction_inputs,
                    accepted_set=accepted_set,
                )
                if accepted_pack.schema_version == "1.0":
                    if accepted_set.input_candidate_count != len(plan.abstraction_inputs):
                        blocker_codes.append("accepted-set-candidate-count-mismatch")
                else:
                    if accepted_pack.planned_source_count != len(plan.abstraction_inputs):
                        raise ValueError("coverage-aware review pack differs from the pilot plan")
                    if accepted_pack.eligible_source_count != len(plan.abstraction_inputs):
                        blocker_codes.append("quality-qualified-source-coverage-incomplete")
                    if accepted_pack.runtime_accepted_source_count != (
                        accepted_pack.eligible_source_count
                    ):
                        blocker_codes.append("runtime-abstraction-coverage-incomplete")
                    if not accepted_set.accepted:
                        blocker_codes.append("ai-review-accepted-abstraction-empty")
                if len(accepted_by_input) != len(plan.abstraction_inputs):
                    blocker_codes.append("accepted-abstraction-set-incomplete")
        expected_ids = {item.input_id for item in plan.abstraction_inputs}
        missing_ids = tuple(sorted(expected_ids - set(accepted_by_input)))
        abstraction_coverage = tuple(
            TrackAAbstractionCoverage(
                input_id=item.input_id,
                source_group_id=item.source_group_id,
                source_domain=item.source_domain,
                status=coverage_by_input[item.input_id][0],
                review_item_id=coverage_by_input[item.input_id][1],
                reason_code=coverage_by_input[item.input_id][2],
            )
            for item in plan.abstraction_inputs
        )
        target_coverage = _target_coverage(
            plan_file=plan_file,
            plan=plan,
            coverage_by_input=coverage_by_input,
        )
        runnable_target_ids = {
            item.target_id for item in target_coverage if item.runnable
        }
        if len(runnable_target_ids) != 24:
            blocker_codes.append("full-target-coverage-incomplete")
        quality_bindings, quality_status = _reference_quality_status(
            root=root,
            plan_file=plan_file,
            plan_inputs=plan.abstraction_inputs,
            spec=spec,
            paths=reference_quality_qualification_paths,
        )
        if quality_status == "formal-qualification-incomplete":
            blocker_codes.append("formal-reference-quality-qualification-incomplete")
        manifest: TrackAPilotSuiteManifest | None = None
        can_materialize = (
            bool(runnable_target_ids)
            and quality_status != "formal-qualification-incomplete"
        )
        if can_materialize:
            assert accepted_binding is not None
            manifest = _materialize_ready_suite(
                root=root,
                staging=staging,
                plan_file=plan_file,
                plan=plan,
                spec=spec,
                plan_binding=plan_binding,
                spec_binding=spec_binding,
                accepted_binding=accepted_binding,
                accepted_by_input=accepted_by_input,
                runnable_target_ids=runnable_target_ids,
                reference_quality_qualifications=quality_bindings,
                reference_quality_status=quality_status,
            )
            manifest_path = staging / "SUITE_MANIFEST.json"
            _write_new_json(manifest_path, manifest.model_dump(mode="json"))
            manifest_binding = TrackASuiteSemanticBinding(
                locator="SUITE_MANIFEST.json",
                file_sha256=_sha256_file(manifest_path),
                semantic_sha256=manifest.manifest_sha256,
            )
            status = "ready" if len(runnable_target_ids) == 24 and not blocker_codes else "partial"
            arm_count = 3 * len(runnable_target_ids)
        else:
            manifest_binding = None
            status = "blocked"
            arm_count = 0
        preparation = TrackAPilotSuitePreparation.create(
            preparation_id=f"{spec.spec_id}-preparation-{plan.plan_sha256[:16]}",
            project_id=plan.project_id,
            prepared_at=prepared_at or datetime.now(UTC),
            pilot_plan=plan_binding,
            suite_spec=spec_binding,
            accepted_abstraction_set=accepted_binding,
            accepted_abstraction_count=len(accepted_by_input),
            abstraction_coverage=abstraction_coverage,
            missing_abstraction_input_ids=missing_ids,
            target_coverage=target_coverage,
            runnable_target_count=len(runnable_target_ids),
            reference_quality_qualifications=quality_bindings,
            reference_quality_status=quality_status,
            blocker_codes=tuple(sorted(set(blocker_codes))),
            status=status,
            suite_manifest=manifest_binding,
            generated_arm_config_count=arm_count,
        )
        _write_new_json(staging / "STATUS.json", preparation.model_dump(mode="json"))
        os.rename(staging, target)
        return preparation
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def load_track_a_pilot_suite_spec(path: str | Path) -> TrackAPilotSuiteSpec:
    source = Path(path)
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Track-A suite spec must contain a mapping")
    return TrackAPilotSuiteSpec.model_validate(payload)


def inspect_track_a_pilot_suite(
    status_path_or_dir: str | Path,
    *,
    evidence_root: str | Path,
) -> TrackAPilotSuiteInspection:
    """Replay a blocked status or every ready manifest/config binding."""

    root = Path(evidence_root).resolve(strict=True)
    status_path = _candidate_path(root, status_path_or_dir)
    if status_path.is_dir():
        status_path /= "STATUS.json"
    source = _regular_file(root, status_path)
    preparation = TrackAPilotSuitePreparation.model_validate_json(source.read_bytes())
    output_root = source.parent.resolve(strict=True)
    _bound_file(root, preparation.pilot_plan)
    _bound_file(root, preparation.suite_spec)
    if preparation.accepted_abstraction_set is not None:
        _bound_file(root, preparation.accepted_abstraction_set)
    for binding in preparation.reference_quality_qualifications:
        _bound_file(root, binding)
    if preparation.status == "blocked":
        return TrackAPilotSuiteInspection(
            path=source,
            file_sha256=_sha256_file(source),
            preparation=preparation,
            manifest_verified=False,
            arm_configs_verified=0,
        )
    assert preparation.suite_manifest is not None
    manifest_path = _bound_file(output_root, preparation.suite_manifest)
    manifest = TrackAPilotSuiteManifest.model_validate_json(manifest_path.read_bytes())
    if manifest.manifest_sha256 != preparation.suite_manifest.semantic_sha256:
        raise ValueError("Track-A suite status binds another manifest")
    if manifest.reference_quality_qualifications != (
        preparation.reference_quality_qualifications
    ):
        raise ValueError("Track-A suite quality bindings differ from its status")
    verified = 0
    for case in manifest.cases:
        for arm in case.arms:
            config_path = _bound_file(output_root, arm.execution_config)
            config = TrackAArmExecutionConfig.model_validate_json(config_path.read_bytes())
            if (
                config.config_sha256 != arm.execution_config.semantic_sha256
                or config.model_visible_request.request_sha256 != arm.model_request_sha256
                or config.target_prompt_sha256 != arm.target_prompt_sha256
            ):
                raise ValueError("Track-A arm config differs from its manifest")
            verified += 1
    return TrackAPilotSuiteInspection(
        path=source,
        file_sha256=_sha256_file(source),
        preparation=preparation,
        manifest_verified=True,
        arm_configs_verified=verified,
    )


def _materialize_ready_suite(
    *,
    root: Path,
    staging: Path,
    plan_file: Path,
    plan: object,
    spec: TrackAPilotSuiteSpec,
    plan_binding: TrackASuiteSemanticBinding,
    spec_binding: TrackASuiteSemanticBinding,
    accepted_binding: TrackASuiteSemanticBinding,
    accepted_by_input: dict[str, _AcceptedAbstraction],
    runnable_target_ids: set[str],
    reference_quality_qualifications: tuple[TrackASuiteSemanticBinding, ...],
    reference_quality_status: Literal[
        "natural-pilot-explicit-override", "all-precedents-qualified"
    ],
) -> TrackAPilotSuiteManifest:
    cases: list[TrackASuiteCaseRecord] = []
    input_record_by_locator = {
        item.input_file.locator: item for item in plan.abstraction_inputs
    }
    for target_record in plan.targets:
        if target_record.target_id not in runnable_target_ids:
            continue
        target_path = plan_file.parent.joinpath(
            *PurePosixPath(target_record.target_file.locator).parts
        )
        if _sha256_file(target_path) != target_record.target_file.file_sha256:
            raise ValueError("Track-A target bytes differ from the pilot plan")
        target = TasteMechanismPilotTarget.model_validate_json(target_path.read_bytes())
        action_order = _ordered_actions(spec, target)
        target_prompt = TrackATargetPrompt(
            instruction=spec.target_instruction,
            decision_family=target.decision_family.value,
            reviewed_abstract=target.decision_context.reviewed_abstract,
            predecision_review_context=target.decision_context.predecision_review_context,
            candidate_actions=action_order,
        )
        target_prompt_sha = _canonical_sha256(target_prompt.model_dump(mode="json"))
        target_prompt_bytes = len(_canonical_json(target_prompt.model_dump(mode="json")))
        if target_prompt_bytes > spec.context_budget.maximum_target_prompt_bytes:
            raise ValueError("Track-A target prompt exceeds its frozen byte budget")
        matched_record = input_record_by_locator[
            target.abstracted_matched_taste.reference.abstraction_input.locator
        ]
        mismatched_record = input_record_by_locator[
            target.abstracted_mismatched_taste.reference.abstraction_input.locator
        ]
        arm_inputs = (
            ("raw-source-rag", matched_record),
            ("abstracted-matched-taste", matched_record),
            ("abstracted-mismatched-taste", mismatched_record),
        )
        arms: list[TrackASuiteArmRecord] = []
        for condition, input_record in arm_inputs:
            source_input = _load_plan_input(plan_file.parent, input_record)
            accepted = accepted_by_input[input_record.input_id]
            if condition == "raw-source-rag":
                representation = "raw-source-projection"
                content = json.loads(source_input.source_projection)
                abstraction_sha = None
            else:
                representation = "grounded-taste-abstraction"
                content = accepted.visible.model_dump(mode="json")
                abstraction_sha = accepted.accepted.abstraction_sha256
            precedent_bytes = len(_canonical_json(content))
            if precedent_bytes > spec.context_budget.maximum_precedent_context_bytes:
                raise ValueError("Track-A precedent context exceeds its frozen byte budget")
            request_identity = _canonical_sha256(
                [spec.spec_sha256, target.target_id, condition, input_record.input_id]
            )
            visible = TrackAModelVisibleRequest(
                request_id=f"track-a-decision-{request_identity[:24]}",
                provider=spec.provider,
                model=spec.model,
                system_instruction=spec.system_instruction,
                target_prompt=target_prompt,
                precedent_representation=representation,
                precedent_content=content,
                output_schema=spec.output_schema,
                sampling=spec.sampling,
                maximum_input_tokens=spec.context_budget.maximum_input_tokens,
            )
            request_bytes = len(
                _canonical_json(visible.model_dump(mode="json", exclude={"request_sha256"}))
            )
            if request_bytes > spec.context_budget.maximum_request_bytes:
                raise ValueError("Track-A decision request exceeds its frozen byte budget")
            config = TrackAArmExecutionConfig.create(
                config_id=f"track-a-config-{request_identity[:24]}",
                target_id=target.target_id,
                condition=condition,
                precedent_input_id=input_record.input_id,
                precedent_source_group_id=input_record.source_group_id,
                precedent_domain=input_record.source_domain,
                source_projection_sha256=input_record.source_projection_sha256,
                accepted_abstraction_sha256=abstraction_sha,
                target_prompt_sha256=target_prompt_sha,
                target_prompt_bytes=target_prompt_bytes,
                precedent_context_bytes=precedent_bytes,
                model_request_bytes=request_bytes,
                model_visible_request=visible,
            )
            relative = (
                PurePosixPath("execution-configs")
                / target.target_id
                / f"{condition}.json"
            )
            config_path = staging.joinpath(*relative.parts)
            _write_new_json(
                config_path,
                config.model_dump(mode="json", exclude_computed_fields=True),
            )
            arms.append(
                TrackASuiteArmRecord(
                    condition=condition,
                    precedent_input_id=input_record.input_id,
                    precedent_source_group_id=input_record.source_group_id,
                    precedent_domain=input_record.source_domain,
                    source_projection_sha256=input_record.source_projection_sha256,
                    accepted_abstraction_sha256=abstraction_sha,
                    execution_config=TrackASuiteSemanticBinding(
                        locator=relative.as_posix(),
                        file_sha256=_sha256_file(config_path),
                        semantic_sha256=config.config_sha256,
                    ),
                    model_request_sha256=visible.request_sha256,
                    target_prompt_sha256=target_prompt_sha,
                    target_prompt_bytes=target_prompt_bytes,
                    precedent_context_bytes=precedent_bytes,
                    model_request_bytes=request_bytes,
                    input_token_count_status="must-measure-before-execution",
                )
            )
        observed_option = next(
            item.action_id
            for item in action_order
            if item.text_sha256 == target.source_observed_action.action_sha256
        )
        cases.append(
            TrackASuiteCaseRecord(
                target_id=target.target_id,
                target_source_group_id=target.source_group_id,
                target_domain=target.domain,
                decision_family=target.decision_family.value,
                source_observed_action_option_id=observed_option,
                source_observed_action_sha256=target.source_observed_action.action_sha256,
                arms=tuple(arms),
            )
        )
    implementation = Path(__file__).resolve(strict=True)
    return TrackAPilotSuiteManifest.create(
        suite_id=f"{spec.spec_id}-{plan.plan_sha256[:16]}",
        project_id=spec.project_id,
        pilot_plan=plan_binding,
        suite_spec=spec_binding,
        accepted_abstraction_set=accepted_binding,
        materializer_implementation_sha256=_sha256_file(implementation),
        provider=spec.provider,
        model=spec.model,
        sampling=spec.sampling,
        context_budget=spec.context_budget,
        study_mode=spec.study_mode,
        reference_quality_status=reference_quality_status,
        reference_quality_qualifications=reference_quality_qualifications,
        cases=tuple(sorted(cases, key=lambda item: item.target_id)),
        case_count=len(cases),
        arm_count=3 * len(cases),
        accepted_abstraction_count=len(accepted_by_input),
        full_target_coverage=len(cases) == 24,
        natural_pilot=spec.study_mode == "natural-ai-pilot",
    )


def _verify_accepted_set(
    *,
    root: Path,
    plan_file: Path,
    plan_inputs: tuple[PilotAbstractionInputRecord, ...],
    accepted_set: AIAcceptedTasteAbstractionSet,
) -> tuple[
    dict[str, _AcceptedAbstraction],
    dict[str, tuple[str, str | None, str]],
    AIAbstractionRequestPack,
]:
    pack_path = _bound_ai_file(root, accepted_set.request_pack)
    pack = load_ai_abstraction_request_pack(pack_path)
    if pack.pack_sha256 != accepted_set.request_pack_sha256:
        raise ValueError("Track-A accepted set binds another review pack")
    _verify_accepted_review_chain(root, accepted_set, pack)
    plan_by_identity = {}
    for record in plan_inputs:
        node_input = _load_plan_input(plan_file.parent, record)
        identity = (node_input.source_id, node_input.candidate_id, node_input.case_id)
        plan_by_identity[identity] = (record, node_input)
    pack_by_review_id = {item.review_item_id: item for item in pack.candidates}
    if len(pack_by_review_id) != len(pack.candidates):
        raise ValueError("Track-A abstraction review pack repeats a review identity")
    pack_identities = {
        (item.source_id, item.candidate_id, item.case_id) for item in pack.candidates
    }
    if not pack_identities.issubset(set(plan_by_identity)):
        raise ValueError("Track-A abstraction review pack contains a foreign pilot input")
    decision_by_review_id = {
        item.review_item_id: item for item in accepted_set.decisions
    }
    if set(decision_by_review_id) != set(pack_by_review_id):
        raise ValueError("Track-A final AI decisions differ from the reviewed candidates")
    coverage_by_input: dict[str, tuple[str, str | None, str]] = {
        item.input_id: (
            "not-present-in-accepted-set",
            None,
            "runtime-or-review-result-not-present",
        )
        for item in plan_inputs
    }
    for review_id, decision in decision_by_review_id.items():
        candidate = pack_by_review_id[review_id]
        record, _ = plan_by_identity[
            (candidate.source_id, candidate.candidate_id, candidate.case_id)
        ]
        if decision.disposition is AIAbstractionFinalDisposition.REJECT:
            coverage_by_input[record.input_id] = (
                "ai-review-rejected",
                review_id,
                "operational-ai-review-rejected",
            )
    accepted_by_input: dict[str, _AcceptedAbstraction] = {}
    for accepted in accepted_set.accepted:
        try:
            candidate = pack_by_review_id[accepted.review_item_id]
        except KeyError as error:
            raise ValueError("Track-A accepted review identity is foreign to its pack") from error
        if (
            (accepted.source_id, accepted.candidate_id, accepted.case_id)
            != (candidate.source_id, candidate.candidate_id, candidate.case_id)
            or accepted.runtime_receipt != candidate.runtime_receipt
            or accepted.runtime_entry_sha256 != candidate.runtime_entry_sha256
            or accepted.abstraction_sha256 != candidate.abstraction_sha256
        ):
            raise ValueError("Track-A accepted abstraction differs from its reviewed candidate")
        identity = (accepted.source_id, accepted.candidate_id, accepted.case_id)
        try:
            record, expected_input = plan_by_identity[identity]
        except KeyError as error:
            raise ValueError("Track-A accepted abstraction is foreign to the pilot") from error
        receipt_path = _bound_ai_file(root, accepted.runtime_receipt)
        receipt = RuntimeInvocationReceipt.model_validate_json(receipt_path.read_bytes())
        if (
            receipt.outcome is not RuntimeOutcome.ACCEPTED
            or receipt.entry_sha256 != accepted.runtime_entry_sha256
            or receipt.result is None
            or receipt.blockers
        ):
            raise ValueError("Track-A accepted abstraction runtime receipt is not accepted")
        result = NodeResult[GroundedTasteCaseAbstraction].model_validate(receipt.result)
        if (
            result.status is not NodeResultStatus.ACCEPTED
            or result.node_name != GROUNDED_TASTE_ABSTRACTION_NODE
            or result.proposal is None
            or result.response.tool_calls
        ):
            raise ValueError("Track-A runtime result is not a clean grounded abstraction")
        request_payload = result.request.input_payload
        if set(request_payload) != {"context", "input"}:
            raise ValueError("Track-A abstraction request input surface drifted")
        observed_input = TasteAbstractionInput.model_validate(request_payload["input"])
        if observed_input != expected_input:
            raise ValueError("Track-A accepted abstraction used different source bytes")
        if validate_grounded_abstraction_against_projection(result.proposal, observed_input):
            raise ValueError("Track-A accepted abstraction failed deterministic grounding")
        visible = AIVisibleGroundedTasteAbstraction.model_validate(
            result.proposal.model_dump(mode="json", exclude={"case_id"})
        )
        if _canonical_sha256(visible.model_dump(mode="json")) != accepted.abstraction_sha256:
            raise ValueError("Track-A accepted abstraction content hash drifted")
        if record.input_id in accepted_by_input:
            raise ValueError("Track-A accepted set repeats a pilot abstraction input")
        accepted_by_input[record.input_id] = _AcceptedAbstraction(
            accepted=accepted,
            node_input=observed_input,
            visible=visible,
        )
        coverage_by_input[record.input_id] = (
            "accepted",
            accepted.review_item_id,
            "operational-ai-review-accepted",
        )
    return accepted_by_input, coverage_by_input, pack


def _verify_accepted_review_chain(
    root: Path,
    accepted_set: AIAcceptedTasteAbstractionSet,
    pack: AIAbstractionRequestPack,
) -> None:
    """Replay the AI-only review bytes behind an operational accepted set."""

    lock_path = _bound_ai_file(root, accepted_set.locked_primary_reviews)
    lock = LockedAIAbstractionPrimaryReviews.model_validate_json(lock_path.read_bytes())
    if (
        lock.review_set_sha256 != accepted_set.locked_primary_review_set_sha256
        or lock.request_pack != accepted_set.request_pack
        or lock.request_pack_sha256 != pack.pack_sha256
    ):
        raise ValueError("Track-A accepted set binds another locked AI review")

    requests: dict[str, tuple[AIAbstractionPrimaryRequest, Path]] = {}
    for binding, request_sha, reviewer_sha in zip(
        pack.primary_requests,
        pack.primary_request_sha256s,
        pack.primary_reviewer_identity_sha256s,
        strict=True,
    ):
        request_path = _bound_ai_file(root, binding)
        request = AIAbstractionPrimaryRequest.model_validate_json(request_path.read_bytes())
        if (
            request.request_sha256 != request_sha
            or request.reviewer.identity_sha256 != reviewer_sha
            or request.protocol_sha256 != pack.protocol_sha256
        ):
            raise ValueError("Track-A AI primary-review request identity drifted")
        requests[request.reviewer.reviewer_id] = (request, request_path)
    if len(requests) != 2:
        raise ValueError("Track-A accepted set lacks two distinct primary AI requests")

    responses: dict[str, tuple[AIAbstractionRawReviewResponse, Path]] = {}
    for binding in lock.raw_responses:
        response_path = _bound_ai_file(root, binding)
        response = AIAbstractionRawReviewResponse.model_validate_json(
            response_path.read_bytes()
        )
        if response.reviewer_id in responses:
            raise ValueError("Track-A locked review repeats a primary AI response")
        responses[response.reviewer_id] = (response, response_path)
    receipts: dict[str, tuple[AIAbstractionReviewExecutionReceipt, Path]] = {}
    for binding in lock.execution_receipts:
        receipt_path = _bound_ai_file(root, binding)
        receipt = AIAbstractionReviewExecutionReceipt.model_validate_json(
            receipt_path.read_bytes()
        )
        if receipt.reviewer_id in receipts:
            raise ValueError("Track-A locked review repeats a primary AI receipt")
        receipts[receipt.reviewer_id] = (receipt, receipt_path)
    if set(responses) != set(requests) or set(receipts) != set(requests):
        raise ValueError("Track-A primary AI review identities do not close")

    row_by_identity = {
        (item.review_item_id, item.reviewer_id): item for item in lock.normalized_rows
    }
    expected_items = {item.review_item_id for item in pack.candidates}
    if len(row_by_identity) != 2 * len(expected_items):
        raise ValueError("Track-A locked AI review row coverage drifted")
    for reviewer_id, (request, request_path) in requests.items():
        response, response_path = responses[reviewer_id]
        receipt, receipt_path = receipts[reviewer_id]
        if (
            response.request_sha256 != request.request_sha256
            or response.reviewer_identity_sha256 != request.reviewer.identity_sha256
            or receipt.request_sha256 != request.request_sha256
            or receipt.reviewer_identity_sha256 != request.reviewer.identity_sha256
            or (receipt.provider, receipt.model, receipt.model_revision)
            != (
                request.reviewer.provider,
                request.reviewer.model,
                request.reviewer.model_revision,
            )
            or _bound_ai_file(root, receipt.request) != request_path
            or _bound_ai_file(root, receipt.raw_response) != response_path
        ):
            raise ValueError("Track-A AI response or receipt identity drifted")
        response_by_item = {item.review_item_id: item for item in response.responses}
        if set(response_by_item) != expected_items:
            raise ValueError("Track-A primary AI response coverage drifted")
        for review_item_id, raw in response_by_item.items():
            try:
                row = row_by_identity[(review_item_id, reviewer_id)]
            except KeyError as error:
                raise ValueError("Track-A primary AI response lacks a locked row") from error
            if (
                row.reviewer_identity_sha256 != request.reviewer.identity_sha256
                or row.request_sha256 != request.request_sha256
                or row.raw_response_file_sha256 != _sha256_file(response_path)
                or row.execution_receipt_file_sha256 != _sha256_file(receipt_path)
                or row.assessment != raw.assessment
                or row.disposition is not raw.disposition
                or row.issue_codes != raw.issue_codes
                or row.rationale != raw.rationale
            ):
                raise ValueError("Track-A normalized primary AI review row drifted")

    adjudication_by_item: dict[str, AIAbstractionRawReviewItem] = {}
    adjudication_request: AIAbstractionAdjudicationRequest | None = None
    adjudication_response_binding = accepted_set.adjudication_response
    adjudication_receipt_binding = accepted_set.adjudication_execution_receipt
    dispute_ids = {item.review_item_id for item in lock.disputes}
    if dispute_ids:
        if (
            lock.adjudication_request is None
            or adjudication_response_binding is None
            or adjudication_receipt_binding is None
        ):
            raise ValueError("Track-A disputed AI review lacks adjudication evidence")
        adjudication_request_path = _bound_ai_file(root, lock.adjudication_request)
        adjudication_request = AIAbstractionAdjudicationRequest.model_validate_json(
            adjudication_request_path.read_bytes()
        )
        response_path = _bound_ai_file(root, adjudication_response_binding)
        response = AIAbstractionAdjudicationResponse.model_validate_json(
            response_path.read_bytes()
        )
        receipt_path = _bound_ai_file(root, adjudication_receipt_binding)
        receipt = AIAbstractionReviewExecutionReceipt.model_validate_json(
            receipt_path.read_bytes()
        )
        if (
            adjudication_request.request_sha256 != lock.adjudication_request_sha256
            or adjudication_request.locked_primary_review_set_sha256
            != lock.primary_review_sha256
            or response.request_sha256 != adjudication_request.request_sha256
            or response.reviewer_identity_sha256
            != adjudication_request.adjudicator.identity_sha256
            or receipt.request_sha256 != adjudication_request.request_sha256
            or receipt.reviewer_identity_sha256
            != adjudication_request.adjudicator.identity_sha256
            or _bound_ai_file(root, receipt.request) != adjudication_request_path
            or _bound_ai_file(root, receipt.raw_response) != response_path
        ):
            raise ValueError("Track-A AI adjudication identity drifted")
        adjudication_by_item = {
            item.review_item_id: item for item in response.responses
        }
        if set(adjudication_by_item) != dispute_ids:
            raise ValueError("Track-A AI adjudication does not close every dispute")
    elif (
        lock.adjudication_request is not None
        or adjudication_response_binding is not None
        or adjudication_receipt_binding is not None
    ):
        raise ValueError("Track-A accepted set carries adjudication without a dispute")

    decision_by_item = {
        item.review_item_id: item for item in accepted_set.decisions
    }
    if set(decision_by_item) != expected_items:
        raise ValueError("Track-A final AI decisions differ from the locked candidate set")
    for review_item_id, decision in decision_by_item.items():
        rows = sorted(
            (
                item
                for item in lock.normalized_rows
                if item.review_item_id == review_item_id
            ),
            key=lambda item: item.reviewer_id,
        )
        if review_item_id in dispute_ids:
            assert adjudication_request is not None
            raw = adjudication_by_item[review_item_id]
            expected_disposition = AIAbstractionFinalDisposition(raw.disposition.value)
            expected_hashes = (
                _canonical_sha256(
                    {
                        "review_item_id": raw.review_item_id,
                        "reviewer_identity_sha256": (
                            adjudication_request.adjudicator.identity_sha256
                        ),
                        "request_sha256": lock.adjudication_request_sha256,
                        "raw_response_file_sha256": adjudication_response_binding.sha256,
                        "execution_receipt_file_sha256": (
                            adjudication_receipt_binding.sha256
                        ),
                        "assessment": raw.assessment.model_dump(mode="json"),
                        "disposition": raw.disposition.value,
                        "issue_codes": raw.issue_codes,
                        "rationale": raw.rationale,
                    }
                ),
            )
            expected_resolution = "ai-adjudicated"
        else:
            if (
                len(rows) != 2
                or rows[0].disposition is not rows[1].disposition
                or rows[0].disposition is AIAbstractionReviewDisposition.NEEDS_DISPUTE
            ):
                raise ValueError("Track-A non-disputed primary AI reviews do not agree")
            expected_disposition = AIAbstractionFinalDisposition(
                rows[0].disposition.value
            )
            expected_hashes = tuple(item.row_sha256 for item in rows)
            expected_resolution = "primary-agreement"
        if (
            decision.disposition is not expected_disposition
            or decision.resolution != expected_resolution
            or decision.deciding_row_sha256s != expected_hashes
        ):
            raise ValueError("Track-A final AI decision differs from its review evidence")


def _target_coverage(
    *,
    plan_file: Path,
    plan: object,
    coverage_by_input: dict[str, tuple[str, str | None, str]],
) -> tuple[TrackATargetCoverage, ...]:
    input_id_by_locator = {
        item.input_file.locator: item.input_id for item in plan.abstraction_inputs
    }
    rows: list[TrackATargetCoverage] = []
    for record in plan.targets:
        target_path = plan_file.parent.joinpath(
            *PurePosixPath(record.target_file.locator).parts
        )
        if _sha256_file(target_path) != record.target_file.file_sha256:
            raise ValueError("Track-A target bytes differ from the pilot plan")
        target = TasteMechanismPilotTarget.model_validate_json(target_path.read_bytes())
        matched_id = input_id_by_locator[
            target.abstracted_matched_taste.reference.abstraction_input.locator
        ]
        mismatched_id = input_id_by_locator[
            target.abstracted_mismatched_taste.reference.abstraction_input.locator
        ]
        matched_status = coverage_by_input[matched_id][0]
        mismatched_status = coverage_by_input[mismatched_id][0]
        blockers = []
        if matched_status != "accepted":
            blockers.append(f"matched-precedent-{matched_status}")
        if mismatched_status != "accepted":
            blockers.append(f"mismatched-precedent-{mismatched_status}")
        rows.append(
            TrackATargetCoverage(
                target_id=target.target_id,
                matched_input_id=matched_id,
                matched_status=matched_status,
                mismatched_input_id=mismatched_id,
                mismatched_status=mismatched_status,
                runnable=not blockers,
                blocker_codes=tuple(sorted(blockers)),
            )
        )
    return tuple(sorted(rows, key=lambda item: item.target_id))


def _reference_quality_status(
    *,
    root: Path,
    plan_file: Path,
    plan_inputs: tuple[PilotAbstractionInputRecord, ...],
    spec: TrackAPilotSuiteSpec,
    paths: Sequence[str | Path],
) -> tuple[
    tuple[TrackASuiteSemanticBinding, ...],
    Literal[
        "natural-pilot-explicit-override",
        "all-precedents-qualified",
        "formal-qualification-incomplete",
    ],
]:
    if spec.study_mode == "natural-ai-pilot":
        if paths:
            raise ValueError(
                "natural Track-A pilot uses its explicit quality override; "
                "formal qualification files belong to a new formal-candidate suite"
            )
        return (), "natural-pilot-explicit-override"

    expected: dict[tuple[str, str], str] = {}
    for record in plan_inputs:
        node_input = _load_plan_input(plan_file.parent, record)
        expected[(node_input.source_id, node_input.source_projection_sha256)] = (
            record.input_id
        )
    qualified_by_input: dict[str, TrackASuiteSemanticBinding] = {}
    for value in paths:
        source = _regular_file(root, value)
        payload = json.loads(source.read_bytes())
        if not isinstance(payload, dict):
            raise ValueError("Track-A reference-quality qualification must be a mapping")
        recorded_hash = payload.pop("report_sha256", None)
        report = ReferenceQualityQualification.model_validate(payload)
        if recorded_hash != report.report_sha256:
            raise ValueError("Track-A reference-quality report hash mismatch")
        identity = (report.source_id, report.source_projection_sha256)
        if identity not in expected:
            raise ValueError("Track-A reference-quality report is foreign to the pilot")
        ledger = _regular_file(root, report.ledger_locator)
        if _sha256_file(ledger) != report.ledger_sha256:
            raise ValueError("Track-A reference-quality report ledger binding drifted")
        if (
            report.verdict is not ReferenceQualityVerdict.QUALIFY
            or not report.qualified_for_human_review
        ):
            continue
        input_id = expected[identity]
        if input_id in qualified_by_input:
            raise ValueError("Track-A reference-quality input was qualified twice")
        qualified_by_input[input_id] = TrackASuiteSemanticBinding(
            locator=_relative(source, root),
            file_sha256=_sha256_file(source),
            semantic_sha256=report.report_sha256,
        )
    bindings = tuple(qualified_by_input[key] for key in sorted(qualified_by_input))
    status = (
        "all-precedents-qualified"
        if len(qualified_by_input) == len(plan_inputs)
        else "formal-qualification-incomplete"
    )
    return bindings, status


def _load_accepted_set(path: Path) -> AIAcceptedTasteAbstractionSet:
    payload = json.loads(path.read_bytes())
    recorded = payload.pop("accepted_set_sha256", None)
    accepted = AIAcceptedTasteAbstractionSet.model_validate(payload)
    if recorded is not None and recorded != accepted.accepted_set_sha256:
        raise ValueError("Track-A accepted-set semantic hash mismatch")
    return accepted


def _ordered_actions(
    spec: TrackAPilotSuiteSpec, target: TasteMechanismPilotTarget
) -> tuple[TrackACandidateAction, TrackACandidateAction]:
    observed = target.source_observed_action
    distractor = target.distractor_action
    observed_first = int(
        _canonical_sha256([spec.spec_sha256, target.target_id, "action-order"]), 16
    ) % 2 == 0
    ordered = (observed, distractor) if observed_first else (distractor, observed)
    return tuple(
        TrackACandidateAction(
            action_id="option-a" if index == 0 else "option-b",
            text=action.action_text,
            text_sha256=action.action_sha256,
        )
        for index, action in enumerate(ordered)
    )


def _load_plan_input(
    plan_root: Path, record: PilotAbstractionInputRecord
) -> TasteAbstractionInput:
    path = plan_root.joinpath(*PurePosixPath(record.input_file.locator).parts)
    if path.is_symlink() or not path.is_file() or _sha256_file(path) != (
        record.input_file.file_sha256
    ):
        raise ValueError("Track-A planned abstraction input binding drifted")
    value = TasteAbstractionInput.model_validate_json(path.read_bytes())
    if (
        value.source_projection_sha256 != record.source_projection_sha256
        or value.domain_tags != (record.source_domain,)
    ):
        raise ValueError("Track-A planned abstraction input identity drifted")
    return value


def _bound_ai_file(
    root: Path,
    binding: AIAbstractionFileBinding | TrackASuiteFileBinding,
) -> Path:
    """Resolve both AI ``path/sha256`` and legacy suite ``locator/file_sha256``."""

    if isinstance(binding, AIAbstractionFileBinding):
        locator = binding.path
        expected_sha256 = binding.sha256
    else:
        locator = binding.locator
        expected_sha256 = binding.file_sha256
    source = _regular_file(root, locator)
    if _sha256_file(source) != expected_sha256:
        raise ValueError("Track-A AI-review artifact hash drifted")
    return source


def _bound_file(root: Path, binding: TrackASuiteFileBinding) -> Path:
    source = _regular_file(root, binding.locator)
    if _sha256_file(source) != binding.file_sha256:
        raise ValueError("Track-A suite artifact hash drifted")
    return source


def _candidate_path(root: Path, value: str | Path) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root.joinpath(*PurePosixPath(candidate.as_posix()).parts)
    try:
        candidate.resolve(strict=False).relative_to(root)
    except ValueError as error:
        raise ValueError("Track-A suite path escapes the evidence root") from error
    return candidate.resolve(strict=False)


def _regular_file(root: Path, value: str | Path) -> Path:
    source = _candidate_path(root, value)
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"Track-A suite requires a regular non-symlink file: {source}")
    if source.stat().st_size > _MAX_CONTROL_BYTES:
        raise ValueError("Track-A suite input exceeds its byte ceiling")
    return source.resolve(strict=True)


def _new_path(root: Path, value: str | Path) -> Path:
    target = _candidate_path(root, value)
    return target


def _safe_locator(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        "\\" in value
        or path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("Track-A suite locator must be normalized and relative")
    return path


def _relative(path: Path, root: Path) -> str:
    return path.resolve(strict=True).relative_to(root).as_posix()


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


def _write_new_json(path: Path, value: object) -> None:
    payload = _canonical_json(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


__all__ = [
    "TrackAArmExecutionConfig",
    "TrackAPilotSuiteInspection",
    "TrackAPilotSuiteManifest",
    "TrackAPilotSuitePreparation",
    "TrackAPilotSuiteSpec",
    "inspect_track_a_pilot_suite",
    "load_track_a_pilot_suite_spec",
    "materialize_track_a_pilot_suite",
]
