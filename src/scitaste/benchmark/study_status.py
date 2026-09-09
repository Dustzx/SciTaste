"""Read-only, integrity-aware status for matched-budget study matrices."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from scitaste.benchmark.study import MatchedStudyEvaluator, MatchedStudyPlanner
from scitaste.benchmark.study_execution import StudyCellCheckpoint, StudyRunManifest
from scitaste.benchmark.study_models import (
    CellStatus,
    ExpertPanelReview,
    MatchedStudyProtocol,
    StudyCell,
    StudyExecutionRecord,
    StudyResults,
    StudyStatus,
)

MAX_RESULT_SOURCES = 512
MAX_RESULT_BYTES = 16 * 1024 * 1024


class StudyResultSourceAudit(BaseModel):
    """Classification of one discovered aggregate result file."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    file_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    protocol_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    compatibility: Literal["compatible", "foreign", "invalid"]
    integrity: Literal["verified", "failed", "not_applicable"]
    record_count: int = Field(default=0, ge=0)
    review_count: int = Field(default=0, ge=0)
    violations: list[str] = Field(default_factory=list)


class StudyCellProgress(BaseModel):
    """Reader-facing status for one exact protocol cell."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cell_id: str
    blind_id: str
    task_id: str
    condition: str
    seed: int
    repetition: int = Field(ge=0)
    execution_status: Literal["missing", "failed", "succeeded"]
    evidence_class: str | None = None
    telemetry_complete: bool = False
    budget_compliant: bool = False
    outcome_consistent: bool = False
    review_status: Literal[
        "missing",
        "invalid",
        "internal_valid",
        "synthetic_valid",
        "external_valid",
    ] = "missing"


class StudyMatrixStatus(BaseModel):
    """Exact current matrix status; foreign protocol runs remain informational."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    study_id: str
    protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluation_status: StudyStatus
    headline_eligible: bool
    planned_cells: int = Field(ge=0)
    integrity_verified_records: int = Field(ge=0)
    succeeded_cells: int = Field(ge=0)
    failed_cells: int = Field(ge=0)
    valid_external_reviews: int = Field(ge=0)
    missing_cells: int = Field(ge=0)
    compatible_sources: int = Field(ge=0)
    foreign_sources: int = Field(ge=0)
    invalid_sources: int = Field(ge=0)
    next_execution_batch: list[str]
    next_review_batch: list[str]
    blockers: list[str]
    sources: list[StudyResultSourceAudit]
    cells: list[StudyCellProgress]

    @property
    def sha256(self) -> str:
        return _content_sha256(self.model_dump(mode="json"))


def discover_study_result_paths(
    outputs_root: str | Path,
    *,
    explicit_paths: list[str | Path] | None = None,
) -> list[Path]:
    """Discover aggregate results without following result-file symlinks."""

    root = Path(outputs_root)
    discovered = list(root.rglob("study_results.json")) if root.is_dir() else []
    paths = {path.absolute() for path in discovered}
    paths.update(Path(path).absolute() for path in explicit_paths or [])
    ordered = sorted(paths, key=lambda path: path.as_posix())
    if len(ordered) > MAX_RESULT_SOURCES:
        raise ValueError(
            f"study status found {len(ordered)} result sources; maximum is {MAX_RESULT_SOURCES}"
        )
    return ordered


def inspect_study_matrix(
    protocol: MatchedStudyProtocol,
    result_paths: list[str | Path],
) -> StudyMatrixStatus:
    """Merge only exact-protocol, integrity-verified execution records."""

    plan = MatchedStudyPlanner().plan(protocol)
    source_audits: list[StudyResultSourceAudit] = []
    records: dict[str, StudyExecutionRecord] = {}
    reviews: dict[str, ExpertPanelReview] = {}
    record_conflicts: set[str] = set()
    review_conflicts: set[str] = set()

    for value in sorted({Path(path).absolute() for path in result_paths}):
        audit, results = _audit_result_source(value, protocol, plan.cells, plan.sha256)
        source_audits.append(audit)
        if results is None or audit.integrity != "verified":
            continue
        for record in results.records:
            _merge_identity_bound_item(
                records,
                record,
                identity=record.cell_id,
                conflicts=record_conflicts,
            )
        for review in results.expert_reviews:
            _merge_identity_bound_item(
                reviews,
                review,
                identity=review.blind_id,
                conflicts=review_conflicts,
            )

    for identity in record_conflicts:
        records.pop(identity, None)
    for identity in review_conflicts:
        reviews.pop(identity, None)

    merged = StudyResults(
        protocol_sha256=protocol.sha256,
        records=[record for cell in plan.cells if (record := records.get(cell.cell_id))],
        expert_reviews=[review for cell in plan.cells if (review := reviews.get(cell.blind_id))],
    )
    report = MatchedStudyEvaluator().evaluate(protocol, merged)
    audit_by_cell = {audit.cell_id: audit for audit in report.audits}
    progress: list[StudyCellProgress] = []
    for cell in plan.cells:
        record = records.get(cell.cell_id)
        review = reviews.get(cell.blind_id)
        cell_audit = audit_by_cell.get(cell.cell_id)
        progress.append(
            StudyCellProgress(
                cell_id=cell.cell_id,
                blind_id=cell.blind_id,
                task_id=cell.task_id,
                condition=cell.condition.value,
                seed=cell.seed,
                repetition=cell.repetition,
                execution_status=(record.status.value if record is not None else "missing"),
                evidence_class=record.evidence_class.value if record is not None else None,
                telemetry_complete=bool(cell_audit and cell_audit.telemetry_complete),
                budget_compliant=bool(cell_audit and cell_audit.budget_compliant),
                outcome_consistent=bool(cell_audit and cell_audit.outcome_consistent),
                review_status=_review_status(review, cell_audit),
            )
        )

    blockers = list(report.blockers)
    failed_integrity = sum(
        source.compatibility == "compatible" and source.integrity == "failed"
        for source in source_audits
    )
    if failed_integrity:
        blockers.append(
            f"{failed_integrity} compatible result sources failed integrity verification"
        )
    if record_conflicts:
        blockers.append(
            "conflicting execution records were excluded: " + ", ".join(sorted(record_conflicts))
        )
    if review_conflicts:
        blockers.append(
            "conflicting expert reviews were excluded: " + ", ".join(sorted(review_conflicts))
        )

    next_execution = _next_execution_batch(plan.cells, records)
    next_review = _next_review_batch(plan.cells, records, reviews, audit_by_cell)
    effective_status = StudyStatus.INCOMPLETE if blockers else report.status
    return StudyMatrixStatus(
        study_id=protocol.study_id,
        protocol_sha256=protocol.sha256,
        plan_sha256=plan.sha256,
        evaluation_status=effective_status,
        headline_eligible=report.headline_eligible and not blockers,
        planned_cells=len(plan.cells),
        integrity_verified_records=len(records),
        succeeded_cells=sum(record.status == CellStatus.SUCCEEDED for record in records.values()),
        failed_cells=sum(record.status == CellStatus.FAILED for record in records.values()),
        valid_external_reviews=sum(item.review_status == "external_valid" for item in progress),
        missing_cells=len(plan.cells) - len(records),
        compatible_sources=sum(source.compatibility == "compatible" for source in source_audits),
        foreign_sources=sum(source.compatibility == "foreign" for source in source_audits),
        invalid_sources=sum(source.compatibility == "invalid" for source in source_audits),
        next_execution_batch=[cell.cell_id for cell in next_execution],
        next_review_batch=[cell.blind_id for cell in next_review],
        blockers=blockers,
        sources=source_audits,
        cells=progress,
    )


def save_study_matrix_status(status: StudyMatrixStatus, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {**status.model_dump(mode="json"), "status_sha256": status.sha256}
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return target


def _audit_result_source(
    path: Path,
    protocol: MatchedStudyProtocol,
    planned_cells: list[StudyCell],
    plan_sha256: str,
) -> tuple[StudyResultSourceAudit, StudyResults | None]:
    label = _display_path(path)
    digest: str | None = None
    try:
        if path.is_symlink():
            raise ValueError("result source cannot be a symlink")
        if not path.is_file():
            raise ValueError("result source is not a regular file")
        if path.stat().st_size > MAX_RESULT_BYTES:
            raise ValueError(f"result source exceeds {MAX_RESULT_BYTES} bytes")
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        results = StudyResults.model_validate_json(raw)
    except (OSError, ValueError) as exc:
        return (
            StudyResultSourceAudit(
                path=label,
                file_sha256=digest,
                compatibility="invalid",
                integrity="not_applicable",
                violations=[str(exc)],
            ),
            None,
        )

    if results.protocol_sha256 != protocol.sha256:
        return (
            StudyResultSourceAudit(
                path=label,
                file_sha256=digest,
                protocol_sha256=results.protocol_sha256,
                compatibility="foreign",
                integrity="not_applicable",
                record_count=len(results.records),
                review_count=len(results.expert_reviews),
                violations=["protocol fingerprint differs from the requested matrix"],
            ),
            None,
        )

    violations = _verify_result_source_integrity(
        path,
        results,
        protocol,
        planned_cells,
        plan_sha256,
    )
    return (
        StudyResultSourceAudit(
            path=label,
            file_sha256=digest,
            protocol_sha256=results.protocol_sha256,
            compatibility="compatible",
            integrity="failed" if violations else "verified",
            record_count=len(results.records),
            review_count=len(results.expert_reviews),
            violations=violations,
        ),
        results if not violations else None,
    )


def _verify_result_source_integrity(
    results_path: Path,
    results: StudyResults,
    protocol: MatchedStudyProtocol,
    planned_cells: list[StudyCell],
    plan_sha256: str,
) -> list[str]:
    root = results_path.parent.absolute()
    cells = {cell.cell_id: cell for cell in planned_cells}
    violations: list[str] = []
    manifest_path = root / "study_run_manifest.json"
    try:
        _require_regular_unlinked_file(manifest_path)
        manifest = StudyRunManifest.model_validate_json(manifest_path.read_bytes())
        if manifest.protocol_sha256 != protocol.sha256 or manifest.plan_sha256 != plan_sha256:
            raise ValueError("study run manifest identity differs from the requested matrix")
    except (OSError, ValueError) as exc:
        return [f"run manifest: {exc}"]

    seen: set[str] = set()
    for record in results.records:
        if record.cell_id in seen:
            violations.append(f"{record.cell_id}: duplicate aggregate record")
            continue
        seen.add(record.cell_id)
        cell = cells.get(record.cell_id)
        if cell is None:
            violations.append(f"{record.cell_id}: cell is not in the requested matrix")
            continue
        try:
            _verify_cell(root, manifest, protocol, cell, record, plan_sha256)
        except (OSError, ValueError) as exc:
            violations.append(f"{record.cell_id}: {exc}")
    known_blind_ids = {cell.blind_id for cell in planned_cells}
    seen_reviews: set[str] = set()
    for review in results.expert_reviews:
        if review.blind_id not in known_blind_ids:
            violations.append(f"{review.blind_id}: review is not in the requested matrix")
        elif review.blind_id in seen_reviews:
            violations.append(f"{review.blind_id}: duplicate expert review")
        seen_reviews.add(review.blind_id)
    return violations


def _verify_cell(
    root: Path,
    manifest: StudyRunManifest,
    protocol: MatchedStudyProtocol,
    cell: StudyCell,
    aggregate: StudyExecutionRecord,
    plan_sha256: str,
) -> None:
    cell_dir = root / "cells" / cell.cell_id
    if cell_dir.is_symlink() or not cell_dir.is_dir():
        raise ValueError("owned cell directory is missing or is a symlink")
    record_path = cell_dir / "execution_record.json"
    request_path = cell_dir / "cell_request.json"
    checkpoint_path = cell_dir / "cell_checkpoint.json"
    for path in (record_path, request_path, checkpoint_path):
        _require_regular_unlinked_file(path)

    record = StudyExecutionRecord.model_validate_json(record_path.read_bytes())
    if record != aggregate or record.cell_id != cell.cell_id:
        raise ValueError("aggregate and owned execution record disagree")
    request = json.loads(request_path.read_bytes())
    if not isinstance(request, dict):
        raise ValueError("cell request root is not an object")
    checkpoint = StudyCellCheckpoint.model_validate_json(checkpoint_path.read_bytes())
    expected_identity = (
        cell.cell_id,
        protocol.sha256,
        plan_sha256,
        manifest.launch_config_sha256,
        _content_sha256(cell.model_dump(mode="json")),
        _content_sha256(request),
        _content_sha256(record.model_dump(mode="json")),
    )
    observed_identity = (
        checkpoint.cell_id,
        checkpoint.protocol_sha256,
        checkpoint.plan_sha256,
        checkpoint.launch_config_sha256,
        checkpoint.cell_sha256,
        checkpoint.request_sha256,
        checkpoint.record_sha256,
    )
    if observed_identity != expected_identity:
        raise ValueError("cell checkpoint identity mismatch")
    _verify_request(protocol, cell, request)

    required = {
        record_path.relative_to(root).as_posix(),
        request_path.relative_to(root).as_posix(),
        *(artifact.path for artifact in record.artifacts),
    }
    if missing := required - checkpoint.evidence_sha256.keys():
        raise ValueError(f"checkpoint omits evidence: {sorted(missing)}")
    for locator, expected_hash in checkpoint.evidence_sha256.items():
        evidence = _contained_regular_file(root, cell_dir, locator)
        if _file_sha256(evidence) != expected_hash:
            raise ValueError(f"evidence hash mismatch: {locator}")
    for artifact in record.artifacts:
        if checkpoint.evidence_sha256.get(artifact.path) != artifact.sha256:
            raise ValueError(f"artifact manifest mismatch: {artifact.path}")


def _verify_request(
    protocol: MatchedStudyProtocol,
    cell: StudyCell,
    request: dict[str, Any],
) -> None:
    task = next(item for item in protocol.tasks if item.task_id == cell.task_id)
    condition = next(item for item in protocol.conditions if item.condition == cell.condition)
    expected = {
        "protocol_sha256": protocol.sha256,
        "cell": cell.model_dump(mode="json"),
        "task": task.model_dump(mode="json"),
        "condition": condition.model_dump(mode="json"),
        "base_model": protocol.base_model,
        "base_model_revision": protocol.base_model_revision,
        "search_access": protocol.search_access.model_dump(mode="json"),
    }
    for key, value in expected.items():
        if request.get(key) != value:
            raise ValueError(f"cell request field differs from protocol: {key}")


def _contained_regular_file(root: Path, cell_dir: Path, locator: str) -> Path:
    relative = Path(locator)
    if relative.is_absolute() or not locator:
        raise ValueError(f"evidence locator is not relative: {locator!r}")
    candidate = root / relative
    resolved_root = root.resolve()
    resolved_cell = cell_dir.resolve()
    resolved = candidate.resolve()
    if not resolved.is_relative_to(resolved_root) or not resolved.is_relative_to(resolved_cell):
        raise ValueError(f"evidence escapes its cell directory: {locator}")
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"evidence path contains a symlink: {locator}")
    _require_regular_unlinked_file(candidate)
    return candidate


def _require_regular_unlinked_file(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"missing or linked regular file: {path.name}")


def _merge_identity_bound_item(target: dict[str, Any], item: Any, *, identity: str, conflicts):
    if identity in conflicts:
        return
    previous = target.get(identity)
    if previous is None:
        target[identity] = item
    elif previous != item:
        conflicts.add(identity)


def _review_status(review, audit) -> str:
    if review is None:
        return "missing"
    if audit is None or not audit.expert_review_valid:
        return "invalid"
    return f"{review.source.value}_valid"


def _next_execution_batch(
    cells: list[StudyCell], records: dict[str, StudyExecutionRecord]
) -> list[StudyCell]:
    groups: dict[tuple[str, int, int], list[StudyCell]] = {}
    for cell in cells:
        groups.setdefault((cell.task_id, cell.seed, cell.repetition), []).append(cell)
    for group in groups.values():
        pending = [
            cell
            for cell in group
            if records.get(cell.cell_id) is None
            or records[cell.cell_id].status != CellStatus.SUCCEEDED
        ]
        if pending:
            return pending
    return []


def _next_review_batch(cells, records, reviews, audits) -> list[StudyCell]:
    groups: dict[tuple[str, int, int], list[StudyCell]] = {}
    for cell in cells:
        groups.setdefault((cell.task_id, cell.seed, cell.repetition), []).append(cell)
    for group in groups.values():
        pending = []
        for cell in group:
            record = records.get(cell.cell_id)
            review = reviews.get(cell.blind_id)
            audit = audits.get(cell.cell_id)
            if (
                record is not None
                and record.status == CellStatus.SUCCEEDED
                and (
                    review is None
                    or review.source.value != "external"
                    or audit is None
                    or not audit.expert_review_valid
                )
            ):
                pending.append(cell)
        if pending:
            return pending
    return []


def _display_path(path: Path) -> str:
    resolved = path.absolute()
    try:
        return resolved.relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _content_sha256(value: Any) -> str:
    canonical = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "StudyCellProgress",
    "StudyMatrixStatus",
    "StudyResultSourceAudit",
    "discover_study_result_paths",
    "inspect_study_matrix",
    "save_study_matrix_status",
]
