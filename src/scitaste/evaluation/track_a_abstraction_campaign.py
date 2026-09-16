"""Resume-safe execution of one frozen Track-A abstraction batch.

The batch compiler freezes one model-node invocation per eligible precedent.
This module removes the remaining operator loop: it discovers already consumed
invocations, executes only entries that do not yet exist, never retries a
terminal entry, and prepares the independent-review bridge after the batch is
closed.  Merely inspecting a campaign performs no model or API call.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from scitaste.evaluation.ai_taste_abstraction_bridge import (
    GroundedAbstractionReviewBridge,
    prepare_ai_taste_abstraction_review_from_batch,
)
from scitaste.evaluation.taste_abstraction_batch import TasteAbstractionRuntimeBatch
from scitaste.model_nodes.facade import ModelNodeFacade, ModelNodeFacadeRequest
from scitaste.model_nodes.profiles import load_model_node_profile_set
from scitaste.model_nodes.registry import first_party_node_types
from scitaste.model_nodes.runtime import (
    ModelNodeRuntime,
    RuntimeLedgerEntry,
    RuntimeOutcome,
)
from scitaste.model_nodes.runtime_config import load_model_node_runtime_config
from scitaste.project import ProjectRuntime

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_CONTROL_BYTES = 64 * 1_048_576


class TrackAAbstractionCampaignStatus(BaseModel):
    """One truthful projection of a frozen abstraction batch and its ledger."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    batch_id: str
    batch_sha256: str = Field(pattern=_SHA256)
    project_id: str
    run_id: str
    project_revision: int = Field(ge=0)
    status: Literal[
        "awaiting-live-authorization",
        "closed-no-reviewable-abstractions",
        "review-prepared",
    ]
    next_action: Literal[
        "execute-missing-abstractions",
        "freeze-empty-consumed-batch",
        "execute-independent-ai-reviews",
    ]
    planned_invocation_count: int = Field(ge=0)
    consumed_invocation_count: int = Field(ge=0)
    missing_invocation_count: int = Field(ge=0)
    accepted_invocation_count: int = Field(ge=0)
    rejected_invocation_count: int = Field(ge=0)
    failed_invocation_count: int = Field(ge=0)
    not_applicable_invocation_count: int = Field(ge=0)
    planned_without_execution_count: int = Field(ge=0)
    invocations_advanced_this_command: int = Field(ge=0)
    provider_call_upper_bound_this_command: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    known_cost_usd: float = Field(ge=0, allow_inf_nan=False)
    unknown_cost_count: int = Field(ge=0)
    review_bridge_sha256: str | None = Field(default=None, pattern=_SHA256)
    review_request_pack_locator: str | None = None
    automatic_retries_performed: Literal[0] = 0
    replacement_sampling_performed: Literal[False] = False
    human_or_expert_validity_claim_allowed: Literal[False] = False


def run_track_a_abstraction_campaign(
    *,
    locator_root: str | Path,
    outputs_root: str | Path,
    batch_path: str | Path,
    review_protocol_path: str | Path,
    review_output_dir: str | Path,
    allow_live: bool = False,
) -> TrackAAbstractionCampaignStatus:
    """Execute only missing frozen calls and materialize the review handoff.

    A terminal ledger entry is immutable regardless of whether it was accepted,
    rejected, failed, not applicable, or planned without execution.  Consequently
    a resumed command cannot silently retry, replace, or resample it.
    """

    root = Path(locator_root).resolve(strict=True)
    outputs = _within_root(root, outputs_root, must_exist=True)
    batch_file = _bounded_file(root, batch_path)
    protocol_file = _bounded_file(root, review_protocol_path)
    review_output = _within_root(root, review_output_dir, must_exist=False)
    batch = _load_batch(batch_file)

    runtime = ModelNodeRuntime(ProjectRuntime(outputs), node_types=first_party_node_types())
    entries = _batch_entries(runtime, batch)
    missing = [item for item in batch.items if item.invocation_id not in entries]
    advanced = 0
    if missing and allow_live:
        loaded_profiles = load_model_node_profile_set(
            _bound_file(root, batch.profile_set.locator, batch.profile_set.file_sha256)
        )
        try:
            profile = loaded_profiles.profiles[batch.profile_id]
        except KeyError as exc:
            raise ValueError(f"unknown Track-A profile {batch.profile_id!r}") from exc
        if profile.fingerprint != batch.profile_fingerprint:
            raise ValueError("Track-A batch profile fingerprint changed")
        facade = ModelNodeFacade(runtime)
        for item in missing:
            config_path = _bound_file(
                root,
                item.runtime_config.locator,
                item.runtime_config.file_sha256,
            )
            loaded_config = load_model_node_runtime_config(config_path)
            config = loaded_config.config
            request = ModelNodeFacadeRequest(
                project_id=batch.project_id,
                run_id=batch.run_id,
                invocation_id=item.invocation_id,
                request_id=config.request_id,
                expected_project_revision=batch.project_revision,
                node_name=config.node_name,
                node_input=config.node_input,
                state_projection=config.state_projection,
                trigger=config.trigger,
                profile=profile,
                policy=config.policy,
                backend_mode=config.backend_mode,
                seed=config.seed,
            )
            result = facade.execute(
                request,
                backend=config.build_backend(item.invocation_id),
                resume=True,
                allow_live=True,
            )
            if result.receipt.outcome is RuntimeOutcome.PLANNED:
                raise RuntimeError(
                    "live Track-A campaign produced a non-executed planned entry: "
                    f"{item.invocation_id}"
                )
            advanced += 1
        entries = _batch_entries(runtime, batch)
        missing = [item for item in batch.items if item.invocation_id not in entries]

    counts = _outcome_counts(entries.values())
    bridge: GroundedAbstractionReviewBridge | None = None
    if not missing and counts[RuntimeOutcome.ACCEPTED] > 0:
        bridge_file = review_output / "BRIDGE.json"
        if review_output.exists() or review_output.is_symlink():
            bridge = _load_bridge(bridge_file)
            if (
                bridge.project_id != batch.project_id
                or bridge.run_id != batch.run_id
                or bridge.source_batch_sha256 != batch.batch_sha256
                or bridge.source_batch.sha256 != _sha256(batch_file)
                or bridge.review_protocol.sha256 != _sha256(protocol_file)
            ):
                raise ValueError("existing Track-A review bridge belongs to another batch")
        else:
            bridge = prepare_ai_taste_abstraction_review_from_batch(
                locator_root=root,
                outputs_root=outputs,
                batch_path=batch_file,
                protocol_path=protocol_file,
                output_dir=review_output,
            )

    if missing:
        status = "awaiting-live-authorization"
        next_action = "execute-missing-abstractions"
    elif bridge is None:
        status = "closed-no-reviewable-abstractions"
        next_action = "freeze-empty-consumed-batch"
    else:
        status = "review-prepared"
        next_action = "execute-independent-ai-reviews"

    selected = tuple(entries.values())
    return TrackAAbstractionCampaignStatus(
        batch_id=batch.batch_id,
        batch_sha256=batch.batch_sha256,
        project_id=batch.project_id,
        run_id=batch.run_id,
        project_revision=batch.project_revision,
        status=status,
        next_action=next_action,
        planned_invocation_count=len(batch.items),
        consumed_invocation_count=len(entries),
        missing_invocation_count=len(missing),
        accepted_invocation_count=counts[RuntimeOutcome.ACCEPTED],
        rejected_invocation_count=counts[RuntimeOutcome.REJECTED],
        failed_invocation_count=counts[RuntimeOutcome.FAILED],
        not_applicable_invocation_count=counts[RuntimeOutcome.NOT_APPLICABLE],
        planned_without_execution_count=counts[RuntimeOutcome.PLANNED],
        invocations_advanced_this_command=advanced,
        provider_call_upper_bound_this_command=advanced,
        input_tokens=sum(item.input_tokens for item in selected),
        output_tokens=sum(item.output_tokens for item in selected),
        known_cost_usd=sum(item.cost_effect_usd or 0.0 for item in selected),
        unknown_cost_count=sum(item.cost_effect_usd is None for item in selected),
        review_bridge_sha256=None if bridge is None else bridge.bridge_sha256,
        review_request_pack_locator=(None if bridge is None else bridge.review_request_pack.path),
    )


def _batch_entries(
    runtime: ModelNodeRuntime,
    batch: TasteAbstractionRuntimeBatch,
) -> dict[str, RuntimeLedgerEntry]:
    entries: dict[str, RuntimeLedgerEntry] = {}
    for item in batch.items:
        entry = runtime.find_entry(
            project_id=batch.project_id,
            run_id=batch.run_id,
            invocation_id=item.invocation_id,
        )
        if entry is not None:
            entries[item.invocation_id] = entry
    return entries


def _outcome_counts(entries: Iterable[RuntimeLedgerEntry]) -> dict[RuntimeOutcome, int]:
    counts = {item: 0 for item in RuntimeOutcome}
    for entry in entries:
        counts[entry.outcome] += 1
    return counts


def _load_batch(path: Path) -> TasteAbstractionRuntimeBatch:
    payload = _json_mapping(path, "Track-A abstraction batch")
    recorded = payload.pop("batch_sha256", None)
    batch = TasteAbstractionRuntimeBatch.model_validate(payload)
    if recorded != batch.batch_sha256:
        raise ValueError("Track-A abstraction batch semantic hash mismatch")
    return batch


def _load_bridge(path: Path) -> GroundedAbstractionReviewBridge:
    payload = _json_mapping(_bounded_file(path.parent.parent, path), "Track-A review bridge")
    payload.pop("bridge_sha256", None)
    return GroundedAbstractionReviewBridge.model_validate(payload)


def _json_mapping(path: Path, label: str) -> dict[str, object]:
    try:
        payload = json.loads(path.read_bytes())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain one JSON object")
    return payload


def _bounded_file(root: Path, value: str | Path) -> Path:
    path = _within_root(root, value, must_exist=True)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Track-A campaign input must be a regular file: {value}")
    if not 1 <= path.stat().st_size <= _MAX_CONTROL_BYTES:
        raise ValueError(f"Track-A campaign input exceeds its byte ceiling: {value}")
    return path


def _bound_file(root: Path, locator: str, expected_sha256: str) -> Path:
    pure = PurePosixPath(locator)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError("Track-A campaign binding is not a safe relative locator")
    path = _bounded_file(root, root.joinpath(*pure.parts))
    if _sha256(path) != expected_sha256:
        raise ValueError(f"Track-A campaign binding changed: {locator}")
    return path


def _within_root(root: Path, value: str | Path, *, must_exist: bool) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root / candidate
    if candidate.is_symlink():
        raise ValueError(f"Track-A campaign path cannot be a symlink: {value}")
    resolved = candidate.resolve(strict=must_exist)
    if not resolved.is_relative_to(root):
        raise ValueError(f"Track-A campaign path escapes the workspace: {value}")
    return resolved


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "TrackAAbstractionCampaignStatus",
    "run_track_a_abstraction_campaign",
]
