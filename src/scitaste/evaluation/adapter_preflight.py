"""Content-addressed, no-run admission review for external-system adapters."""

from __future__ import annotations

import hashlib
import json
import subprocess
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.evaluation.prelaunch import ReadinessStatus
from scitaste.evaluation.resources import (
    EvaluationResourceKind,
    ExternalResourceCorpus,
)

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_COMMIT = r"^[0-9a-f]{40}$"
_MAX_FILE_BYTES = 16 * 1024 * 1024
_MAX_MANIFEST_BYTES = 1_048_576


class AdapterRequirement(StrEnum):
    TASK_MAPPING = "task_mapping"
    MODEL_MAPPING = "model_mapping"
    SANDBOX = "sandbox"
    TELEMETRY = "telemetry"
    ARTIFACT_MAPPING = "artifact_mapping"
    FAILURE_RESUME = "failure_resume"


class AdapterRequirementEvidence(BaseModel):
    model_config = _CONFIG

    status: ReadinessStatus
    summary: str = Field(min_length=1, max_length=4_000)
    evidence_ref: str | None = Field(default=None, max_length=1_000)
    evidence_sha256: str | None = Field(default=None, pattern=_SHA256)

    @model_validator(mode="after")
    def verified_evidence_is_content_bound(self) -> AdapterRequirementEvidence:
        paired = (self.evidence_ref is None) == (self.evidence_sha256 is None)
        if not paired:
            raise ValueError("adapter evidence reference and SHA-256 must be paired")
        if self.status is ReadinessStatus.VERIFIED and self.evidence_ref is None:
            raise ValueError("verified adapter requirements require content-bound evidence")
        return self


class ExternalAdapterPreflightManifest(BaseModel):
    """One pinned upstream and first-party adapter, with no launch authority."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    preflight_id: str = Field(pattern=_ID)
    authorization_scope: Literal["static-inspection-only"]
    external_resource_id: str = Field(pattern=_ID)
    expected_upstream_commit: str = Field(pattern=_COMMIT)
    upstream_checkout: str = Field(min_length=1, max_length=1_000)
    require_clean_upstream: Literal[True] = True
    adapter_entrypoint: str = Field(min_length=1, max_length=1_000)
    adapter_entrypoint_sha256: str = Field(pattern=_SHA256)
    requirements: dict[AdapterRequirement, AdapterRequirementEvidence]
    no_external_download: Literal[True] = True
    no_execution_performed: Literal[True] = True

    @model_validator(mode="after")
    def requirement_matrix_is_complete(self) -> ExternalAdapterPreflightManifest:
        missing = set(AdapterRequirement) - set(self.requirements)
        extra = set(self.requirements) - set(AdapterRequirement)
        if missing or extra:
            raise ValueError(
                "adapter requirement matrix must be complete: "
                f"missing={sorted(item.value for item in missing)}, "
                f"extra={sorted(str(item) for item in extra)}"
            )
        return self

    @property
    def proposal_sha256(self) -> str:
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


class AdapterPreflightInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    manifest: ExternalAdapterPreflightManifest


class AdapterPreflightFinding(BaseModel):
    model_config = _CONFIG

    code: str = Field(pattern=r"^[a-z0-9]+(?:[a-z0-9_:-]*[a-z0-9])?$")
    message: str = Field(min_length=1, max_length=4_000)


class AdapterPreflightReport(BaseModel):
    """Static admission evidence; it can propose corpus updates but never run a system."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    preflight_id: str
    proposal_sha256: str = Field(pattern=_SHA256)
    resource_corpus_sha256: str = Field(pattern=_SHA256)
    observed_upstream_commit: str | None = Field(default=None, pattern=_COMMIT)
    upstream_tree_clean: bool | None = None
    ready_for_corpus_revision_review: bool
    ready_for_matched_adapter: bool
    authorizes_execution: Literal[False] = False
    blockers: tuple[AdapterPreflightFinding, ...]
    pending_requirements: tuple[AdapterRequirement, ...]
    corpus_revision_candidates: tuple[AdapterRequirement, ...]
    no_external_download: Literal[True] = True
    no_execution_performed: Literal[True] = True


def load_adapter_preflight_manifest(path: str | Path) -> AdapterPreflightInspection:
    requested = Path(path)
    if requested.is_symlink():
        raise ValueError("adapter-preflight manifest must not be a symlink")
    resolved = requested.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size > _MAX_MANIFEST_BYTES:
        raise ValueError("adapter-preflight manifest must be a bounded regular file")
    raw = resolved.read_bytes()
    try:
        payload = yaml.safe_load(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ValueError("adapter-preflight manifest must be UTF-8") from exc
    if not isinstance(payload, dict):
        raise ValueError("adapter-preflight manifest must contain a YAML mapping")
    return AdapterPreflightInspection(
        path=resolved,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        manifest=ExternalAdapterPreflightManifest.model_validate(payload),
    )


def inspect_adapter_preflight(
    manifest: ExternalAdapterPreflightManifest,
    resource_corpus: ExternalResourceCorpus,
    *,
    source_root: str | Path,
) -> AdapterPreflightReport:
    """Inspect local bytes and Git identity without invoking the external system."""

    blockers: list[AdapterPreflightFinding] = []
    resources = {item.resource_id: item for item in resource_corpus.resources}
    resource = resources.get(manifest.external_resource_id)
    if resource is None:
        _add(blockers, "unknown_external_resource", "external system is absent from corpus")
    elif resource.resource_kind is not EvaluationResourceKind.SYSTEM:
        _add(blockers, "wrong_resource_kind", "adapter preflight requires a system resource")
    elif resource.repository_commit != manifest.expected_upstream_commit:
        _add(blockers, "upstream_pin_mismatch", "manifest and corpus upstream commits differ")

    try:
        root = Path(source_root).resolve(strict=True)
    except (OSError, ValueError):
        root = None
        _add(blockers, "source_root_unavailable", "source root could not be resolved")

    observed_commit: str | None = None
    upstream_clean: bool | None = None
    if root is not None:
        upstream = _resolve_bounded_path(root, manifest.upstream_checkout)
        if upstream is None or not upstream.is_dir():
            _add(blockers, "upstream_checkout_unavailable", "upstream checkout is unavailable")
        else:
            try:
                observed_commit = _git(upstream, "rev-parse", "HEAD")
                upstream_clean = not bool(
                    _git(upstream, "status", "--porcelain=v1", "--untracked-files=all")
                )
            except ValueError as exc:
                _add(blockers, "upstream_git_unavailable", str(exc))
            else:
                if observed_commit != manifest.expected_upstream_commit:
                    _add(
                        blockers,
                        "observed_upstream_commit_mismatch",
                        "local upstream checkout differs from the registered commit",
                    )
                if manifest.require_clean_upstream and not upstream_clean:
                    _add(blockers, "upstream_tree_dirty", "local upstream checkout is dirty")
        _verify_file(
            blockers,
            root,
            manifest.adapter_entrypoint,
            manifest.adapter_entrypoint_sha256,
            code_prefix="adapter_entrypoint",
        )

    pending: list[AdapterRequirement] = []
    revision_candidates: list[AdapterRequirement] = []
    for requirement in AdapterRequirement:
        evidence = manifest.requirements[requirement]
        if evidence.status is not ReadinessStatus.VERIFIED:
            pending.append(requirement)
            continue
        if root is None or evidence.evidence_ref is None or evidence.evidence_sha256 is None:
            _add(
                blockers,
                f"requirement_evidence_unobserved:{requirement.value}",
                f"verified {requirement.value} evidence could not be inspected",
            )
            continue
        before = len(blockers)
        _verify_file(
            blockers,
            root,
            evidence.evidence_ref,
            evidence.evidence_sha256,
            code_prefix=f"requirement:{requirement.value}",
        )
        if len(blockers) == before:
            revision_candidates.append(requirement)

    ready_for_revision = not blockers
    ready_for_matched = ready_for_revision and not pending
    return AdapterPreflightReport(
        preflight_id=manifest.preflight_id,
        proposal_sha256=manifest.proposal_sha256,
        resource_corpus_sha256=resource_corpus.semantic_sha256,
        observed_upstream_commit=observed_commit,
        upstream_tree_clean=upstream_clean,
        ready_for_corpus_revision_review=ready_for_revision,
        ready_for_matched_adapter=ready_for_matched,
        blockers=tuple(blockers),
        pending_requirements=tuple(pending),
        corpus_revision_candidates=tuple(revision_candidates),
    )


def _verify_file(
    blockers: list[AdapterPreflightFinding],
    root: Path,
    locator: str,
    expected_sha256: str,
    *,
    code_prefix: str,
) -> None:
    candidate = _resolve_bounded_path(root, locator)
    if candidate is None or not candidate.is_file():
        _add(blockers, f"{code_prefix}:missing", f"evidence file is missing: {locator}")
        return
    if candidate.stat().st_size > _MAX_FILE_BYTES:
        _add(blockers, f"{code_prefix}:oversized", f"evidence file is oversized: {locator}")
        return
    observed = hashlib.sha256(candidate.read_bytes()).hexdigest()
    if observed != expected_sha256:
        _add(blockers, f"{code_prefix}:hash_mismatch", f"evidence hash differs: {locator}")


def _resolve_bounded_path(root: Path, locator: str) -> Path | None:
    pure = PurePosixPath(locator)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        return None
    candidate = root.joinpath(*pure.parts)
    current = root
    for part in pure.parts:
        current = current / part
        if current.is_symlink():
            return None
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError):
        return None
    return resolved


def _git(cwd: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("unable to inspect upstream Git identity") from exc
    if len(result.stdout) > 1_048_576:
        raise ValueError("upstream Git inspection exceeded its output limit")
    return result.stdout.strip()


def _add(findings: list[AdapterPreflightFinding], code: str, message: str) -> None:
    findings.append(AdapterPreflightFinding(code=code, message=message))


__all__ = [
    "AdapterPreflightFinding",
    "AdapterPreflightInspection",
    "AdapterPreflightReport",
    "AdapterRequirement",
    "AdapterRequirementEvidence",
    "ExternalAdapterPreflightManifest",
    "inspect_adapter_preflight",
    "load_adapter_preflight_manifest",
]
