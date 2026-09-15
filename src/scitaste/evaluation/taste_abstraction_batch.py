"""Compile one deduplicated Track-A precedent pool into bounded model-node calls."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from scitaste.evaluation.taste_mechanism_pilot import (
    PilotAbstractionInputRecord,
    load_taste_mechanism_pilot_plan,
)
from scitaste.evaluation.taste_reference_quality_batch import (
    TasteReferenceQualityBatchItem,
    TasteReferenceQualityRuntimeBatch,
)
from scitaste.model_nodes.facade import ImmutableStateProjection
from scitaste.model_nodes.models import NodePolicy
from scitaste.model_nodes.openai_compatible import (
    load_structured_openai_compatible_config,
)
from scitaste.model_nodes.profiles import (
    load_model_node_profile_set,
    validate_profile_binding,
)
from scitaste.model_nodes.runtime import ModelNodeTrigger
from scitaste.model_nodes.runtime_config import (
    LiveRuntimeBackend,
    ModelNodeRuntimeConfig,
    load_model_node_runtime_config,
)
from scitaste.project import ProjectRuntime
from scitaste.taste.reference_quality import (
    REFERENCE_QUALITY_NODE,
    ReferenceQualityInput,
    ReferenceQualityQualification,
    ReferenceQualityVerdict,
    compile_reference_quality_qualification,
)
from scitaste.taste.semantic import (
    load_verified_taste_abstraction_ledger,
    reference_quality_from_ledger,
)
from scitaste.taste.semantic_models import GROUNDED_TASTE_ABSTRACTION_NODE, TasteAbstractionInput

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_INPUT_BYTES = 2 * 1_048_576


class _FileBinding(Protocol):
    locator: str
    file_sha256: str


class TasteAbstractionBatchFile(BaseModel):
    model_config = _CONFIG

    locator: str = Field(min_length=1, max_length=2_000)
    file_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def locator_is_safe(self) -> TasteAbstractionBatchFile:
        _safe_locator(self.locator)
        return self


class TasteAbstractionQualityQualification(BaseModel):
    """One AI-only quality receipt replayed against its canonical runtime ledger."""

    model_config = _CONFIG

    quality_batch_ordinal: int = Field(gt=0, le=100)
    screening_id: str = Field(pattern=_ID)
    source_id: str = Field(pattern=_ID)
    quality_source_projection_sha256: str = Field(pattern=_SHA256)
    proposal_sha256: str = Field(pattern=_SHA256)
    qualification_receipt: TasteAbstractionBatchFile
    qualification_report_sha256: str = Field(pattern=_SHA256)
    quality_ledger: TasteAbstractionBatchFile
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    operational_abstraction_qualification: Literal[True] = True
    formal_human_validity: Literal[False] = False


class TasteAbstractionBatchItem(BaseModel):
    model_config = _CONFIG

    ordinal: int = Field(gt=0, le=20)
    plan_ordinal: int | None = Field(default=None, gt=0, le=20)
    input_id: str = Field(pattern=_ID)
    source_group_id: str = Field(pattern=_ID)
    source_projection_sha256: str = Field(pattern=_SHA256)
    invocation_id: str = Field(pattern=_ID)
    runtime_config: TasteAbstractionBatchFile
    reference_quality_qualification: TasteAbstractionQualityQualification | None = None


class TasteAbstractionRuntimeBatch(BaseModel):
    """Exact no-call manifest consumed by repeated ``model-node runtime execute`` calls."""

    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1"] = "1.0"
    batch_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    project_revision: int = Field(ge=0)
    run_id: str = Field(pattern=_ID)
    pilot_plan: TasteAbstractionBatchFile
    pilot_plan_sha256: str = Field(pattern=_SHA256)
    profile_set: TasteAbstractionBatchFile
    profile_id: str = Field(pattern=_ID)
    profile_fingerprint: str = Field(pattern=_SHA256)
    backend_config: TasteAbstractionBatchFile
    provider: str = Field(min_length=1, max_length=200)
    model: str = Field(min_length=1, max_length=300)
    items: tuple[TasteAbstractionBatchItem, ...] = Field(max_length=20)
    unique_source_group_count: int = Field(ge=0, le=20)
    reference_quality_batch: TasteAbstractionBatchFile | None = None
    reference_quality_batch_sha256: str | None = Field(default=None, pattern=_SHA256)
    planned_source_count: int | None = Field(default=None, ge=0, le=20)
    eligible_source_count: int | None = Field(default=None, ge=0, le=20)
    excluded_source_count: int | None = Field(default=None, ge=0, le=20)
    quality_gate_mode: Literal["ai-only-operational"] | None = None
    compiled_at: datetime
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    human_validity_claim_allowed: Literal[False] = False
    formal_human_validity: Literal[False] = False
    model_calls_performed: Literal[False] = False
    api_calls_performed: Literal[False] = False
    automatic_retry_permitted: Literal[False] = False

    @model_validator(mode="after")
    def batch_is_deduplicated_and_bounded(self) -> TasteAbstractionRuntimeBatch:
        if self.compiled_at.utcoffset() is None:
            raise ValueError("Taste abstraction batch timestamp must include a timezone")
        if tuple(item.ordinal for item in self.items) != tuple(range(1, len(self.items) + 1)):
            raise ValueError("Taste abstraction batch ordinals must be contiguous")
        for values, label in (
            ([item.input_id for item in self.items], "input IDs"),
            ([item.source_group_id for item in self.items], "source groups"),
            ([item.invocation_id for item in self.items], "invocation IDs"),
            ([item.runtime_config.locator for item in self.items], "runtime configs"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"Taste abstraction batch repeats {label}")
        if self.unique_source_group_count != len(self.items):
            raise ValueError("Taste abstraction batch source-group count differs")
        if self.schema_version == "1.0":
            if any(item.reference_quality_qualification is not None for item in self.items):
                raise ValueError("schema 1.0 cannot bind reference-quality qualifications")
            return self
        if self.reference_quality_batch is None or self.reference_quality_batch_sha256 is None:
            raise ValueError("schema 1.1 requires a bound reference-quality batch")
        if self.quality_gate_mode != "ai-only-operational":
            raise ValueError("schema 1.1 requires the AI-only operational quality lane")
        counts = (
            self.planned_source_count,
            self.eligible_source_count,
            self.excluded_source_count,
        )
        if any(value is None for value in counts):
            raise ValueError("schema 1.1 requires planned, eligible, and excluded counts")
        planned, eligible, excluded = counts
        assert planned is not None and eligible is not None and excluded is not None
        if eligible != len(self.items) or planned != eligible + excluded:
            raise ValueError("Taste abstraction quality-gate counts are inconsistent")
        if any(item.reference_quality_qualification is None for item in self.items):
            raise ValueError("every eligible abstraction must bind its qualification receipt")
        plan_ordinals = [item.plan_ordinal for item in self.items]
        if any(value is None for value in plan_ordinals):
            raise ValueError("every quality-gated abstraction must retain its plan ordinal")
        if plan_ordinals != sorted(plan_ordinals):
            raise ValueError("quality-gated abstraction sources must retain plan order")
        return self

    @computed_field
    @property
    def batch_sha256(self) -> str:
        payload = self.model_dump(mode="json", exclude={"batch_sha256"})
        if self.schema_version == "1.0":
            for field in (
                "reference_quality_batch",
                "reference_quality_batch_sha256",
                "planned_source_count",
                "eligible_source_count",
                "excluded_source_count",
                "quality_gate_mode",
                "formal_human_validity",
            ):
                payload.pop(field, None)
            for item in payload["items"]:
                item.pop("plan_ordinal", None)
                item.pop("reference_quality_qualification", None)
        return _canonical_sha256(payload)


def compile_taste_abstraction_runtime_batch(
    *,
    locator_root: str | Path,
    outputs_root: str | Path,
    pilot_plan_path: str | Path,
    profile_set_path: str | Path,
    profile_id: str,
    backend_config_path: str | Path,
    project_id: str,
    run_id: str,
    expected_project_revision: int,
    output_dir: str | Path,
    compiled_at: datetime | None = None,
    reference_quality_batch_path: str | Path | None = None,
    reference_quality_qualification_paths: Sequence[str | Path] = (),
) -> TasteAbstractionRuntimeBatch:
    """Compile, but never execute, one call per eligible unique precedent episode.

    Calls without reference-quality arguments retain the legacy schema-1.0
    behavior.  Supplying ``reference_quality_batch_path`` activates the
    fail-closed schema-1.1 lane: only sources with verified ``qualify`` receipts
    are materialized, while every other planned source is counted as excluded.
    """

    root = Path(locator_root).resolve(strict=True)
    outputs = _within_root(root, outputs_root, must_exist=True)
    plan_file = _within_root(root, pilot_plan_path, must_exist=True)
    profile_file = _within_root(root, profile_set_path, must_exist=True)
    backend_file = _within_root(root, backend_config_path, must_exist=True)
    target = _within_root(root, output_dir, must_exist=False)
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)

    plan_inspection = load_taste_mechanism_pilot_plan(plan_file, locator_root=root)
    plan = plan_inspection.plan
    if plan.project_id != project_id:
        raise ValueError("Taste abstraction batch project differs from the pilot plan")
    if plan.unique_abstraction_invocation_count != len(plan.abstraction_inputs):
        raise ValueError("Taste abstraction plan did not deduplicate precedent invocations")

    if reference_quality_batch_path is None and reference_quality_qualification_paths:
        raise ValueError("reference-quality receipts require their originating batch")
    quality_batch: TasteReferenceQualityRuntimeBatch | None = None
    quality_batch_file: Path | None = None
    qualifications: dict[str, TasteAbstractionQualityQualification] = {}
    if reference_quality_batch_path is not None:
        quality_batch_file = _bounded_file(
            root,
            reference_quality_batch_path,
            max_bytes=_MAX_INPUT_BYTES,
        )
        quality_batch = _load_reference_quality_batch(quality_batch_file)
        qualifications = _verify_reference_quality_gate(
            root=root,
            outputs=outputs,
            plan_file=plan_file,
            plan_inputs=plan.abstraction_inputs,
            project_id=project_id,
            quality_batch=quality_batch,
            qualification_paths=reference_quality_qualification_paths,
        )
    selected_records = tuple(
        (plan_ordinal, record, qualifications.get(record.input_id))
        for plan_ordinal, record in enumerate(plan.abstraction_inputs, 1)
        if quality_batch is None or record.input_id in qualifications
    )

    snapshot = ProjectRuntime(outputs).open(project_id)
    if snapshot.revision != expected_project_revision:
        raise ValueError(
            f"stale project revision {expected_project_revision}; current is {snapshot.revision}"
        )
    if run_id not in snapshot.run_locators:
        raise ValueError(f"unknown project run {run_id!r}")

    loaded_profiles = load_model_node_profile_set(profile_file)
    if not loaded_profiles.profile_set.live_enabled:
        raise ValueError("Taste abstraction profile set does not permit live execution")
    try:
        profile = loaded_profiles.profiles[profile_id]
    except KeyError as exc:
        raise ValueError(f"unknown Taste abstraction profile {profile_id!r}") from exc
    if GROUNDED_TASTE_ABSTRACTION_NODE not in profile.allowed_node_names:
        raise ValueError("profile does not permit grounded Taste abstraction")
    if not profile.live_execution_permitted:
        raise ValueError("profile does not permit live model-node execution")
    if len(selected_records) > profile.cumulative_project.max_invocations:
        raise ValueError("deduplicated abstraction batch exceeds the profile call ceiling")

    backend_config = load_structured_openai_compatible_config(backend_file)
    if not backend_config.live_enabled:
        raise ValueError("backend config must explicitly enable live execution")
    if backend_config.max_retries != 0:
        raise ValueError("Track-A abstraction batch prohibits automatic retries")
    if not backend_config.pricing_confirmed or backend_config.pricing is None:
        raise ValueError("Track-A live abstraction requires explicit pricing provenance")
    if (backend_config.provider, backend_config.model) != (profile.provider, profile.model):
        raise ValueError("backend provider/model differs from the selected profile")

    policy = NodePolicy(
        policy_id=f"{profile_id}-track-a-pilot",
        enabled=True,
        allowed_node_names=[GROUNDED_TASTE_ABSTRACTION_NODE],
        expected_backend=profile.provider,
        expected_model=profile.model,
        allowed_tool_names=list(profile.admission.allowed_tool_names),
        allowed_action_types=[],
        max_request_bytes=profile.admission.max_request_bytes,
        max_input_tokens=profile.admission.max_input_tokens,
        max_output_tokens=profile.admission.max_output_tokens,
        max_total_tokens=profile.admission.max_total_tokens,
        max_api_cost_usd=profile.cumulative_project.max_api_cost_usd,
        max_latency_ms=profile.admission.max_latency_ms,
    )
    validate_profile_binding(profile, policy, node_name=GROUNDED_TASTE_ABSTRACTION_NODE)

    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{target.name}.", dir=target.parent) as temporary:
        workspace = Path(temporary)
        configs = workspace / "runtime-configs"
        configs.mkdir()
        items: list[TasteAbstractionBatchItem] = []
        for ordinal, (plan_ordinal, record, qualification) in enumerate(selected_records, 1):
            abstraction_input = _load_abstraction_input(plan_file.parent, record)
            gate_identity = "" if quality_batch is None else f"-q{quality_batch.batch_sha256[:8]}"
            invocation_id = (
                f"track-a-{plan.plan_sha256[:10]}{gate_identity}-abstraction-"
                f"{plan_ordinal:02d}-{record.input_id}"
            )
            runtime_config = ModelNodeRuntimeConfig(
                node_name=GROUNDED_TASTE_ABSTRACTION_NODE,
                node_input=abstraction_input.model_dump(mode="json"),
                state_projection=ImmutableStateProjection(
                    project_id=project_id,
                    state_snapshot_id=abstraction_input.source_projection_sha256,
                    state_revision=expected_project_revision,
                    stage=abstraction_input.stage,
                    evidence_ids=(abstraction_input.source_id,),
                    # The model sees only the canonical TasteAbstractionInput. Pilot,
                    # relation, and source-group metadata remain controller-side.
                    metadata={},
                ),
                trigger=ModelNodeTrigger(
                    trigger_id=invocation_id,
                    reason=(
                        "Distill one unique natural-source precedent for the AI-only Track-A "
                        "mechanism pilot; proposal remains untrusted until independent AI review."
                    ),
                ),
                policy=policy,
                backend=LiveRuntimeBackend(config=backend_config),
                seed=0,
            )
            relative = Path("runtime-configs") / f"{ordinal:02d}-{record.input_id}.json"
            runtime_path = workspace / relative
            _write_json(
                runtime_path,
                runtime_config.model_dump(mode="json", exclude_computed_fields=True),
            )
            items.append(
                TasteAbstractionBatchItem(
                    ordinal=ordinal,
                    plan_ordinal=(None if quality_batch is None else plan_ordinal),
                    input_id=record.input_id,
                    source_group_id=record.source_group_id,
                    source_projection_sha256=record.source_projection_sha256,
                    invocation_id=invocation_id,
                    runtime_config=TasteAbstractionBatchFile(
                        locator=_relative(target / relative, root),
                        file_sha256=_sha256_file(runtime_path),
                    ),
                    reference_quality_qualification=qualification,
                )
            )
        batch = TasteAbstractionRuntimeBatch(
            schema_version="1.0" if quality_batch is None else "1.1",
            batch_id=(
                f"track-a-abstraction-batch-{plan.plan_sha256[:20]}"
                if quality_batch is None
                else (
                    f"track-a-qualified-abstraction-{plan.plan_sha256[:10]}-"
                    f"{quality_batch.batch_sha256[:10]}"
                )
            ),
            project_id=project_id,
            project_revision=expected_project_revision,
            run_id=run_id,
            pilot_plan=TasteAbstractionBatchFile(
                locator=_relative(plan_file, root),
                file_sha256=_sha256_file(plan_file),
            ),
            pilot_plan_sha256=plan.plan_sha256,
            profile_set=TasteAbstractionBatchFile(
                locator=_relative(profile_file, root),
                file_sha256=loaded_profiles.source_sha256,
            ),
            profile_id=profile_id,
            profile_fingerprint=profile.fingerprint,
            backend_config=TasteAbstractionBatchFile(
                locator=_relative(backend_file, root),
                file_sha256=_sha256_file(backend_file),
            ),
            provider=profile.provider,
            model=profile.model,
            items=tuple(items),
            unique_source_group_count=len(items),
            reference_quality_batch=(
                None
                if quality_batch_file is None
                else TasteAbstractionBatchFile(
                    locator=_relative(quality_batch_file, root),
                    file_sha256=_sha256_file(quality_batch_file),
                )
            ),
            reference_quality_batch_sha256=(
                None if quality_batch is None else quality_batch.batch_sha256
            ),
            planned_source_count=(None if quality_batch is None else len(plan.abstraction_inputs)),
            eligible_source_count=(None if quality_batch is None else len(items)),
            excluded_source_count=(
                None if quality_batch is None else len(plan.abstraction_inputs) - len(items)
            ),
            quality_gate_mode=(None if quality_batch is None else "ai-only-operational"),
            compiled_at=compiled_at or datetime.now(UTC),
        )
        _write_json(workspace / "BATCH.json", batch.model_dump(mode="json"))
        os.replace(workspace, target)
    return batch


def _load_reference_quality_batch(path: Path) -> TasteReferenceQualityRuntimeBatch:
    if path.is_symlink() or not path.is_file() or not 1 <= path.stat().st_size <= _MAX_INPUT_BYTES:
        raise ValueError("reference-quality batch must be a bounded regular file")
    try:
        payload = json.loads(path.read_bytes())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("reference-quality batch is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("reference-quality batch must be a JSON object")
    recorded = payload.pop("batch_sha256", None)
    batch = TasteReferenceQualityRuntimeBatch.model_validate(payload)
    if recorded != batch.batch_sha256:
        raise ValueError("reference-quality batch semantic hash mismatch")
    return batch


def _verify_reference_quality_gate(
    *,
    root: Path,
    outputs: Path,
    plan_file: Path,
    plan_inputs: tuple[PilotAbstractionInputRecord, ...],
    project_id: str,
    quality_batch: TasteReferenceQualityRuntimeBatch,
    qualification_paths: Sequence[str | Path],
) -> dict[str, TasteAbstractionQualityQualification]:
    """Replay every supplied receipt and return only operationally qualified inputs."""

    if quality_batch.project_id != project_id:
        raise ValueError("reference-quality batch belongs to another project")
    bound_plan = _bound_file(root, quality_batch.pilot_plan)
    if bound_plan != plan_file or quality_batch.pilot_plan_sha256 != (
        load_taste_mechanism_pilot_plan(plan_file, locator_root=root).plan.plan_sha256
    ):
        raise ValueError("reference-quality batch differs from the abstraction pilot plan")
    if len(quality_batch.items) != len(plan_inputs):
        raise ValueError("reference-quality batch does not cover the planned source pool")

    expected_by_invocation: dict[
        str,
        tuple[PilotAbstractionInputRecord, TasteAbstractionInput, TasteReferenceQualityBatchItem],
    ] = {}
    for plan_ordinal, (record, quality_item) in enumerate(
        zip(plan_inputs, quality_batch.items, strict=True),
        1,
    ):
        abstraction_input = _load_abstraction_input(plan_file.parent, record)
        if (
            quality_item.ordinal != plan_ordinal
            or quality_item.input_id != record.input_id
            or quality_item.source_group_id != record.source_group_id
            or quality_item.precedent_projection_sha256 != record.source_projection_sha256
            or abstraction_input.source_projection_sha256 != record.source_projection_sha256
        ):
            raise ValueError("reference-quality batch source order or plan binding differs")
        loaded_runtime = load_model_node_runtime_config(
            _bound_file(root, quality_item.runtime_config)
        )
        if loaded_runtime.source_sha256 != quality_item.runtime_config.file_sha256:
            raise ValueError("reference-quality runtime-config hash drifted")
        runtime = loaded_runtime.config
        quality_input = ReferenceQualityInput.model_validate(runtime.node_input)
        if (
            runtime.node_name != REFERENCE_QUALITY_NODE
            or runtime.trigger.trigger_id != quality_item.invocation_id
            or quality_input.screening_id != quality_item.screening_id
            or quality_input.source_id != abstraction_input.source_id
            or quality_input.source_projection_sha256 != quality_item.source_projection_sha256
            or quality_input.source_content_sha256 != quality_item.source_projection_sha256
            or runtime.state_projection.project_id != project_id
            or runtime.state_projection.state_revision != quality_batch.project_revision
            or runtime.state_projection.state_snapshot_id != quality_item.source_projection_sha256
            or runtime.state_projection.evidence_ids != (abstraction_input.source_id,)
        ):
            raise ValueError("reference-quality runtime config differs from its batch item")
        expected_by_invocation[quality_item.invocation_id] = (
            record,
            abstraction_input,
            quality_item,
        )

    seen_inputs: set[str] = set()
    qualified: dict[str, TasteAbstractionQualityQualification] = {}
    for value in qualification_paths:
        receipt_file = _bounded_file(root, value, max_bytes=_MAX_INPUT_BYTES)
        try:
            payload = json.loads(receipt_file.read_bytes())
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("reference-quality qualification is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("reference-quality qualification must be a JSON object")
        recorded_report_sha256 = payload.pop("report_sha256", None)
        report = ReferenceQualityQualification.model_validate(payload)
        if recorded_report_sha256 != report.report_sha256:
            raise ValueError("reference-quality qualification semantic hash mismatch")
        try:
            record, abstraction_input, quality_item = expected_by_invocation[report.invocation_id]
        except KeyError as exc:
            raise ValueError("reference-quality qualification is foreign to the batch") from exc
        if record.input_id in seen_inputs:
            raise ValueError("reference-quality source has more than one qualification receipt")
        seen_inputs.add(record.input_id)

        verified = reference_quality_from_ledger(
            report.ledger_locator,
            evidence_root=outputs,
        )
        entry, ledger_file, _ = load_verified_taste_abstraction_ledger(
            report.ledger_locator,
            evidence_root=outputs,
        )
        expected_report = compile_reference_quality_qualification(verified)
        if report != expected_report:
            raise ValueError("reference-quality receipt differs from its verified ledger")
        if (
            entry.intent.project_id != quality_batch.project_id
            or entry.intent.run_id != quality_batch.run_id
            or entry.intent.project_revision != quality_batch.project_revision
            or entry.intent.state_revision != quality_batch.project_revision
            or entry.intent.invocation_id != quality_item.invocation_id
            or entry.intent.context.project_id != quality_batch.project_id
            or entry.intent.context.state_snapshot_id != quality_item.source_projection_sha256
            or tuple(entry.intent.context.evidence_ids) != (abstraction_input.source_id,)
            or verified.input.screening_id != quality_item.screening_id
            or verified.input.source_id != abstraction_input.source_id
            or verified.input.source_projection_sha256 != quality_item.source_projection_sha256
            or verified.input.source_content_sha256 != quality_item.source_projection_sha256
            or report.source_projection_sha256 != quality_item.source_projection_sha256
            or report.source_content_sha256 != quality_item.source_projection_sha256
            or report.backend != quality_batch.provider
            or report.model != quality_batch.model
        ):
            raise ValueError("reference-quality receipt identity differs from plan/batch/ledger")
        if report.verdict is not ReferenceQualityVerdict.QUALIFY:
            continue
        qualified[record.input_id] = TasteAbstractionQualityQualification(
            quality_batch_ordinal=quality_item.ordinal,
            screening_id=report.screening_id,
            source_id=report.source_id,
            quality_source_projection_sha256=report.source_projection_sha256,
            proposal_sha256=report.proposal_sha256,
            qualification_receipt=TasteAbstractionBatchFile(
                locator=_relative(receipt_file, root),
                file_sha256=_sha256_file(receipt_file),
            ),
            qualification_report_sha256=report.report_sha256,
            quality_ledger=TasteAbstractionBatchFile(
                locator=_relative(ledger_file, root),
                file_sha256=report.ledger_sha256,
            ),
        )
    return qualified


def _load_abstraction_input(
    plan_root: Path, record: PilotAbstractionInputRecord
) -> TasteAbstractionInput:
    path = _within_root(plan_root, record.input_file.locator, must_exist=True)
    if _sha256_file(path) != record.input_file.file_sha256:
        raise ValueError("Taste abstraction input file hash drifted")
    if path.stat().st_size > _MAX_INPUT_BYTES:
        raise ValueError("Taste abstraction input exceeds the read ceiling")
    value = TasteAbstractionInput.model_validate_json(path.read_bytes())
    if value.source_projection_sha256 != record.source_projection_sha256 or value.domain_tags != (
        record.source_domain,
    ):
        raise ValueError("Taste abstraction input identity differs from the pilot plan")
    return value


def _bound_file(root: Path, binding: _FileBinding) -> Path:
    path = _bounded_file(root, binding.locator, max_bytes=_MAX_INPUT_BYTES)
    if _sha256_file(path) != binding.file_sha256:
        raise ValueError("bound Track-A file hash drifted")
    return path


def _bounded_file(root: Path, value: str | Path, *, max_bytes: int) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root.joinpath(*PurePosixPath(candidate.as_posix()).parts)
    if candidate.is_symlink():
        raise ValueError("Track-A evidence files must not be symlinks")
    resolved = _within_root(root, candidate, must_exist=True)
    if not resolved.is_file() or not 1 <= resolved.stat().st_size <= max_bytes:
        raise ValueError("Track-A evidence must be a bounded regular file")
    return resolved


def _safe_locator(value: str) -> None:
    if "\\" in value:
        raise ValueError("Taste abstraction locators must use POSIX separators")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("Taste abstraction locator must be normalized and relative")


def _within_root(root: Path, value: str | Path, *, must_exist: bool) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root.joinpath(*PurePosixPath(candidate.as_posix()).parts)
    resolved = candidate.resolve(strict=must_exist)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("Taste abstraction path escapes its locator root") from exc
    return resolved


def _relative(path: Path, root: Path) -> str:
    return path.resolve(strict=False).relative_to(root).as_posix()


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


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n",
        encoding="utf-8",
    )


__all__ = [
    "TasteAbstractionBatchFile",
    "TasteAbstractionBatchItem",
    "TasteAbstractionQualityQualification",
    "TasteAbstractionRuntimeBatch",
    "compile_taste_abstraction_runtime_batch",
]
