"""Project-owned refresh bundles for learned scientific Taste policies."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.project import ProjectRuntime, inspect_current_idea_revision
from scitaste.project.idea_revision import (
    ProjectIdeaRevisionBinding,
    idea_binding_matches_current,
)
from scitaste.project.models import (
    content_sha256,
    validate_entry_id,
    validate_project_id,
    validate_relative_locator,
)
from scitaste.taste.decision_families import (
    FamilyConditionedLifecycleTastePolicy,
    ScientificDecisionFamilyAssignment,
    ScientificTasteDecisionFamily,
    fit_family_conditioned_lifecycle_taste_policy,
)
from scitaste.taste.episode_learning import (
    AdmittedTasteEpisode,
    LifecycleTastePolicyConfig,
)
from scitaste.taste.episodes import TasteEpisodePartition

_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_ARTIFACT_BYTES = 64 * 1024 * 1024


class ProjectTastePolicyEpisodeBinding(BaseModel):
    """One exact admission/assignment pair owned by a project corpus."""

    model_config = _CONFIG

    admission_id: str = Field(pattern=_ID)
    admission_locator: str
    admission_artifact_sha256: str = Field(pattern=_SHA256)
    admission_sha256: str = Field(pattern=_SHA256)
    assignment_locator: str
    assignment_artifact_sha256: str = Field(pattern=_SHA256)
    assignment_sha256: str = Field(pattern=_SHA256)
    decision_family: ScientificTasteDecisionFamily
    dataset_partition: TasteEpisodePartition
    source_group_id: str = Field(pattern=_ID)
    cross_model_ai_attribution: Literal[True] = True
    runtime_bound_ai_family_review: Literal[True] = True
    not_human_review: Literal[True] = True

    @model_validator(mode="after")
    def binding_is_closed(self) -> ProjectTastePolicyEpisodeBinding:
        validate_entry_id(self.admission_id, field_name="project Taste admission_id")
        validate_relative_locator(self.admission_locator, field_name="Taste admission locator")
        validate_relative_locator(self.assignment_locator, field_name="Taste assignment locator")
        if self.dataset_partition is TasteEpisodePartition.FORMAL_HELDOUT:
            raise ValueError("formal-heldout Taste episodes cannot enter a project policy corpus")
        return self


class ProjectTastePolicyCorpusManifest(BaseModel):
    """Explicit, immutable project population used by one policy refresh."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    corpus_id: str = Field(pattern=_ID)
    project_id: str
    observed_project_revision: int = Field(ge=0)
    observed_project_snapshot_sha256: str = Field(pattern=_SHA256)
    idea_revision: ProjectIdeaRevisionBinding
    episodes: tuple[ProjectTastePolicyEpisodeBinding, ...] = Field(min_length=1)
    population_sha256: str = Field(pattern=_SHA256)
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    human_validity_claim_allowed: Literal[False] = False
    policy_refresh_authorized: Literal[False] = False
    corpus_manifest_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def manifest_is_closed(self) -> ProjectTastePolicyCorpusManifest:
        validate_entry_id(self.corpus_id, field_name="project Taste corpus_id")
        validate_project_id(self.project_id)
        if self.idea_revision.project_id != self.project_id:
            raise ValueError("project Taste corpus Idea belongs to another project")
        if self.idea_revision.observed_project_revision > self.observed_project_revision:
            raise ValueError("project Taste corpus predates its Idea binding")
        if self.episodes != tuple(sorted(self.episodes, key=lambda item: item.admission_id)):
            raise ValueError("project Taste corpus episodes are not canonical")
        if len({item.admission_id for item in self.episodes}) != len(self.episodes):
            raise ValueError("project Taste corpus repeats an admission")
        expected_population = content_sha256(
            tuple(item.model_dump(mode="json") for item in self.episodes)
        )
        if self.population_sha256 != expected_population:
            raise ValueError("project Taste corpus population hash differs")
        expected = content_sha256(
            self.model_dump(mode="json", exclude={"corpus_manifest_sha256"})
        )
        if self.corpus_manifest_sha256 != expected:
            raise ValueError("project Taste corpus manifest hash differs")
        return self

    @classmethod
    def create(cls, **values: object) -> ProjectTastePolicyCorpusManifest:
        payload = {
            "schema_version": "1.0",
            "reviewer_kind": "ai",
            "not_human_review": True,
            "human_validity_claim_allowed": False,
            "policy_refresh_authorized": False,
            **values,
        }
        payload.pop("corpus_manifest_sha256", None)
        episodes = tuple(
            sorted(payload["episodes"], key=lambda item: item.admission_id)  # type: ignore[arg-type]
        )
        payload["episodes"] = episodes
        payload["population_sha256"] = content_sha256(
            tuple(item.model_dump(mode="json") for item in episodes)
        )
        unsigned = cls.model_construct(corpus_manifest_sha256="0" * 64, **payload)
        return cls(
            **payload,
            corpus_manifest_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"corpus_manifest_sha256"})
            ),
        )


class ProjectTastePolicyFamilyReadiness(BaseModel):
    """Support and actionability of one isolated decision-family head."""

    model_config = _CONFIG

    decision_family: ScientificTasteDecisionFamily
    source_episode_count: int = Field(ge=0)
    training_episode_count: int = Field(ge=0)
    maximum_feature_support: float = Field(ge=0.0)
    support_sufficient: bool
    adaptive_head_ready: bool


class ProjectTastePolicyReadiness(BaseModel):
    """Conservative activation gate; it never substitutes for an effect experiment."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    corpus_id: str = Field(pattern=_ID)
    corpus_manifest_sha256: str = Field(pattern=_SHA256)
    policy_id: str = Field(pattern=_ID)
    policy_sha256: str = Field(pattern=_SHA256)
    minimum_feature_support: float = Field(ge=0.0)
    families: tuple[ProjectTastePolicyFamilyReadiness, ...]
    source_episode_count: int = Field(ge=1)
    training_episode_count: int = Field(ge=0)
    observed_family_count: int = Field(ge=0)
    support_sufficient_family_count: int = Field(ge=0)
    adaptive_head_ready_family_count: int = Field(ge=0)
    policy_application_ready: bool
    policy_application_authorized: Literal[False] = False
    formal_effect_claim_ready: Literal[False] = False
    scientific_effectiveness_established: Literal[False] = False
    reason_codes: tuple[str, ...] = Field(min_length=1)
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    human_validity_claim_allowed: Literal[False] = False
    readiness_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def readiness_is_closed(self) -> ProjectTastePolicyReadiness:
        validate_project_id(self.project_id)
        ordered = tuple(sorted(self.families, key=lambda item: item.decision_family.value))
        if self.families != ordered or {item.decision_family for item in ordered} != set(
            ScientificTasteDecisionFamily
        ):
            raise ValueError("project Taste readiness must cover the canonical family ontology")
        expected_counts = (
            sum(item.source_episode_count for item in ordered),
            sum(item.training_episode_count for item in ordered),
            sum(item.source_episode_count > 0 for item in ordered),
            sum(item.support_sufficient for item in ordered),
            sum(item.adaptive_head_ready for item in ordered),
        )
        observed_counts = (
            self.source_episode_count,
            self.training_episode_count,
            self.observed_family_count,
            self.support_sufficient_family_count,
            self.adaptive_head_ready_family_count,
        )
        if observed_counts != expected_counts:
            raise ValueError("project Taste readiness aggregate counts differ")
        if self.policy_application_ready != bool(self.adaptive_head_ready_family_count):
            raise ValueError("project Taste application readiness differs from family heads")
        expected_reasons = _readiness_reason_codes(ordered)
        if self.reason_codes != expected_reasons:
            raise ValueError("project Taste readiness reasons differ")
        expected = content_sha256(self.model_dump(mode="json", exclude={"readiness_sha256"}))
        if self.readiness_sha256 != expected:
            raise ValueError("project Taste readiness hash differs")
        return self

    @classmethod
    def create(cls, **values: object) -> ProjectTastePolicyReadiness:
        payload = {
            "schema_version": "1.0",
            "policy_application_authorized": False,
            "formal_effect_claim_ready": False,
            "scientific_effectiveness_established": False,
            "reviewer_kind": "ai",
            "not_human_review": True,
            "human_validity_claim_allowed": False,
            **values,
        }
        payload.pop("readiness_sha256", None)
        unsigned = cls.model_construct(readiness_sha256="0" * 64, **payload)
        return cls(
            **payload,
            readiness_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"readiness_sha256"})
            ),
        )


class ProjectTastePolicyRefreshReceipt(BaseModel):
    """File-level closure over one atomically published refresh bundle."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    refresh_id: str = Field(pattern=_ID)
    project_id: str
    observed_project_revision: int = Field(ge=0)
    observed_project_snapshot_sha256: str = Field(pattern=_SHA256)
    idea_revision: ProjectIdeaRevisionBinding
    corpus_manifest_sha256: str = Field(pattern=_SHA256)
    config_sha256: str = Field(pattern=_SHA256)
    policy_sha256: str = Field(pattern=_SHA256)
    readiness_sha256: str = Field(pattern=_SHA256)
    artifacts: dict[str, str]
    policy_application_ready: bool
    policy_application_authorized: Literal[False] = False
    formal_effect_claim_ready: Literal[False] = False
    no_model_calls_performed: Literal[True] = True
    no_api_calls_performed: Literal[True] = True
    no_gpu_work_performed: Literal[True] = True
    refresh_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def receipt_is_closed(self) -> ProjectTastePolicyRefreshReceipt:
        validate_entry_id(self.refresh_id, field_name="project Taste refresh_id")
        validate_project_id(self.project_id)
        if self.idea_revision.project_id != self.project_id:
            raise ValueError("project Taste refresh Idea belongs to another project")
        if tuple(self.artifacts) != tuple(sorted(self.artifacts)):
            raise ValueError("project Taste refresh artifacts are not canonical")
        if set(self.artifacts) != {
            "CORPUS_MANIFEST.json",
            "POLICY_CONFIG.json",
            "POLICY.json",
            "READINESS.json",
        }:
            raise ValueError("project Taste refresh bundle is incomplete")
        if any(len(value) != 64 for value in self.artifacts.values()):
            raise ValueError("project Taste refresh artifact hash is malformed")
        expected = content_sha256(self.model_dump(mode="json", exclude={"refresh_sha256"}))
        if self.refresh_sha256 != expected:
            raise ValueError("project Taste refresh receipt hash differs")
        return self

    @classmethod
    def create(cls, **values: object) -> ProjectTastePolicyRefreshReceipt:
        payload = {
            "schema_version": "1.0",
            "policy_application_authorized": False,
            "formal_effect_claim_ready": False,
            "no_model_calls_performed": True,
            "no_api_calls_performed": True,
            "no_gpu_work_performed": True,
            **values,
        }
        payload.pop("refresh_sha256", None)
        unsigned = cls.model_construct(refresh_sha256="0" * 64, **payload)
        return cls(
            **payload,
            refresh_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"refresh_sha256"})
            ),
        )


def seal_project_taste_policy_corpus(
    runtime: ProjectRuntime,
    *,
    project_id: str,
    corpus_id: str,
    episode_paths: tuple[str | Path, ...],
    assignment_paths: tuple[str | Path, ...],
    expected_project_revision: int,
) -> ProjectTastePolicyCorpusManifest:
    """Bind an explicit AI-reviewed episode population without fitting a policy."""

    snapshot = runtime.open(project_id)
    if snapshot.revision != expected_project_revision:
        raise ValueError(
            "project Taste corpus expected revision "
            f"{expected_project_revision}, observed {snapshot.revision}"
        )
    idea = inspect_current_idea_revision(runtime, project_id)
    if idea.current_binding is None:
        codes = ", ".join(item.code for item in idea.findings)
        raise ValueError(f"project Taste corpus requires a verified current Idea: {codes}")
    if not episode_paths or len(episode_paths) != len(assignment_paths):
        raise ValueError("project Taste corpus requires one assignment per episode")

    project_root = runtime.projects_root / project_id
    episodes = {
        episode.admission_id: (episode, locator, artifact_sha256)
        for episode, locator, artifact_sha256 in (
            _load_project_admission(project_root, path) for path in episode_paths
        )
    }
    assignments = {
        assignment.admission_id: (assignment, locator, artifact_sha256)
        for assignment, locator, artifact_sha256 in (
            _load_project_assignment(project_root, path) for path in assignment_paths
        )
    }
    if len(episodes) != len(episode_paths) or len(assignments) != len(assignment_paths):
        raise ValueError("project Taste corpus received duplicate episode identities")
    if set(episodes) != set(assignments):
        raise ValueError("project Taste corpus assignments do not exactly cover episodes")

    bindings: list[ProjectTastePolicyEpisodeBinding] = []
    for admission_id in sorted(episodes):
        episode, admission_locator, admission_artifact_sha256 = episodes[admission_id]
        assignment, assignment_locator, assignment_artifact_sha256 = assignments[admission_id]
        if episode.candidate.project_id != project_id:
            raise ValueError("project Taste corpus episode belongs to another project")
        if not idea_binding_matches_current(
            episode.candidate.idea_revision,
            idea.current_binding,
        ):
            raise ValueError("project Taste corpus episode belongs to a stale Idea")
        if episode.review_evidence_kind != "ai" or not episode.cross_model_ai_panel:
            raise ValueError("project Taste corpus requires cross-model AI attribution")
        if assignment.admission_sha256 != episode.admission_sha256:
            raise ValueError("project Taste family assignment binds different episode bytes")
        if not assignment.runtime_review_evidence_bound:
            raise ValueError("project Taste corpus requires runtime-bound AI family review")
        partition = episode.candidate.dataset_partition
        source_group_id = episode.candidate.source_group_id
        if partition is None or source_group_id is None:
            raise ValueError("project Taste corpus requires a frozen episode sampling unit")
        bindings.append(
            ProjectTastePolicyEpisodeBinding(
                admission_id=admission_id,
                admission_locator=admission_locator,
                admission_artifact_sha256=admission_artifact_sha256,
                admission_sha256=episode.admission_sha256,
                assignment_locator=assignment_locator,
                assignment_artifact_sha256=assignment_artifact_sha256,
                assignment_sha256=assignment.assignment_sha256,
                decision_family=assignment.decision_family,
                dataset_partition=partition,
                source_group_id=source_group_id,
                cross_model_ai_attribution=True,
                runtime_bound_ai_family_review=True,
                not_human_review=True,
            )
        )
    return ProjectTastePolicyCorpusManifest.create(
        corpus_id=corpus_id,
        project_id=project_id,
        observed_project_revision=snapshot.revision,
        observed_project_snapshot_sha256=snapshot.snapshot_sha256,
        idea_revision=idea.current_binding,
        episodes=tuple(bindings),
    )


def refresh_project_taste_policy(
    runtime: ProjectRuntime,
    manifest: ProjectTastePolicyCorpusManifest,
    config: LifecycleTastePolicyConfig,
    *,
    policy_id: str,
    expected_project_revision: int,
) -> tuple[FamilyConditionedLifecycleTastePolicy, ProjectTastePolicyReadiness]:
    """Reverify a corpus, fit isolated heads, and report conservative actionability."""

    validate_entry_id(policy_id, field_name="project Taste policy_id")
    snapshot = runtime.open(manifest.project_id)
    if snapshot.revision != expected_project_revision:
        raise ValueError(
            "project Taste refresh expected revision "
            f"{expected_project_revision}, observed {snapshot.revision}"
        )
    idea = inspect_current_idea_revision(runtime, manifest.project_id)
    if idea.current_binding is None:
        codes = ", ".join(item.code for item in idea.findings)
        raise ValueError(f"project Taste refresh requires a verified current Idea: {codes}")
    if not idea_binding_matches_current(manifest.idea_revision, idea.current_binding):
        raise ValueError("project Taste corpus belongs to a stale Idea")
    if not idea_binding_matches_current(config.idea_revision, idea.current_binding):
        raise ValueError("project Taste policy config belongs to a stale Idea")

    project_root = runtime.projects_root / manifest.project_id
    episodes: list[AdmittedTasteEpisode] = []
    assignments: list[ScientificDecisionFamilyAssignment] = []
    for binding in manifest.episodes:
        episode, admission_raw = _load_bound_admission(project_root, binding.admission_locator)
        assignment, assignment_raw = _load_bound_assignment(
            project_root,
            binding.assignment_locator,
        )
        if _sha256(admission_raw) != binding.admission_artifact_sha256:
            raise ValueError("project Taste admission artifact changed after corpus sealing")
        if _sha256(assignment_raw) != binding.assignment_artifact_sha256:
            raise ValueError("project Taste assignment artifact changed after corpus sealing")
        if (
            episode.admission_id != binding.admission_id
            or episode.admission_sha256 != binding.admission_sha256
            or assignment.admission_id != binding.admission_id
            or assignment.admission_sha256 != binding.admission_sha256
            or assignment.assignment_sha256 != binding.assignment_sha256
            or assignment.decision_family is not binding.decision_family
        ):
            raise ValueError("project Taste corpus semantic binding changed")
        episodes.append(episode)
        assignments.append(assignment)

    policy = fit_family_conditioned_lifecycle_taste_policy(
        tuple(episodes),
        tuple(assignments),
        config,
        policy_id=policy_id,
    )
    families: list[ProjectTastePolicyFamilyReadiness] = []
    for family in sorted(ScientificTasteDecisionFamily, key=lambda item: item.value):
        head = policy.family_heads.get(family)
        maximum_support = max(
            (item.support for item in (() if head is None else head.feature_posteriors)),
            default=0.0,
        )
        families.append(
            ProjectTastePolicyFamilyReadiness(
                decision_family=family,
                source_episode_count=(0 if head is None else len(head.source_episode_ids)),
                training_episode_count=(0 if head is None else head.training_episode_count),
                maximum_feature_support=maximum_support,
                support_sufficient=(
                    head is not None
                    and bool(head.feature_posteriors)
                    and maximum_support >= head.config.minimum_feature_support
                ),
                adaptive_head_ready=(head is not None and head.h4_adaptive_policy_eligible),
            )
        )
    family_readiness = tuple(families)
    return policy, ProjectTastePolicyReadiness.create(
        project_id=manifest.project_id,
        corpus_id=manifest.corpus_id,
        corpus_manifest_sha256=manifest.corpus_manifest_sha256,
        policy_id=policy.policy_id,
        policy_sha256=policy.policy_sha256,
        minimum_feature_support=config.minimum_feature_support,
        families=family_readiness,
        source_episode_count=sum(item.source_episode_count for item in family_readiness),
        training_episode_count=sum(item.training_episode_count for item in family_readiness),
        observed_family_count=sum(item.source_episode_count > 0 for item in family_readiness),
        support_sufficient_family_count=sum(
            item.support_sufficient for item in family_readiness
        ),
        adaptive_head_ready_family_count=sum(
            item.adaptive_head_ready for item in family_readiness
        ),
        policy_application_ready=any(item.adaptive_head_ready for item in family_readiness),
        reason_codes=_readiness_reason_codes(family_readiness),
    )


def materialize_project_taste_policy_refresh(
    runtime: ProjectRuntime,
    manifest: ProjectTastePolicyCorpusManifest,
    config: LifecycleTastePolicyConfig,
    *,
    refresh_id: str,
    policy_id: str,
    expected_project_revision: int,
    output_directory: str | Path,
) -> ProjectTastePolicyRefreshReceipt:
    """Publish one complete refresh directory or leave no partial bundle."""

    policy, readiness = refresh_project_taste_policy(
        runtime,
        manifest,
        config,
        policy_id=policy_id,
        expected_project_revision=expected_project_revision,
    )
    snapshot = runtime.open(manifest.project_id)
    idea = inspect_current_idea_revision(runtime, manifest.project_id)
    assert idea.current_binding is not None
    target = Path(output_directory).resolve()
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{target.name}-", dir=target.parent))
    try:
        payloads = {
            "CORPUS_MANIFEST.json": _json_bytes(manifest),
            "POLICY_CONFIG.json": _json_bytes(config),
            "POLICY.json": _json_bytes(policy),
            "READINESS.json": _json_bytes(readiness),
        }
        artifact_hashes = {name: _sha256(raw) for name, raw in sorted(payloads.items())}
        receipt = ProjectTastePolicyRefreshReceipt.create(
            refresh_id=refresh_id,
            project_id=manifest.project_id,
            observed_project_revision=snapshot.revision,
            observed_project_snapshot_sha256=snapshot.snapshot_sha256,
            idea_revision=idea.current_binding,
            corpus_manifest_sha256=manifest.corpus_manifest_sha256,
            config_sha256=config.config_sha256,
            policy_sha256=policy.policy_sha256,
            readiness_sha256=readiness.readiness_sha256,
            artifacts=artifact_hashes,
            policy_application_ready=readiness.policy_application_ready,
        )
        for name, raw in payloads.items():
            _write_new(temporary / name, raw)
        _write_new(temporary / "REFRESH.json", _json_bytes(receipt))
        _fsync_directory(temporary)
        os.replace(temporary, target)
        _fsync_directory(target.parent)
        return receipt
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def load_project_taste_policy_corpus(
    path: str | Path,
) -> ProjectTastePolicyCorpusManifest:
    """Load one bounded immutable project corpus manifest."""

    raw = _bounded_regular_file(Path(path), label="project Taste corpus manifest")
    return ProjectTastePolicyCorpusManifest.model_validate_json(raw, strict=True)


def save_project_taste_policy_corpus(
    manifest: ProjectTastePolicyCorpusManifest,
    path: str | Path,
) -> Path:
    """Persist one new corpus manifest without replacing earlier evidence."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    _write_new(target, _json_bytes(manifest))
    _fsync_directory(target.parent)
    return target


def _load_project_admission(
    project_root: Path,
    path: str | Path,
) -> tuple[AdmittedTasteEpisode, str, str]:
    locator, raw = _project_file_from_path(project_root, Path(path), label="Taste admission")
    return AdmittedTasteEpisode.model_validate_json(raw, strict=True), locator, _sha256(raw)


def _load_project_assignment(
    project_root: Path,
    path: str | Path,
) -> tuple[ScientificDecisionFamilyAssignment, str, str]:
    locator, raw = _project_file_from_path(project_root, Path(path), label="Taste assignment")
    return (
        ScientificDecisionFamilyAssignment.model_validate_json(raw, strict=True),
        locator,
        _sha256(raw),
    )


def _load_bound_admission(
    project_root: Path,
    locator: str,
) -> tuple[AdmittedTasteEpisode, bytes]:
    raw = _project_file_from_locator(project_root, locator, label="Taste admission")
    return AdmittedTasteEpisode.model_validate_json(raw, strict=True), raw


def _load_bound_assignment(
    project_root: Path,
    locator: str,
) -> tuple[ScientificDecisionFamilyAssignment, bytes]:
    raw = _project_file_from_locator(project_root, locator, label="Taste assignment")
    return ScientificDecisionFamilyAssignment.model_validate_json(raw, strict=True), raw


def _project_file_from_path(
    project_root: Path,
    path: Path,
    *,
    label: str,
) -> tuple[str, bytes]:
    source = path.resolve(strict=True)
    root = project_root.resolve(strict=True)
    try:
        locator = source.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError(f"{label} must be owned by the target project") from exc
    return locator, _project_file_from_locator(project_root, locator, label=label)


def _project_file_from_locator(project_root: Path, locator: str, *, label: str) -> bytes:
    validate_relative_locator(locator, field_name=f"{label} locator")
    root = project_root.resolve(strict=True)
    path = project_root / PurePosixPath(locator)
    cursor = project_root
    for part in PurePosixPath(locator).parts:
        cursor /= part
        if cursor.is_symlink():
            raise ValueError(f"{label} locator cannot traverse a symbolic link")
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label} locator escapes its project") from exc
    return _bounded_regular_file(resolved, label=label)


def _bounded_regular_file(path: Path, *, label: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular non-symlink file")
    raw = path.read_bytes()
    if not 1 <= len(raw) <= _MAX_ARTIFACT_BYTES:
        raise ValueError(f"{label} has an invalid size")
    return raw


def _readiness_reason_codes(
    families: tuple[ProjectTastePolicyFamilyReadiness, ...],
) -> tuple[str, ...]:
    codes: list[str] = ["formal-effect-evaluation-required"]
    if not any(item.training_episode_count for item in families):
        codes.append("no-training-eligible-episodes")
    if not all(item.source_episode_count for item in families):
        codes.append("incomplete-decision-family-coverage")
    if not any(item.support_sufficient for item in families):
        codes.append("insufficient-family-support")
    if not any(item.adaptive_head_ready for item in families):
        codes.append("no-adaptive-head-ready")
    else:
        codes.append("bounded-application-ready")
    return tuple(sorted(codes))


def _json_bytes(value: BaseModel) -> bytes:
    return (
        json.dumps(
            value.model_dump(mode="json"),
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode()


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _write_new(path: Path, raw: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "ProjectTastePolicyCorpusManifest",
    "ProjectTastePolicyEpisodeBinding",
    "ProjectTastePolicyFamilyReadiness",
    "ProjectTastePolicyReadiness",
    "ProjectTastePolicyRefreshReceipt",
    "load_project_taste_policy_corpus",
    "materialize_project_taste_policy_refresh",
    "refresh_project_taste_policy",
    "save_project_taste_policy_corpus",
    "seal_project_taste_policy_corpus",
]
