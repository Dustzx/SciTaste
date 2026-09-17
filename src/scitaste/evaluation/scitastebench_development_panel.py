"""Disagreement-only third-model panel for SciTasteBench development screening."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import Counter
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from scitaste.benchmark.models import BenchmarkDecisionContextFamily
from scitaste.evaluation.scitastebench_development_screening import (
    CaseabilityExclusion,
    CaseabilityLevel,
    DevelopmentCaseabilityDecision,
    DevelopmentNormalizedDecision,
    DevelopmentScreenCandidate,
    ScreenFileBinding,
)
from scitaste.model_nodes.models import StructuredModelRequest
from scitaste.model_nodes.openai_compatible import (
    StructuredOpenAICompatibleBackend,
    load_structured_openai_compatible_config,
)
from scitaste.model_nodes.profiles import ModelNodeProfile, load_model_node_profile
from scitaste.project.models import content_sha256, validate_project_id
from scitaste.taste.decision_families import ScientificTasteDecisionFamily

_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_FILE_BYTES = 64 * 1024 * 1024
_NODE_NAME = "scitastebench-caseability-adjudication"


class DevelopmentPanelPrimary(BaseModel):
    model_config = _CONFIG

    role: Literal["primary-a", "primary-b"]
    plan: ScreenFileBinding
    normalization: ScreenFileBinding
    decisions: ScreenFileBinding


class DevelopmentPanelConfig(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    panel_id: str = Field(pattern=_ID)
    project_id: str
    screening_items: ScreenFileBinding
    primary_a: DevelopmentPanelPrimary
    primary_b: DevelopmentPanelPrimary
    profile: ScreenFileBinding
    backend_config: ScreenFileBinding
    batch_size: int = Field(default=8, ge=1, le=12)
    seed: int = Field(default=6027, ge=0)
    disagreement_only: Literal[True] = True
    automatic_retry_permitted: Literal[False] = False
    target_outcomes_visible: Literal[False] = False
    formal_split_access_authorized: Literal[False] = False

    @model_validator(mode="after")
    def config_is_closed(self) -> DevelopmentPanelConfig:
        validate_project_id(self.project_id)
        if self.primary_a.role != "primary-a" or self.primary_b.role != "primary-b":
            raise ValueError("development panel primary roles differ")
        return self


class AdjudicationResolution(StrEnum):
    PRIMARY_A = "primary-a"
    PRIMARY_B = "primary-b"
    NEW_RESOLUTION = "new-resolution"
    NEITHER_INELIGIBLE = "neither-ineligible"


class DevelopmentAdjudicationDecision(BaseModel):
    model_config = _CONFIG

    position: int = Field(gt=0, le=12)
    eligible: bool
    decision_context_family: BenchmarkDecisionContextFamily | None = None
    taste_judgment_family: ScientificTasteDecisionFamily | None = None
    atomic_decision_question: str | None = Field(default=None, max_length=500)
    ambiguity: CaseabilityLevel | None = None
    decision_leverage: CaseabilityLevel | None = None
    memorization_risk: CaseabilityLevel | None = None
    exclusion_codes: tuple[CaseabilityExclusion, ...] = ()
    resolution: AdjudicationResolution
    rationale: str = Field(min_length=1, max_length=700)

    @model_validator(mode="after")
    def decision_is_atomic(self) -> DevelopmentAdjudicationDecision:
        fields = (
            self.decision_context_family,
            self.taste_judgment_family,
            self.atomic_decision_question,
            self.ambiguity,
            self.decision_leverage,
            self.memorization_risk,
        )
        if self.eligible:
            if any(item is None for item in fields) or self.exclusion_codes:
                raise ValueError("eligible adjudication decision is incomplete")
            if self.resolution is AdjudicationResolution.NEITHER_INELIGIBLE:
                raise ValueError("eligible adjudication cannot resolve to neither")
        else:
            if any(item is not None for item in fields) or not self.exclusion_codes:
                raise ValueError("ineligible adjudication decision is inconsistent")
            if self.resolution is not AdjudicationResolution.NEITHER_INELIGIBLE:
                raise ValueError("ineligible adjudication must resolve to neither")
        return self


class DevelopmentAdjudicationBatchOutput(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    batch_id: str = Field(pattern=_ID)
    decisions: tuple[DevelopmentAdjudicationDecision, ...] = Field(min_length=1, max_length=12)
    target_outcomes_used: Literal[False] = False
    benchmark_admission_claimed: Literal[False] = False


class DevelopmentPanelBatchPlan(BaseModel):
    model_config = _CONFIG

    ordinal: int = Field(gt=0)
    batch_id: str = Field(pattern=_ID)
    candidate_ids: tuple[str, ...] = Field(min_length=1, max_length=12)
    request: ScreenFileBinding
    request_fingerprint: str = Field(pattern=_SHA256)


class DevelopmentPanelPlan(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    panel_id: str = Field(pattern=_ID)
    project_id: str
    prepared_at: datetime
    config: ScreenFileBinding
    primary_a_provider: str
    primary_a_model: str
    primary_b_provider: str
    primary_b_model: str
    adjudicator_provider: str
    adjudicator_model: str
    agreed_eligible_count: int = Field(ge=0)
    agreed_ineligible_count: int = Field(ge=0)
    disputed_count: int = Field(gt=0)
    batches: tuple[DevelopmentPanelBatchPlan, ...] = Field(min_length=1)
    profile: ScreenFileBinding
    profile_fingerprint: str = Field(pattern=_SHA256)
    backend_config: ScreenFileBinding
    disagreement_only: Literal[True] = True
    outcome_fields_exposed: Literal[False] = False
    automatic_retry_permitted: Literal[False] = False
    model_calls_performed: Literal[False] = False

    @computed_field
    @property
    def plan_sha256(self) -> str:
        return content_sha256(self.model_dump(mode="json", exclude={"plan_sha256"}))

    @model_validator(mode="after")
    def plan_is_consistent(self) -> DevelopmentPanelPlan:
        validate_project_id(self.project_id)
        if self.prepared_at.utcoffset() is None:
            raise ValueError("development panel time must be timezone-aware")
        if tuple(item.ordinal for item in self.batches) != tuple(range(1, len(self.batches) + 1)):
            raise ValueError("development panel batch ordinals must be contiguous")
        candidate_ids = [value for item in self.batches for value in item.candidate_ids]
        if len(candidate_ids) != self.disputed_count or len(candidate_ids) != len(
            set(candidate_ids)
        ):
            raise ValueError("development panel disputed population differs")
        identities = {
            (self.primary_a_provider, self.primary_a_model),
            (self.primary_b_provider, self.primary_b_model),
            (self.adjudicator_provider, self.adjudicator_model),
        }
        if len(identities) != 3:
            raise ValueError("development panel model identities must be distinct")
        return self


class DevelopmentPanelReceipt(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    panel_id: str = Field(pattern=_ID)
    plan_sha256: str = Field(pattern=_SHA256)
    batch_id: str = Field(pattern=_ID)
    completed_at: datetime
    outcome: Literal["accepted", "rejected", "failed"]
    request_fingerprint: str = Field(pattern=_SHA256)
    response: ScreenFileBinding | None = None
    raw_response: ScreenFileBinding | None = None
    provider: str | None = None
    model: str | None = None
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cost_usd: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    latency_ms: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    failure_code: str | None = None
    failure_detail: str | None = Field(default=None, max_length=1_000)
    retry_permitted: Literal[False] = False

    @model_validator(mode="after")
    def receipt_is_consistent(self) -> DevelopmentPanelReceipt:
        if self.completed_at.utcoffset() is None:
            raise ValueError("development panel completion time must be timezone-aware")
        if self.outcome == "accepted":
            if (
                self.response is None
                or self.raw_response is None
                or self.provider is None
                or self.model is None
                or self.failure_code is not None
            ):
                raise ValueError("accepted development panel receipt is incomplete")
        elif self.outcome == "rejected":
            if (
                self.raw_response is None
                or self.provider is None
                or self.model is None
                or self.failure_code is None
            ):
                raise ValueError("rejected development panel receipt is incomplete")
        elif self.failure_code is None:
            raise ValueError("failed development panel receipt lacks a failure code")
        return self


class PanelDecisionDisposition(StrEnum):
    PRIMARY_AGREEMENT = "primary-agreement"
    PRIMARY_INELIGIBLE = "primary-ineligible"
    ADJUDICATED = "adjudicated"


class DevelopmentPanelDecisionRecord(BaseModel):
    model_config = _CONFIG

    intake_candidate_id: str = Field(pattern=_ID)
    source_group_id: str = Field(pattern=_ID)
    domain: str = Field(pattern=_ID)
    disposition: PanelDecisionDisposition
    primary_a: DevelopmentCaseabilityDecision
    primary_b: DevelopmentCaseabilityDecision
    adjudicator: DevelopmentAdjudicationDecision | None = None
    final_decision: DevelopmentCaseabilityDecision | None = None

    @model_validator(mode="after")
    def record_is_consistent(self) -> DevelopmentPanelDecisionRecord:
        if self.disposition is PanelDecisionDisposition.PRIMARY_INELIGIBLE:
            if self.final_decision is not None or self.adjudicator is not None:
                raise ValueError("jointly ineligible panel record cannot have a resolution")
        elif self.disposition is PanelDecisionDisposition.PRIMARY_AGREEMENT:
            if self.final_decision is None or self.adjudicator is not None:
                raise ValueError("primary agreement panel record is inconsistent")
        elif self.adjudicator is None or self.final_decision is None:
            raise ValueError("adjudicated panel record requires the ruling and final decision")
        return self


class DevelopmentPanelSummary(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    panel_id: str = Field(pattern=_ID)
    plan_sha256: str = Field(pattern=_SHA256)
    finalized_at: datetime
    batch_count: int = Field(gt=0)
    accepted_batch_count: int = Field(ge=0)
    rejected_batch_count: int = Field(ge=0)
    failed_batch_count: int = Field(ge=0)
    final_eligible_count: int = Field(ge=0)
    context_family_counts: dict[str, int]
    judgment_family_counts: dict[str, int]
    domain_counts: dict[str, int]
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_usd: float = Field(ge=0, allow_inf_nan=False)
    decisions: ScreenFileBinding | None = None
    complete: bool
    ready_for_allocation: bool
    target_outcomes_used: Literal[False] = False
    formal_split_opened: Literal[False] = False


class DevelopmentNormalizedAdjudication(BaseModel):
    model_config = _CONFIG

    batch_id: str = Field(pattern=_ID)
    position: int = Field(gt=0, le=12)
    original_receipt_outcome: Literal["accepted", "rejected"]
    provider_resolution: AdjudicationResolution
    canonical_resolution: AdjudicationResolution
    semantic_echo_correction_count: int = Field(ge=0)
    ineligible_field_nullification_count: int = Field(ge=0)
    envelope_field_removal_count: int = Field(ge=0)
    rationale_truncated: bool
    decision: DevelopmentAdjudicationDecision


class DevelopmentPanelNormalizationManifest(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    panel_id: str = Field(pattern=_ID)
    plan_sha256: str = Field(pattern=_SHA256)
    normalized_at: datetime
    source_batch_count: int = Field(gt=0)
    source_accepted_batch_count: int = Field(ge=0)
    source_rejected_batch_count: int = Field(ge=0)
    source_input_tokens: int = Field(ge=0)
    source_output_tokens: int = Field(ge=0)
    source_cost_usd: float = Field(ge=0, allow_inf_nan=False)
    normalized_adjudication_count: int = Field(gt=0)
    final_eligible_count: int = Field(ge=0)
    semantic_echo_correction_count: int = Field(ge=0)
    ineligible_field_nullification_count: int = Field(ge=0)
    envelope_field_removal_count: int = Field(ge=0)
    rationale_truncation_count: int = Field(ge=0)
    adjudicator_choice_change_count: Literal[0] = 0
    context_family_counts: dict[str, int]
    judgment_family_counts: dict[str, int]
    domain_counts: dict[str, int]
    adjudications: ScreenFileBinding
    decisions: ScreenFileBinding
    all_batches_normalized: bool
    ready_for_allocation: bool
    model_calls_performed: Literal[False] = False
    target_outcomes_used: Literal[False] = False
    formal_split_opened: Literal[False] = False
    manifest_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def normalization_is_consistent(self) -> DevelopmentPanelNormalizationManifest:
        if self.normalized_at.utcoffset() is None:
            raise ValueError("development panel normalization time must be timezone-aware")
        expected = content_sha256(self.model_dump(mode="json", exclude={"manifest_sha256"}))
        if self.manifest_sha256 != expected:
            raise ValueError("development panel normalization hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> DevelopmentPanelNormalizationManifest:
        payload = {"schema_version": "1.0", **values}
        payload.pop("manifest_sha256", None)
        unsigned = cls.model_construct(manifest_sha256="0" * 64, **payload)
        return cls(
            **payload,
            manifest_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"manifest_sha256"})
            ),
        )


def prepare_scitastebench_development_panel(
    *,
    config_path: str | Path,
    locator_root: str | Path,
    output_dir: str | Path,
    prepared_at: datetime | None = None,
) -> DevelopmentPanelPlan:
    """Freeze disagreement-only adjudication requests without model calls."""

    root = Path(locator_root).resolve(strict=True)
    config_path = _within(root, config_path)
    config = DevelopmentPanelConfig.model_validate(yaml.safe_load(_bounded_bytes(config_path)))
    visible_items = _load_visible_items(_require_binding(root, config.screening_items))
    primary_a, identity_a = _load_primary(root, config.primary_a)
    primary_b, identity_b = _load_primary(root, config.primary_b)
    if set(primary_a) != set(primary_b) or set(primary_a) != set(visible_items):
        raise ValueError("development panel primary and visible populations differ")
    agreed_eligible: list[str] = []
    agreed_ineligible: list[str] = []
    disputed: list[str] = []
    for candidate_id in sorted(primary_a):
        left = primary_a[candidate_id]
        right = primary_b[candidate_id]
        if not left.eligible and not right.eligible:
            agreed_ineligible.append(candidate_id)
        elif (
            left.eligible
            and right.eligible
            and left.decision_context_family == right.decision_context_family
            and left.taste_judgment_family == right.taste_judgment_family
        ):
            agreed_eligible.append(candidate_id)
        else:
            disputed.append(candidate_id)
    profile = load_model_node_profile(_require_binding(root, config.profile))
    if _NODE_NAME not in profile.allowed_node_names or not profile.live_execution_permitted:
        raise ValueError("development panel profile does not permit adjudication")
    backend = load_structured_openai_compatible_config(
        _require_binding(root, config.backend_config)
    )
    if not backend.live_enabled or backend.max_retries != 0:
        raise ValueError("development panel backend must be live with zero retries")
    if not backend.pricing_confirmed or backend.pricing is None:
        raise ValueError("development panel backend lacks pricing provenance")
    if (profile.provider, profile.model) != (backend.provider, backend.model):
        raise ValueError("development panel profile and backend identities differ")
    if (profile.provider, profile.model) in {identity_a, identity_b} or identity_a == identity_b:
        raise ValueError("development panel identities are not independent")
    ranked = sorted(
        disputed,
        key=lambda value: hashlib.sha256(f"{config.panel_id}:{value}".encode()).hexdigest(),
    )
    chunks = [
        ranked[index : index + config.batch_size]
        for index in range(0, len(ranked), config.batch_size)
    ]
    if len(chunks) > profile.cumulative_project.max_invocations:
        raise ValueError("development panel exceeds the adjudicator invocation ceiling")

    target = Path(output_dir)
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"development panel output already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    try:
        requests = temporary / "requests"
        requests.mkdir()
        batch_plans: list[DevelopmentPanelBatchPlan] = []
        policy_sha = content_sha256(
            {
                "panel_id": config.panel_id,
                "profile": profile.fingerprint,
                "prompt": "scitastebench-caseability-adjudication-v1",
            }
        )
        for ordinal, candidate_ids in enumerate(chunks, 1):
            batch_id = f"{config.panel_id}-batch-{ordinal:02d}"
            request = _adjudication_request(
                batch_id=batch_id,
                candidate_ids=candidate_ids,
                visible_items=visible_items,
                primary_a=primary_a,
                primary_b=primary_b,
                identity_a=identity_a,
                identity_b=identity_b,
                profile=profile,
                policy_sha=policy_sha,
                seed=config.seed + ordinal - 1,
            )
            relative = Path("requests") / f"{ordinal:02d}.json"
            request_path = temporary / relative
            _write_json(request_path, request.model_dump(mode="json", exclude_computed_fields=True))
            batch_plans.append(
                DevelopmentPanelBatchPlan(
                    ordinal=ordinal,
                    batch_id=batch_id,
                    candidate_ids=tuple(candidate_ids),
                    request=ScreenFileBinding(
                        locator=relative.as_posix(), sha256=_sha256_file(request_path)
                    ),
                    request_fingerprint=request.fingerprint,
                )
            )
        plan = DevelopmentPanelPlan(
            panel_id=config.panel_id,
            project_id=config.project_id,
            prepared_at=prepared_at or datetime.now(UTC),
            config=_binding(config_path, root),
            primary_a_provider=identity_a[0],
            primary_a_model=identity_a[1],
            primary_b_provider=identity_b[0],
            primary_b_model=identity_b[1],
            adjudicator_provider=profile.provider,
            adjudicator_model=profile.model,
            agreed_eligible_count=len(agreed_eligible),
            agreed_ineligible_count=len(agreed_ineligible),
            disputed_count=len(disputed),
            batches=tuple(batch_plans),
            profile=config.profile,
            profile_fingerprint=profile.fingerprint,
            backend_config=config.backend_config,
        )
        _write_json(temporary / "PLAN.json", plan.model_dump(mode="json"))
        os.replace(temporary, target)
    except BaseException:
        _cleanup(temporary)
        raise
    return plan


def execute_scitastebench_development_panel(
    *,
    panel_dir: str | Path,
    locator_root: str | Path,
    allow_live: bool,
) -> DevelopmentPanelSummary:
    """Execute every frozen adjudication batch at most once and finalize labels."""

    if not allow_live:
        raise ValueError("development adjudication requires explicit --allow-live")
    root = Path(locator_root).resolve(strict=True)
    directory = _within(root, panel_dir)
    plan = _load_plan(directory / "PLAN.json")
    config = DevelopmentPanelConfig.model_validate(
        yaml.safe_load(_bounded_bytes(_require_binding(root, plan.config)))
    )
    profile = load_model_node_profile(_require_binding(root, plan.profile))
    backend_config = load_structured_openai_compatible_config(
        _require_binding(root, plan.backend_config)
    )
    backend = StructuredOpenAICompatibleBackend(backend_config)
    receipts = directory / "receipts"
    responses = directory / "responses"
    attempts = directory / "attempts"
    receipts.mkdir(exist_ok=True)
    responses.mkdir(exist_ok=True)
    attempts.mkdir(exist_ok=True)
    for batch in plan.batches:
        receipt_path = receipts / f"{batch.ordinal:02d}.json"
        if receipt_path.exists():
            _load_receipt(receipt_path, plan=plan, batch=batch)
            continue
        request_path = directory / PurePosixPath(batch.request.locator)
        request = StructuredModelRequest.model_validate_json(_bounded_bytes(request_path))
        if _sha256_file(request_path) != batch.request.sha256 or (
            request.fingerprint != batch.request_fingerprint
        ):
            raise ValueError("development panel request drifted")
        attempt = attempts / f"{batch.ordinal:02d}.json"
        if attempt.exists():
            receipt = _failed_receipt(plan, batch, "ambiguous-prior-attempt")
            _write_json(receipt_path, receipt.model_dump(mode="json"))
            break
        _write_json(
            attempt,
            {
                "panel_id": plan.panel_id,
                "plan_sha256": plan.plan_sha256,
                "batch_id": batch.batch_id,
                "request_fingerprint": batch.request_fingerprint,
                "started_at": datetime.now(UTC).isoformat(),
                "retry_permitted": False,
            },
        )
        try:
            response = backend.complete(request)
        except Exception as exc:
            receipt = _failed_receipt(
                plan,
                batch,
                "provider-or-transport-failure",
                detail=f"{type(exc).__name__}: {exc}"[:1_000],
            )
            _write_json(receipt_path, receipt.model_dump(mode="json"))
            break
        raw_path = responses / f"{batch.ordinal:02d}-provider.json"
        _atomic_write(raw_path, response.raw_response or "")
        package_path = responses / f"{batch.ordinal:02d}-adjudication.json"
        try:
            if response.backend != plan.adjudicator_provider or (
                response.model != plan.adjudicator_model
            ):
                raise ValueError("adjudicator response identity differs")
            if response.tool_calls:
                raise ValueError("adjudicator tool calls are forbidden")
            output = DevelopmentAdjudicationBatchOutput.model_validate(response.output_payload)
            _validate_output(output, batch=batch, request=request)
            _validate_telemetry(response, profile=profile)
            _atomic_write(package_path, output.model_dump_json(indent=2) + "\n")
            receipt = DevelopmentPanelReceipt(
                panel_id=plan.panel_id,
                plan_sha256=plan.plan_sha256,
                batch_id=batch.batch_id,
                completed_at=datetime.now(UTC),
                outcome="accepted",
                request_fingerprint=batch.request_fingerprint,
                response=_binding(package_path, directory),
                raw_response=_binding(raw_path, directory),
                provider=response.backend,
                model=response.model,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                cost_usd=response.usage.cost_usd,
                latency_ms=response.latency_ms,
            )
        except Exception as exc:
            receipt = DevelopmentPanelReceipt(
                panel_id=plan.panel_id,
                plan_sha256=plan.plan_sha256,
                batch_id=batch.batch_id,
                completed_at=datetime.now(UTC),
                outcome="rejected",
                request_fingerprint=batch.request_fingerprint,
                raw_response=_binding(raw_path, directory),
                provider=response.backend,
                model=response.model,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                cost_usd=response.usage.cost_usd,
                latency_ms=response.latency_ms,
                failure_code="invalid-adjudication-response",
                failure_detail=f"{type(exc).__name__}: {exc}"[:1_000],
            )
        _write_json(receipt_path, receipt.model_dump(mode="json"))
        _validate_budget(_receipt_list(directory, plan=plan), profile=profile)
    summary = _finalize(directory, root=root, plan=plan, config=config)
    _validate_budget(_receipt_list(directory, plan=plan), profile=profile)
    _write_json(directory / "SUMMARY.json", summary.model_dump(mode="json"))
    return summary


def normalize_scitastebench_development_panel(
    *,
    panel_dir: str | Path,
    locator_root: str | Path,
    normalized_at: datetime | None = None,
) -> DevelopmentPanelNormalizationManifest:
    """Project declared adjudication choices onto frozen primary semantics.

    The provider's resolution is authoritative.  When it selects a primary,
    repeated semantic fields are redundant and are deterministically replaced
    by the selected frozen primary record.  No model call or outcome lookup is
    performed.
    """

    root = Path(locator_root).resolve(strict=True)
    directory = _within(root, panel_dir)
    plan = _load_plan(directory / "PLAN.json")
    config = DevelopmentPanelConfig.model_validate(
        yaml.safe_load(_bounded_bytes(_require_binding(root, plan.config)))
    )
    visible = _load_visible_items(_require_binding(root, config.screening_items))
    primary_a, _ = _load_primary(root, config.primary_a)
    primary_b, _ = _load_primary(root, config.primary_b)
    target = directory / "normalization"
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"development panel normalization already exists: {target}")
    temporary = Path(tempfile.mkdtemp(prefix=".normalization.", dir=directory))
    try:
        normalized: list[DevelopmentNormalizedAdjudication] = []
        by_candidate: dict[str, DevelopmentAdjudicationDecision] = {}
        receipts: list[DevelopmentPanelReceipt] = []
        for batch in plan.batches:
            receipt = _load_receipt(
                directory / "receipts" / f"{batch.ordinal:02d}.json",
                plan=plan,
                batch=batch,
            )
            if receipt.outcome not in {"accepted", "rejected"}:
                raise ValueError("cannot normalize a provider-failed panel batch")
            receipts.append(receipt)
            request = StructuredModelRequest.model_validate_json(
                _bounded_bytes(directory / PurePosixPath(batch.request.locator))
            )
            raw_items = request.input_payload.get("items")
            if not isinstance(raw_items, list) or len(raw_items) != len(batch.candidate_ids):
                raise ValueError("development panel request population differs")
            raw_output = _provider_adjudication_output(
                directory / "responses" / f"{batch.ordinal:02d}-provider.json"
            )
            if raw_output.get("batch_id") != batch.batch_id:
                raise ValueError("development panel provider response names another batch")
            if raw_output.get("target_outcomes_used", False) is not False or raw_output.get(
                "benchmark_admission_claimed", False
            ) is not False:
                raise ValueError("development panel provider response exceeds its authority")
            raw_decisions = raw_output.get("decisions")
            if not isinstance(raw_decisions, list) or len(raw_decisions) != len(
                batch.candidate_ids
            ):
                raise ValueError("development panel provider response coverage differs")
            for position, (candidate_id, raw_item, raw_decision) in enumerate(
                zip(batch.candidate_ids, raw_items, raw_decisions, strict=True), 1
            ):
                if not isinstance(raw_item, dict) or not isinstance(raw_decision, dict):
                    raise ValueError("development panel provider decision is malformed")
                decision, audit = _normalize_adjudication_decision(
                    raw_decision,
                    raw_item=raw_item,
                    position=position,
                )
                if candidate_id in by_candidate:
                    raise ValueError("development panel normalization repeats a candidate")
                by_candidate[candidate_id] = decision
                normalized.append(
                    DevelopmentNormalizedAdjudication(
                        batch_id=batch.batch_id,
                        position=position,
                        original_receipt_outcome=receipt.outcome,
                        provider_resolution=audit["provider_resolution"],
                        canonical_resolution=decision.resolution,
                        semantic_echo_correction_count=audit[
                            "semantic_echo_correction_count"
                        ],
                        ineligible_field_nullification_count=audit[
                            "ineligible_field_nullification_count"
                        ],
                        envelope_field_removal_count=audit[
                            "envelope_field_removal_count"
                        ],
                        rationale_truncated=audit["rationale_truncated"],
                        decision=decision,
                    )
                )
        if set(by_candidate) != {
            candidate_id for batch in plan.batches for candidate_id in batch.candidate_ids
        }:
            raise ValueError("development panel normalized population differs")

        records: list[DevelopmentPanelDecisionRecord] = []
        contexts: Counter[str] = Counter()
        judgments: Counter[str] = Counter()
        domains: Counter[str] = Counter()
        for candidate_id in sorted(primary_a):
            left = primary_a[candidate_id]
            right = primary_b[candidate_id]
            source = visible[candidate_id]
            if candidate_id in by_candidate:
                disposition = PanelDecisionDisposition.ADJUDICATED
                adjudicator = by_candidate[candidate_id]
                final = _resolve_adjudication(
                    adjudicator,
                    candidate_id=candidate_id,
                    source_group_id=source.source_group_id,
                    primary_a=left,
                    primary_b=right,
                )
            elif not left.eligible and not right.eligible:
                disposition = PanelDecisionDisposition.PRIMARY_INELIGIBLE
                adjudicator = None
                final = None
            else:
                disposition = PanelDecisionDisposition.PRIMARY_AGREEMENT
                adjudicator = None
                final = left
            records.append(
                DevelopmentPanelDecisionRecord(
                    intake_candidate_id=candidate_id,
                    source_group_id=source.source_group_id,
                    domain=source.domain,
                    disposition=disposition,
                    primary_a=left,
                    primary_b=right,
                    adjudicator=adjudicator,
                    final_decision=final,
                )
            )
            if final is not None and final.eligible:
                assert final.decision_context_family is not None
                assert final.taste_judgment_family is not None
                contexts[final.decision_context_family.value] += 1
                judgments[final.taste_judgment_family.value] += 1
                domains[source.domain] += 1

        adjudications_path = temporary / "NORMALIZED_ADJUDICATIONS.jsonl"
        _atomic_write(
            adjudications_path,
            "".join(item.model_dump_json() + "\n" for item in normalized),
        )
        decisions_path = temporary / "FINAL_DECISIONS.jsonl"
        _atomic_write(
            decisions_path,
            "".join(item.model_dump_json() + "\n" for item in records),
        )
        complete = len(normalized) == plan.disputed_count
        ready = (
            complete
            and all(contexts[item.value] >= 6 for item in BenchmarkDecisionContextFamily)
            and set(judgments) == {item.value for item in ScientificTasteDecisionFamily}
            and len(domains) >= 3
        )
        manifest = DevelopmentPanelNormalizationManifest.create(
            panel_id=plan.panel_id,
            plan_sha256=plan.plan_sha256,
            normalized_at=normalized_at or datetime.now(UTC),
            source_batch_count=len(receipts),
            source_accepted_batch_count=sum(
                item.outcome == "accepted" for item in receipts
            ),
            source_rejected_batch_count=sum(
                item.outcome == "rejected" for item in receipts
            ),
            source_input_tokens=sum(item.input_tokens for item in receipts),
            source_output_tokens=sum(item.output_tokens for item in receipts),
            source_cost_usd=sum(item.cost_usd or 0.0 for item in receipts),
            normalized_adjudication_count=len(normalized),
            final_eligible_count=sum(
                item.final_decision is not None and item.final_decision.eligible
                for item in records
            ),
            semantic_echo_correction_count=sum(
                item.semantic_echo_correction_count for item in normalized
            ),
            ineligible_field_nullification_count=sum(
                item.ineligible_field_nullification_count for item in normalized
            ),
            envelope_field_removal_count=sum(
                item.envelope_field_removal_count for item in normalized
            ),
            rationale_truncation_count=sum(item.rationale_truncated for item in normalized),
            context_family_counts=dict(sorted(contexts.items())),
            judgment_family_counts=dict(sorted(judgments.items())),
            domain_counts=dict(sorted(domains.items())),
            adjudications=_binding(adjudications_path, temporary),
            decisions=_binding(decisions_path, temporary),
            all_batches_normalized=complete,
            ready_for_allocation=ready,
        )
        _write_json(temporary / "NORMALIZATION.json", manifest.model_dump(mode="json"))
        os.replace(temporary, target)
    except BaseException:
        _cleanup(temporary)
        raise
    return manifest


def _provider_adjudication_output(path: Path) -> dict[str, object]:
    payload = json.loads(_bounded_bytes(path))
    if not isinstance(payload, dict):
        raise ValueError("development panel provider response root is not an object")
    choices = payload.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise ValueError("development panel provider response must have one choice")
    choice = choices[0]
    if not isinstance(choice, dict) or choice.get("finish_reason") != "stop":
        raise ValueError("development panel provider response is not final")
    message = choice.get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), str):
        raise ValueError("development panel provider response content is not text")
    output = json.loads(message["content"])
    if not isinstance(output, dict):
        raise ValueError("development panel provider content is not an object")
    return output


def _normalize_adjudication_decision(
    raw: dict[str, object],
    *,
    raw_item: dict[str, object],
    position: int,
) -> tuple[DevelopmentAdjudicationDecision, dict[str, object]]:
    permitted = set(DevelopmentAdjudicationDecision.model_fields)
    unknown = set(raw) - permitted
    if not unknown <= {"echoes_primary"}:
        raise ValueError("development panel response contains an unknown semantic field")
    if raw.get("position") != position:
        raise ValueError("development panel response positions differ")
    rationale = raw.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        raise ValueError("development panel response lacks an adjudication rationale")
    rationale = rationale.strip()
    rationale_truncated = len(rationale) > 700
    if rationale_truncated:
        rationale = rationale[:700]
    resolution = AdjudicationResolution(raw.get("resolution"))
    semantic_echo_corrections = 0
    ineligible_nullifications = 0

    if resolution in {AdjudicationResolution.PRIMARY_A, AdjudicationResolution.PRIMARY_B}:
        key = (
            "primary_a_decision"
            if resolution is AdjudicationResolution.PRIMARY_A
            else "primary_b_decision"
        )
        primary = DevelopmentCaseabilityDecision.model_validate(raw_item.get(key))
        if raw.get("eligible") is not primary.eligible:
            raise ValueError("development panel selection disagrees with primary eligibility")
        canonical = primary.model_dump(
            mode="json",
            exclude={"intake_candidate_id", "source_group_id", "rationale"},
        )
        semantic_echo_corrections = sum(
            raw.get(field) != value for field, value in canonical.items()
        )
        canonical.update(
            {
                "position": position,
                "resolution": (
                    resolution
                    if primary.eligible
                    else AdjudicationResolution.NEITHER_INELIGIBLE
                ),
                "rationale": rationale,
            }
        )
        decision = DevelopmentAdjudicationDecision.model_validate(canonical)
    elif resolution is AdjudicationResolution.NEITHER_INELIGIBLE:
        normalized = {key: value for key, value in raw.items() if key in permitted}
        for field in (
            "decision_context_family",
            "taste_judgment_family",
            "atomic_decision_question",
            "ambiguity",
            "decision_leverage",
            "memorization_risk",
        ):
            if normalized.get(field) is not None:
                ineligible_nullifications += 1
            normalized[field] = None
        normalized.update(
            {
                "position": position,
                "eligible": False,
                "resolution": AdjudicationResolution.NEITHER_INELIGIBLE,
                "rationale": rationale,
            }
        )
        decision = DevelopmentAdjudicationDecision.model_validate(normalized)
    else:
        normalized = {key: value for key, value in raw.items() if key in permitted}
        normalized.update(
            {
                "position": position,
                "eligible": True,
                "resolution": AdjudicationResolution.NEW_RESOLUTION,
                "rationale": rationale,
            }
        )
        normalized.setdefault("exclusion_codes", [])
        decision = DevelopmentAdjudicationDecision.model_validate(normalized)
    return decision, {
        "provider_resolution": resolution,
        "semantic_echo_correction_count": semantic_echo_corrections,
        "ineligible_field_nullification_count": ineligible_nullifications,
        "envelope_field_removal_count": len(unknown),
        "rationale_truncated": rationale_truncated,
    }


def _adjudication_request(
    *,
    batch_id: str,
    candidate_ids: list[str],
    visible_items: dict[str, DevelopmentScreenCandidate],
    primary_a: dict[str, DevelopmentCaseabilityDecision],
    primary_b: dict[str, DevelopmentCaseabilityDecision],
    identity_a: tuple[str, str],
    identity_b: tuple[str, str],
    profile: ModelNodeProfile,
    policy_sha: str,
    seed: int,
) -> StructuredModelRequest:
    items = []
    for position, candidate_id in enumerate(candidate_ids, 1):
        items.append(
            {
                "position": position,
                "visible_source": visible_items[candidate_id].model_dump(mode="json"),
                "primary_a_identity": {"provider": identity_a[0], "model": identity_a[1]},
                "primary_a_decision": primary_a[candidate_id].model_dump(mode="json"),
                "primary_b_identity": {"provider": identity_b[0], "model": identity_b[1]},
                "primary_b_decision": primary_b[candidate_id].model_dump(mode="json"),
            }
        )
    return StructuredModelRequest(
        request_id=batch_id,
        node_name=_NODE_NAME,
        stage="benchmark-development-adjudication",
        state_snapshot_id=content_sha256(candidate_ids),
        expected_backend=profile.provider,
        expected_model=profile.model,
        policy_id="scitastebench-caseability-adjudication-v1",
        policy_fingerprint=policy_sha,
        system_instruction=(
            "Act as the disagreement-only third adjudicator for outcome-blind Scientific Taste "
            "case screening. You see the same visible source and two independent primary "
            "proposals, never the later outcome. Resolve construct validity rather than voting "
            "mechanically. A problem/idea decision asks whether a research direction is worth "
            "pursuing. A hypothesis decision asks which falsifiable explanation or prediction to "
            "commit to. An experiment-design decision asks how to distinguish explanations or "
            "control confounds. A resource-allocation decision asks whether or where to spend a "
            "limited research budget, continue, pivot, or stop; merely specifying an experimental "
            "control is not resource allocation. Evidence interpretation concerns what results "
            "warrant. Claim/review closure concerns what may be asserted or how a concern is "
            "closed. Keep decision context separate from the Taste judgment exercised. Mark a "
            "case ineligible if the source does not expose two plausible consequential actions "
            "without hidden outcomes. Output positions in exact order; never copy or invent source "
            "identifiers; return only the requested JSON object."
        ),
        input_payload={
            "batch_id": batch_id,
            "items": items,
            "decision_context_families": [item.value for item in BenchmarkDecisionContextFamily],
            "taste_judgment_families": [item.value for item in ScientificTasteDecisionFamily],
            "target_outcomes_visible": False,
        },
        output_schema=DevelopmentAdjudicationBatchOutput.model_json_schema(mode="serialization"),
        seed=seed,
        prompt_version="scitastebench-caseability-adjudication-v1",
        profile_id=profile.profile_id,
        profile_fingerprint=profile.fingerprint,
        generation_envelope=profile.generation,
        admission_budget=profile.admission,
        cumulative_project_budget=profile.cumulative_project,
    )


def _finalize(
    directory: Path,
    *,
    root: Path,
    plan: DevelopmentPanelPlan,
    config: DevelopmentPanelConfig,
) -> DevelopmentPanelSummary:
    receipts = _receipt_list(directory, plan=plan)
    complete = len(receipts) == len(plan.batches) and all(
        item.outcome == "accepted" for item in receipts
    )
    accepted = sum(item.outcome == "accepted" for item in receipts)
    rejected = sum(item.outcome == "rejected" for item in receipts)
    failed = sum(item.outcome == "failed" for item in receipts)
    decisions_binding: ScreenFileBinding | None = None
    records: list[DevelopmentPanelDecisionRecord] = []
    contexts: Counter[str] = Counter()
    judgments: Counter[str] = Counter()
    domains: Counter[str] = Counter()
    if complete:
        visible = _load_visible_items(_require_binding(root, config.screening_items))
        primary_a, _ = _load_primary(root, config.primary_a)
        primary_b, _ = _load_primary(root, config.primary_b)
        adjudicated: dict[str, DevelopmentAdjudicationDecision] = {}
        for batch, receipt in zip(plan.batches, receipts, strict=True):
            assert receipt.response is not None
            output = DevelopmentAdjudicationBatchOutput.model_validate_json(
                _bounded_bytes(directory / PurePosixPath(receipt.response.locator))
            )
            for candidate_id, decision in zip(batch.candidate_ids, output.decisions, strict=True):
                adjudicated[candidate_id] = decision
        for candidate_id in sorted(primary_a):
            left = primary_a[candidate_id]
            right = primary_b[candidate_id]
            source = visible[candidate_id]
            if candidate_id in adjudicated:
                disposition = PanelDecisionDisposition.ADJUDICATED
                adjudicator = adjudicated[candidate_id]
                final = _resolve_adjudication(
                    adjudicator,
                    candidate_id=candidate_id,
                    source_group_id=source.source_group_id,
                    primary_a=left,
                    primary_b=right,
                )
            elif not left.eligible and not right.eligible:
                disposition = PanelDecisionDisposition.PRIMARY_INELIGIBLE
                adjudicator = None
                final = None
            else:
                disposition = PanelDecisionDisposition.PRIMARY_AGREEMENT
                adjudicator = None
                final = left
            records.append(
                DevelopmentPanelDecisionRecord(
                    intake_candidate_id=candidate_id,
                    source_group_id=source.source_group_id,
                    domain=source.domain,
                    disposition=disposition,
                    primary_a=left,
                    primary_b=right,
                    adjudicator=adjudicator,
                    final_decision=final,
                )
            )
            if final is not None and final.eligible:
                assert final.decision_context_family is not None
                assert final.taste_judgment_family is not None
                contexts[final.decision_context_family.value] += 1
                judgments[final.taste_judgment_family.value] += 1
                domains[source.domain] += 1
        output_path = directory / "FINAL_DECISIONS.jsonl"
        _atomic_write(
            output_path,
            "".join(item.model_dump_json() + "\n" for item in records),
        )
        decisions_binding = _binding(output_path, directory)
    ready = (
        complete
        and all(contexts[item.value] >= 6 for item in BenchmarkDecisionContextFamily)
        and set(judgments) == {item.value for item in ScientificTasteDecisionFamily}
        and len(domains) >= 3
    )
    return DevelopmentPanelSummary(
        panel_id=plan.panel_id,
        plan_sha256=plan.plan_sha256,
        finalized_at=datetime.now(UTC),
        batch_count=len(plan.batches),
        accepted_batch_count=accepted,
        rejected_batch_count=rejected,
        failed_batch_count=failed,
        final_eligible_count=sum(
            item.final_decision is not None and item.final_decision.eligible for item in records
        ),
        context_family_counts=dict(sorted(contexts.items())),
        judgment_family_counts=dict(sorted(judgments.items())),
        domain_counts=dict(sorted(domains.items())),
        input_tokens=sum(item.input_tokens for item in receipts),
        output_tokens=sum(item.output_tokens for item in receipts),
        cost_usd=sum(item.cost_usd or 0.0 for item in receipts),
        decisions=decisions_binding,
        complete=complete,
        ready_for_allocation=ready,
    )


def _resolve_adjudication(
    decision: DevelopmentAdjudicationDecision,
    *,
    candidate_id: str,
    source_group_id: str,
    primary_a: DevelopmentCaseabilityDecision,
    primary_b: DevelopmentCaseabilityDecision,
) -> DevelopmentCaseabilityDecision:
    if decision.resolution is AdjudicationResolution.PRIMARY_A:
        return primary_a
    if decision.resolution is AdjudicationResolution.PRIMARY_B:
        return primary_b
    return DevelopmentCaseabilityDecision.model_validate(
        {
            **decision.model_dump(mode="json", exclude={"position", "resolution"}),
            "intake_candidate_id": candidate_id,
            "source_group_id": source_group_id,
        }
    )


def _load_primary(
    root: Path,
    binding: DevelopmentPanelPrimary,
) -> tuple[dict[str, DevelopmentCaseabilityDecision], tuple[str, str]]:
    plan = json.loads(_bounded_bytes(_require_binding(root, binding.plan)))
    identity = (str(plan["provider"]), str(plan["model"]))
    _require_binding(root, binding.normalization)
    decisions_path = _require_binding(root, binding.decisions)
    decisions: dict[str, DevelopmentCaseabilityDecision] = {}
    for line in _bounded_bytes(decisions_path).decode("utf-8").splitlines():
        if not line.strip():
            continue
        record = DevelopmentNormalizedDecision.model_validate_json(line)
        candidate_id = record.decision.intake_candidate_id
        if candidate_id in decisions:
            raise ValueError("development panel primary repeats a candidate")
        decisions[candidate_id] = record.decision
    return decisions, identity


def _load_visible_items(path: Path) -> dict[str, DevelopmentScreenCandidate]:
    items: dict[str, DevelopmentScreenCandidate] = {}
    for line in _bounded_bytes(path).decode("utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        if raw.get("prior_track_a_role") != "unused":
            continue
        if raw.get("outcome_fields_exposed") is not False:
            raise ValueError("development panel visible item exposes an outcome")
        item = DevelopmentScreenCandidate.model_validate(
            {name: raw[name] for name in DevelopmentScreenCandidate.model_fields}
        )
        items[item.intake_candidate_id] = item
    return items


def _validate_output(
    output: DevelopmentAdjudicationBatchOutput,
    *,
    batch: DevelopmentPanelBatchPlan,
    request: StructuredModelRequest,
) -> None:
    if output.batch_id != batch.batch_id:
        raise ValueError("development panel response names another batch")
    if tuple(item.position for item in output.decisions) != tuple(
        range(1, len(batch.candidate_ids) + 1)
    ):
        raise ValueError("development panel response positions differ")
    raw_items = request.input_payload.get("items")
    if not isinstance(raw_items, list) or len(raw_items) != len(output.decisions):
        raise ValueError("development panel request population differs")
    for decision, raw_item in zip(output.decisions, raw_items, strict=True):
        if not isinstance(raw_item, dict):
            raise ValueError("development panel request item is malformed")
        if decision.resolution not in {
            AdjudicationResolution.PRIMARY_A,
            AdjudicationResolution.PRIMARY_B,
        }:
            continue
        key = (
            "primary_a_decision"
            if decision.resolution is AdjudicationResolution.PRIMARY_A
            else "primary_b_decision"
        )
        primary = DevelopmentCaseabilityDecision.model_validate(raw_item.get(key))
        primary_semantics = primary.model_dump(
            mode="json",
            exclude={"intake_candidate_id", "source_group_id", "rationale"},
        )
        adjudicator_semantics = decision.model_dump(
            mode="json",
            exclude={"position", "resolution", "rationale"},
        )
        if adjudicator_semantics != primary_semantics:
            raise ValueError("development panel selected a primary but changed its semantics")


def _validate_telemetry(response: object, *, profile: ModelNodeProfile) -> None:
    from scitaste.model_nodes.models import StructuredModelResponse

    assert isinstance(response, StructuredModelResponse)
    cost = response.usage.cost_usd
    total = response.usage.input_tokens + response.usage.output_tokens
    budget = profile.admission
    if cost is None or (
        response.usage.input_tokens > budget.max_input_tokens
        or response.usage.output_tokens > budget.max_output_tokens
        or total > budget.max_total_tokens
        or cost > budget.max_response_cost_usd
        or response.latency_ms > budget.max_latency_ms
    ):
        raise ValueError("development panel response exceeds its per-call budget")


def _receipt_list(
    directory: Path,
    *,
    plan: DevelopmentPanelPlan,
) -> list[DevelopmentPanelReceipt]:
    receipts: list[DevelopmentPanelReceipt] = []
    for batch in plan.batches:
        path = directory / "receipts" / f"{batch.ordinal:02d}.json"
        if not path.exists():
            continue
        receipts.append(_load_receipt(path, plan=plan, batch=batch))
    return receipts


def _load_receipt(
    path: Path,
    *,
    plan: DevelopmentPanelPlan,
    batch: DevelopmentPanelBatchPlan,
) -> DevelopmentPanelReceipt:
    receipt = DevelopmentPanelReceipt.model_validate_json(_bounded_bytes(path))
    if (
        receipt.panel_id != plan.panel_id
        or receipt.plan_sha256 != plan.plan_sha256
        or receipt.batch_id != batch.batch_id
        or receipt.request_fingerprint != batch.request_fingerprint
    ):
        raise ValueError("development panel receipt differs from its plan")
    return receipt


def _failed_receipt(
    plan: DevelopmentPanelPlan,
    batch: DevelopmentPanelBatchPlan,
    code: str,
    *,
    detail: str | None = None,
) -> DevelopmentPanelReceipt:
    return DevelopmentPanelReceipt(
        panel_id=plan.panel_id,
        plan_sha256=plan.plan_sha256,
        batch_id=batch.batch_id,
        completed_at=datetime.now(UTC),
        outcome="failed",
        request_fingerprint=batch.request_fingerprint,
        failure_code=code,
        failure_detail=detail,
    )


def _validate_budget(
    receipts: list[DevelopmentPanelReceipt],
    *,
    profile: ModelNodeProfile,
) -> None:
    budget = profile.cumulative_project
    if (
        len(receipts) > budget.max_invocations
        or sum(item.input_tokens + item.output_tokens for item in receipts)
        > budget.max_total_tokens
        or sum(item.cost_usd or 0.0 for item in receipts) > budget.max_api_cost_usd
    ):
        raise ValueError("development panel cumulative budget exceeded")


def _load_plan(path: Path) -> DevelopmentPanelPlan:
    payload = json.loads(_bounded_bytes(path))
    if not isinstance(payload, dict):
        raise ValueError("development panel plan root is not an object")
    observed = payload.pop("plan_sha256", None)
    plan = DevelopmentPanelPlan.model_validate(payload)
    if observed != plan.plan_sha256:
        raise ValueError("development panel plan hash mismatch")
    return plan


def _require_binding(root: Path, binding: ScreenFileBinding) -> Path:
    path = _within(root, binding.locator)
    if _sha256_file(path) != binding.sha256:
        raise ValueError(f"development panel binding drifted: {binding.locator}")
    return path


def _binding(path: Path, root: Path) -> ScreenFileBinding:
    return ScreenFileBinding(
        locator=path.resolve(strict=True).relative_to(root.resolve(strict=True)).as_posix(),
        sha256=_sha256_file(path),
    )


def _within(root: Path, locator: str | Path) -> Path:
    candidate = Path(locator)
    if not candidate.is_absolute():
        pure = PurePosixPath(candidate.as_posix())
        if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
            raise ValueError("development panel locator must be safe and relative")
        candidate = root.joinpath(*pure.parts)
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("development panel path escapes locator root") from exc
    return resolved


def _bounded_bytes(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_FILE_BYTES:
        raise ValueError(f"development panel input is not a bounded regular file: {path}")
    return path.read_bytes()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(_bounded_bytes(path)).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    _atomic_write(
        path,
        json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n",
    )


def _atomic_write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _cleanup(path: Path) -> None:
    if not path.exists():
        return
    for child in sorted(path.rglob("*"), reverse=True):
        if child.is_file():
            child.unlink(missing_ok=True)
        elif child.is_dir():
            child.rmdir()
    path.rmdir()


__all__ = [
    "DevelopmentPanelNormalizationManifest",
    "DevelopmentPanelPlan",
    "DevelopmentPanelSummary",
    "execute_scitastebench_development_panel",
    "normalize_scitastebench_development_panel",
    "prepare_scitastebench_development_panel",
]
