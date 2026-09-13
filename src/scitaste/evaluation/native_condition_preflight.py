"""Git-pinned, no-run scientific preflight for native Taste conditions."""

from __future__ import annotations

import hashlib
import json
import os
import posixpath
import subprocess
import tempfile
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from scitaste.evaluation.prelaunch import ReadinessStatus
from scitaste.taste.conditions import (
    NativeConditionComponents,
    NativeConditionMatrix,
    NativeTasteCondition,
    load_native_condition_matrix,
)

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_COMMIT = r"^[0-9a-f]{40}$"
_MAX_MANIFEST_BYTES = 1_048_576
_MAX_GIT_OBJECT_BYTES = 2 * 1_048_576
_IMPLEMENTATION_EVIDENCE_PATHS = (
    "src/scitaste/full_workflow.py",
    "src/scitaste/taste/conditions.py",
    "src/scitaste/taste/controller.py",
    "src/scitaste/taste/critics.py",
    "src/scitaste/executor/native.py",
    "src/scitaste/state/persistence.py",
)
_FIXTURE_STAGE_NAMES = ("discovery", "evidence", "communication", "figure")


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
    curation_runtime_status: ReadinessStatus = ReadinessStatus.PENDING
    curation_runtime_ref: str | None = Field(default=None, max_length=1_000)
    curation_runtime_sha256: str | None = Field(default=None, pattern=_SHA256)
    zero_retrieval_invalidates_cell: Literal[True] = True

    @model_validator(mode="after")
    def parity_contract_is_closed(self) -> NativeCorpusPairContract:
        if set(self.dimensions) != set(CorpusParityDimension):
            raise ValueError("native corpus parity dimension matrix must be complete")
        pairs = (
            (self.matched_corpus_ref, self.matched_corpus_sha256),
            (self.placebo_corpus_ref, self.placebo_corpus_sha256),
            (self.pair_attestation_ref, self.pair_attestation_sha256),
            (self.curation_runtime_ref, self.curation_runtime_sha256),
        )
        if any((ref is None) != (digest is None) for ref, digest in pairs):
            raise ValueError("native corpus references and SHA-256 values must be paired")
        any_verified = any(
            status is ReadinessStatus.VERIFIED for status in self.dimensions.values()
        )
        corpus_pairs = pairs[:3]
        if any_verified and not all(ref is not None for pair in corpus_pairs for ref in pair):
            raise ValueError("verified corpus parity requires both corpora and pair attestation")
        if (
            self.curation_runtime_status is ReadinessStatus.VERIFIED
            and self.curation_runtime_ref is None
        ):
            raise ValueError("verified corpus curation runtime requires Git-pinned evidence")
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
    corpus_curation_runtime_verified: bool
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


class NativeImplementationEvidenceFile(BaseModel):
    """One implementation object proved identical at the pinned source and HEAD."""

    model_config = _CONFIG

    path: str = Field(min_length=1, max_length=1_000)
    source_sha256: str = Field(pattern=_SHA256)
    head_sha256: str = Field(pattern=_SHA256)
    unchanged: bool


class NativeConditionBehaviorProbe(BaseModel):
    """Observed condition wiring from one complete offline fixture workflow."""

    model_config = _CONFIG

    condition_id: NativeTasteCondition
    components: NativeConditionComponents
    stage_names: tuple[Literal["discovery", "evidence", "communication", "figure"], ...]
    decision_count: int = Field(gt=0)
    knowledge_result_basis: Literal["knowledge-library-retrieval", "workflow-component-receipt"]
    retrieved_document_count: int = Field(ge=0)
    retrieved_taste_case_ids: tuple[str, ...]
    final_blocking_findings: int = Field(ge=0)
    integrity_gates_invariant: bool
    condition_contract_verified: bool


class NativeTasteRoutingProbe(BaseModel):
    """A closed two-case probe of matched versus source-disjoint retrieval."""

    model_config = _CONFIG

    matched_case_ids: tuple[str, ...]
    mismatched_case_ids: tuple[str, ...]
    matched_selected_action_id: str
    mismatched_selected_action_id: str
    disjoint: bool
    verified: bool


class NativeCriticRoutingProbe(BaseModel):
    """A fixed decision probe showing the critic switch changes score evidence."""

    model_config = _CONFIG

    control_commit_score: float
    critics_commit_score: float
    control_has_critic_rationale: bool
    critics_has_critic_rationale: bool
    critics_selected_action_id: str
    verified: bool


class NativeConditionImplementationAttestation(BaseModel):
    """Behavioral evidence for all six first-party conditions, never a model result."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    attestation_id: str = Field(pattern=_ID)
    preflight_id: str = Field(pattern=_ID)
    preflight_proposal_sha256: str = Field(pattern=_SHA256)
    source_commit: str = Field(pattern=_COMMIT)
    observed_head_commit: str = Field(pattern=_COMMIT)
    fixture_workflow_ref: str = Field(min_length=1, max_length=1_000)
    fixture_workflow_sha256: str = Field(pattern=_SHA256)
    implementation_evidence: tuple[NativeImplementationEvidenceFile, ...] = Field(min_length=1)
    condition_probes: tuple[NativeConditionBehaviorProbe, ...]
    taste_routing_probe: NativeTasteRoutingProbe | None = None
    critic_routing_probe: NativeCriticRoutingProbe | None = None
    exact_condition_population_verified: bool
    workflow_component_routes_verified: bool
    full_placebo_single_factor_verified: bool
    implementation_qualified: bool
    findings: tuple[NativeConditionPreflightFinding, ...]
    local_fixture_execution_performed: bool
    real_task_or_experiment_execution_performed: Literal[False] = False
    model_calls: Literal[0] = 0
    api_calls: Literal[0] = 0
    gpu_jobs: Literal[0] = 0
    network_access: Literal[False] = False
    authorizes_experiment_execution: Literal[False] = False

    @computed_field
    @property
    def attestation_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"attestation_sha256"}))


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
            corpus_evidence = (
                (
                    manifest.corpus_pair.matched_corpus_ref,
                    manifest.corpus_pair.matched_corpus_sha256,
                ),
                (
                    manifest.corpus_pair.placebo_corpus_ref,
                    manifest.corpus_pair.placebo_corpus_sha256,
                ),
                (
                    manifest.corpus_pair.pair_attestation_ref,
                    manifest.corpus_pair.pair_attestation_sha256,
                ),
                (
                    manifest.corpus_pair.curation_runtime_ref,
                    manifest.corpus_pair.curation_runtime_sha256,
                ),
            )
            for locator, expected_sha256 in corpus_evidence:
                if locator is None or expected_sha256 is None:
                    continue
                prior = expected_objects.get(locator)
                if prior is not None and prior != expected_sha256:
                    _add(
                        blockers,
                        "conflicting_evidence_hash",
                        f"one Git object has conflicting hashes: {locator}",
                    )
                expected_objects[locator] = expected_sha256
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
    curation_ref = manifest.corpus_pair.curation_runtime_ref
    curation_sha256 = manifest.corpus_pair.curation_runtime_sha256
    curation_runtime_verified = bool(
        manifest.corpus_pair.curation_runtime_status is ReadinessStatus.VERIFIED
        and curation_ref is not None
        and curation_sha256 is not None
        and curation_ref in objects
        and hashlib.sha256(objects[curation_ref]).hexdigest() == curation_sha256
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
        corpus_curation_runtime_verified=curation_runtime_verified,
        corpus_pair_verified=corpus_verified,
        checkpoint_execution_verified=checkpoint_verified,
        ready_for_experiment=ready,
        verified_requirements=verified,
        pending_requirements=pending,
        blocked_requirements=blocked,
        corpus_parity_status=manifest.corpus_pair.dimensions,
        blockers=tuple(blockers),
    )


def attest_native_condition_implementations(
    inspection: NativeConditionPreflightInspection,
    *,
    fixture_workflow: str | Path,
    source_root: str | Path,
    workspace_root: str | Path,
    seed: int = 7,
    allow_local_fixture_execution: bool = False,
) -> NativeConditionImplementationAttestation:
    """Execute all six conditions on one local fixture without external resources."""

    if not allow_local_fixture_execution:
        raise ValueError("native condition attestation requires --allow-local-fixture-execution")
    root = Path(source_root).resolve(strict=True)
    workspace = Path(workspace_root).resolve(strict=True)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("native condition source root must be a real directory")
    if workspace.is_symlink() or not workspace.is_dir():
        raise ValueError("native condition workspace root must be a real directory")
    head = _git_text(root, "rev-parse", "HEAD")
    preflight = inspect_native_condition_preflight(inspection, source_root=root)
    if not preflight.source_commit_available or not preflight.source_commit_is_ancestor:
        raise ValueError("native condition source commit is unavailable or not an ancestor")
    if not (
        preflight.static_action_path_verified
        and preflight.model_candidate_generation_verified
        and preflight.corpus_curation_runtime_verified
    ):
        raise ValueError("native condition static implementation preflight is not qualified")

    fixture_path = Path(fixture_workflow).resolve(strict=True)
    try:
        fixture_locator = fixture_path.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError("native condition fixture workflow must be inside source root") from exc
    findings: list[NativeConditionPreflightFinding] = []
    evidence = _inspect_head_implementation_evidence(
        inspection.manifest,
        root=root,
        head=head,
        fixture_locator=fixture_locator,
        findings=findings,
    )

    from scitaste.full_workflow import load_full_workflow_config

    fixture_sha256 = hashlib.sha256(fixture_path.read_bytes()).hexdigest()
    config = load_full_workflow_config(fixture_path)
    _inspect_fixture_workflow_safety(
        config,
        fixture_path=fixture_path,
        condition_matrix_ref=inspection.manifest.condition_matrix_ref,
        source_root=root,
        findings=findings,
    )

    probes: tuple[NativeConditionBehaviorProbe, ...] = ()
    taste_probe: NativeTasteRoutingProbe | None = None
    critic_probe: NativeCriticRoutingProbe | None = None
    execution_performed = False
    if not findings:
        with tempfile.TemporaryDirectory(
            prefix=".scitaste-native-condition-attestation-",
            dir=workspace,
        ) as temporary_name:
            temporary_root = Path(temporary_name)
            execution_performed = True
            probes = _run_condition_workflow_probes(
                config,
                matrix=load_native_condition_matrix(config.native_condition_config).matrix,
                output_root=temporary_root / "outputs",
                seed=seed,
                findings=findings,
            )
            taste_probe = _run_taste_routing_probe(
                load_native_condition_matrix(config.native_condition_config).matrix,
                workspace=temporary_root,
                seed=seed,
                findings=findings,
            )
            critic_probe = _run_critic_routing_probe(
                load_native_condition_matrix(config.native_condition_config).matrix,
                seed=seed,
                findings=findings,
            )

    expected_conditions = set(NativeTasteCondition)
    observed_conditions = {item.condition_id for item in probes}
    exact_population = observed_conditions == expected_conditions and len(probes) == len(
        expected_conditions
    )
    if not exact_population:
        _add(
            findings,
            "condition_probe_population_incomplete",
            "behavioral probes do not cover the closed six-condition population",
        )
    routes_verified = bool(probes) and all(item.condition_contract_verified for item in probes)
    full = inspection.manifest
    matrix = load_native_condition_matrix(config.native_condition_config).matrix
    full_components = matrix.profile(NativeTasteCondition.FULL).components
    placebo_components = matrix.profile(NativeTasteCondition.MISMATCHED_PLACEBO).components
    single_factor = (
        full_components.model_copy(update={"taste_retrieval": placebo_components.taste_retrieval})
        == placebo_components
    )
    all_evidence_unchanged = bool(evidence) and all(item.unchanged for item in evidence)
    qualified = bool(
        not findings
        and execution_performed
        and exact_population
        and routes_verified
        and single_factor
        and taste_probe is not None
        and taste_probe.verified
        and critic_probe is not None
        and critic_probe.verified
        and all_evidence_unchanged
    )
    return NativeConditionImplementationAttestation(
        attestation_id=f"{full.preflight_id}-behavioral-v1",
        preflight_id=full.preflight_id,
        preflight_proposal_sha256=full.proposal_sha256,
        source_commit=full.source_commit,
        observed_head_commit=head,
        fixture_workflow_ref=fixture_locator,
        fixture_workflow_sha256=fixture_sha256,
        implementation_evidence=evidence,
        condition_probes=probes,
        taste_routing_probe=taste_probe,
        critic_routing_probe=critic_probe,
        exact_condition_population_verified=exact_population,
        workflow_component_routes_verified=routes_verified,
        full_placebo_single_factor_verified=single_factor,
        implementation_qualified=qualified,
        findings=tuple(findings),
        local_fixture_execution_performed=execution_performed,
    )


def save_native_condition_implementation_attestation(
    report: NativeConditionImplementationAttestation,
    path: str | Path,
) -> Path:
    """Publish an immutable attestation report without replacing existing evidence."""

    destination = Path(path)
    if destination.is_symlink() or destination.exists():
        raise FileExistsError(f"native condition attestation already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    parent = destination.parent.resolve(strict=True)
    if destination.parent.is_symlink() or not parent.is_dir():
        raise ValueError("native condition attestation parent must be a real directory")
    payload = (report.model_dump_json(indent=2) + "\n").encode()
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def _inspect_head_implementation_evidence(
    manifest: NativeConditionPreflightManifest,
    *,
    root: Path,
    head: str,
    fixture_locator: str,
    findings: list[NativeConditionPreflightFinding],
) -> tuple[NativeImplementationEvidenceFile, ...]:
    locators = tuple(
        dict.fromkeys(
            (
                manifest.workflow_config_ref,
                manifest.condition_matrix_ref,
                fixture_locator,
                *_IMPLEMENTATION_EVIDENCE_PATHS,
            )
        )
    )
    result: list[NativeImplementationEvidenceFile] = []
    for locator in locators:
        source_bytes = _git_object(root, manifest.source_commit, locator, findings)
        head_bytes = _git_object(root, head, locator, findings)
        if source_bytes is None or head_bytes is None:
            continue
        source_sha256 = hashlib.sha256(source_bytes).hexdigest()
        head_sha256 = hashlib.sha256(head_bytes).hexdigest()
        unchanged = source_sha256 == head_sha256
        if not unchanged:
            _add(
                findings,
                "implementation_evidence_drift",
                f"native condition implementation changed after the pinned source: {locator}",
            )
        result.append(
            NativeImplementationEvidenceFile(
                path=locator,
                source_sha256=source_sha256,
                head_sha256=head_sha256,
                unchanged=unchanged,
            )
        )
    return tuple(result)


def _inspect_fixture_workflow_safety(
    config: object,
    *,
    fixture_path: Path,
    condition_matrix_ref: str,
    source_root: Path,
    findings: list[NativeConditionPreflightFinding],
) -> None:
    expected_matrix = (source_root / condition_matrix_ref).resolve(strict=True)
    observed_matrix = getattr(config, "native_condition_config", None)
    safe = (
        getattr(config, "execution_backend", None) == "scitaste-native"
        and getattr(config, "provider", None) == "mock"
        and getattr(config, "model", None) == "deterministic-controller"
        and getattr(config, "native_preference_backend_config", None) is None
        and getattr(config, "native_candidate_generation_enabled", None) is False
        and getattr(config, "native_code_generation_config", None) is None
        and getattr(config, "native_code_repair_config", None) is None
        and getattr(config, "model_node_advisory", None) is None
        and getattr(config, "tool_intelligence_advisory", None) is None
        and observed_matrix == expected_matrix
    )
    if not safe:
        _add(
            findings,
            "unsafe_fixture_workflow",
            f"fixture workflow is not the bounded offline native condition path: {fixture_path}",
        )


def _run_condition_workflow_probes(
    config: object,
    *,
    matrix: NativeConditionMatrix,
    output_root: Path,
    seed: int,
    findings: list[NativeConditionPreflightFinding],
) -> tuple[NativeConditionBehaviorProbe, ...]:
    from scitaste.full_workflow import FullWorkflow
    from scitaste.state.persistence import StateStore

    probes: list[NativeConditionBehaviorProbe] = []
    for condition in NativeTasteCondition:
        condition_slug = condition.value.replace("-", "_")
        condition_config = config.model_copy(
            update={
                "project_id": "native-condition-implementation-attestation",
                "condition": condition.value,
                "paper_id": f"{condition_slug}-attestation-paper",
                "paper_directory": f"{condition_slug}-attestation-paper",
                "paper_title": f"Native condition fixture: {condition.value}",
            }
        )
        run_id = f"{condition_slug}-seed-{seed:02d}"
        try:
            result = FullWorkflow(seed=seed).run(
                condition_config,
                outputs_root=output_root,
                run_id=run_id,
            )
            condition_payload = result.get("native_condition")
            if not isinstance(condition_payload, dict):
                raise ValueError("full workflow omitted native condition telemetry")
            components = NativeConditionComponents.model_validate(
                condition_payload.get("components")
            )
            run_root = (
                output_root / "projects/native-condition-implementation-attestation/runs" / run_id
            )
            state = StateStore(run_root / "stages/figure").load()
            search = next(
                item
                for item in state.decision_history
                if item.selected_action.action_id == "discovery-search"
            )
            outcome = search.actual_outcome
            if not isinstance(outcome, dict) or not isinstance(outcome.get("data"), dict):
                raise ValueError("discovery search omitted native executor telemetry")
            outcome_data = outcome["data"]
            basis = outcome_data.get("result_basis")
            if basis not in {
                "knowledge-library-retrieval",
                "workflow-component-receipt",
            }:
                raise ValueError("discovery search has an unknown result basis")
            document_ids = outcome_data.get("retrieved_document_ids", [])
            if not isinstance(document_ids, list) or not all(
                isinstance(item, str) for item in document_ids
            ):
                raise ValueError("discovery search document IDs are malformed")
            taste_ids = tuple(
                sorted(
                    {
                        case_id
                        for decision in state.decision_history
                        for case_id in decision.retrieved_taste_cases
                    }
                )
            )
            expected = matrix.profile(condition).components
            knowledge_expected = expected.knowledge_retrieval_enabled
            taste_expected = expected.taste_retrieval.value != "disabled"
            stages = result.get("stages")
            if not isinstance(stages, dict):
                raise ValueError("full workflow omitted stage summaries")
            figure = stages.get("figure")
            if not isinstance(figure, dict):
                raise ValueError("full workflow omitted figure summary")
            final_blockers = figure.get("final_blocking_findings")
            if not isinstance(final_blockers, int):
                raise ValueError("figure summary omitted final blocking finding count")
            stage_names = tuple(stages)
            contract_verified = bool(
                condition_payload.get("condition_id") == condition.value
                and components == expected
                and condition_payload.get("integrity_gates_invariant") is True
                and stage_names == _FIXTURE_STAGE_NAMES
                and final_blockers == 0
                and (
                    (knowledge_expected and basis == "knowledge-library-retrieval" and document_ids)
                    or (
                        not knowledge_expected
                        and basis == "workflow-component-receipt"
                        and not document_ids
                    )
                )
                and ((taste_expected and taste_ids) or (not taste_expected and not taste_ids))
            )
            if not contract_verified:
                _add(
                    findings,
                    f"condition_contract_failed:{condition.value}",
                    f"offline workflow did not preserve the {condition.value} component contract",
                )
            probes.append(
                NativeConditionBehaviorProbe(
                    condition_id=condition,
                    components=components,
                    stage_names=stage_names,
                    decision_count=len(state.decision_history),
                    knowledge_result_basis=basis,
                    retrieved_document_count=len(document_ids),
                    retrieved_taste_case_ids=taste_ids,
                    final_blocking_findings=final_blockers,
                    integrity_gates_invariant=(
                        condition_payload.get("integrity_gates_invariant") is True
                    ),
                    condition_contract_verified=contract_verified,
                )
            )
        except (OSError, RuntimeError, StopIteration, TypeError, ValueError) as exc:
            _add(
                findings,
                f"condition_probe_failed:{condition.value}",
                f"{type(exc).__name__}: {str(exc)[:1_000]}",
            )
    return tuple(probes)


def _run_taste_routing_probe(
    matrix: NativeConditionMatrix,
    *,
    workspace: Path,
    seed: int,
    findings: list[NativeConditionPreflightFinding],
) -> NativeTasteRoutingProbe | None:
    from scitaste.data.models import ProvenanceRecord, TasteCase
    from scitaste.data.store import TasteLibrary
    from scitaste.schema.actions import MetaAction, ResearchAction
    from scitaste.state.research_state import ResearchState
    from scitaste.taste.conditions import build_native_condition_runtime

    try:
        library = TasteLibrary(workspace / "routing-probe.jsonl")
        library.add(
            TasteCase(
                case_id="matched-probe",
                stage="DISCOVERY",
                context_summary="Choose a bounded diagnostic action",
                candidate_actions=[MetaAction.PROBE.value, MetaAction.SEARCH.value],
                preferred_action=MetaAction.PROBE.value,
                decision_principle="Use a source-matched diagnostic precedent.",
                why_preferred="The matched precedent favors a bounded probe.",
                provenance=[
                    ProvenanceRecord(source_type="attestation", locator="fixture://matched")
                ],
                confidence=1.0,
                retrieval_eligible=True,
                domain_tags=["testing"],
            )
        )
        library.add(
            TasteCase(
                case_id="mismatched-search",
                stage="DISCOVERY",
                context_summary="Choose a bounded diagnostic action",
                candidate_actions=[MetaAction.PROBE.value, MetaAction.SEARCH.value],
                preferred_action=MetaAction.SEARCH.value,
                decision_principle="Use a source-disjoint precedent only in placebo routing.",
                why_preferred="The mismatched precedent favors search.",
                provenance=[
                    ProvenanceRecord(source_type="attestation", locator="fixture://mismatched")
                ],
                confidence=1.0,
                retrieval_eligible=True,
                domain_tags=["biology"],
            )
        )
        state = ResearchState(
            project_id="native-condition-routing-attestation",
            research_direction="Choose one bounded diagnostic action",
            target_domain="testing",
        )
        actions = [
            ResearchAction(action_id="probe", type=MetaAction.PROBE, description="Probe"),
            ResearchAction(action_id="search", type=MetaAction.SEARCH, description="Search"),
        ]
        matched = build_native_condition_runtime(
            matrix.profile(NativeTasteCondition.FULL),
            seed=seed,
            taste_library=library,
        ).controller.decide(state=state, candidate_actions=actions)
        mismatched = build_native_condition_runtime(
            matrix.profile(NativeTasteCondition.MISMATCHED_PLACEBO),
            seed=seed,
            taste_library=library,
        ).controller.decide(state=state, candidate_actions=actions)
        matched_ids = tuple(matched.retrieved_taste_cases)
        mismatched_ids = tuple(mismatched.retrieved_taste_cases)
        disjoint = set(matched_ids).isdisjoint(mismatched_ids)
        verified = bool(
            matched_ids == ("matched-probe",)
            and mismatched_ids == ("mismatched-search",)
            and matched.selected_action.action_id == "probe"
            and mismatched.selected_action.action_id == "search"
            and disjoint
        )
        if not verified:
            _add(
                findings,
                "taste_routing_probe_failed",
                "matched and mismatched Taste conditions did not route disjoint precedents",
            )
        return NativeTasteRoutingProbe(
            matched_case_ids=matched_ids,
            mismatched_case_ids=mismatched_ids,
            matched_selected_action_id=matched.selected_action.action_id,
            mismatched_selected_action_id=mismatched.selected_action.action_id,
            disjoint=disjoint,
            verified=verified,
        )
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        _add(
            findings,
            "taste_routing_probe_failed",
            f"{type(exc).__name__}: {str(exc)[:1_000]}",
        )
        return None


def _run_critic_routing_probe(
    matrix: NativeConditionMatrix,
    *,
    seed: int,
    findings: list[NativeConditionPreflightFinding],
) -> NativeCriticRoutingProbe | None:
    from scitaste.schema.actions import MetaAction, ResearchAction
    from scitaste.state.research_state import ResearchState
    from scitaste.taste.conditions import build_native_condition_runtime

    try:
        state = ResearchState(
            project_id="native-condition-critic-attestation",
            research_direction="Choose one bounded diagnostic action",
            target_domain="testing",
        )
        actions = [
            ResearchAction(
                action_id="probe",
                type=MetaAction.PROBE,
                description="Run a diagnostic probe",
                expected_value={"information_gain": 0.25},
            ),
            ResearchAction(
                action_id="commit",
                type=MetaAction.FORMULATE_PROBLEM,
                description="Commit before observing the system",
                expected_value={"information_gain": 1.0, "problem_validity": 1.0},
            ),
        ]
        control = build_native_condition_runtime(
            matrix.profile(NativeTasteCondition.BASE),
            seed=seed,
            taste_library=None,
        ).controller.decide(state=state, candidate_actions=actions)
        critics = build_native_condition_runtime(
            matrix.profile(NativeTasteCondition.CRITICS),
            seed=seed,
            taste_library=None,
        ).controller.decide(state=state, candidate_actions=actions)
        control_score = float(control.candidate_scores["commit"] or 0.0)
        critics_score = float(critics.candidate_scores["commit"] or 0.0)
        control_has = "Taste critics:" in control.rationale
        critics_has = "Taste critics:" in critics.rationale
        verified = bool(
            control_score == 0.0
            and critics_score < control_score
            and not control_has
            and critics_has
            and critics.selected_action.action_id == "probe"
        )
        if not verified:
            _add(
                findings,
                "critic_routing_probe_failed",
                "native critics did not produce the expected bounded score evidence",
            )
        return NativeCriticRoutingProbe(
            control_commit_score=control_score,
            critics_commit_score=critics_score,
            control_has_critic_rationale=control_has,
            critics_has_critic_rationale=critics_has,
            critics_selected_action_id=critics.selected_action.action_id,
            verified=verified,
        )
    except (RuntimeError, TypeError, ValueError) as exc:
        _add(
            findings,
            "critic_routing_probe_failed",
            f"{type(exc).__name__}: {str(exc)[:1_000]}",
        )
        return None


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
        and workflow.get("native_candidate_generation_enabled") is not True
    ):
        _add(
            blockers,
            "candidate_generation_claim_inconsistent",
            "verified candidate generation is not enabled by the bound workflow",
        )
    corpus_status = manifest.requirements[NativePathRequirement.MATCHED_PLACEBO_CORPORA].status
    if corpus_status is ReadinessStatus.VERIFIED:
        attestation_ref = manifest.corpus_pair.pair_attestation_ref
        if attestation_ref is None or attestation_ref not in objects:
            _add(
                blockers,
                "corpus_pair_attestation_missing",
                "verified corpus parity has no available Git-bound attestation",
            )
            return
        try:
            attestation = _yaml_mapping(objects[attestation_ref], "corpus pair attestation")
        except ValueError as exc:
            _add(blockers, "corpus_pair_attestation_invalid", str(exc))
            return
        parity = attestation.get("parity_status")
        attested = (
            attestation.get("qualified") is True
            and attestation.get("no_external_action_performed") is True
            and attestation.get("authorizes_execution") is False
            and attestation.get("matched_corpus_sha256")
            == manifest.corpus_pair.matched_corpus_sha256
            and attestation.get("placebo_corpus_sha256")
            == manifest.corpus_pair.placebo_corpus_sha256
            and isinstance(parity, dict)
            and set(parity) == {item.value for item in CorpusParityDimension}
            and set(parity.values()) == {ReadinessStatus.VERIFIED.value}
        )
        if not attested:
            _add(
                blockers,
                "corpus_pair_attestation_invalid",
                "corpus pair attestation does not prove closed parity and contamination gates",
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
    "NativeConditionBehaviorProbe",
    "NativeConditionImplementationAttestation",
    "NativeConditionPreflightFinding",
    "NativeConditionPreflightInspection",
    "NativeConditionPreflightManifest",
    "NativeConditionPreflightReport",
    "NativeCorpusPairContract",
    "NativeCriticRoutingProbe",
    "NativeImplementationEvidenceFile",
    "NativePathRequirement",
    "NativeRequirementEvidence",
    "NativeTasteRoutingProbe",
    "attest_native_condition_implementations",
    "inspect_native_condition_preflight",
    "load_native_condition_preflight_manifest",
    "save_native_condition_implementation_attestation",
]
