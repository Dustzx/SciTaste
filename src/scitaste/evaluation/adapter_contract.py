"""Static translation contracts for real external research systems."""

from __future__ import annotations

import hashlib
import json
import re
import string
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.evaluation.adapter_preflight import AdapterRequirement
from scitaste.evaluation.prelaunch import ReadinessStatus
from scitaste.evaluation.resources import (
    EvaluationResourceKind,
    ExternalResourceCorpus,
)

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_COMMIT = r"^[0-9a-f]{40}$"
_ENV = r"^[A-Z][A-Z0-9_]{1,100}$"
_MAX_MANIFEST_BYTES = 1_048_576
_MAX_EVIDENCE_BYTES = 16 * 1024 * 1024
_ALLOWED_PLACEHOLDERS = {
    "coding_agent",
    "config_path",
    "model_id",
    "output_root",
    "python",
    "seed",
    "task_root",
    "upstream_root",
}
_SHELL_CONTROL = re.compile(r"(?:&&|\|\||[|;<>`]|\$\()")


class AdapterContractEvidence(BaseModel):
    model_config = _CONFIG

    status: ReadinessStatus
    summary: str = Field(min_length=1, max_length=4_000)
    official_source_urls: tuple[str, ...] = Field(min_length=1, max_length=20)
    evidence_ref: str = Field(min_length=1, max_length=1_000)
    evidence_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def sources_and_evidence_are_bounded(self) -> AdapterContractEvidence:
        if any(not url.startswith("https://") for url in self.official_source_urls):
            raise ValueError("adapter-contract sources must use HTTPS")
        _validate_relative_path(self.evidence_ref, "adapter-contract evidence path")
        return self


class AdapterInvocationContract(BaseModel):
    """Shell-free native entrypoint shape. This is a template, not a launch command."""

    model_config = _CONFIG

    upstream_entrypoint: str = Field(min_length=1, max_length=1_000)
    argv_template: tuple[str, ...] = Field(min_length=1, max_length=100)
    environment_allowlist: tuple[str, ...] = Field(default=(), max_length=50)
    shell: Literal[False] = False

    @model_validator(mode="after")
    def invocation_is_safe_and_closed(self) -> AdapterInvocationContract:
        _validate_relative_path(self.upstream_entrypoint, "upstream entrypoint")
        if len(self.environment_allowlist) != len(set(self.environment_allowlist)):
            raise ValueError("adapter environment allowlist entries must be unique")
        for name in self.environment_allowlist:
            if re.fullmatch(_ENV, name) is None:
                raise ValueError("adapter environment names must be explicit uppercase names")
        for argument in self.argv_template:
            if not argument or _SHELL_CONTROL.search(argument):
                raise ValueError("adapter argv template must not contain shell syntax")
            fields = {
                field_name
                for _, field_name, _, _ in string.Formatter().parse(argument)
                if field_name is not None
            }
            if fields - _ALLOWED_PLACEHOLDERS:
                raise ValueError("adapter argv template contains an unknown placeholder")
        return self


class AdapterTaskTranslation(BaseModel):
    model_config = _CONFIG

    selected_task_form: Literal["task-directory", "research-topic-config"]
    upstream_input_name: str = Field(min_length=1, max_length=500)
    one_task_per_process: bool
    preserves_exact_starting_bytes: bool
    runtime_acquisition_policy_injectable: bool


class AdapterModelTranslation(BaseModel):
    model_config = _CONFIG

    provider_id: str = Field(pattern=_ID)
    requested_model_id: str = Field(min_length=1, max_length=200)
    requested_model_revision: str = Field(min_length=1, max_length=200)
    upstream_model_id: str | None = Field(default=None, max_length=200)
    all_model_roles_matched: bool
    unmatched_roles: tuple[str, ...] = Field(default=(), max_length=30)

    @model_validator(mode="after")
    def unmatched_roles_are_explicit(self) -> AdapterModelTranslation:
        if self.all_model_roles_matched == bool(self.unmatched_roles):
            raise ValueError("model-role match flag and unmatched roles are inconsistent")
        if len(self.unmatched_roles) != len(set(self.unmatched_roles)):
            raise ValueError("unmatched model roles must be unique")
        return self


class ExternalAdapterContractManifest(BaseModel):
    """Evidence-bound translation feasibility for one system/model pair."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    contract_id: str = Field(pattern=_ID)
    authorization_scope: Literal["static-translation-only"]
    external_resource_id: str = Field(pattern=_ID)
    expected_upstream_commit: str = Field(pattern=_COMMIT)
    invocation: AdapterInvocationContract
    task_translation: AdapterTaskTranslation
    model_translation: AdapterModelTranslation
    requirements: dict[AdapterRequirement, AdapterContractEvidence]
    forbidden_changes: tuple[str, ...] = Field(min_length=1, max_length=30)
    requires_separate_upstream_preflight: Literal[True] = True
    no_external_download: Literal[True] = True
    no_execution_performed: Literal[True] = True

    @model_validator(mode="after")
    def contract_is_complete(self) -> ExternalAdapterContractManifest:
        missing = set(AdapterRequirement) - set(self.requirements)
        extra = set(self.requirements) - set(AdapterRequirement)
        if missing or extra:
            raise ValueError(
                "adapter-contract requirement matrix must be complete: "
                f"missing={sorted(item.value for item in missing)}, "
                f"extra={sorted(str(item) for item in extra)}"
            )
        if len(self.forbidden_changes) != len(set(self.forbidden_changes)):
            raise ValueError("adapter forbidden changes must be unique")
        if self.requirements[AdapterRequirement.TASK_MAPPING].status is ReadinessStatus.VERIFIED:
            task_checks = (
                self.task_translation.one_task_per_process,
                self.task_translation.preserves_exact_starting_bytes,
                self.task_translation.runtime_acquisition_policy_injectable,
            )
            if not all(task_checks):
                raise ValueError("verified task mapping requires exact, isolated task injection")
        if self.requirements[AdapterRequirement.MODEL_MAPPING].status is ReadinessStatus.VERIFIED:
            model = self.model_translation
            if (
                not model.all_model_roles_matched
                or model.upstream_model_id != model.requested_model_id
            ):
                raise ValueError(
                    "verified model mapping requires the exact model ID for every role"
                )
        return self

    @property
    def proposal_sha256(self) -> str:
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


class AdapterContractInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    manifest: ExternalAdapterContractManifest


class AdapterContractFinding(BaseModel):
    model_config = _CONFIG

    code: str = Field(pattern=r"^[a-z0-9]+(?:[a-z0-9_:-]*[a-z0-9])?$")
    message: str = Field(min_length=1, max_length=4_000)


class AdapterContractReport(BaseModel):
    """Static feasibility report; a clean result still requires upstream preflight."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    contract_id: str
    proposal_sha256: str = Field(pattern=_SHA256)
    resource_corpus_sha256: str = Field(pattern=_SHA256)
    ready_for_adapter_implementation: bool
    ready_for_upstream_preflight: bool
    ready_for_matched_adapter: Literal[False] = False
    authorizes_execution: Literal[False] = False
    blockers: tuple[AdapterContractFinding, ...]
    blocked_requirements: tuple[AdapterRequirement, ...]
    pending_requirements: tuple[AdapterRequirement, ...]
    verified_requirements: tuple[AdapterRequirement, ...]
    no_external_download: Literal[True] = True
    no_execution_performed: Literal[True] = True


def load_adapter_contract_manifest(path: str | Path) -> AdapterContractInspection:
    requested = Path(path)
    if requested.is_symlink():
        raise ValueError("adapter-contract manifest must not be a symlink")
    resolved = requested.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size > _MAX_MANIFEST_BYTES:
        raise ValueError("adapter-contract manifest must be a bounded regular file")
    raw = resolved.read_bytes()
    try:
        payload = yaml.safe_load(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ValueError("adapter-contract manifest must be UTF-8") from exc
    if not isinstance(payload, dict):
        raise ValueError("adapter-contract manifest must contain a YAML mapping")
    return AdapterContractInspection(
        path=resolved,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        manifest=ExternalAdapterContractManifest.model_validate(payload),
    )


def inspect_adapter_contract(
    manifest: ExternalAdapterContractManifest,
    resource_corpus: ExternalResourceCorpus,
    *,
    source_root: str | Path,
) -> AdapterContractReport:
    """Verify static compatibility claims without acquiring or importing upstream code."""

    blockers: list[AdapterContractFinding] = []
    resources = {resource.resource_id: resource for resource in resource_corpus.resources}
    resource = resources.get(manifest.external_resource_id)
    if resource is None:
        _add(blockers, "unknown_external_resource", "external system is absent from corpus")
    else:
        if resource.resource_kind is not EvaluationResourceKind.SYSTEM:
            _add(blockers, "wrong_resource_kind", "adapter contract requires a system resource")
        if resource.repository_commit != manifest.expected_upstream_commit:
            _add(blockers, "upstream_pin_mismatch", "manifest and corpus commits differ")

    try:
        root = Path(source_root).resolve(strict=True)
    except (OSError, ValueError):
        root = None
        _add(blockers, "source_root_unavailable", "source root could not be resolved")

    blocked: list[AdapterRequirement] = []
    pending: list[AdapterRequirement] = []
    verified: list[AdapterRequirement] = []
    for requirement in AdapterRequirement:
        evidence = manifest.requirements[requirement]
        if not any(
            manifest.expected_upstream_commit in url for url in evidence.official_source_urls
        ):
            _add(
                blockers,
                f"source_unpinned:{requirement.value}",
                f"{requirement.value} evidence lacks the expected commit",
            )
        if root is not None:
            _verify_file(
                blockers,
                root,
                evidence.evidence_ref,
                evidence.evidence_sha256,
                f"requirement:{requirement.value}",
            )
        if evidence.status is ReadinessStatus.BLOCKED:
            blocked.append(requirement)
            _add(
                blockers,
                f"requirement_blocked:{requirement.value}",
                evidence.summary,
            )
        elif evidence.status is ReadinessStatus.PENDING:
            pending.append(requirement)
        else:
            verified.append(requirement)

    if manifest.model_translation.all_model_roles_matched and (
        manifest.model_translation.upstream_model_id
        != manifest.model_translation.requested_model_id
    ):
        _add(
            blockers,
            "model_identity_mismatch",
            "an exact model mapping must preserve the requested callable model ID",
        )

    ready = not blockers and not blocked
    return AdapterContractReport(
        contract_id=manifest.contract_id,
        proposal_sha256=manifest.proposal_sha256,
        resource_corpus_sha256=resource_corpus.semantic_sha256,
        ready_for_adapter_implementation=ready,
        ready_for_upstream_preflight=ready and not pending,
        blockers=tuple(blockers),
        blocked_requirements=tuple(blocked),
        pending_requirements=tuple(pending),
        verified_requirements=tuple(verified),
    )


def _verify_file(
    blockers: list[AdapterContractFinding],
    root: Path,
    locator: str,
    expected_sha256: str,
    code_prefix: str,
) -> None:
    candidate = _resolve_bounded_path(root, locator)
    if candidate is None or not candidate.is_file():
        _add(blockers, f"{code_prefix}:missing", f"evidence file is missing: {locator}")
        return
    if candidate.stat().st_size > _MAX_EVIDENCE_BYTES:
        _add(blockers, f"{code_prefix}:oversized", f"evidence file is oversized: {locator}")
        return
    if hashlib.sha256(candidate.read_bytes()).hexdigest() != expected_sha256:
        _add(blockers, f"{code_prefix}:hash_mismatch", f"evidence hash differs: {locator}")


def _resolve_bounded_path(root: Path, locator: str) -> Path | None:
    try:
        _validate_relative_path(locator, "bounded path")
    except ValueError:
        return None
    current = root
    for part in PurePosixPath(locator).parts:
        current = current / part
        if current.is_symlink():
            return None
    try:
        resolved = current.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError):
        return None
    return resolved


def _validate_relative_path(locator: str, label: str) -> None:
    pure = PurePosixPath(locator)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError(f"{label} must be a bounded relative POSIX path")


def _add(findings: list[AdapterContractFinding], code: str, message: str) -> None:
    findings.append(AdapterContractFinding(code=code, message=message))


__all__ = [
    "AdapterContractEvidence",
    "AdapterContractFinding",
    "AdapterContractInspection",
    "AdapterContractReport",
    "AdapterInvocationContract",
    "AdapterModelTranslation",
    "AdapterTaskTranslation",
    "ExternalAdapterContractManifest",
    "inspect_adapter_contract",
    "load_adapter_contract_manifest",
]
