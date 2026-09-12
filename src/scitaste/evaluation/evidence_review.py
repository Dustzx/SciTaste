"""Program-bound review packages for ICLR evidence acquisition and adapters."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from scitaste.evaluation.acquisition import (
    inspect_dataset_acquisition_request,
    load_dataset_acquisition_request,
)
from scitaste.evaluation.adapter_contract import (
    inspect_adapter_contract,
    load_adapter_contract_manifest,
)
from scitaste.evaluation.evidence_program import inspect_evidence_program
from scitaste.evaluation.resources import load_external_resource_corpus

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_MANIFEST_BYTES = 1_048_576


class SourceProposalKind(StrEnum):
    CONSTRUCTION_SCREEN = "construction_screen"
    ACQUISITION_REQUEST = "acquisition_request"
    ACQUIRED_METADATA_INVENTORY = "acquired_metadata_inventory"


class ReviewFileBinding(BaseModel):
    model_config = _CONFIG

    path: str = Field(min_length=1, max_length=1_000)
    file_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def path_is_bounded(self) -> ReviewFileBinding:
        _validate_relative_path(self.path)
        return self


class SourceProposalBinding(ReviewFileBinding):
    source_id: str = Field(pattern=_ID)
    kind: SourceProposalKind
    proposal_sha256: str | None = Field(default=None, pattern=_SHA256)

    @model_validator(mode="after")
    def proposal_hash_matches_kind(self) -> SourceProposalBinding:
        requires_proposal = self.kind is SourceProposalKind.ACQUISITION_REQUEST
        if requires_proposal != (self.proposal_sha256 is not None):
            raise ValueError("only acquisition-request bindings require a proposal SHA-256")
        return self


class MethodProposalBinding(ReviewFileBinding):
    system_id: str = Field(pattern=_ID)
    proposal_sha256: str = Field(pattern=_SHA256)


class EvidenceReviewPackage(BaseModel):
    """Exact proposal coverage; never an approval or execution manifest."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    package_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    evidence_program: ReviewFileBinding
    evidence_program_sha256: str = Field(pattern=_SHA256)
    resource_corpus: ReviewFileBinding
    resource_corpus_sha256: str = Field(pattern=_SHA256)
    source_proposals: tuple[SourceProposalBinding, ...] = Field(min_length=1, max_length=30)
    method_proposals: tuple[MethodProposalBinding, ...] = Field(min_length=2, max_length=30)
    authorizes_download: Literal[False] = False
    authorizes_repository_checkout: Literal[False] = False
    authorizes_api_calls: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False
    authorizes_human_recruitment: Literal[False] = False
    authorizes_execution: Literal[False] = False

    @model_validator(mode="after")
    def proposal_ids_are_unique(self) -> EvidenceReviewPackage:
        for values, label in (
            ([item.source_id for item in self.source_proposals], "source"),
            ([item.system_id for item in self.method_proposals], "method"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"evidence review {label} proposal IDs must be unique")
        return self

    @computed_field
    @property
    def package_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"package_sha256"}))


class EvidenceReviewInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    package: EvidenceReviewPackage


class EvidenceReviewFinding(BaseModel):
    model_config = _CONFIG

    code: str = Field(pattern=r"^[a-z0-9]+(?:[a-z0-9_:.\/-]*[a-z0-9])?$")
    message: str = Field(min_length=1, max_length=4_000)


class SourceProposalStatus(BaseModel):
    model_config = _CONFIG

    source_id: str
    kind: SourceProposalKind
    ready_for_scope_review: bool
    requested_item_count: int = Field(ge=0)
    maximum_requested_bytes: int = Field(ge=0)
    action_authorized: Literal[False] = False
    unresolved_codes: tuple[str, ...]


class MethodProposalStatus(BaseModel):
    model_config = _CONFIG

    system_id: str
    ready_for_proposal_review: bool
    proposal_viable: bool
    ready_for_adapter_implementation: bool
    ready_for_upstream_preflight: bool
    action_authorized: Literal[False] = False
    resource_gate_blockers: tuple[str, ...]
    unresolved_requirements: tuple[str, ...]


class EvidenceReviewReport(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    package_id: str
    package_sha256: str = Field(pattern=_SHA256)
    evidence_program_sha256: str = Field(pattern=_SHA256)
    resource_corpus_sha256: str = Field(pattern=_SHA256)
    scientifically_coherent: bool
    exact_bindings_verified: bool
    source_proposal_coverage_complete: bool
    method_proposal_coverage_complete: bool
    ready_for_owner_review: bool
    ready_for_experiment: Literal[False] = False
    requested_metadata_item_count: int = Field(ge=0)
    maximum_requested_metadata_bytes: int = Field(ge=0)
    unresolved_experiment_blocker_count: int = Field(ge=0)
    source_statuses: tuple[SourceProposalStatus, ...]
    method_statuses: tuple[MethodProposalStatus, ...]
    findings: tuple[EvidenceReviewFinding, ...]
    authorizes_download: Literal[False] = False
    authorizes_repository_checkout: Literal[False] = False
    authorizes_api_calls: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False
    authorizes_human_recruitment: Literal[False] = False
    authorizes_execution: Literal[False] = False
    no_external_action_performed: Literal[True] = True

    @model_validator(mode="after")
    def summary_is_derived_from_bound_statuses(self) -> EvidenceReviewReport:
        if self.exact_bindings_verified != (not self.findings):
            raise ValueError("evidence-review exactness must match its findings")
        expected_items = sum(item.requested_item_count for item in self.source_statuses)
        expected_bytes = sum(item.maximum_requested_bytes for item in self.source_statuses)
        if self.requested_metadata_item_count != expected_items:
            raise ValueError("evidence-review requested item count is inconsistent")
        if self.maximum_requested_metadata_bytes != expected_bytes:
            raise ValueError("evidence-review requested byte ceiling is inconsistent")
        expected_ready = (
            self.scientifically_coherent
            and self.exact_bindings_verified
            and self.source_proposal_coverage_complete
            and self.method_proposal_coverage_complete
            and all(item.ready_for_scope_review for item in self.source_statuses)
            and all(item.ready_for_proposal_review for item in self.method_statuses)
        )
        if self.ready_for_owner_review != expected_ready:
            raise ValueError("evidence-review owner-review readiness is inconsistent")
        return self


def load_evidence_review_package(path: str | Path) -> EvidenceReviewInspection:
    requested = Path(path)
    if requested.is_symlink():
        raise ValueError("evidence-review package must not be a symlink")
    resolved = requested.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size > _MAX_MANIFEST_BYTES:
        raise ValueError("evidence-review package must be a bounded regular file")
    raw = resolved.read_bytes()
    try:
        payload = yaml.safe_load(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ValueError("evidence-review package must be UTF-8") from exc
    if not isinstance(payload, dict):
        raise ValueError("evidence-review package must contain a YAML mapping")
    return EvidenceReviewInspection(
        path=resolved,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        package=EvidenceReviewPackage.model_validate(payload),
    )


def inspect_evidence_review_package(
    inspection: EvidenceReviewInspection,
    *,
    workspace_root: str | Path,
) -> EvidenceReviewReport:
    """Verify proposal coverage and exact bytes without authorizing any action."""

    package = inspection.package
    root = Path(workspace_root).resolve(strict=True)
    findings: list[EvidenceReviewFinding] = []

    program_path = _verify_binding(root, package.evidence_program, findings, "program")
    corpus_path = _verify_binding(root, package.resource_corpus, findings, "corpus")
    program_inspection = None
    corpus_inspection = None
    evidence_report = None
    if program_path is not None and corpus_path is not None:
        corpus_inspection = load_external_resource_corpus(corpus_path)
        program_inspection = inspect_evidence_program(program_path, corpus_path)
        evidence_report = program_inspection.report
        if program_inspection.program.proposal_sha256 != package.evidence_program_sha256:
            _add(findings, "program:semantic-hash-mismatch", "evidence-program hash differs")
        if corpus_inspection.semantic_sha256 != package.resource_corpus_sha256:
            _add(findings, "corpus:semantic-hash-mismatch", "resource-corpus hash differs")

    selected_sources = (
        {
            item.source_id
            for item in program_inspection.program.task_sources
            if item.selected_for_acquisition_proposal
        }
        if program_inspection is not None
        else set()
    )
    bound_sources = {item.source_id for item in package.source_proposals}
    source_coverage = bool(selected_sources) and selected_sources == bound_sources
    if selected_sources != bound_sources:
        _add(
            findings,
            "source:coverage-mismatch",
            f"selected={sorted(selected_sources)} bound={sorted(bound_sources)}",
        )

    selected_methods = (
        {
            item.system_id
            for item in program_inspection.program.system_candidates
            if item.selected_for_adapter_proposal
        }
        if program_inspection is not None
        else set()
    )
    bound_methods = {item.system_id for item in package.method_proposals}
    method_coverage = len(selected_methods) >= 2 and selected_methods == bound_methods
    if selected_methods != bound_methods:
        _add(
            findings,
            "method:coverage-mismatch",
            f"selected={sorted(selected_methods)} bound={sorted(bound_methods)}",
        )

    source_statuses: list[SourceProposalStatus] = []
    for binding in package.source_proposals:
        path = _verify_binding(root, binding, findings, f"source:{binding.source_id}")
        ready = path is not None
        requested_items = 0
        requested_bytes = 0
        unresolved: list[str] = []
        if path is not None and binding.kind is SourceProposalKind.ACQUISITION_REQUEST:
            request_inspection = load_dataset_acquisition_request(path)
            request = request_inspection.request
            if request.request_sha256 != binding.proposal_sha256:
                _add(
                    findings,
                    f"source:{binding.source_id}:proposal-hash-mismatch",
                    "acquisition request semantic hash differs",
                )
                ready = False
            request_report = inspect_dataset_acquisition_request(request, workspace_root=root)
            requested_items = request_report.item_count
            requested_bytes = request_report.maximum_total_bytes
            unresolved.extend(item.code for item in request_report.authorization_blockers)
            scope_blockers = tuple(
                item
                for item in request_report.blockers
                if not (item.code.startswith("destination:") and item.code.endswith(":exists"))
            )
            unresolved.extend(item.code for item in scope_blockers)
            # A review package evaluates the frozen acquisition scope, not whether
            # its one-shot destination is still empty.  Once an approved download
            # has materialized the exact destination, the original proposal remains
            # reviewable even though it must never become executable a second time.
            ready = ready and not scope_blockers
            if request_report.download_authorized:
                _add(
                    findings,
                    f"source:{binding.source_id}:already-authorized",
                    "review package must bind an unapproved acquisition request",
                )
                ready = False
        source_statuses.append(
            SourceProposalStatus(
                source_id=binding.source_id,
                kind=binding.kind,
                ready_for_scope_review=ready,
                requested_item_count=requested_items,
                maximum_requested_bytes=requested_bytes,
                unresolved_codes=tuple(unresolved),
            )
        )

    method_statuses: list[MethodProposalStatus] = []
    if corpus_inspection is not None:
        for binding in package.method_proposals:
            path = _verify_binding(root, binding, findings, f"method:{binding.system_id}")
            if path is None:
                method_statuses.append(
                    MethodProposalStatus(
                        system_id=binding.system_id,
                        ready_for_proposal_review=False,
                        proposal_viable=False,
                        ready_for_adapter_implementation=False,
                        ready_for_upstream_preflight=False,
                        resource_gate_blockers=("contract_binding_invalid",),
                        unresolved_requirements=(),
                    )
                )
                continue
            contract = load_adapter_contract_manifest(path).manifest
            if contract.external_resource_id != binding.system_id:
                _add(
                    findings,
                    f"method:{binding.system_id}:resource-mismatch",
                    "adapter contract targets another resource",
                )
            if contract.proposal_sha256 != binding.proposal_sha256:
                _add(
                    findings,
                    f"method:{binding.system_id}:proposal-hash-mismatch",
                    "adapter contract semantic hash differs",
                )
            report = inspect_adapter_contract(contract, corpus_inspection.corpus, source_root=root)
            unresolved = tuple(
                item.value for item in (*report.blocked_requirements, *report.pending_requirements)
            )
            method_statuses.append(
                MethodProposalStatus(
                    system_id=binding.system_id,
                    ready_for_proposal_review=report.ready_for_proposal_review,
                    proposal_viable=report.proposal_viable,
                    ready_for_adapter_implementation=report.ready_for_adapter_implementation,
                    ready_for_upstream_preflight=report.ready_for_upstream_preflight,
                    resource_gate_blockers=report.resource_gate_blockers,
                    unresolved_requirements=unresolved,
                )
            )

    exact = not findings
    scientific = bool(evidence_report and evidence_report.scientifically_coherent)
    source_review_ready = source_coverage and all(
        item.ready_for_scope_review for item in source_statuses
    )
    method_review_ready = method_coverage and all(
        item.ready_for_proposal_review for item in method_statuses
    )
    return EvidenceReviewReport(
        package_id=package.package_id,
        package_sha256=package.package_sha256,
        evidence_program_sha256=package.evidence_program_sha256,
        resource_corpus_sha256=package.resource_corpus_sha256,
        scientifically_coherent=scientific,
        exact_bindings_verified=exact,
        source_proposal_coverage_complete=source_coverage,
        method_proposal_coverage_complete=method_coverage,
        ready_for_owner_review=(
            scientific and exact and source_review_ready and method_review_ready
        ),
        requested_metadata_item_count=sum(item.requested_item_count for item in source_statuses),
        maximum_requested_metadata_bytes=sum(
            item.maximum_requested_bytes for item in source_statuses
        ),
        unresolved_experiment_blocker_count=(
            len(evidence_report.experiment_findings) if evidence_report is not None else 0
        ),
        source_statuses=tuple(source_statuses),
        method_statuses=tuple(method_statuses),
        findings=tuple(findings),
    )


def _verify_binding(
    root: Path,
    binding: ReviewFileBinding,
    findings: list[EvidenceReviewFinding],
    owner: str,
) -> Path | None:
    current = root
    for part in PurePosixPath(binding.path).parts:
        current /= part
        if current.is_symlink():
            _add(findings, f"{owner}:symlink", binding.path)
            return None
    try:
        resolved = current.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError):
        _add(findings, f"{owner}:missing", binding.path)
        return None
    if not resolved.is_file() or resolved.stat().st_size > _MAX_MANIFEST_BYTES:
        _add(findings, f"{owner}:invalid-file", binding.path)
        return None
    observed = hashlib.sha256(resolved.read_bytes()).hexdigest()
    if observed != binding.file_sha256:
        _add(findings, f"{owner}:file-hash-mismatch", binding.path)
        return None
    return resolved


def _validate_relative_path(path: str) -> None:
    pure = PurePosixPath(path)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError("evidence-review paths must be normalized relative POSIX paths")


def _canonical_sha256(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _add(findings: list[EvidenceReviewFinding], code: str, message: str) -> None:
    findings.append(EvidenceReviewFinding(code=code, message=message))


__all__ = [
    "EvidenceReviewFinding",
    "EvidenceReviewInspection",
    "EvidenceReviewPackage",
    "EvidenceReviewReport",
    "MethodProposalBinding",
    "MethodProposalStatus",
    "ReviewFileBinding",
    "SourceProposalBinding",
    "SourceProposalKind",
    "SourceProposalStatus",
    "inspect_evidence_review_package",
    "load_evidence_review_package",
]
