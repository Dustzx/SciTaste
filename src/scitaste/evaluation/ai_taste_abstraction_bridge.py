"""Bridge verified grounded-abstraction batches into AI-only review packs."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from scitaste.evaluation.ai_taste_abstraction_review import (
    AIAbstractionFileBinding,
    compile_ai_taste_abstraction_review_requests,
)
from scitaste.evaluation.taste_abstraction_batch import (
    TasteAbstractionBatchFile,
    TasteAbstractionBatchItem,
    TasteAbstractionRuntimeBatch,
)
from scitaste.evaluation.taste_mechanism_pilot import (
    PilotAbstractionInputRecord,
    load_taste_mechanism_pilot_plan,
)
from scitaste.evaluation.taste_reference_quality_batch import (
    TasteReferenceQualityRuntimeBatch,
)
from scitaste.model_nodes.models import NodeResult, NodeResultStatus
from scitaste.model_nodes.profiles import load_model_node_profile_set
from scitaste.model_nodes.registry import first_party_node_types
from scitaste.model_nodes.runtime import (
    ModelNodeRuntime,
    ModelNodeRuntimeError,
    RuntimeBackendMode,
    RuntimeInvocationReceipt,
    RuntimeInvocationTelemetry,
    RuntimeLedgerEntry,
    RuntimeOutcome,
)
from scitaste.model_nodes.runtime_config import load_model_node_runtime_config
from scitaste.project import ProjectRuntime
from scitaste.taste.intrinsic import TasteTask
from scitaste.taste.reference_quality import (
    ReferenceQualityQualification,
    ReferenceQualityVerdict,
    compile_reference_quality_qualification,
)
from scitaste.taste.semantic import (
    is_verified_model_generation_entry,
    load_verified_taste_abstraction_ledger,
    reference_quality_from_ledger,
)
from scitaste.taste.semantic_models import (
    GROUNDED_TASTE_ABSTRACTION_NODE,
    GroundedTasteCaseAbstraction,
    TasteAbstractionInput,
    validate_grounded_abstraction_against_projection,
)

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_INPUT_BYTES = 256 * 1_048_576


class GroundedAbstractionBridgeAdmission(BaseModel):
    """One accepted model generation admitted to independent AI review."""

    model_config = _CONFIG

    ordinal: int = Field(gt=0, le=100_000)
    input_id: str = Field(pattern=_ID)
    source_group_id: str = Field(pattern=_ID)
    source_domain: Literal["computing", "ecology", "public-health"]
    decision_family: TasteTask
    invocation_id: str = Field(pattern=_ID)
    provider: str = Field(min_length=1, max_length=200)
    model: str = Field(min_length=1, max_length=300)
    backend_mode: Literal["live", "local"]
    runtime_config: AIAbstractionFileBinding
    ledger_entry: AIAbstractionFileBinding
    raw_recording: AIAbstractionFileBinding
    accepted_result: AIAbstractionFileBinding
    derived_runtime_receipt: AIAbstractionFileBinding
    runtime_entry_sha256: str = Field(pattern=_SHA256)
    accepted_result_sha256: str = Field(pattern=_SHA256)
    raw_recording_sha256: str = Field(pattern=_SHA256)
    source_projection_sha256: str = Field(pattern=_SHA256)
    provider_execution_preexisting: Literal[True] = True
    provider_execution_fabricated: Literal[False] = False
    bridge_model_calls_performed: Literal[False] = False
    source_quality_status: Literal[
        "not-formally-qualified",
        "ai-operational-qualified",
    ] = "not-formally-qualified"
    source_quality_missing_reason: (
        Literal["no-reference-quality-qualification-bound"] | None
    ) = "no-reference-quality-qualification-bound"
    reference_quality_qualification: AIAbstractionFileBinding | None = None
    reference_quality_report_sha256: str | None = Field(default=None, pattern=_SHA256)
    operational_reference_quality_qualification_bound: bool = False
    formal_reference_quality_qualification_bound: Literal[False] = False
    formal_human_validity: Literal[False] = False

    @model_validator(mode="after")
    def hashes_match_bindings(self) -> GroundedAbstractionBridgeAdmission:
        if self.raw_recording.sha256 != self.raw_recording_sha256:
            raise ValueError("bridge raw-recording hashes differ")
        qualified = self.source_quality_status == "ai-operational-qualified"
        if qualified != self.operational_reference_quality_qualification_bound:
            raise ValueError("bridge operational quality status differs from its binding")
        if qualified != (self.reference_quality_qualification is not None):
            raise ValueError("bridge quality receipt presence differs from its status")
        if qualified != (self.reference_quality_report_sha256 is not None):
            raise ValueError("bridge quality report hash presence differs from its status")
        if qualified == (self.source_quality_missing_reason is not None):
            raise ValueError("bridge quality missing reason differs from its status")
        return self


class GroundedAbstractionBridgeExclusion(BaseModel):
    """Planned batch item intentionally absent from every reviewer request."""

    model_config = _CONFIG

    ordinal: int = Field(gt=0, le=100_000)
    input_id: str = Field(pattern=_ID)
    source_group_id: str = Field(pattern=_ID)
    source_domain: Literal["computing", "ecology", "public-health"]
    decision_family: TasteTask
    invocation_id: str = Field(pattern=_ID)
    disposition: Literal[
        "not-executed",
        "rejected",
        "failed",
        "not-applicable",
        "planned-no-execution",
    ]
    ledger_entry: AIAbstractionFileBinding | None = None
    runtime_entry_sha256: str | None = Field(default=None, pattern=_SHA256)
    failure_receipt: AIAbstractionFileBinding | None = None
    backend_may_have_started: bool = False
    unknown_cost: bool = False
    reason_details: tuple[str, ...] = Field(min_length=1, max_length=32)
    result_exposed_to_review: Literal[False] = False
    included_in_request_pack: Literal[False] = False

    @model_validator(mode="after")
    def ledger_matches_execution_state(self) -> GroundedAbstractionBridgeExclusion:
        missing = self.disposition == "not-executed"
        if missing == (self.ledger_entry is not None):
            raise ValueError("bridge exclusion ledger binding differs from execution state")
        if missing == (self.runtime_entry_sha256 is not None):
            raise ValueError("bridge exclusion entry hash differs from execution state")
        if self.unknown_cost and not self.backend_may_have_started:
            raise ValueError("unknown provider cost requires a backend-started observation")
        if (self.failure_receipt is not None) != (self.disposition == "failed"):
            raise ValueError("bridge failure receipt differs from failed backend-start state")
        return self


class GroundedAbstractionReviewBridge(BaseModel):
    """Complete batch-to-review handoff with no new provider execution."""

    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1"] = "1.0"
    bridge_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    run_id: str = Field(pattern=_ID)
    source_batch: AIAbstractionFileBinding
    source_batch_sha256: str = Field(pattern=_SHA256)
    review_protocol: AIAbstractionFileBinding
    review_protocol_sha256: str = Field(pattern=_SHA256)
    review_request_pack: AIAbstractionFileBinding
    review_request_pack_sha256: str = Field(pattern=_SHA256)
    admissions: tuple[GroundedAbstractionBridgeAdmission, ...] = Field(min_length=1)
    exclusions: tuple[GroundedAbstractionBridgeExclusion, ...]
    batch_item_count: int = Field(gt=0)
    accepted_item_count: int = Field(gt=0)
    excluded_item_count: int = Field(ge=0)
    planned_source_count: int | None = Field(default=None, ge=0)
    eligible_source_count: int | None = Field(default=None, ge=0)
    runtime_accepted_source_count: int | None = Field(default=None, ge=0)
    runtime_rejected_source_count: int | None = Field(default=None, ge=0)
    accepted_counts_by_domain: dict[str, int]
    accepted_counts_by_decision_family: dict[str, int]
    formal_reference_quality_qualified_count: Literal[0] = 0
    prepared_at: datetime
    accepted_only_review_pack: Literal[True] = True
    rejected_failed_and_missing_excluded: Literal[True] = True
    provider_execution_fabricated: Literal[False] = False
    bridge_model_calls_performed: Literal[False] = False
    bridge_api_calls_performed: Literal[False] = False
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    human_validity_claim_allowed: Literal[False] = False
    no_human_or_expert_validity_claim: Literal[True] = True
    natural_pilot_only: Literal[True] = True
    formal_evidence_eligible: Literal[False] = False
    formal_requires_reference_quality_qualification: Literal[True] = True
    formal_human_validity: Literal[False] = False
    replacement_sampling_performed: Literal[False] = False

    @model_validator(mode="after")
    def bridge_is_closed(self) -> GroundedAbstractionReviewBridge:
        if self.prepared_at.utcoffset() is None:
            raise ValueError("AI abstraction bridge time must include a timezone")
        if self.accepted_item_count != len(self.admissions):
            raise ValueError("AI abstraction bridge accepted count mismatch")
        if self.excluded_item_count != len(self.exclusions):
            raise ValueError("AI abstraction bridge exclusion count mismatch")
        if self.batch_item_count != self.accepted_item_count + self.excluded_item_count:
            raise ValueError("AI abstraction bridge does not cover its complete batch")
        if self.schema_version == "1.1":
            counts = (
                self.planned_source_count,
                self.eligible_source_count,
                self.runtime_accepted_source_count,
                self.runtime_rejected_source_count,
            )
            if any(value is None for value in counts):
                raise ValueError("coverage-aware bridge requires all source counts")
            planned, eligible, runtime_accepted, runtime_rejected = counts
            assert planned is not None and eligible is not None
            assert runtime_accepted is not None and runtime_rejected is not None
            observed_rejected = sum(
                item.disposition == "rejected" for item in self.exclusions
            )
            if (
                not 0 < runtime_accepted <= eligible <= planned
                or eligible != self.batch_item_count
                or runtime_accepted != self.accepted_item_count
                or runtime_rejected != observed_rejected
                or runtime_accepted + runtime_rejected > eligible
            ):
                raise ValueError("coverage-aware bridge source counts are inconsistent")
            if any(
                not item.operational_reference_quality_qualification_bound
                for item in self.admissions
            ):
                raise ValueError("coverage-aware bridge admission lacks quality qualification")
        admission_ids = {item.invocation_id for item in self.admissions}
        excluded_ids = {item.invocation_id for item in self.exclusions}
        if admission_ids.intersection(excluded_ids):
            raise ValueError("AI abstraction bridge both admits and excludes an invocation")
        if len(admission_ids) != len(self.admissions) or len(excluded_ids) != len(self.exclusions):
            raise ValueError("AI abstraction bridge repeats an invocation")
        domain_counts: dict[str, int] = {}
        family_counts: dict[str, int] = {}
        for item in self.admissions:
            domain_counts[item.source_domain] = domain_counts.get(item.source_domain, 0) + 1
            family = item.decision_family.value
            family_counts[family] = family_counts.get(family, 0) + 1
        if self.accepted_counts_by_domain != dict(sorted(domain_counts.items())):
            raise ValueError("AI abstraction bridge domain coverage mismatch")
        if self.accepted_counts_by_decision_family != dict(sorted(family_counts.items())):
            raise ValueError("AI abstraction bridge decision-family coverage mismatch")
        return self

    @computed_field
    @property
    def bridge_sha256(self) -> str:
        payload = self.model_dump(mode="json", exclude={"bridge_sha256"})
        if self.schema_version == "1.0":
            for field in (
                "planned_source_count",
                "eligible_source_count",
                "runtime_accepted_source_count",
                "runtime_rejected_source_count",
                "formal_human_validity",
                "replacement_sampling_performed",
            ):
                payload.pop(field, None)
            for admission in payload["admissions"]:
                for field in (
                    "reference_quality_qualification",
                    "reference_quality_report_sha256",
                    "operational_reference_quality_qualification_bound",
                    "formal_human_validity",
                ):
                    admission.pop(field, None)
        return _canonical_sha256(payload)


def prepare_ai_taste_abstraction_review_from_batch(
    *,
    locator_root: str | Path,
    outputs_root: str | Path,
    batch_path: str | Path,
    protocol_path: str | Path,
    output_dir: str | Path,
    prepared_at: datetime | None = None,
) -> GroundedAbstractionReviewBridge:
    """Admit accepted BATCH entries and compile their two AI-only request packs."""

    root = Path(locator_root).resolve(strict=True)
    outputs = _within_root(root, outputs_root, must_exist=True)
    batch_file = _regular_file(root, batch_path)
    protocol_file = _regular_file(root, protocol_path)
    target = _new_target(root, output_dir)
    batch = _load_batch(batch_file)
    _verify_batch_sources(root, batch)
    plan_file = _bound_batch_file(root, batch.pilot_plan)
    plan = load_taste_mechanism_pilot_plan(plan_file, locator_root=root).plan
    if plan.plan_sha256 != batch.pilot_plan_sha256:
        raise ValueError("Taste abstraction BATCH binds another pilot plan")
    plan_inputs = {item.input_id: item for item in plan.abstraction_inputs}
    if batch.schema_version == "1.0":
        if set(plan_inputs) != {item.input_id for item in batch.items}:
            raise ValueError("Taste abstraction BATCH differs from pilot abstraction inputs")
    else:
        _verify_quality_qualified_subset(
            root=root,
            outputs=outputs,
            batch=batch,
            plan_file=plan_file,
            plan_inputs=plan.abstraction_inputs,
        )

    runtime = ModelNodeRuntime(ProjectRuntime(outputs), node_types=first_party_node_types())
    runtime.verify(project_id=batch.project_id, run_id=batch.run_id)
    target.mkdir(parents=True)
    runtime_receipt_paths: list[Path] = []
    admissions: list[GroundedAbstractionBridgeAdmission] = []
    exclusions: list[GroundedAbstractionBridgeExclusion] = []
    for item in batch.items:
        planned = plan_inputs[item.input_id]
        if (
            planned.source_group_id != item.source_group_id
            or planned.source_projection_sha256 != item.source_projection_sha256
        ):
            raise ValueError("Taste abstraction BATCH item differs from its pilot plan")
        runtime_config_file = _bound_batch_file(root, item.runtime_config)
        loaded_config = load_model_node_runtime_config(runtime_config_file)
        if loaded_config.source_sha256 != item.runtime_config.file_sha256:
            raise ValueError("Taste abstraction runtime-config hash mismatch")
        try:
            entry = runtime.entry(
                project_id=batch.project_id,
                run_id=batch.run_id,
                invocation_id=item.invocation_id,
            )
        except ModelNodeRuntimeError:
            exclusions.append(_missing_exclusion(item, planned))
            continue
        ledger_file = _ledger_path(outputs, entry)
        ledger_binding = _binding(root, ledger_file)
        if entry.outcome is not RuntimeOutcome.ACCEPTED:
            exclusions.append(
                _outcome_exclusion(
                    root=root,
                    outputs=outputs,
                    item=item,
                    planned=planned,
                    entry=entry,
                    binding=ledger_binding,
                )
            )
            continue
        admitted = _admit_entry(
            root=root,
            outputs=outputs,
            target=target,
            batch=batch,
            item=item,
            planned=planned,
            entry=entry,
            runtime=runtime,
            runtime_config_file=runtime_config_file,
            ledger_binding=ledger_binding,
        )
        admissions.append(admitted)
        runtime_receipt_paths.append(_bound_file(root, admitted.derived_runtime_receipt))
    if not admissions:
        raise ValueError("Taste abstraction BATCH has no accepted generation eligible for review")

    runtime_rejected_count = sum(
        item.disposition == "rejected" for item in exclusions
    )

    request_pack = compile_ai_taste_abstraction_review_requests(
        evidence_root=root,
        runtime_receipt_paths=runtime_receipt_paths,
        protocol_path=protocol_file,
        output_dir=target / "review-pack",
        planned_source_count=(
            None if batch.schema_version == "1.0" else batch.planned_source_count
        ),
        eligible_source_count=(
            None if batch.schema_version == "1.0" else batch.eligible_source_count
        ),
        runtime_rejected_source_count=(
            None if batch.schema_version == "1.0" else runtime_rejected_count
        ),
    )
    pack_file = target / "review-pack" / "PACK.json"
    when = prepared_at or datetime.now(UTC)
    bridge_identity = _canonical_sha256(
        [batch.batch_sha256, request_pack.pack_sha256, when.isoformat()]
    )
    bridge = GroundedAbstractionReviewBridge(
        schema_version=batch.schema_version,
        bridge_id=f"grounded-abstraction-review-{bridge_identity[:24]}",
        project_id=batch.project_id,
        run_id=batch.run_id,
        source_batch=_binding(root, batch_file),
        source_batch_sha256=batch.batch_sha256,
        review_protocol=_binding(root, protocol_file),
        review_protocol_sha256=request_pack.protocol_sha256,
        review_request_pack=_binding(root, pack_file),
        review_request_pack_sha256=request_pack.pack_sha256,
        admissions=tuple(admissions),
        exclusions=tuple(exclusions),
        batch_item_count=len(batch.items),
        accepted_item_count=len(admissions),
        excluded_item_count=len(exclusions),
        planned_source_count=(
            None if batch.schema_version == "1.0" else batch.planned_source_count
        ),
        eligible_source_count=(
            None if batch.schema_version == "1.0" else batch.eligible_source_count
        ),
        runtime_accepted_source_count=(
            None if batch.schema_version == "1.0" else len(admissions)
        ),
        runtime_rejected_source_count=(
            None if batch.schema_version == "1.0" else runtime_rejected_count
        ),
        accepted_counts_by_domain=_counts(item.source_domain for item in admissions),
        accepted_counts_by_decision_family=_counts(
            item.decision_family.value for item in admissions
        ),
        prepared_at=when,
    )
    _write_new_json(
        target / "BRIDGE.json",
        bridge.model_dump(mode="json", exclude={"bridge_sha256"}),
    )
    return bridge


def _admit_entry(
    *,
    root: Path,
    outputs: Path,
    target: Path,
    batch: TasteAbstractionRuntimeBatch,
    item: TasteAbstractionBatchItem,
    planned: PilotAbstractionInputRecord,
    entry: RuntimeLedgerEntry,
    runtime: ModelNodeRuntime,
    runtime_config_file: Path,
    ledger_binding: AIAbstractionFileBinding,
) -> GroundedAbstractionBridgeAdmission:
    if not is_verified_model_generation_entry(entry):
        raise ValueError("accepted abstraction is not a verified live/local model generation")
    if entry.intent.backend_mode not in {RuntimeBackendMode.LIVE, RuntimeBackendMode.LOCAL}:
        raise ValueError("accepted abstraction uses an ineligible backend mode")
    if (
        entry.intent.project_id != batch.project_id
        or entry.intent.run_id != batch.run_id
        or entry.intent.project_revision != batch.project_revision
        or entry.intent.node_name != GROUNDED_TASTE_ABSTRACTION_NODE
        or entry.intent.invocation_id != item.invocation_id
        or entry.intent.profile.profile_id != batch.profile_id
        or entry.intent.profile.fingerprint != batch.profile_fingerprint
        or (entry.intent.profile.provider, entry.intent.profile.model)
        != (batch.provider, batch.model)
        or entry.result is None
        or entry.result_sha256 is None
        or entry.request_fingerprint is None
        or entry.recording_sha256 is None
        or entry.blockers
    ):
        raise ValueError("accepted abstraction ledger entry differs from its BATCH contract")
    config = load_model_node_runtime_config(runtime_config_file).config
    expected_context = config.state_projection.to_node_context().model_copy(
        update={"cumulative_api_cost_usd": entry.intent.context.cumulative_api_cost_usd}
    )
    if (
        config.node_name != entry.intent.node_name
        or config.node_input != entry.intent.node_input
        or expected_context != entry.intent.context
        or config.trigger != entry.intent.trigger
        or config.policy != entry.intent.policy
        or config.backend_mode != entry.intent.backend_mode
        or config.seed != entry.intent.seed
    ):
        raise ValueError("accepted abstraction ledger entry differs from its runtime config")
    result = NodeResult[GroundedTasteCaseAbstraction].model_validate(entry.result)
    if (
        result.status is not NodeResultStatus.ACCEPTED
        or result.proposal is None
        or result.node_name != GROUNDED_TASTE_ABSTRACTION_NODE
        or result.request.fingerprint != entry.request_fingerprint
        or result.response.request_fingerprint != entry.request_fingerprint
        or (result.response.backend, result.response.model) != (batch.provider, batch.model)
        or result.response.tool_calls
    ):
        raise ValueError("accepted abstraction result differs from the grounded-node contract")
    node_input = TasteAbstractionInput.model_validate(entry.intent.node_input)
    if (
        node_input.source_projection_sha256 != item.source_projection_sha256
        or result.proposal.case_id != node_input.case_id
    ):
        raise ValueError("accepted abstraction result differs from its planned source input")
    findings = validate_grounded_abstraction_against_projection(result.proposal, node_input)
    if findings:
        raise ValueError(f"accepted abstraction fails deterministic grounding: {findings}")

    recording_file = _recording_path(outputs, entry)
    if _sha256_file(recording_file) != entry.recording_sha256:
        raise ValueError("accepted abstraction raw recording hash differs from its ledger")
    stem = f"{item.ordinal:02d}-{item.input_id}"
    result_file = target / "accepted-results" / f"{stem}.json"
    _write_new_json(result_file, entry.result)
    receipt_file = target / "derived-runtime-receipts" / f"{stem}.json"
    receipt = RuntimeInvocationReceipt(
        project_id=entry.intent.project_id,
        run_id=entry.intent.run_id,
        invocation_id=entry.intent.invocation_id,
        outcome=entry.outcome,
        entry_sha256=entry.entry_sha256,
        request_fingerprint=entry.request_fingerprint,
        result=entry.result,
        telemetry=RuntimeInvocationTelemetry(
            input_tokens=entry.input_tokens,
            output_tokens=entry.output_tokens,
            total_tokens=entry.input_tokens + entry.output_tokens,
            cost_usd=entry.cost_effect_usd,
            latency_ms=entry.latency_ms,
            cached=entry.cached,
            replayed=entry.replayed,
        ),
        totals=runtime.totals_through_entry(
            project_id=batch.project_id,
            run_id=batch.run_id,
            invocation_id=item.invocation_id,
        ),
        ledger_locator=(f"projects/{batch.project_id}/runs/{batch.run_id}/model_nodes/ledger"),
        recording_locator=recording_file.relative_to(outputs).as_posix(),
        blockers=entry.blockers,
        recovered_without_provider=True,
        generation_envelope=entry.intent.profile.generation.model_dump(mode="json"),
        admission_budget=entry.intent.profile.admission.model_dump(mode="json"),
        cumulative_project_budget=(entry.intent.profile.cumulative_project.model_dump(mode="json")),
    )
    _write_new_json(receipt_file, receipt.model_dump(mode="json"))
    quality = item.reference_quality_qualification
    quality_receipt = (
        None
        if quality is None
        else _binding(root, _bound_batch_file(root, quality.qualification_receipt))
    )
    return GroundedAbstractionBridgeAdmission(
        ordinal=item.ordinal,
        input_id=item.input_id,
        source_group_id=item.source_group_id,
        source_domain=planned.source_domain,
        decision_family=planned.decision_family,
        invocation_id=item.invocation_id,
        provider=batch.provider,
        model=batch.model,
        backend_mode=entry.intent.backend_mode.value,
        runtime_config=_binding(root, runtime_config_file),
        ledger_entry=ledger_binding,
        raw_recording=_binding(root, recording_file),
        accepted_result=_binding(root, result_file),
        derived_runtime_receipt=_binding(root, receipt_file),
        runtime_entry_sha256=entry.entry_sha256,
        accepted_result_sha256=entry.result_sha256,
        raw_recording_sha256=entry.recording_sha256,
        source_projection_sha256=node_input.source_projection_sha256,
        source_quality_status=(
            "not-formally-qualified"
            if quality is None
            else "ai-operational-qualified"
        ),
        source_quality_missing_reason=(
            "no-reference-quality-qualification-bound"
            if quality is None
            else None
        ),
        reference_quality_qualification=quality_receipt,
        reference_quality_report_sha256=(
            None if quality is None else quality.qualification_report_sha256
        ),
        operational_reference_quality_qualification_bound=(quality is not None),
    )


def _load_batch(path: Path) -> TasteAbstractionRuntimeBatch:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Taste abstraction BATCH must be a JSON object")
    recorded = payload.pop("batch_sha256", None)
    batch = TasteAbstractionRuntimeBatch.model_validate(payload)
    if recorded != batch.batch_sha256:
        raise ValueError("Taste abstraction BATCH semantic hash mismatch")
    return batch


def _verify_quality_qualified_subset(
    *,
    root: Path,
    outputs: Path,
    batch: TasteAbstractionRuntimeBatch,
    plan_file: Path,
    plan_inputs: tuple[PilotAbstractionInputRecord, ...],
) -> None:
    """Verify schema-1.1 coverage and every retained AI-only qualification."""

    if (
        batch.reference_quality_batch is None
        or batch.reference_quality_batch_sha256 is None
        or batch.planned_source_count != len(plan_inputs)
        or batch.eligible_source_count != len(batch.items)
        or batch.excluded_source_count != len(plan_inputs) - len(batch.items)
    ):
        raise ValueError("qualified abstraction BATCH coverage counts differ from its plan")
    quality_batch_file = _bound_batch_file(root, batch.reference_quality_batch)
    payload = json.loads(quality_batch_file.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("reference-quality BATCH must be a JSON object")
    recorded_quality_sha256 = payload.pop("batch_sha256", None)
    quality_batch = TasteReferenceQualityRuntimeBatch.model_validate(payload)
    if (
        recorded_quality_sha256 != quality_batch.batch_sha256
        or batch.reference_quality_batch_sha256 != quality_batch.batch_sha256
        or quality_batch.project_id != batch.project_id
        or quality_batch.pilot_plan_sha256 != batch.pilot_plan_sha256
        or len(quality_batch.items) != len(plan_inputs)
    ):
        raise ValueError("qualified abstraction BATCH binds another quality batch")
    quality_plan_file = _regular_file(root, quality_batch.pilot_plan.locator)
    if (
        quality_plan_file != plan_file
        or _sha256_file(quality_plan_file) != quality_batch.pilot_plan.file_sha256
    ):
        raise ValueError("reference-quality BATCH binds another pilot-plan file")

    expected_plan_ordinals: list[int] = []
    for item in batch.items:
        qualification = item.reference_quality_qualification
        if item.plan_ordinal is None or qualification is None:
            raise ValueError("qualified abstraction item lacks plan/quality provenance")
        plan_ordinal = item.plan_ordinal
        if plan_ordinal > len(plan_inputs):
            raise ValueError("qualified abstraction plan ordinal is out of range")
        planned = plan_inputs[plan_ordinal - 1]
        planned_input_file = _regular_file(plan_file.parent, planned.input_file.locator)
        if _sha256_file(planned_input_file) != planned.input_file.file_sha256:
            raise ValueError("qualified abstraction pilot input file hash drifted")
        planned_input = TasteAbstractionInput.model_validate_json(
            planned_input_file.read_bytes()
        )
        quality_item = quality_batch.items[plan_ordinal - 1]
        if (
            item.input_id != planned.input_id
            or item.source_group_id != planned.source_group_id
            or item.source_projection_sha256 != planned.source_projection_sha256
            or quality_item.ordinal != plan_ordinal
            or quality_item.input_id != item.input_id
            or quality_item.source_group_id != item.source_group_id
            or quality_item.precedent_projection_sha256
            != item.source_projection_sha256
            or qualification.quality_batch_ordinal != quality_item.ordinal
            or qualification.screening_id != quality_item.screening_id
            or qualification.source_id != planned_input.source_id
            or qualification.quality_source_projection_sha256
            != quality_item.source_projection_sha256
        ):
            raise ValueError("qualified abstraction item differs from plan/quality batch")

        receipt_file = _bound_batch_file(root, qualification.qualification_receipt)
        receipt_payload = json.loads(receipt_file.read_text(encoding="utf-8"))
        if not isinstance(receipt_payload, dict):
            raise ValueError("reference-quality qualification must be a JSON object")
        recorded_report_sha256 = receipt_payload.pop("report_sha256", None)
        report = ReferenceQualityQualification.model_validate(receipt_payload)
        ledger_file = _bound_batch_file(root, qualification.quality_ledger)
        expected_ledger_file = _regular_file(outputs, report.ledger_locator)
        verified = reference_quality_from_ledger(
            report.ledger_locator,
            evidence_root=outputs,
        )
        entry, _, _ = load_verified_taste_abstraction_ledger(
            report.ledger_locator,
            evidence_root=outputs,
        )
        if (
            recorded_report_sha256 != report.report_sha256
            or report != compile_reference_quality_qualification(verified)
            or report.verdict is not ReferenceQualityVerdict.QUALIFY
            or not report.qualified_for_human_review
            or report.report_sha256 != qualification.qualification_report_sha256
            or report.screening_id != qualification.screening_id
            or report.source_id != qualification.source_id
            or report.proposal_sha256 != qualification.proposal_sha256
            or report.source_projection_sha256
            != qualification.quality_source_projection_sha256
            or report.source_content_sha256
            != qualification.quality_source_projection_sha256
            or report.invocation_id != quality_item.invocation_id
            or ledger_file != expected_ledger_file
            or report.ledger_sha256 != qualification.quality_ledger.file_sha256
            or entry.intent.project_id != quality_batch.project_id
            or entry.intent.run_id != quality_batch.run_id
            or entry.intent.project_revision != quality_batch.project_revision
            or entry.intent.invocation_id != quality_item.invocation_id
        ):
            raise ValueError("qualified abstraction receipt differs from its verified ledger")
        expected_plan_ordinals.append(plan_ordinal)
    if expected_plan_ordinals != sorted(set(expected_plan_ordinals)):
        raise ValueError("qualified abstraction subset does not retain unique plan order")


def _verify_batch_sources(root: Path, batch: TasteAbstractionRuntimeBatch) -> None:
    profile_file = _bound_batch_file(root, batch.profile_set)
    profiles = load_model_node_profile_set(profile_file)
    try:
        profile = profiles.profiles[batch.profile_id]
    except KeyError as exc:
        raise ValueError("Taste abstraction BATCH profile is absent") from exc
    if (
        profiles.source_sha256 != batch.profile_set.file_sha256
        or profile.fingerprint != batch.profile_fingerprint
        or (profile.provider, profile.model) != (batch.provider, batch.model)
    ):
        raise ValueError("Taste abstraction BATCH profile binding mismatch")
    _bound_batch_file(root, batch.backend_config)


def _missing_exclusion(
    item: TasteAbstractionBatchItem,
    planned: PilotAbstractionInputRecord,
) -> GroundedAbstractionBridgeExclusion:
    return GroundedAbstractionBridgeExclusion(
        ordinal=item.ordinal,
        input_id=item.input_id,
        source_group_id=item.source_group_id,
        source_domain=planned.source_domain,
        decision_family=planned.decision_family,
        invocation_id=item.invocation_id,
        disposition="not-executed",
        reason_details=("no committed model-node ledger entry",),
    )


def _outcome_exclusion(
    *,
    root: Path,
    outputs: Path,
    item: TasteAbstractionBatchItem,
    planned: PilotAbstractionInputRecord,
    entry: RuntimeLedgerEntry,
    binding: AIAbstractionFileBinding,
) -> GroundedAbstractionBridgeExclusion:
    allowed = {
        RuntimeOutcome.REJECTED: "rejected",
        RuntimeOutcome.FAILED: "failed",
        RuntimeOutcome.NOT_APPLICABLE: "not-applicable",
        RuntimeOutcome.PLANNED: "planned-no-execution",
    }
    try:
        disposition = allowed[entry.outcome]
    except KeyError as exc:
        raise ValueError("committed BATCH entry has an unsupported non-accepted outcome") from exc
    details = tuple(entry.blockers)
    failure_binding: AIAbstractionFileBinding | None = None
    backend_started = False
    unknown_cost = False
    if entry.outcome is RuntimeOutcome.REJECTED and entry.result is not None:
        result = NodeResult[GroundedTasteCaseAbstraction].model_validate(entry.result)
        details = tuple(result.rejection_reasons) or ("grounded proposal rejected",)
    elif entry.outcome is RuntimeOutcome.FAILED:
        failure_file = _archived_failure_path(outputs, entry)
        failure = json.loads(failure_file.read_text(encoding="utf-8"))
        if (
            not isinstance(failure, dict)
            or failure.get("invocation_id") != entry.intent.invocation_id
        ):
            raise ValueError("archived abstraction failure binds another invocation")
        backend_started = failure.get("backend_may_have_started") is True
        unknown_cost = failure.get("unknown_cost") is True
        failure_binding = _binding(root, failure_file)
        details = tuple(entry.blockers) or ("model-node invocation failed",)
    if not details:
        details = (f"runtime outcome: {entry.outcome.value}",)
    return GroundedAbstractionBridgeExclusion(
        ordinal=item.ordinal,
        input_id=item.input_id,
        source_group_id=item.source_group_id,
        source_domain=planned.source_domain,
        decision_family=planned.decision_family,
        invocation_id=item.invocation_id,
        disposition=disposition,
        ledger_entry=binding,
        runtime_entry_sha256=entry.entry_sha256,
        failure_receipt=failure_binding,
        backend_may_have_started=backend_started,
        unknown_cost=unknown_cost,
        reason_details=details,
    )


def _archived_failure_path(outputs: Path, entry: RuntimeLedgerEntry) -> Path:
    attempts = _within_root(
        outputs,
        Path(
            "projects",
            entry.intent.project_id,
            "runs",
            entry.intent.run_id,
            "model_nodes",
            "attempts",
        ),
        must_exist=True,
    )
    matches = sorted(attempts.glob(f"{entry.intent.invocation_id}--*/failure.json"))
    if len(matches) != 1:
        raise ValueError("failed abstraction must bind one archived failure receipt")
    return _regular_file(outputs, matches[0])


def _ledger_path(outputs: Path, entry: RuntimeLedgerEntry) -> Path:
    return _regular_file(
        outputs,
        Path(
            "projects",
            entry.intent.project_id,
            "runs",
            entry.intent.run_id,
            "model_nodes",
            "ledger",
            f"{entry.index:08d}__{entry.intent.invocation_id}.json",
        ),
    )


def _recording_path(outputs: Path, entry: RuntimeLedgerEntry) -> Path:
    return _regular_file(
        outputs,
        Path(
            "projects",
            entry.intent.project_id,
            "runs",
            entry.intent.run_id,
            "model_nodes",
            "recordings",
            f"{entry.intent.invocation_id}.jsonl",
        ),
    )


def _bound_batch_file(root: Path, binding: TasteAbstractionBatchFile) -> Path:
    path = _regular_file(root, binding.locator)
    if _sha256_file(path) != binding.file_sha256:
        raise ValueError("Taste abstraction BATCH file binding mismatch")
    return path


def _bound_file(root: Path, binding: AIAbstractionFileBinding) -> Path:
    path = _regular_file(root, binding.path)
    if _sha256_file(path) != binding.sha256:
        raise ValueError("AI abstraction bridge file binding mismatch")
    return path


def _regular_file(root: Path, value: str | Path) -> Path:
    path = _within_root(root, value, must_exist=True)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_INPUT_BYTES:
        raise ValueError("AI abstraction bridge input must be a bounded regular file")
    return path


def _within_root(root: Path, value: str | Path, *, must_exist: bool) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root.joinpath(*PurePosixPath(candidate.as_posix()).parts)
    if candidate.is_symlink():
        raise ValueError("AI abstraction bridge paths cannot be symlinks")
    resolved = candidate.resolve(strict=must_exist)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("AI abstraction bridge path escapes its locator root") from exc
    return resolved


def _new_target(root: Path, value: str | Path) -> Path:
    target = _within_root(root, value, must_exist=False)
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    return target


def _binding(root: Path, path: Path) -> AIAbstractionFileBinding:
    resolved = _regular_file(root, path)
    return AIAbstractionFileBinding(
        path=resolved.relative_to(root).as_posix(),
        sha256=_sha256_file(resolved),
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1_048_576):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _counts(values: Iterable[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        result[value] = result.get(value, 0) + 1
    return dict(sorted(result.items()))


def _write_new_json(path: Path, value: object) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


__all__ = [
    "GroundedAbstractionBridgeAdmission",
    "GroundedAbstractionBridgeExclusion",
    "GroundedAbstractionReviewBridge",
    "prepare_ai_taste_abstraction_review_from_batch",
]
