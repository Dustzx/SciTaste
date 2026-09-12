"""Git-pinned, no-run scientific preflight for native Taste conditions."""

from __future__ import annotations

import hashlib
import json
import posixpath
import subprocess
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.evaluation.prelaunch import ReadinessStatus
from scitaste.taste.conditions import NativeConditionMatrix, NativeTasteCondition

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_COMMIT = r"^[0-9a-f]{40}$"
_MAX_MANIFEST_BYTES = 1_048_576
_MAX_GIT_OBJECT_BYTES = 2 * 1_048_576


class NativePathRequirement(StrEnum):
    CONDITION_RUNTIME = "condition_runtime"
    FIXED_CANDIDATE_SELECTION = "fixed_candidate_selection"
    BACKEND_IDENTITY = "backend_identity"
    DECISION_TELEMETRY = "decision_telemetry"
    MODEL_CANDIDATE_GENERATION = "model_candidate_generation"
    MATCHED_PLACEBO_CORPORA = "matched_placebo_corpora"
    CHECKPOINT_EXECUTION = "checkpoint_execution"


class CorpusParityDimension(StrEnum):
    STAGE_DECISION_ROLE = "stage_decision_role"
    ELIGIBLE_CASE_COUNT = "eligible_case_count"
    RETRIEVED_CASE_COUNT = "retrieved_case_count"
    CONTEXT_TOKEN_BUDGET = "context_token_budget"
    PROVENANCE_TIER = "provenance_tier"
    CURATION_TIER = "curation_tier"
    OUTCOME_INFORMATION_AVAILABILITY = "outcome_information_availability"


class NativeRequirementEvidence(BaseModel):
    model_config = _CONFIG

    status: ReadinessStatus
    summary: str = Field(min_length=1, max_length=4_000)
    evidence_ref: str | None = Field(default=None, max_length=1_000)
    evidence_sha256: str | None = Field(default=None, pattern=_SHA256)

    @model_validator(mode="after")
    def evidence_binding_is_complete(self) -> NativeRequirementEvidence:
        if (self.evidence_ref is None) != (self.evidence_sha256 is None):
            raise ValueError("native requirement evidence reference and SHA-256 must be paired")
        if self.status is ReadinessStatus.VERIFIED and self.evidence_ref is None:
            raise ValueError("verified native requirements require Git-pinned evidence")
        return self


class NativeCorpusPairContract(BaseModel):
    model_config = _CONFIG

    matched_relation: Literal["task-domain-matched"]
    placebo_relation: Literal["source-disjoint-domain-mismatched"]
    only_permitted_difference: Literal["source_domain_relation"]
    dimensions: dict[CorpusParityDimension, ReadinessStatus]
    matched_corpus_ref: str | None = Field(default=None, max_length=1_000)
    matched_corpus_sha256: str | None = Field(default=None, pattern=_SHA256)
    placebo_corpus_ref: str | None = Field(default=None, max_length=1_000)
    placebo_corpus_sha256: str | None = Field(default=None, pattern=_SHA256)
    pair_attestation_ref: str | None = Field(default=None, max_length=1_000)
    pair_attestation_sha256: str | None = Field(default=None, pattern=_SHA256)
    zero_retrieval_invalidates_cell: Literal[True] = True

    @model_validator(mode="after")
    def parity_contract_is_closed(self) -> NativeCorpusPairContract:
        if set(self.dimensions) != set(CorpusParityDimension):
            raise ValueError("native corpus parity dimension matrix must be complete")
        pairs = (
            (self.matched_corpus_ref, self.matched_corpus_sha256),
            (self.placebo_corpus_ref, self.placebo_corpus_sha256),
            (self.pair_attestation_ref, self.pair_attestation_sha256),
        )
        if any((ref is None) != (digest is None) for ref, digest in pairs):
            raise ValueError("native corpus references and SHA-256 values must be paired")
        any_verified = any(
            status is ReadinessStatus.VERIFIED for status in self.dimensions.values()
        )
        if any_verified and not all(ref is not None for pair in pairs for ref in pair):
            raise ValueError("verified corpus parity requires both corpora and pair attestation")
        return self


class NativeConditionPreflightManifest(BaseModel):
    """One fixed implementation claim that cannot authorize a model or experiment run."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    preflight_id: str = Field(pattern=_ID)
    authorization_scope: Literal["static-git-inspection-only"]
    source_commit: str = Field(pattern=_COMMIT)
    workflow_config_ref: str = Field(min_length=1, max_length=1_000)
    workflow_config_sha256: str = Field(pattern=_SHA256)
    condition_matrix_ref: str = Field(min_length=1, max_length=1_000)
    condition_matrix_sha256: str = Field(pattern=_SHA256)
    preference_backend_ref: str = Field(min_length=1, max_length=1_000)
    preference_backend_sha256: str = Field(pattern=_SHA256)
    expected_provider: str = Field(min_length=1, max_length=200)
    expected_model: str = Field(min_length=1, max_length=500)
    expected_checkpoint_sha256: str = Field(pattern=_SHA256)
    requirements: dict[NativePathRequirement, NativeRequirementEvidence]
    corpus_pair: NativeCorpusPairContract
    no_dataset_download: Literal[True] = True
    no_api_call: Literal[True] = True
    no_ssh: Literal[True] = True
    no_gpu_or_model_execution: Literal[True] = True
    no_experiment_execution: Literal[True] = True
    authorizes_execution: Literal[False] = False

    @model_validator(mode="after")
    def requirement_matrix_is_complete(self) -> NativeConditionPreflightManifest:
        if set(self.requirements) != set(NativePathRequirement):
            raise ValueError("native path requirement matrix must be complete")
        return self

    @property
    def proposal_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json"))


class NativeConditionPreflightInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    manifest: NativeConditionPreflightManifest


class NativeConditionPreflightFinding(BaseModel):
    model_config = _CONFIG

    code: str = Field(pattern=r"^[a-z0-9]+(?:[a-z0-9_:-]*[a-z0-9])?$")
    message: str = Field(min_length=1, max_length=4_000)


class NativeConditionPreflightReport(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    preflight_id: str
    proposal_sha256: str = Field(pattern=_SHA256)
    source_commit: str = Field(pattern=_COMMIT)
    observed_head_commit: str | None = Field(default=None, pattern=_COMMIT)
    source_commit_available: bool
    source_commit_is_ancestor: bool
    static_action_path_verified: bool
    model_candidate_generation_verified: bool
    corpus_pair_verified: bool
    checkpoint_execution_verified: bool
    ready_for_experiment: bool
    authorizes_execution: Literal[False] = False
    verified_requirements: tuple[NativePathRequirement, ...]
    pending_requirements: tuple[NativePathRequirement, ...]
    blocked_requirements: tuple[NativePathRequirement, ...]
    corpus_parity_status: dict[CorpusParityDimension, ReadinessStatus]
    blockers: tuple[NativeConditionPreflightFinding, ...]
    no_external_action_performed: Literal[True] = True


def load_native_condition_preflight_manifest(
    path: str | Path,
) -> NativeConditionPreflightInspection:
    requested = Path(path)
    if requested.is_symlink():
        raise ValueError("native condition preflight must not be a symlink")
    resolved = requested.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size > _MAX_MANIFEST_BYTES:
        raise ValueError("native condition preflight must be a bounded regular file")
    raw = resolved.read_bytes()
    try:
        payload = yaml.safe_load(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ValueError("native condition preflight must be UTF-8") from exc
    if not isinstance(payload, dict):
        raise ValueError("native condition preflight root must be a YAML mapping")
    return NativeConditionPreflightInspection(
        path=resolved,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        manifest=NativeConditionPreflightManifest.model_validate(payload),
    )


def inspect_native_condition_preflight(
    inspection: NativeConditionPreflightInspection,
    *,
    source_root: str | Path,
) -> NativeConditionPreflightReport:
    """Inspect only local Git objects; never load a checkpoint or touch external state."""

    manifest = inspection.manifest
    blockers: list[NativeConditionPreflightFinding] = []
    try:
        root = Path(source_root).resolve(strict=True)
        head = _git_text(root, "rev-parse", "HEAD")
    except (OSError, ValueError) as exc:
        root = None
        head = None
        _add(blockers, "source_repository_unavailable", str(exc))

    source_available = False
    source_is_ancestor = False
    objects: dict[str, bytes] = {}
    if root is not None:
        source_available = _git_commit_exists(root, manifest.source_commit)
        if not source_available:
            _add(blockers, "source_commit_unavailable", "source commit is absent from local Git")
        else:
            source_is_ancestor = _git_is_ancestor(root, manifest.source_commit, head)
            if not source_is_ancestor:
                _add(
                    blockers,
                    "source_commit_not_ancestor",
                    "source commit is not an ancestor of the inspected checkout",
                )
            expected_objects = {
                manifest.workflow_config_ref: manifest.workflow_config_sha256,
                manifest.condition_matrix_ref: manifest.condition_matrix_sha256,
                manifest.preference_backend_ref: manifest.preference_backend_sha256,
            }
            for evidence in manifest.requirements.values():
                if evidence.evidence_ref is not None and evidence.evidence_sha256 is not None:
                    prior = expected_objects.get(evidence.evidence_ref)
                    if prior is not None and prior != evidence.evidence_sha256:
                        _add(
                            blockers,
                            "conflicting_evidence_hash",
                            f"one Git object has conflicting hashes: {evidence.evidence_ref}",
                        )
                    expected_objects[evidence.evidence_ref] = evidence.evidence_sha256
            for locator, expected_sha256 in expected_objects.items():
                value = _git_object(root, manifest.source_commit, locator, blockers)
                if value is None:
                    continue
                objects[locator] = value
                if hashlib.sha256(value).hexdigest() != expected_sha256:
                    _add(
                        blockers,
                        "git_object_hash_mismatch",
                        f"Git object hash differs: {locator}",
                    )

    _inspect_semantic_bindings(manifest, objects, blockers)

    verified = tuple(
        requirement
        for requirement in NativePathRequirement
        if manifest.requirements[requirement].status is ReadinessStatus.VERIFIED
    )
    pending = tuple(
        requirement
        for requirement in NativePathRequirement
        if manifest.requirements[requirement].status is ReadinessStatus.PENDING
    )
    blocked = tuple(
        requirement
        for requirement in NativePathRequirement
        if manifest.requirements[requirement].status is ReadinessStatus.BLOCKED
    )
    action_requirements = {
        NativePathRequirement.CONDITION_RUNTIME,
        NativePathRequirement.FIXED_CANDIDATE_SELECTION,
        NativePathRequirement.BACKEND_IDENTITY,
        NativePathRequirement.DECISION_TELEMETRY,
    }
    static_action = not blockers and action_requirements <= set(verified)
    candidate_generation = (
        manifest.requirements[NativePathRequirement.MODEL_CANDIDATE_GENERATION].status
        is ReadinessStatus.VERIFIED
    )
    corpus_verified = manifest.requirements[
        NativePathRequirement.MATCHED_PLACEBO_CORPORA
    ].status is ReadinessStatus.VERIFIED and all(
        status is ReadinessStatus.VERIFIED for status in manifest.corpus_pair.dimensions.values()
    )
    checkpoint_verified = (
        manifest.requirements[NativePathRequirement.CHECKPOINT_EXECUTION].status
        is ReadinessStatus.VERIFIED
    )
    for requirement in (*pending, *blocked):
        _add(
            blockers,
            f"requirement_not_verified:{requirement.value}",
            manifest.requirements[requirement].summary,
        )
    for dimension, status in manifest.corpus_pair.dimensions.items():
        if status is not ReadinessStatus.VERIFIED:
            _add(
                blockers,
                f"corpus_parity_not_verified:{dimension.value}",
                f"matched/placebo corpus parity is {status.value}: {dimension.value}",
            )
    ready = (
        static_action
        and candidate_generation
        and corpus_verified
        and checkpoint_verified
        and len(verified) == len(NativePathRequirement)
        and not blockers
    )
    return NativeConditionPreflightReport(
        preflight_id=manifest.preflight_id,
        proposal_sha256=manifest.proposal_sha256,
        source_commit=manifest.source_commit,
        observed_head_commit=head,
        source_commit_available=source_available,
        source_commit_is_ancestor=source_is_ancestor,
        static_action_path_verified=static_action,
        model_candidate_generation_verified=candidate_generation,
        corpus_pair_verified=corpus_verified,
        checkpoint_execution_verified=checkpoint_verified,
        ready_for_experiment=ready,
        verified_requirements=verified,
        pending_requirements=pending,
        blocked_requirements=blocked,
        corpus_parity_status=manifest.corpus_pair.dimensions,
        blockers=tuple(blockers),
    )


def _inspect_semantic_bindings(
    manifest: NativeConditionPreflightManifest,
    objects: dict[str, bytes],
    blockers: list[NativeConditionPreflightFinding],
) -> None:
    required = (
        manifest.workflow_config_ref,
        manifest.condition_matrix_ref,
        manifest.preference_backend_ref,
    )
    if any(locator not in objects for locator in required):
        return
    try:
        workflow = _yaml_mapping(objects[manifest.workflow_config_ref], "workflow")
        matrix_payload = _yaml_mapping(objects[manifest.condition_matrix_ref], "condition matrix")
        backend = _yaml_mapping(objects[manifest.preference_backend_ref], "preference backend")
        matrix = NativeConditionMatrix.model_validate(matrix_payload)
    except ValueError as exc:
        _add(blockers, "semantic_binding_invalid", str(exc))
        return
    if {item.condition_id for item in matrix.profiles} != set(NativeTasteCondition):
        _add(
            blockers,
            "condition_population_drift",
            "condition matrix is not the closed six-arm set",
        )
    workflow_parent = PurePosixPath(manifest.workflow_config_ref).parent
    expected_matrix = _relative_locator(workflow_parent, workflow.get("native_condition_config"))
    expected_backend = _relative_locator(
        workflow_parent, workflow.get("native_preference_backend_config")
    )
    if expected_matrix != manifest.condition_matrix_ref:
        _add(
            blockers,
            "workflow_matrix_binding_mismatch",
            "workflow binds another condition matrix",
        )
    if expected_backend != manifest.preference_backend_ref:
        _add(
            blockers,
            "workflow_backend_binding_mismatch",
            "workflow binds another preference backend",
        )
    expected_model = f"{backend.get('model_id')}@{backend.get('model_revision')}"
    identities = (
        workflow.get("provider") == manifest.expected_provider == backend.get("provider"),
        workflow.get("model") == manifest.expected_model == expected_model,
        backend.get("checkpoint_sha256") == manifest.expected_checkpoint_sha256,
    )
    if not all(identities):
        _add(blockers, "model_identity_binding_mismatch", "workflow and backend identities differ")
    if workflow.get("execution_backend") != "scitaste-native":
        _add(blockers, "non_native_workflow", "native condition preflight requires SciTaste Native")
    generation_status = manifest.requirements[
        NativePathRequirement.MODEL_CANDIDATE_GENERATION
    ].status
    if (
        generation_status is ReadinessStatus.VERIFIED
        and workflow.get("native_code_generation_config") is None
    ):
        _add(
            blockers,
            "candidate_generation_claim_inconsistent",
            "verified candidate generation has no workflow binding",
        )


def _relative_locator(parent: PurePosixPath, value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    candidate = PurePosixPath(value)
    if candidate.is_absolute():
        return None
    normalized = posixpath.normpath((parent / candidate).as_posix())
    if normalized == ".." or normalized.startswith("../"):
        return None
    return normalized


def _yaml_mapping(raw: bytes, label: str) -> dict[str, object]:
    try:
        value = yaml.safe_load(raw.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError(f"{label} Git object is not valid UTF-8 YAML") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} Git object must contain a YAML mapping")
    return value


def _git_object(
    root: Path,
    commit: str,
    locator: str,
    blockers: list[NativeConditionPreflightFinding],
) -> bytes | None:
    if not _safe_git_locator(locator):
        _add(blockers, "unsafe_git_locator", f"unsafe Git evidence locator: {locator}")
        return None
    try:
        result = subprocess.run(
            ["git", "show", f"{commit}:{locator}"],
            cwd=root,
            check=True,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        _add(blockers, "git_object_unavailable", f"Git evidence is unavailable: {locator}")
        return None
    if len(result.stdout) > _MAX_GIT_OBJECT_BYTES:
        _add(blockers, "git_object_oversized", f"Git evidence exceeds byte ceiling: {locator}")
        return None
    return result.stdout


def _safe_git_locator(locator: str) -> bool:
    path = PurePosixPath(locator)
    return bool(
        not path.is_absolute()
        and path.parts
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def _git_commit_exists(root: Path, commit: str) -> bool:
    try:
        subprocess.run(
            ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
            cwd=root,
            check=True,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return True


def _git_is_ancestor(root: Path, ancestor: str, descendant: str | None) -> bool:
    if descendant is None:
        return False
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=root,
        check=False,
        capture_output=True,
        timeout=10,
    )
    return result.returncode == 0


def _git_text(root: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("unable to inspect local Git repository") from exc
    value = result.stdout.strip()
    if len(value) > 1_000:
        raise ValueError("Git identity output exceeds its byte ceiling")
    return value


def _canonical_sha256(value: object) -> str:
    canonical = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _add(
    findings: list[NativeConditionPreflightFinding],
    code: str,
    message: str,
) -> None:
    findings.append(NativeConditionPreflightFinding(code=code, message=message))


__all__ = [
    "CorpusParityDimension",
    "NativeConditionPreflightFinding",
    "NativeConditionPreflightInspection",
    "NativeConditionPreflightManifest",
    "NativeConditionPreflightReport",
    "NativeCorpusPairContract",
    "NativePathRequirement",
    "NativeRequirementEvidence",
    "inspect_native_condition_preflight",
    "load_native_condition_preflight_manifest",
]
