"""Compile one deduplicated Track-A precedent pool into bounded model-node calls."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from scitaste.evaluation.taste_mechanism_pilot import (
    PilotAbstractionInputRecord,
    load_taste_mechanism_pilot_plan,
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
from scitaste.model_nodes.runtime_config import LiveRuntimeBackend, ModelNodeRuntimeConfig
from scitaste.project import ProjectRuntime
from scitaste.taste.semantic_models import GROUNDED_TASTE_ABSTRACTION_NODE, TasteAbstractionInput

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_INPUT_BYTES = 2 * 1_048_576


class TasteAbstractionBatchFile(BaseModel):
    model_config = _CONFIG

    locator: str = Field(min_length=1, max_length=2_000)
    file_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def locator_is_safe(self) -> TasteAbstractionBatchFile:
        _safe_locator(self.locator)
        return self


class TasteAbstractionBatchItem(BaseModel):
    model_config = _CONFIG

    ordinal: int = Field(gt=0, le=20)
    input_id: str = Field(pattern=_ID)
    source_group_id: str = Field(pattern=_ID)
    source_projection_sha256: str = Field(pattern=_SHA256)
    invocation_id: str = Field(pattern=_ID)
    runtime_config: TasteAbstractionBatchFile


class TasteAbstractionRuntimeBatch(BaseModel):
    """Exact no-call manifest consumed by repeated ``model-node runtime execute`` calls."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
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
    items: tuple[TasteAbstractionBatchItem, ...] = Field(min_length=1, max_length=20)
    unique_source_group_count: int = Field(gt=0, le=20)
    compiled_at: datetime
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    human_validity_claim_allowed: Literal[False] = False
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
        return self

    @computed_field
    @property
    def batch_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"batch_sha256"}))


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
) -> TasteAbstractionRuntimeBatch:
    """Compile, but never execute, one call per unique precedent episode."""

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
    if len(plan.abstraction_inputs) > profile.cumulative_project.max_invocations:
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
        for ordinal, record in enumerate(plan.abstraction_inputs, 1):
            abstraction_input = _load_abstraction_input(plan_file.parent, record)
            invocation_id = f"track-a-abstraction-{ordinal:02d}-{record.input_id}"
            runtime_config = ModelNodeRuntimeConfig(
                node_name=GROUNDED_TASTE_ABSTRACTION_NODE,
                node_input=abstraction_input.model_dump(mode="json"),
                state_projection=ImmutableStateProjection(
                    project_id=project_id,
                    state_snapshot_id=plan.plan_sha256,
                    state_revision=expected_project_revision,
                    stage="TASTE_ABSTRACTION",
                    metadata={
                        "pilot_plan_sha256": plan.plan_sha256,
                        "input_id": record.input_id,
                        "source_group_id": record.source_group_id,
                        "source_projection_sha256": record.source_projection_sha256,
                        "natural_pilot": True,
                        "formal_evidence_eligible": False,
                        "reviewer_kind": "ai",
                        "not_human_review": True,
                    },
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
            _write_json(runtime_path, runtime_config.model_dump(mode="json"))
            items.append(
                TasteAbstractionBatchItem(
                    ordinal=ordinal,
                    input_id=record.input_id,
                    source_group_id=record.source_group_id,
                    source_projection_sha256=record.source_projection_sha256,
                    invocation_id=invocation_id,
                    runtime_config=TasteAbstractionBatchFile(
                        locator=_relative(target / relative, root),
                        file_sha256=_sha256_file(runtime_path),
                    ),
                )
            )
        batch = TasteAbstractionRuntimeBatch(
            batch_id=f"track-a-abstraction-batch-{plan.plan_sha256[:20]}",
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
            compiled_at=compiled_at or datetime.now(UTC),
        )
        _write_json(workspace / "BATCH.json", batch.model_dump(mode="json"))
        os.replace(workspace, target)
    return batch


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
    "TasteAbstractionRuntimeBatch",
    "compile_taste_abstraction_runtime_batch",
]
