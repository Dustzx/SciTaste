"""Fail-closed integrity gate for natural Track-A decision episodes.

The historical Track-A v3 planner paired one extracted review action with an
action taken from another paper.  It also exposed response-state or publication
recommendation proxies as an ``outcome``.  Those records are useful source
material, but they are not identified two-alternative decisions with an
action-aligned observed outcome.

This module deliberately leaves the v3 planner untouched.  It replays that
plan, emits content-free exclusion receipts, and only admits records whose
*source projection* already carries the structured decision-episode bindings
defined here.  Post-decision prose is never used to invent a pre-decision
alternative.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.evaluation.taste_mechanism_pilot import (
    TasteMechanismPilotTarget,
    load_taste_mechanism_pilot_plan,
)
from scitaste.taste.semantic_models import TasteAbstractionInput

_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)
_SHA256 = r"^[0-9a-f]{64}$"
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_MAX_CONTROL_BYTES = 64 * 1_048_576
_POLICY_ID = "track-a-decision-episode-integrity-v1"
_REQUIRED_SOURCE_DATA = (
    "predecision source spans identifying at least two simultaneously live candidate actions",
    "a source-bound choice record selecting exactly one member of that candidate set",
    "author-response or revision spans explicitly aligned to the selected action",
    "a post-action scientific outcome observation distinct from response and publication proxies",
    "an explicit outcome-attribution uncertainty assessment that preserves alternative causes",
)

DecisionEpisodeExclusionCode = Literal[
    "cross-source-distractor-is-not-a-live-alternative",
    "fewer-than-two-explicit-predecision-live-alternatives",
    "chosen-action-not-bound-to-predecision-alternative-set",
    "postdecision-material-cannot-backfill-predecision-alternatives",
    "response-or-revision-not-explicitly-aligned-to-action",
    "response-state-is-not-a-scientific-outcome",
    "publication-recommendation-is-not-an-action-outcome",
    "outcome-proxy-kind-unclassified",
    "no-aligned-edit-observed-is-not-an-outcome",
    "outcome-attribution-uncertainty-unbound",
]

OutcomeProxyKind = Literal[
    "response-absence",
    "response-alignment",
    "response-presence",
    "publication-recommendation",
    "unclassified",
]


class DecisionEpisodeFileBinding(BaseModel):
    model_config = _CONFIG

    locator: str = Field(min_length=1, max_length=2_000)
    file_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def locator_is_safe(self) -> DecisionEpisodeFileBinding:
        _safe_locator(self.locator)
        return self


class DecisionEpisodeSemanticBinding(DecisionEpisodeFileBinding):
    semantic_sha256: str = Field(pattern=_SHA256)


class TrackATargetIntegrityAudit(BaseModel):
    """Content-free audit of one v3 target pair."""

    model_config = _CONFIG

    target_id: str = Field(pattern=_ID)
    source_review_item_id: str = Field(pattern=_ID)
    source_group_id: str = Field(pattern=_ID)
    source_action_sha256: str = Field(pattern=_SHA256)
    distractor_action_sha256: str = Field(pattern=_SHA256)
    distractor_source_target_id: str = Field(pattern=_ID)
    source_local_candidate_action_count: Literal[1] = 1
    distractor_from_different_source_target: Literal[True] = True
    explicit_predecision_live_alternative_set_bound: Literal[False] = False
    target_outcome_included: Literal[False] = False
    relation_label_included: Literal[False] = False
    eligible: Literal[False] = False
    exclusion_reasons: tuple[DecisionEpisodeExclusionCode, ...] = (
        "cross-source-distractor-is-not-a-live-alternative",
        "fewer-than-two-explicit-predecision-live-alternatives",
        "chosen-action-not-bound-to-predecision-alternative-set",
    )

    @model_validator(mode="after")
    def audit_is_fail_closed(self) -> TrackATargetIntegrityAudit:
        if self.source_action_sha256 == self.distractor_action_sha256:
            raise ValueError("decision-episode target actions must differ")
        if self.target_id == self.distractor_source_target_id:
            raise ValueError("historical Track-A distractor unexpectedly comes from this target")
        return self


class TrackAPrecedentIntegrityAudit(BaseModel):
    """Content-free audit of one precedent projection."""

    model_config = _CONFIG

    input_id: str = Field(pattern=_ID)
    source_review_item_id: str = Field(pattern=_ID)
    source_group_id: str = Field(pattern=_ID)
    source_segment_id: str = Field(pattern=_ID)
    source_projection_sha256: str = Field(pattern=_SHA256)
    explicit_predecision_live_alternative_count: int = Field(ge=0, le=128)
    selected_action_bound_to_alternative_set: bool
    author_response_present: bool
    revised_abstract_present: bool
    response_or_revision_action_alignment_bound: bool
    outcome_proxy_kind: OutcomeProxyKind
    outcome_attribution_uncertainty: Literal["unbound"] = "unbound"
    target_specific_content_included: Literal[False] = False
    relation_label_included: Literal[False] = False
    eligible: bool
    exclusion_reasons: tuple[DecisionEpisodeExclusionCode, ...]

    @model_validator(mode="after")
    def admission_requires_a_complete_episode(self) -> TrackAPrecedentIntegrityAudit:
        complete = (
            self.explicit_predecision_live_alternative_count >= 2
            and self.selected_action_bound_to_alternative_set
            and self.response_or_revision_action_alignment_bound
            and self.outcome_attribution_uncertainty != "unbound"
            and self.outcome_proxy_kind == "unclassified"
        )
        # Schema v1 intentionally has no scientific-outcome field, so an
        # unclassified legacy value is not enough to pass either.  The explicit
        # False keeps this gate closed until a new source contract is supplied.
        complete = complete and False
        if self.eligible != complete:
            raise ValueError("precedent eligibility differs from decision-episode evidence")
        if self.eligible == bool(self.exclusion_reasons):
            raise ValueError("precedent exclusion reasons differ from eligibility")
        return self


class TrackADecisionEpisodeIntegrityPlan(BaseModel):
    """Natural-pilot v4 gate; this is not a quality or experiment result."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    plan_revision: Literal[4] = 4
    plan_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    integrity_policy_id: Literal["track-a-decision-episode-integrity-v1"] = _POLICY_ID
    integrity_policy_sha256: str = Field(pattern=_SHA256)
    source_pilot_plan: DecisionEpisodeSemanticBinding
    prepared_at: datetime
    target_audits: tuple[TrackATargetIntegrityAudit, ...]
    precedent_audits: tuple[TrackAPrecedentIntegrityAudit, ...]
    source_target_count: int = Field(ge=0, le=10_000)
    source_precedent_count: int = Field(ge=0, le=10_000)
    eligible_target_ids: tuple[str, ...]
    eligible_precedent_input_ids: tuple[str, ...]
    eligible_target_count: int = Field(ge=0, le=10_000)
    eligible_precedent_count: int = Field(ge=0, le=10_000)
    excluded_target_count: int = Field(ge=0, le=10_000)
    excluded_precedent_count: int = Field(ge=0, le=10_000)
    exclusion_reason_counts: dict[str, int]
    required_source_data: tuple[str, ...] = _REQUIRED_SOURCE_DATA
    status: Literal["blocked-no-eligible-decision-episodes"]
    reference_quality_authorized: Literal[False] = False
    taste_abstraction_authorized: Literal[False] = False
    decision_suite_authorized: Literal[False] = False
    target_outcomes_hidden: Literal[True] = True
    target_relationship_labels_hidden: Literal[True] = True
    outcome_attribution_uncertainty_preserved: Literal[True] = True
    natural_pilot: Literal[True] = True
    formal_evidence_eligible: Literal[False] = False
    model_calls_performed: Literal[False] = False
    api_calls_performed: Literal[False] = False
    gpu_work_performed: Literal[False] = False
    experiment_performed: Literal[False] = False
    plan_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def plan_is_closed(self) -> TrackADecisionEpisodeIntegrityPlan:
        if self.prepared_at.utcoffset() is None:
            raise ValueError("decision-episode plan timestamp must include a timezone")
        if self.required_source_data != _REQUIRED_SOURCE_DATA:
            raise ValueError("decision-episode source-data requirements drifted")
        if self.integrity_policy_sha256 != _policy_sha256():
            raise ValueError("decision-episode integrity policy hash drifted")
        target_ids = tuple(item.target_id for item in self.target_audits)
        input_ids = tuple(item.input_id for item in self.precedent_audits)
        if target_ids != tuple(sorted(set(target_ids))):
            raise ValueError("decision-episode target audits must be sorted and unique")
        if input_ids != tuple(sorted(set(input_ids))):
            raise ValueError("decision-episode precedent audits must be sorted and unique")
        if self.source_target_count != len(self.target_audits):
            raise ValueError("decision-episode source target count differs")
        if self.source_precedent_count != len(self.precedent_audits):
            raise ValueError("decision-episode source precedent count differs")
        eligible_targets = tuple(item.target_id for item in self.target_audits if item.eligible)
        eligible_inputs = tuple(item.input_id for item in self.precedent_audits if item.eligible)
        if self.eligible_target_ids != eligible_targets:
            raise ValueError("decision-episode eligible target IDs differ")
        if self.eligible_precedent_input_ids != eligible_inputs:
            raise ValueError("decision-episode eligible precedent IDs differ")
        if self.eligible_target_count != len(eligible_targets):
            raise ValueError("decision-episode eligible target count differs")
        if self.eligible_precedent_count != len(eligible_inputs):
            raise ValueError("decision-episode eligible precedent count differs")
        if self.excluded_target_count != self.source_target_count - self.eligible_target_count:
            raise ValueError("decision-episode excluded target count differs")
        if self.excluded_precedent_count != (
            self.source_precedent_count - self.eligible_precedent_count
        ):
            raise ValueError("decision-episode excluded precedent count differs")
        observed_counts = Counter(
            reason
            for audit in (*self.target_audits, *self.precedent_audits)
            for reason in audit.exclusion_reasons
        )
        if self.exclusion_reason_counts != dict(sorted(observed_counts.items())):
            raise ValueError("decision-episode exclusion reason counts differ")
        expected = _canonical_sha256(self.model_dump(mode="json", exclude={"plan_sha256"}))
        if self.plan_sha256 != expected:
            raise ValueError("decision-episode integrity plan hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> TrackADecisionEpisodeIntegrityPlan:
        payload = {"schema_version": "1.0", "plan_revision": 4, **values}
        payload.pop("plan_sha256", None)
        unsigned = cls.model_construct(plan_sha256="0" * 64, **payload)
        return cls(
            **payload,
            plan_sha256=_canonical_sha256(
                unsigned.model_dump(mode="json", exclude={"plan_sha256"})
            ),
        )


class TrackADecisionEpisodeIntegrityInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    plan: TrackADecisionEpisodeIntegrityPlan
    source_plan_replayed: Literal[True] = True
    target_bindings_verified: Literal[True] = True
    precedent_bindings_verified: Literal[True] = True
    no_target_outcome_or_relation_label_exposed: Literal[True] = True


def prepare_track_a_decision_episode_integrity_plan(
    *,
    source_plan_path: str | Path,
    evidence_root: str | Path,
    output_dir: str | Path,
    prepared_at: datetime | None = None,
) -> TrackADecisionEpisodeIntegrityPlan:
    """Replay a historical plan and atomically emit its v4 integrity gate."""

    root = Path(evidence_root).resolve(strict=True)
    source_plan_file = _within_root(root, source_plan_path, must_exist=True)
    source = load_taste_mechanism_pilot_plan(source_plan_file, locator_root=root).plan
    target_audits, precedent_audits = _audit_source_plan(source_plan_file, source)
    reasons = Counter(
        reason
        for audit in (*target_audits, *precedent_audits)
        for reason in audit.exclusion_reasons
    )
    eligible_targets = tuple(item.target_id for item in target_audits if item.eligible)
    eligible_precedents = tuple(item.input_id for item in precedent_audits if item.eligible)
    plan = TrackADecisionEpisodeIntegrityPlan.create(
        plan_id=f"{source.plan_id}-decision-integrity-v4",
        project_id=source.project_id,
        integrity_policy_sha256=_policy_sha256(),
        source_pilot_plan=DecisionEpisodeSemanticBinding(
            locator=_relative(source_plan_file, root),
            file_sha256=_sha256_file(source_plan_file),
            semantic_sha256=source.plan_sha256,
        ),
        prepared_at=prepared_at or datetime.now(UTC),
        target_audits=target_audits,
        precedent_audits=precedent_audits,
        source_target_count=len(target_audits),
        source_precedent_count=len(precedent_audits),
        eligible_target_ids=eligible_targets,
        eligible_precedent_input_ids=eligible_precedents,
        eligible_target_count=len(eligible_targets),
        eligible_precedent_count=len(eligible_precedents),
        excluded_target_count=len(target_audits) - len(eligible_targets),
        excluded_precedent_count=len(precedent_audits) - len(eligible_precedents),
        exclusion_reason_counts=dict(sorted(reasons.items())),
        status="blocked-no-eligible-decision-episodes",
    )
    target = _within_root(root, output_dir, must_exist=False)
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{target.name}.", dir=target.parent) as temporary:
        workspace = Path(temporary)
        _write_new(
            workspace / "PLAN.json",
            _canonical_json(plan.model_dump(mode="json")) + b"\n",
        )
        os.replace(workspace, target)
    return plan


def inspect_track_a_decision_episode_integrity_plan(
    path: str | Path,
    *,
    evidence_root: str | Path,
) -> TrackADecisionEpisodeIntegrityInspection:
    """Replay the v3 bindings and every content-free v4 exclusion."""

    root = Path(evidence_root).resolve(strict=True)
    plan_file = _within_root(root, path, must_exist=True)
    if plan_file.stat().st_size > _MAX_CONTROL_BYTES:
        raise ValueError("decision-episode integrity plan exceeds its byte ceiling")
    plan = TrackADecisionEpisodeIntegrityPlan.model_validate_json(plan_file.read_bytes())
    source_plan_file = _bound_file(root, plan.source_pilot_plan)
    source = load_taste_mechanism_pilot_plan(source_plan_file, locator_root=root).plan
    if source.plan_sha256 != plan.source_pilot_plan.semantic_sha256:
        raise ValueError("decision-episode source plan semantic hash drifted")
    targets, precedents = _audit_source_plan(source_plan_file, source)
    if targets != plan.target_audits or precedents != plan.precedent_audits:
        raise ValueError("decision-episode audits differ from deterministic replay")
    return TrackADecisionEpisodeIntegrityInspection(
        path=plan_file,
        file_sha256=_sha256_file(plan_file),
        plan=plan,
    )


def _audit_source_plan(
    source_plan_file: Path, source: object
) -> tuple[tuple[TrackATargetIntegrityAudit, ...], tuple[TrackAPrecedentIntegrityAudit, ...]]:
    plan_root = source_plan_file.parent.resolve(strict=True)
    targets: list[TrackATargetIntegrityAudit] = []
    for record in source.targets:
        target_file = _bound_file(plan_root, record.target_file)
        target = TasteMechanismPilotTarget.model_validate_json(target_file.read_bytes())
        if target.target_sha256 != record.target_file.semantic_sha256:
            raise ValueError("decision-episode target semantic hash drifted")
        targets.append(
            TrackATargetIntegrityAudit(
                target_id=target.target_id,
                source_review_item_id=target.source_review_item_id,
                source_group_id=target.source_group_id,
                source_action_sha256=target.source_observed_action.action_sha256,
                distractor_action_sha256=target.distractor_action.action_sha256,
                distractor_source_target_id=target.distractor_action.source_target_id,
            )
        )
    precedents: list[TrackAPrecedentIntegrityAudit] = []
    for record in source.abstraction_inputs:
        input_file = _bound_file(plan_root, record.input_file)
        abstraction = TasteAbstractionInput.model_validate_json(input_file.read_bytes())
        if abstraction.source_projection_sha256 != record.source_projection_sha256:
            raise ValueError("decision-episode precedent projection hash drifted")
        projection = _load_projection(abstraction.source_projection)
        fields = projection["fields"]
        alternatives = _structured_predecision_alternatives(fields)
        selected_action_bound = _selected_action_is_bound(fields, alternatives)
        response_present = "deidentified_author_response" in fields
        revision_present = "revised_abstract" in fields
        alignment_bound = _response_alignment_is_bound(fields)
        proxy_kind = _outcome_proxy_kind(fields)
        reasons: list[DecisionEpisodeExclusionCode] = []
        if len(alternatives) < 2:
            reasons.append("fewer-than-two-explicit-predecision-live-alternatives")
        if not selected_action_bound:
            reasons.append("chosen-action-not-bound-to-predecision-alternative-set")
        if response_present or revision_present:
            reasons.append("postdecision-material-cannot-backfill-predecision-alternatives")
        if not alignment_bound:
            reasons.append("response-or-revision-not-explicitly-aligned-to-action")
        if proxy_kind == "response-absence":
            reasons.extend(
                (
                    "no-aligned-edit-observed-is-not-an-outcome",
                    "response-state-is-not-a-scientific-outcome",
                )
            )
        elif proxy_kind in {"response-alignment", "response-presence"}:
            reasons.append("response-state-is-not-a-scientific-outcome")
        elif proxy_kind == "publication-recommendation":
            reasons.append("publication-recommendation-is-not-an-action-outcome")
        else:
            reasons.append("outcome-proxy-kind-unclassified")
        reasons.append("outcome-attribution-uncertainty-unbound")
        precedents.append(
            TrackAPrecedentIntegrityAudit(
                input_id=record.input_id,
                source_review_item_id=record.source_review_item_id,
                source_group_id=record.source_group_id,
                source_segment_id=record.source_segment_id,
                source_projection_sha256=record.source_projection_sha256,
                explicit_predecision_live_alternative_count=len(alternatives),
                selected_action_bound_to_alternative_set=selected_action_bound,
                author_response_present=response_present,
                revised_abstract_present=revision_present,
                response_or_revision_action_alignment_bound=alignment_bound,
                outcome_proxy_kind=proxy_kind,
                eligible=False,
                exclusion_reasons=tuple(dict.fromkeys(reasons)),
            )
        )
    return tuple(sorted(targets, key=lambda item: item.target_id)), tuple(
        sorted(precedents, key=lambda item: item.input_id)
    )


def _load_projection(value: str) -> dict[str, object]:
    payload = json.loads(value)
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0":
        raise ValueError("decision-episode precedent projection schema is unsupported")
    fields = payload.get("fields")
    if not isinstance(fields, dict):
        raise ValueError("decision-episode precedent projection lacks fields")
    if "target_outcome" in fields or "relation" in fields or "relationship_label" in fields:
        raise ValueError("decision-episode precedent projection leaks target or relation metadata")
    return payload


def _structured_predecision_alternatives(fields: dict[str, object]) -> tuple[str, ...]:
    record = fields.get("predecision_live_alternatives")
    if not isinstance(record, dict) or record.get("source_phase") != "predecision":
        return ()
    values = record.get("value")
    if not isinstance(values, list) or any(not isinstance(item, dict) for item in values):
        return ()
    candidate_ids = tuple(
        item.get("candidate_id")
        for item in values
        if isinstance(item.get("candidate_id"), str)
        and isinstance(item.get("verbatim_source_span_sha256"), str)
    )
    if len(candidate_ids) != len(values) or len(candidate_ids) != len(set(candidate_ids)):
        return ()
    return candidate_ids


def _selected_action_is_bound(fields: dict[str, object], candidates: tuple[str, ...]) -> bool:
    record = fields.get("observed_choice")
    if not isinstance(record, dict) or record.get("source_phase") != "decision":
        return False
    value = record.get("value")
    return (
        isinstance(value, dict)
        and isinstance(value.get("selected_candidate_id"), str)
        and value["selected_candidate_id"] in candidates
        and isinstance(value.get("verbatim_choice_span_sha256"), str)
    )


def _response_alignment_is_bound(fields: dict[str, object]) -> bool:
    record = fields.get("action_aligned_response")
    if not isinstance(record, dict) or record.get("source_phase") != "postdecision":
        return False
    value = record.get("value")
    return (
        isinstance(value, dict)
        and isinstance(value.get("selected_candidate_id"), str)
        and isinstance(value.get("verbatim_response_span_sha256"), str)
        and isinstance(value.get("verbatim_revision_span_sha256"), str)
    )


def _outcome_proxy_kind(fields: dict[str, object]) -> OutcomeProxyKind:
    record = fields.get("observed_natural_outcome")
    value = record.get("value") if isinstance(record, dict) else None
    if value == "no-aligned-edit-observed":
        return "response-absence"
    if value == "aligned-edit-observed":
        return "response-alignment"
    if value == "public-author-reply-observed":
        return "response-presence"
    if value == "approved-with-reservations":
        return "publication-recommendation"
    return "unclassified"


def _policy_sha256() -> str:
    return _canonical_sha256(
        {
            "policy_id": _POLICY_ID,
            "minimum_predecision_live_alternatives": 2,
            "cross_source_foil_allowed": False,
            "postdecision_alternative_backfill_allowed": False,
            "action_aligned_response_revision_required": True,
            "response_state_as_scientific_outcome_allowed": False,
            "publication_recommendation_as_action_outcome_allowed": False,
            "outcome_attribution_uncertainty_required": True,
            "target_outcome_allowed": False,
            "target_relation_label_allowed": False,
            "required_source_data": _REQUIRED_SOURCE_DATA,
        }
    )


def _bound_file(root: Path, binding: DecisionEpisodeFileBinding | object) -> Path:
    locator = binding.locator
    expected_sha256 = binding.file_sha256
    source = _within_root(root, locator, must_exist=True)
    if source.stat().st_size > _MAX_CONTROL_BYTES:
        raise ValueError("decision-episode bound file exceeds its byte ceiling")
    if _sha256_file(source) != expected_sha256:
        raise ValueError(f"decision-episode bound file hash drifted: {locator}")
    return source


def _safe_locator(locator: str) -> PurePosixPath:
    path = PurePosixPath(locator)
    if "\\" in locator or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("decision-episode artifact locator is unsafe")
    return path


def _within_root(root: Path, value: str | Path, *, must_exist: bool) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root.joinpath(*PurePosixPath(candidate.as_posix()).parts)
    resolved = candidate.resolve(strict=must_exist)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("decision-episode path escapes its evidence root") from exc
    if must_exist and (resolved.is_symlink() or not resolved.is_file()):
        raise ValueError("decision-episode input must be a regular non-symlink")
    return resolved


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


def _write_new(path: Path, payload: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


__all__ = [
    "TrackADecisionEpisodeIntegrityInspection",
    "TrackADecisionEpisodeIntegrityPlan",
    "inspect_track_a_decision_episode_integrity_plan",
    "prepare_track_a_decision_episode_integrity_plan",
]
