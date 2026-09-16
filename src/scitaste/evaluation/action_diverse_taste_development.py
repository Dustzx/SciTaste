"""Outcome-blind action-diverse curation of prospective Taste trajectories.

The source decisions were locked prospectively.  The balanced turn selection is
retrospective and development-only: it may construct a policy intervention, but
it is never itself evidence that the intervention works.  Effect evidence must
come from a later source-disjoint paired evaluation.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.evaluation.interactive_development import (
    finalize_interactive_development_episodes,
    load_interactive_taste_development_protocol,
)
from scitaste.evaluation.interactive_research import (
    InteractiveResearchRunReceipt,
    InteractiveTurnRecord,
    guidance_action_complied,
    load_interactive_research_run_receipt,
)
from scitaste.project.idea_revision import (
    idea_binding_matches_current,
    idea_scientific_contract_sha256,
    inspect_current_idea_revision,
)
from scitaste.project.models import content_sha256, validate_entry_id, validate_project_id
from scitaste.project.runtime import ProjectRuntime
from scitaste.taste.trajectory_reconstruction import (
    load_taste_prospective_decision_lock,
    load_taste_trajectory_sampling_plan,
)

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_MANIFEST_BYTES = 2 * 1_048_576
_MAX_SOURCE_BYTES = 64 * 1_048_576
ActionType = Literal[
    "PROBE",
    "PILOT",
    "EXPERIMENT",
    "ANALYZE",
    "REFINE",
    "PIVOT",
    "STOP",
]
_ACTION_TYPES = frozenset(
    {"PROBE", "PILOT", "EXPERIMENT", "ANALYZE", "REFINE", "PIVOT", "STOP"}
)


class CurationSourceSpec(BaseModel):
    model_config = _CONFIG

    run_id: str

    @model_validator(mode="after")
    def identity_is_safe(self) -> CurationSourceSpec:
        validate_entry_id(self.run_id, field_name="action-diverse source run_id")
        return self


class ActionQuota(BaseModel):
    model_config = _CONFIG

    action_type: ActionType
    count: int = Field(ge=1, le=100)


class ActionDiverseCurationManifest(BaseModel):
    """Versioned intent; exact source bytes are frozen in the compiled plan."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    curation_id: str
    project_id: str
    purpose: str
    selection_timing: Literal["retrospective-development-only"]
    source_decisions_prospectively_locked: Literal[True]
    selection_uses_terminal_metric_or_credit: Literal[False]
    one_episode_per_source_group: Literal[True]
    formal_evidence: Literal[False]
    effect_claim_authorized: Literal[False]
    selection_algorithm: Literal["balanced-action-feasible-hash-v1"]
    selection_salt: str = Field(min_length=1, max_length=200)
    quotas: tuple[ActionQuota, ...]
    sources: tuple[CurationSourceSpec, ...]
    projection_stage: str
    credit_projection: Literal["action-local-scientific-v4", "allocation-local-v5"]

    @model_validator(mode="after")
    def manifest_is_closed(self) -> ActionDiverseCurationManifest:
        validate_entry_id(self.curation_id, field_name="action-diverse curation_id")
        validate_project_id(self.project_id)
        validate_entry_id(self.projection_stage, field_name="action-diverse projection_stage")
        actions = tuple(item.action_type for item in self.quotas)
        if len(actions) < 2 or len(actions) != len(set(actions)):
            raise ValueError("action-diverse quotas require at least two unique actions")
        run_ids = tuple(item.run_id for item in self.sources)
        if len(run_ids) != len(set(run_ids)):
            raise ValueError("action-diverse source runs must be unique")
        if sum(item.count for item in self.quotas) > len(self.sources):
            raise ValueError("action-diverse quotas exceed the frozen source population")
        return self

    @property
    def fingerprint(self) -> str:
        return content_sha256(self.model_dump(mode="json"))


class CurationFileBinding(BaseModel):
    model_config = _CONFIG

    locator: str
    sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def locator_is_safe(self) -> CurationFileBinding:
        _safe_locator(self.locator)
        return self


class EligibleActionTurn(BaseModel):
    model_config = _CONFIG

    action_type: ActionType
    turn: int = Field(ge=1, le=100)
    lock: CurationFileBinding
    lock_sha256: str = Field(pattern=_SHA256)


class CurationSourceEvidence(BaseModel):
    model_config = _CONFIG

    run_id: str
    task_id: str
    source_group_id: str
    observed_project_revision: int = Field(ge=0)
    observed_project_snapshot_sha256: str = Field(pattern=_SHA256)
    protocol: CurationFileBinding
    sampling_plan: CurationFileBinding
    terminal_receipt: CurationFileBinding
    eligible_turns: tuple[EligibleActionTurn, ...]

    @model_validator(mode="after")
    def source_is_closed(self) -> CurationSourceEvidence:
        turns = tuple((item.action_type, item.turn) for item in self.eligible_turns)
        if turns != tuple(sorted(set(turns), key=lambda item: (item[1], item[0]))):
            raise ValueError("eligible action turns must be unique and turn ordered")
        return self


class CuratedActionTurn(BaseModel):
    model_config = _CONFIG

    ordinal: int = Field(ge=1)
    run_id: str
    task_id: str
    source_group_id: str
    action_type: ActionType
    turn: int = Field(ge=1, le=100)
    lock: CurationFileBinding
    lock_sha256: str = Field(pattern=_SHA256)


class ActionDiverseCurationPlan(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    curation_id: str
    project_id: str
    manifest_fingerprint: str = Field(pattern=_SHA256)
    idea_revision_id: str
    idea_record_sha256: str = Field(pattern=_SHA256)
    idea_scientific_contract_sha256: str = Field(pattern=_SHA256)
    selection_timing: Literal["retrospective-development-only"]
    selection_algorithm: Literal["balanced-action-feasible-hash-v1"]
    selection_salt: str
    selection_uses_terminal_metric_or_credit: Literal[False]
    one_episode_per_source_group: Literal[True]
    formal_evidence: Literal[False]
    effect_claim_authorized: Literal[False]
    quotas: tuple[ActionQuota, ...]
    sources: tuple[CurationSourceEvidence, ...]
    selections: tuple[CuratedActionTurn, ...]
    plan_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def plan_is_closed(self) -> ActionDiverseCurationPlan:
        validate_entry_id(self.curation_id, field_name="action-diverse plan curation_id")
        validate_project_id(self.project_id)
        expected_ordinals = tuple(range(1, len(self.selections) + 1))
        if tuple(item.ordinal for item in self.selections) != expected_ordinals:
            raise ValueError("action-diverse selection ordinals must be contiguous")
        source_groups = tuple(item.source_group_id for item in self.selections)
        if len(source_groups) != len(set(source_groups)):
            raise ValueError("action-diverse plan selected a source group more than once")
        expected_counts = {item.action_type: item.count for item in self.quotas}
        if Counter(item.action_type for item in self.selections) != Counter(expected_counts):
            raise ValueError("action-diverse selection counts differ from frozen quotas")
        availability = {
            (source.source_group_id, item.action_type, item.turn, item.lock_sha256)
            for source in self.sources
            for item in source.eligible_turns
        }
        if any(
            (item.source_group_id, item.action_type, item.turn, item.lock_sha256)
            not in availability
            for item in self.selections
        ):
            raise ValueError("action-diverse selection is absent from source availability")
        expected = content_sha256(self.model_dump(mode="json", exclude={"plan_sha256"}))
        if self.plan_sha256 != expected:
            raise ValueError("action-diverse plan hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> ActionDiverseCurationPlan:
        payload = {"schema_version": "1.0", **values}
        payload.pop("plan_sha256", None)
        unsigned = cls.model_construct(plan_sha256="0" * 64, **payload)
        return cls(
            **payload,
            plan_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"plan_sha256"})
            ),
        )


class MaterializedCuratedCandidate(BaseModel):
    model_config = _CONFIG

    ordinal: int = Field(ge=1)
    run_id: str
    source_group_id: str
    action_type: ActionType
    turn: int = Field(ge=1, le=100)
    batch: CurationFileBinding
    batch_sha256: str = Field(pattern=_SHA256)
    candidate: CurationFileBinding
    candidate_id: str
    candidate_sha256: str = Field(pattern=_SHA256)


class ActionDiverseCurationReceipt(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    curation_id: str
    project_id: str
    plan_sha256: str = Field(pattern=_SHA256)
    candidates: tuple[MaterializedCuratedCandidate, ...]
    api_calls: Literal[0] = 0
    gpu_generations: Literal[0] = 0
    policy_update_authorized: Literal[False] = False
    formal_evidence: Literal[False] = False
    effect_claim_authorized: Literal[False] = False
    receipt_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def receipt_is_closed(self) -> ActionDiverseCurationReceipt:
        if tuple(item.ordinal for item in self.candidates) != tuple(
            range(1, len(self.candidates) + 1)
        ):
            raise ValueError("materialized candidate ordinals must be contiguous")
        expected = content_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        if self.receipt_sha256 != expected:
            raise ValueError("action-diverse curation receipt hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> ActionDiverseCurationReceipt:
        payload = {"schema_version": "1.0", **values}
        payload.pop("receipt_sha256", None)
        unsigned = cls.model_construct(receipt_sha256="0" * 64, **payload)
        return cls(
            **payload,
            receipt_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"receipt_sha256"})
            ),
        )


def select_balanced_action_turns(
    availability: dict[str, dict[str, int]],
    *,
    quotas: dict[str, int],
    salt: str,
) -> dict[str, tuple[str, int]]:
    """Return one feasible action/turn per source without consulting outcomes."""

    if (
        len(quotas) < 2
        or set(quotas) - _ACTION_TYPES
        or any(value <= 0 for value in quotas.values())
    ):
        raise ValueError("balanced action selection requires positive supported-action quotas")
    if len(availability) != sum(quotas.values()):
        raise ValueError("balanced action selection needs one eligible source per quota slot")
    if any(not choices for choices in availability.values()):
        raise ValueError("balanced action selection source has no eligible action")
    if any(set(choices) - _ACTION_TYPES for choices in availability.values()):
        raise ValueError("balanced action selection received an unsupported action")

    ordered_sources = sorted(
        availability,
        key=lambda source_group: (len(availability[source_group]), source_group),
    )
    assignment: dict[str, tuple[str, int]] = {}

    def feasible(index: int, remaining: dict[str, int]) -> bool:
        pending = ordered_sources[index:]
        return all(
            remaining[action]
            <= sum(action in availability[source_group] for source_group in pending)
            for action in quotas
        )

    def search(index: int, remaining: dict[str, int]) -> bool:
        if index == len(ordered_sources):
            return all(value == 0 for value in remaining.values())
        if not feasible(index, remaining):
            return False
        source_group = ordered_sources[index]
        actions = sorted(
            availability[source_group],
            key=lambda action: hashlib.sha256(
                f"{salt}:{source_group}:{action}".encode()
            ).hexdigest(),
        )
        for action in actions:
            if remaining[action] == 0:
                continue
            assignment[source_group] = (action, availability[source_group][action])
            next_remaining = {**remaining, action: remaining[action] - 1}
            if search(index + 1, next_remaining):
                return True
            assignment.pop(source_group)
        return False

    if not search(0, dict(quotas)):
        raise ValueError("no source-unique action-balanced assignment exists")
    return assignment


def compile_action_diverse_curation_plan(
    manifest: ActionDiverseCurationManifest,
    *,
    workspace_root: str | Path,
    outputs_root: str | Path,
) -> ActionDiverseCurationPlan:
    workspace = Path(workspace_root).expanduser().resolve()
    runtime = ProjectRuntime(outputs_root)
    idea = inspect_current_idea_revision(runtime, manifest.project_id).current_binding
    if idea is None:
        raise ValueError("action-diverse curation requires a current project Idea")

    sources: list[CurationSourceEvidence] = []
    source_groups: set[str] = set()
    requested_actions = {item.action_type for item in manifest.quotas}
    for spec in manifest.sources:
        run_root = runtime.projects_root / manifest.project_id / "runs" / spec.run_id
        stage_root = run_root / "interactive_development"
        protocol_path = stage_root / "PROTOCOL.json"
        plan_path = stage_root / "SAMPLING_PLAN.json"
        receipt_path = stage_root / "RESULT" / "RECEIPT.json"
        protocol = load_interactive_taste_development_protocol(protocol_path)
        plan = load_taste_trajectory_sampling_plan(plan_path)
        receipt = load_interactive_research_run_receipt(receipt_path)
        if (
            protocol.project_id != manifest.project_id
            or plan.source_run_id != spec.run_id
            or receipt.run_id != spec.run_id
            or plan.source_group_id != protocol.source_group_id
            or receipt.project_id != manifest.project_id
        ):
            raise ValueError(f"action-diverse source identity mismatch: {spec.run_id}")
        if not idea_binding_matches_current(plan.idea_revision, idea):
            raise ValueError(f"action-diverse source belongs to a stale Idea: {spec.run_id}")
        if plan.source_group_id in source_groups:
            raise ValueError("action-diverse source groups must be unique")
        source_groups.add(plan.source_group_id)
        effective_lock_paths = _effective_lock_paths(stage_root, receipt)

        eligible: list[EligibleActionTurn] = []
        for index, record in enumerate(receipt.turns):
            action_type = record.guidance.guidance.action_type
            if (
                action_type not in requested_actions
                or not guidance_action_complied(
                    action_type, record.decision.proposal.action
                )
            ):
                continue
            action_local_evidence_available = (
                (
                    record.observation is not None
                    and index + 1 < len(receipt.turns)
                )
                or record.decision.proposal.action == "submit_hypothesis"
            )
            if not action_local_evidence_available:
                continue
            turn = index + 1
            lock_path = effective_lock_paths[index]
            lock = load_taste_prospective_decision_lock(lock_path)
            if (
                lock.plan_sha256 != plan.plan_sha256
                or lock.selected_action_id != record.guidance.guidance.action_id
            ):
                raise ValueError(f"action-diverse lock differs at {spec.run_id} turn {turn}")
            eligible.append(
                EligibleActionTurn(
                    action_type=action_type,
                    turn=turn,
                    lock=_binding(workspace, lock_path),
                    lock_sha256=lock.lock_sha256,
                )
            )
        sources.append(
            CurationSourceEvidence(
                run_id=spec.run_id,
                task_id=receipt.task_id,
                source_group_id=plan.source_group_id,
                observed_project_revision=plan.observed_project_revision,
                observed_project_snapshot_sha256=plan.observed_project_snapshot_sha256,
                protocol=_binding(workspace, protocol_path),
                sampling_plan=_binding(workspace, plan_path),
                terminal_receipt=_binding(workspace, receipt_path),
                eligible_turns=tuple(eligible),
            )
        )

    availability = {
        source.source_group_id: {
            action_type: min(
                candidate.turn
                for candidate in source.eligible_turns
                if candidate.action_type == action_type
            )
            for action_type in {item.action_type for item in source.eligible_turns}
        }
        for source in sources
        if source.eligible_turns
    }
    quotas = {item.action_type: item.count for item in manifest.quotas}
    assignment = select_balanced_action_turns(
        availability,
        quotas=quotas,
        salt=manifest.selection_salt,
    )
    source_by_group = {item.source_group_id: item for item in sources}
    chosen: list[CuratedActionTurn] = []
    for ordinal, source_group in enumerate(sorted(assignment), 1):
        action_type, turn = assignment[source_group]
        source = source_by_group[source_group]
        eligible = next(
            item
            for item in source.eligible_turns
            if item.action_type == action_type and item.turn == turn
        )
        chosen.append(
            CuratedActionTurn(
                ordinal=ordinal,
                run_id=source.run_id,
                task_id=source.task_id,
                source_group_id=source_group,
                action_type=action_type,
                turn=turn,
                lock=eligible.lock,
                lock_sha256=eligible.lock_sha256,
            )
        )
    return ActionDiverseCurationPlan.create(
        curation_id=manifest.curation_id,
        project_id=manifest.project_id,
        manifest_fingerprint=manifest.fingerprint,
        idea_revision_id=idea.revision_id,
        idea_record_sha256=idea.record_sha256,
        idea_scientific_contract_sha256=idea_scientific_contract_sha256(idea),
        selection_timing=manifest.selection_timing,
        selection_algorithm=manifest.selection_algorithm,
        selection_salt=manifest.selection_salt,
        selection_uses_terminal_metric_or_credit=False,
        one_episode_per_source_group=True,
        formal_evidence=False,
        effect_claim_authorized=False,
        quotas=manifest.quotas,
        sources=tuple(sorted(sources, key=lambda item: item.source_group_id)),
        selections=tuple(chosen),
    )


def materialize_action_diverse_curation(
    manifest: ActionDiverseCurationManifest,
    plan: ActionDiverseCurationPlan,
    *,
    workspace_root: str | Path,
    outputs_root: str | Path,
) -> ActionDiverseCurationReceipt:
    workspace = Path(workspace_root).expanduser().resolve()
    runtime = ProjectRuntime(outputs_root)
    if (
        plan.curation_id != manifest.curation_id
        or plan.project_id != manifest.project_id
        or plan.manifest_fingerprint != manifest.fingerprint
    ):
        raise ValueError("action-diverse plan belongs to another manifest")
    idea = inspect_current_idea_revision(runtime, manifest.project_id).current_binding
    if (
        idea is None
        or idea.revision_id != plan.idea_revision_id
        or idea.record_sha256 != plan.idea_record_sha256
        or idea_scientific_contract_sha256(idea) != plan.idea_scientific_contract_sha256
    ):
        raise ValueError("action-diverse plan belongs to a stale current Idea")

    sources = {item.source_group_id: item for item in plan.sources}
    materialized: list[MaterializedCuratedCandidate] = []
    for selected in plan.selections:
        source = sources[selected.source_group_id]
        source_bindings = (
            source.protocol,
            source.sampling_plan,
            source.terminal_receipt,
            selected.lock,
        )
        for binding in source_bindings:
            if _sha256(_bound_file(workspace, binding.locator)) != binding.sha256:
                raise ValueError("action-diverse source bytes changed after plan compilation")
        protocol_path = _bound_file(workspace, source.protocol.locator)
        sampling_path = _bound_file(workspace, source.sampling_plan.locator)
        receipt_path = _bound_file(workspace, source.terminal_receipt.locator)
        protocol = load_interactive_taste_development_protocol(protocol_path)
        sampling_plan = load_taste_trajectory_sampling_plan(sampling_path)
        terminal_receipt = load_interactive_research_run_receipt(receipt_path)
        run_root = runtime.projects_root / manifest.project_id / "runs" / selected.run_id
        lock_paths = _effective_lock_paths(
            run_root / "interactive_development",
            terminal_receipt,
        )
        output_root = run_root / "interactive_development" / manifest.projection_stage
        batch = finalize_interactive_development_episodes(
            protocol,
            sampling_plan,
            runtime=runtime,
            current_idea_revision=idea,
            expected_project_revision=sampling_plan.observed_project_revision,
            lock_paths=lock_paths,
            receipt_path=receipt_path,
            output_root=output_root,
            curated_turn=selected.turn,
            historical_source_projection=True,
            curated_credit_projection=manifest.credit_projection,
        )
        if len(batch.items) != 1:
            raise ValueError("action-diverse curated turn did not yield exactly one candidate")
        item = batch.items[0]
        if item.turn != selected.turn:
            raise ValueError("action-diverse materialized turn differs from its plan")
        batch_path = output_root / "BATCH.json"
        candidate_path = run_root / PurePosixPath(item.candidate_locator)
        materialized.append(
            MaterializedCuratedCandidate(
                ordinal=selected.ordinal,
                run_id=selected.run_id,
                source_group_id=selected.source_group_id,
                action_type=selected.action_type,
                turn=selected.turn,
                batch=_binding(workspace, batch_path),
                batch_sha256=batch.batch_sha256,
                candidate=_binding(workspace, candidate_path),
                candidate_id=item.candidate_id,
                candidate_sha256=item.candidate_sha256,
            )
        )
    return ActionDiverseCurationReceipt.create(
        curation_id=manifest.curation_id,
        project_id=manifest.project_id,
        plan_sha256=plan.plan_sha256,
        candidates=tuple(materialized),
    )


def load_action_diverse_curation_manifest(
    path: str | Path,
) -> ActionDiverseCurationManifest:
    source = _bounded_file(path, _MAX_MANIFEST_BYTES)
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    return ActionDiverseCurationManifest.model_validate(payload)


def load_action_diverse_curation_plan(path: str | Path) -> ActionDiverseCurationPlan:
    source = _bounded_file(path, _MAX_SOURCE_BYTES)
    return ActionDiverseCurationPlan.model_validate_json(source.read_bytes(), strict=True)


def save_action_diverse_artifact(
    artifact: ActionDiverseCurationPlan | ActionDiverseCurationReceipt,
    path: str | Path,
) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as handle:
        handle.write(artifact.model_dump_json(indent=2) + "\n")
    return target


def _binding(workspace: Path, path: Path) -> CurationFileBinding:
    source = path.expanduser().resolve()
    if not source.is_relative_to(workspace):
        raise ValueError("action-diverse source escapes the workspace")
    return CurationFileBinding(
        locator=source.relative_to(workspace).as_posix(),
        sha256=_sha256(source),
    )


def _effective_lock_paths(
    stage_root: Path,
    receipt: InteractiveResearchRunReceipt,
) -> tuple[Path, ...]:
    """Resolve the exact effective lock retained for every executed turn.

    A supported early submission replaces the initially locked meta-action
    with a separately persisted STOP adjudication.  The receipt binds that
    replacement by semantic hash, so path conventions must not decide which
    predecision record becomes supervision.
    """

    lock_root = stage_root / "taste_locks"
    candidates = tuple(sorted(lock_root.glob("*/LOCK.json")))
    if not candidates:
        raise ValueError("action-diverse source has no prospective locks")
    by_semantic_sha256: dict[str, Path] = {}
    for path in candidates:
        lock = load_taste_prospective_decision_lock(_bounded_file(path, _MAX_SOURCE_BYTES))
        if lock.lock_sha256 in by_semantic_sha256:
            raise ValueError("action-diverse source repeats a prospective lock hash")
        by_semantic_sha256[lock.lock_sha256] = path

    resolved: list[Path] = []
    for record in receipt.turns:
        semantic_sha256 = _effective_lock_sha256(record)
        path = by_semantic_sha256.get(semantic_sha256)
        if path is None:
            raise ValueError(
                f"action-diverse receipt effective lock is absent at turn {record.turn}"
            )
        resolved.append(path)
    return tuple(resolved)


def _effective_lock_sha256(record: InteractiveTurnRecord) -> str:
    audit = record.guidance.audit
    value = audit.get("effective_prospective_lock_sha256")
    if value is None:
        value = audit.get("prospective_lock_sha256")
    if not isinstance(value, str) or len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError(
            f"action-diverse receipt has no valid effective lock at turn {record.turn}"
        )
    return value


def _bound_file(workspace: Path, locator: str) -> Path:
    _safe_locator(locator)
    source = workspace.joinpath(*PurePosixPath(locator).parts)
    return _bounded_file(source, _MAX_SOURCE_BYTES)


def _safe_locator(locator: str) -> None:
    pure = PurePosixPath(locator)
    if pure.is_absolute() or ".." in pure.parts or pure.as_posix() != locator:
        raise ValueError(f"unsafe action-diverse locator: {locator}")


def _bounded_file(path: str | Path, maximum_bytes: int) -> Path:
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"action-diverse input must be a regular file: {source}")
    if not 1 <= source.stat().st_size <= maximum_bytes:
        raise ValueError(f"action-diverse input exceeds its byte ceiling: {source}")
    return source


def _sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest()
