"""Compile ARIES review--revision episodes into a de-identified Taste candidate set.

The compiler deliberately stops before scientific-quality admission.  A natural
review, an observed paper revision, or an upstream alignment annotation is useful
reference evidence, but none of them is automatically a correct scientific
decision.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tarfile
import tempfile
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scitaste.evaluation.acquisition import (
    DatasetAcquisitionReceipt,
    DatasetAcquisitionRequest,
    load_dataset_acquisition_receipt,
    load_dataset_acquisition_request,
)
from scitaste.evaluation.source_identity import canonical_openreview_source_group_id
from scitaste.model_nodes.verification_policy import (
    ActionEffect,
    ActionReversibility,
    VerificationDecision,
    VerificationDecisionInput,
    VerificationRoute,
    decide_verification_route,
)
from scitaste.project import ProjectRun, ProjectRuntime, ProjectSnapshot
from scitaste.project.models import validate_entry_id, validate_project_id

_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)
_SHA256 = r"^[0-9a-f]{64}$"
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_EXPECTED_REQUEST_ID = "aries-review-edit-population-v1"
_EXPECTED_ITEMS = {
    "review_comments": "review_comments.jsonl",
    "paper_edits": "paper_edits.jsonl",
    "edit_labels_test": "edit_labels_test.jsonl",
    "alignment_human_eval": "alignment_human_eval.jsonl",
    "split_ids": "split_ids.json",
    "s2orc": "s2orc.tar.gz",
    "license": "LICENSE",
}
_MAX_JSONL_LINE_BYTES = 16 * 1024 * 1024
_MAX_JSON_ROWS = 20_000
_MAX_TAR_MEMBERS = 5_000
_MAX_TAR_EXPANDED_BYTES = 1_000_000_000
_MAX_S2ORC_MEMBER_BYTES = 16 * 1024 * 1024
_MAX_CONTEXT_CHARS = 4_000
_MAX_EDIT_TEXT_CHARS = 6_000
_PROJECT_STAGE = "taste_candidate_population"
_PROJECT_PROJECTION = "aries-taste-candidate-population-v1"
_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])")


class AriesPopulationFinding(BaseModel):
    model_config = _CONFIG

    code: str = Field(pattern=r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$")
    message: str = Field(min_length=1, max_length=2_000)


class AriesObservedEdit(BaseModel):
    """One real paragraph-level change referenced by an upstream alignment source."""

    model_config = _CONFIG

    edit_id: int = Field(ge=0)
    source_paragraph_indices: tuple[int, ...] = Field(max_length=100)
    target_paragraph_indices: tuple[int, ...] = Field(max_length=100)
    source_text: str = Field(max_length=_MAX_EDIT_TEXT_CHARS)
    target_text: str = Field(max_length=_MAX_EDIT_TEXT_CHARS)


class AriesTasteCandidate(BaseModel):
    """Model-visible reference episode with only opaque local identities."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    candidate_id: str = Field(pattern=_ID)
    source_group_id: str = Field(pattern=_ID)
    source_split: Literal["test"] = "test"
    decision_family: Literal["review-guided-revision"] = "review-guided-revision"
    paper_context: str = Field(min_length=1, max_length=_MAX_CONTEXT_CHARS)
    review_comment: str = Field(min_length=1, max_length=_MAX_CONTEXT_CHARS)
    observed_edits: tuple[AriesObservedEdit, ...] = Field(max_length=100)
    primary_alignment_edit_ids: tuple[int, ...] = Field(max_length=100)
    human_alignment_edit_ids: tuple[int, ...] = Field(max_length=100)
    alignment_status: Literal["agreed", "disagreed"]
    observed_response: Literal["aligned-edit-observed", "no-aligned-edit-observed"]
    natural_review_annotation: Literal[True] = True
    observed_revision_is_not_gold: Literal[True] = True
    upstream_alignment_is_not_gold: Literal[True] = True
    author_identity_hidden: Literal[True] = True
    reviewer_identity_hidden: Literal[True] = True
    source_document_identity_hidden: Literal[True] = True

    @model_validator(mode="after")
    def alignment_is_closed(self) -> AriesTasteCandidate:
        if self.alignment_status != (
            "agreed"
            if self.primary_alignment_edit_ids == self.human_alignment_edit_ids
            else "disagreed"
        ):
            raise ValueError("ARIES candidate alignment status differs from its labels")
        expected_response = (
            "aligned-edit-observed" if self.observed_edits else "no-aligned-edit-observed"
        )
        if self.observed_response != expected_response:
            raise ValueError("ARIES candidate response state differs from its edit evidence")
        visible_edit_ids = {item.edit_id for item in self.observed_edits}
        expected_edit_ids = set(self.primary_alignment_edit_ids) | set(
            self.human_alignment_edit_ids
        )
        if visible_edit_ids != expected_edit_ids:
            raise ValueError("ARIES candidate edit excerpts differ from alignment evidence")
        return self


class AriesTastePopulationReport(BaseModel):
    """Receipt-bound candidate-population result; never a benchmark admission."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    population_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    request_id: str = Field(pattern=_ID)
    request_file_sha256: str = Field(pattern=_SHA256)
    request_sha256: str = Field(pattern=_SHA256)
    receipt_file_sha256: str = Field(pattern=_SHA256)
    receipt_sha256: str = Field(pattern=_SHA256)
    compiler_implementation_sha256: str = Field(pattern=_SHA256)
    compiled_at: datetime
    candidate_file: Literal["CANDIDATES.jsonl"] = "CANDIDATES.jsonl"
    candidate_file_sha256: str = Field(pattern=_SHA256)
    candidate_count: int = Field(gt=0)
    source_group_count: int = Field(gt=0)
    acquired_document_pair_count: int = Field(gt=0)
    natural_review_row_count: int = Field(gt=0)
    synthetic_review_row_count_excluded: int = Field(ge=0)
    alignment_agreement_count: int = Field(ge=0)
    alignment_disagreement_count: int = Field(ge=0)
    no_aligned_edit_count: int = Field(ge=0)
    split_source_group_counts: dict[Literal["train", "dev", "test"], int]
    source_group_overlap_count: Literal[0] = 0
    target_population_floor: int = Field(default=120, ge=1)
    target_population_floor_met: bool
    domain_count_observed: Literal[1] = 1
    target_domain_count: int = Field(default=3, ge=1)
    target_domain_floor_met: Literal[False] = False
    exact_acquisition_verified: Literal[True] = True
    natural_content_only: Literal[True] = True
    direct_identifiers_removed: Literal[True] = True
    observed_revisions_are_not_quality_labels: Literal[True] = True
    upstream_alignments_are_not_quality_labels: Literal[True] = True
    ready_for_taste_abstraction_review: Literal[True] = True
    ready_for_benchmark_admission: Literal[False] = False
    blockers: tuple[AriesPopulationFinding, ...] = Field(min_length=1)
    verification: VerificationDecision
    standalone_preflight_performed: Literal[False] = False
    inline_integrity_guards_performed: Literal[True] = True
    local_content_read_performed: Literal[True] = True
    network_access_performed: Literal[False] = False
    model_calls_performed: Literal[False] = False
    gpu_work_performed: Literal[False] = False
    experiment_performed: Literal[False] = False
    authorizes_model_calls: Literal[False] = False
    authorizes_experiment: Literal[False] = False
    report_sha256: str = Field(pattern=_SHA256)

    @field_validator("compiled_at")
    @classmethod
    def time_is_aware(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("ARIES population time must include a timezone")
        return value

    @model_validator(mode="after")
    def report_is_closed(self) -> AriesTastePopulationReport:
        if self.candidate_count != self.natural_review_row_count:
            raise ValueError("ARIES candidate count differs from natural review population")
        if self.candidate_count != (
            self.alignment_agreement_count + self.alignment_disagreement_count
        ):
            raise ValueError("ARIES alignment counts do not cover the candidate population")
        if self.target_population_floor_met != (
            self.candidate_count >= self.target_population_floor
        ):
            raise ValueError("ARIES population-floor status is inconsistent")
        if self.source_group_count != self.split_source_group_counts["test"]:
            raise ValueError("ARIES candidate groups must be the held-out test groups")
        if self.verification.route is not VerificationRoute.DIRECT_PATH:
            raise ValueError("local ARIES compilation must use the direct path")
        expected = _sha256_json(self.model_dump(mode="json", exclude={"report_sha256"}))
        if self.report_sha256 != expected:
            raise ValueError("ARIES population report hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> AriesTastePopulationReport:
        payload = {"schema_version": "1.0", **values}
        payload.pop("report_sha256", None)
        unsigned = cls.model_construct(report_sha256="0" * 64, **payload)
        digest = _sha256_json(unsigned.model_dump(mode="json", exclude={"report_sha256"}))
        return cls(**payload, report_sha256=digest)


def materialize_aries_taste_population(
    *,
    approved_request_path: str | Path,
    receipt_path: str | Path,
    workspace_root: str | Path,
    output_directory: str | Path,
    compiled_at: datetime | None = None,
) -> AriesTastePopulationReport:
    """Read the exact local ARIES slice and atomically emit candidate episodes."""

    request_inspection = load_dataset_acquisition_request(approved_request_path)
    receipt_inspection = load_dataset_acquisition_receipt(receipt_path)
    request = request_inspection.request
    receipt = receipt_inspection.receipt
    root = Path(workspace_root).resolve(strict=True)
    _verify_acquisition_chain(request, receipt)
    raw_root = _resolve_raw_root(root, request, receipt)
    paths = _verify_raw_inventory(raw_root, request, receipt)

    verification = decide_verification_route(
        VerificationDecisionInput(
            action_id="compile-local-aries-taste-population",
            reversibility=ActionReversibility.REVERSIBLE,
            effects=(ActionEffect.READ_ONLY_LOCAL, ActionEffect.FILESYSTEM_WRITE),
            evidence_state="current",
            semantic_uncertainty="medium",
            failure_probability=0.08,
            failure_impact_units=8.0,
            targeted_check_cost_units=1.0,
            targeted_detection_probability=0.8,
            full_preflight_cost_units=3.0,
            full_preflight_detection_probability=0.95,
        )
    )
    if verification.route is not VerificationRoute.DIRECT_PATH:
        raise ValueError("ARIES local compilation unexpectedly requires a preflight")

    reviews = _load_jsonl(paths["review_comments"])
    paper_edits = _load_jsonl(paths["paper_edits"])
    labels = _load_jsonl(paths["edit_labels_test"])
    human_labels = _load_jsonl(paths["alignment_human_eval"])
    split_rows = _load_json(paths["split_ids"])
    split_groups = _split_groups(split_rows)
    if any(
        split_groups[left] & split_groups[right]
        for left, right in (("train", "dev"), ("train", "test"), ("dev", "test"))
    ):
        raise ValueError("ARIES source groups overlap across upstream splits")

    natural_reviews, synthetic_count = _natural_reviews(reviews)
    edit_by_doc = _unique_by(paper_edits, "doc_id", label="paper edit")
    label_by_key = _unique_comment_rows(labels, label="primary alignment")
    human_by_key = _deduplicated_human_rows(human_labels)
    natural_by_key = _unique_comment_rows(natural_reviews, label="natural review")
    if set(natural_by_key) != set(label_by_key) or set(natural_by_key) != set(human_by_key):
        raise ValueError("ARIES natural review and alignment populations differ")
    candidate_docs = {doc_id for doc_id, _ in natural_by_key}
    if candidate_docs - split_groups["test"]:
        raise ValueError("ARIES natural review candidates escape the held-out test split")
    if candidate_docs - set(edit_by_doc):
        raise ValueError("ARIES natural review candidate lacks its paper-edit record")

    source_ids = {edit_by_doc[doc_id]["source_pdf_id"] for doc_id in candidate_docs}
    target_ids = {edit_by_doc[doc_id]["target_pdf_id"] for doc_id in candidate_docs}
    s2orc = _load_s2orc_members(paths["s2orc"], source_ids | target_ids)
    candidates: list[AriesTasteCandidate] = []
    for raw_key in sorted(natural_by_key, key=lambda item: (item[0], item[1])):
        doc_id, comment_id = raw_key
        review = natural_by_key[raw_key]
        edit_record = edit_by_doc[doc_id]
        primary_ids = _positive_edit_ids(label_by_key[raw_key], label="primary alignment")
        human_ids = _positive_edit_ids(human_by_key[raw_key], label="human alignment")
        source = s2orc[_required_text(edit_record, "source_pdf_id")]
        target = s2orc[_required_text(edit_record, "target_pdf_id")]
        edits_by_id = _validated_edits(edit_record, source, target)
        visible_ids = tuple(sorted(set(primary_ids) | set(human_ids)))
        try:
            observed_edits = tuple(edits_by_id[edit_id] for edit_id in visible_ids)
        except KeyError as exc:
            raise ValueError("ARIES alignment references an unknown edit") from exc
        candidates.append(
            AriesTasteCandidate(
                candidate_id=_opaque_id(
                    "aries-candidate", receipt.receipt_sha256, doc_id, str(comment_id)
                ),
                source_group_id=canonical_openreview_source_group_id(doc_id),
                paper_context=_clean_text(source["abstract"], maximum=_MAX_CONTEXT_CHARS),
                review_comment=_clean_text(review["comment"], maximum=_MAX_CONTEXT_CHARS),
                observed_edits=observed_edits,
                primary_alignment_edit_ids=primary_ids,
                human_alignment_edit_ids=human_ids,
                alignment_status="agreed" if primary_ids == human_ids else "disagreed",
                observed_response=(
                    "aligned-edit-observed" if observed_edits else "no-aligned-edit-observed"
                ),
            )
        )

    target = Path(output_directory)
    if target.is_symlink() or target.exists():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{target.name}.",
            suffix=".staging",
            dir=target.parent,
        )
    )
    try:
        candidate_bytes = b"".join(
            _canonical_json(item.model_dump(mode="json")) + b"\n" for item in candidates
        )
        _write_new(staging / "CANDIDATES.jsonl", candidate_bytes)
        agreement_count = sum(item.alignment_status == "agreed" for item in candidates)
        report = AriesTastePopulationReport.create(
            population_id="aries-review-edit-taste-candidates-v1",
            project_id=request.project_id,
            request_id=request.request_id,
            request_file_sha256=request_inspection.file_sha256,
            request_sha256=request.request_sha256,
            receipt_file_sha256=receipt_inspection.file_sha256,
            receipt_sha256=receipt.receipt_sha256,
            compiler_implementation_sha256=_implementation_sha256(),
            compiled_at=compiled_at or datetime.now(UTC),
            candidate_file_sha256=hashlib.sha256(candidate_bytes).hexdigest(),
            candidate_count=len(candidates),
            source_group_count=len(candidate_docs),
            acquired_document_pair_count=len(edit_by_doc),
            natural_review_row_count=len(natural_reviews),
            synthetic_review_row_count_excluded=synthetic_count,
            alignment_agreement_count=agreement_count,
            alignment_disagreement_count=len(candidates) - agreement_count,
            no_aligned_edit_count=sum(not item.observed_edits for item in candidates),
            split_source_group_counts={key: len(value) for key, value in split_groups.items()},
            target_population_floor_met=len(candidates) >= 120,
            blockers=(
                AriesPopulationFinding(
                    code="single-domain-source",
                    message=(
                        "ARIES contributes one ML peer-review domain; at least two "
                        "additional domains remain required."
                    ),
                ),
                AriesPopulationFinding(
                    code="independent-quality-labels-pending",
                    message=(
                        "Two conflict-checked blinded reviewers have not judged "
                        "scientific-quality or Taste dimensions."
                    ),
                ),
                AriesPopulationFinding(
                    code="decision-family-stratification-pending",
                    message=(
                        "Review comments still require family and difficulty "
                        "stratification before a formal split can be frozen."
                    ),
                ),
                AriesPopulationFinding(
                    code="privacy-review-pending",
                    message=(
                        "Direct dataset identifiers are hidden, but the projected "
                        "text still requires a release privacy review."
                    ),
                ),
            ),
            verification=verification,
        )
        _write_new(staging / "REPORT.json", report.model_dump_json(indent=2).encode() + b"\n")
        os.rename(staging, target)
        return report
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def load_aries_taste_population_report(path: str | Path) -> AriesTastePopulationReport:
    requested = Path(path)
    if (
        requested.is_symlink()
        or not requested.is_file()
        or requested.stat().st_size > 4 * 1024 * 1024
    ):
        raise ValueError("ARIES population report must be a bounded regular file")
    report = AriesTastePopulationReport.model_validate_json(requested.read_bytes())
    candidate_path = requested.parent / report.candidate_file
    if candidate_path.is_symlink() or not candidate_path.is_file():
        raise ValueError("ARIES population candidate file is unavailable")
    if hashlib.sha256(candidate_path.read_bytes()).hexdigest() != report.candidate_file_sha256:
        raise ValueError("ARIES population candidate file hash mismatch")
    return report


def publish_aries_taste_population_run(
    runtime: ProjectRuntime,
    *,
    project_id: str,
    run_id: str,
    source_report_path: str | Path,
    expected_revision: int,
) -> tuple[ProjectSnapshot, AriesTastePopulationReport]:
    """Register an already compiled local population as project-owned evidence."""

    validate_project_id(project_id)
    validate_entry_id(run_id, field_name="run_id")
    source_report = load_aries_taste_population_report(source_report_path)
    if source_report.project_id != project_id:
        raise ValueError("ARIES population belongs to another project")
    source_directory = Path(source_report_path).resolve(strict=True).parent
    project_root = runtime.projects_root.joinpath(project_id).resolve(strict=True)
    if not source_directory.is_relative_to(project_root):
        raise ValueError("ARIES population source must remain inside its project")

    snapshot = runtime.open(project_id)
    existing = next((item for item in snapshot.manifest.runs if item.run_id == run_id), None)
    artifact = f"runs/{run_id}/{_PROJECT_STAGE}/REPORT.json"
    if existing is not None and existing.status == "complete-taste-candidate-population":
        observed = load_aries_taste_population_report(project_root / artifact)
        if observed.report_sha256 != source_report.report_sha256:
            raise ValueError("registered ARIES population differs from its source")
        return snapshot, observed
    if existing is None:
        if snapshot.revision != expected_revision:
            raise ValueError("ARIES population publication uses a stale project revision")
        snapshot = runtime.begin_run(
            project_id,
            ProjectRun(
                run_id=run_id,
                provider="scitaste-native",
                model="aries-review-edit-population-compiler-v1",
                condition="scientific-taste-natural-reference-population",
                seed=0,
                status="preparing-taste-candidate-population",
                evidence_scope=(
                    "receipt-bound-natural-review-revision-candidates-not-quality-labels"
                ),
                stage_path=_PROJECT_STAGE,
                artifact=artifact,
                generative_ui_projection=_PROJECT_PROJECTION,
                population_id=source_report.population_id,
                source_request_sha256=source_report.request_sha256,
                source_receipt_sha256=source_report.receipt_sha256,
                authorizes_model_calls=False,
                authorizes_experiment=False,
                no_model_call_performed=True,
                no_gpu_work_performed=True,
                no_experiment_performed=True,
            ),
            expected_revision=expected_revision,
        )
    elif existing.status != "preparing-taste-candidate-population":
        raise ValueError("ARIES population run cannot be resumed from its current state")

    stage = project_root / "runs" / run_id / _PROJECT_STAGE
    target_report = stage / "REPORT.json"
    target_candidates = stage / source_report.candidate_file
    if not target_report.exists() and not target_candidates.exists():
        _write_new(
            target_candidates,
            (source_directory / source_report.candidate_file).read_bytes(),
        )
        _write_new(target_report, Path(source_report_path).read_bytes())
    observed = load_aries_taste_population_report(target_report)
    if observed.report_sha256 != source_report.report_sha256:
        raise ValueError("published ARIES population differs from its compiled source")
    snapshot = runtime.update_run(
        project_id,
        run_id,
        expected_revision=snapshot.revision,
        status="complete-taste-candidate-population",
        population_report_sha256=observed.report_sha256,
        candidate_file_sha256=observed.candidate_file_sha256,
        candidate_count=observed.candidate_count,
        source_group_count=observed.source_group_count,
        ready_for_taste_abstraction_review=observed.ready_for_taste_abstraction_review,
        ready_for_benchmark_admission=observed.ready_for_benchmark_admission,
        blocker_codes=[item.code for item in observed.blockers],
        verification_route=observed.verification.route.value,
        standalone_preflight_performed=observed.standalone_preflight_performed,
        inline_integrity_guards_performed=observed.inline_integrity_guards_performed,
    )
    return snapshot, observed


def _verify_acquisition_chain(
    request: DatasetAcquisitionRequest,
    receipt: DatasetAcquisitionReceipt,
) -> None:
    if request.request_id != _EXPECTED_REQUEST_ID:
        raise ValueError("ARIES compiler requires its exact acquisition request")
    if (
        not request.approval.approved
        or request.approval.request_sha256 != request.request_sha256
        or request.approval.scope != "download-only-no-ingestion"
        or receipt.request_id != request.request_id
        or receipt.request_sha256 != request.request_sha256
        or receipt.approved_by != request.approval.approved_by
        or receipt.approved_at != request.approval.approved_at
        or receipt.destination_root != request.destination_root
    ):
        raise ValueError("ARIES request and receipt chain is invalid")
    request_items = {item.item_id: item for item in request.items}
    receipt_items = {item.item_id: item for item in receipt.items}
    if set(request_items) != set(_EXPECTED_ITEMS) or set(receipt_items) != set(_EXPECTED_ITEMS):
        raise ValueError("ARIES acquisition inventory differs from the compiler contract")
    for item_id, destination in _EXPECTED_ITEMS.items():
        requested = request_items[item_id]
        received = receipt_items[item_id]
        if (
            requested.destination != destination
            or received.destination != destination
            or received.source_url != requested.source_url
            or received.source_revision != requested.source_revision
            or received.expected_http_etag != requested.expected_http_etag
            or received.expected_sha256 != requested.expected_sha256
        ):
            raise ValueError(f"ARIES acquisition binding differs for {item_id}")


def _resolve_raw_root(
    root: Path,
    request: DatasetAcquisitionRequest,
    receipt: DatasetAcquisitionReceipt,
) -> Path:
    candidate = root.joinpath(*PurePosixPath(receipt.destination_root).parts)
    if candidate.is_symlink() or not candidate.is_dir():
        raise ValueError("ARIES raw acquisition directory is unavailable")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(root) or receipt.destination_root != request.destination_root:
        raise ValueError("ARIES raw acquisition directory escapes the workspace")
    return resolved


def _verify_raw_inventory(
    raw_root: Path,
    request: DatasetAcquisitionRequest,
    receipt: DatasetAcquisitionReceipt,
) -> dict[str, Path]:
    requested = {item.item_id: item for item in request.items}
    received = {item.item_id: item for item in receipt.items}
    paths: dict[str, Path] = {}
    for item_id, relative in _EXPECTED_ITEMS.items():
        request_item = requested[item_id]
        receipt_item = received[item_id]
        path = raw_root.joinpath(*PurePosixPath(relative).parts)
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(raw_root):
            raise ValueError(f"ARIES raw item is unavailable: {item_id}")
        raw = path.read_bytes()
        if (
            len(raw) != receipt_item.size_bytes
            or hashlib.sha256(raw).hexdigest() != receipt_item.sha256
        ):
            raise ValueError(f"ARIES raw item differs from its receipt: {item_id}")
        if len(raw) > request_item.maximum_bytes:
            raise ValueError(f"ARIES raw item exceeds its approved ceiling: {item_id}")
        paths[item_id] = path
    observed = {
        path.relative_to(raw_root).as_posix()
        for path in raw_root.rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    if observed != set(_EXPECTED_ITEMS.values()):
        raise ValueError("ARIES raw directory contains missing or unregistered files")
    return paths


def _load_jsonl(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with path.open("rb") as handle:
        for line_number, raw in enumerate(handle, start=1):
            if line_number > _MAX_JSON_ROWS or len(raw) > _MAX_JSONL_LINE_BYTES:
                raise ValueError(f"ARIES JSONL bounds exceeded: {path.name}")
            value = _parse_json(raw)
            if not isinstance(value, dict):
                raise ValueError(f"ARIES JSONL row must be an object: {path.name}")
            rows.append(value)
    if not rows:
        raise ValueError(f"ARIES JSONL file is empty: {path.name}")
    return rows


def _load_json(path: Path) -> object:
    if path.stat().st_size > _MAX_JSONL_LINE_BYTES:
        raise ValueError("ARIES JSON file exceeds its read bound")
    return _parse_json(path.read_bytes())


def _parse_json(raw: bytes) -> object:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"duplicate JSON key: {key}")
            value[key] = item
        return value

    try:
        return json.loads(raw, object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("ARIES source contains invalid JSON") from exc


def _split_groups(value: object) -> dict[str, set[str]]:
    if not isinstance(value, dict) or set(value) != {"train", "dev", "test"}:
        raise ValueError("ARIES split inventory must contain train, dev, and test")
    result: dict[str, set[str]] = {}
    for split, rows in value.items():
        if not isinstance(rows, list):
            raise ValueError("ARIES split rows must be a list")
        identifiers: list[str] = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("ARIES split row must be an object")
            identifiers.append(_required_text(row, "doc_id"))
            _required_text(row, "source_pdf_id")
            _required_text(row, "target_pdf_id")
        if len(identifiers) != len(set(identifiers)):
            raise ValueError(f"ARIES {split} split contains duplicate source groups")
        result[split] = set(identifiers)
    return result


def _natural_reviews(rows: list[dict[str, object]]) -> tuple[list[dict[str, object]], int]:
    natural: list[dict[str, object]] = []
    synthetic = 0
    for row in rows:
        annotation = _required_text(row, "annotation")
        _required_text(row, "doc_id")
        _required_int(row, "comment_id")
        _required_text(row, "comment")
        if annotation == "manual":
            natural.append(row)
        elif annotation == "synthetic":
            synthetic += 1
        else:
            raise ValueError("ARIES review uses an unknown annotation source")
    if not natural:
        raise ValueError("ARIES source contains no natural review decisions")
    return natural, synthetic


def _unique_by(
    rows: list[dict[str, object]],
    key: str,
    *,
    label: str,
) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for row in rows:
        value = _required_text(row, key)
        if value in result:
            raise ValueError(f"ARIES {label} identity is duplicated")
        result[value] = row
    return result


def _unique_comment_rows(
    rows: list[dict[str, object]],
    *,
    label: str,
) -> dict[tuple[str, int], dict[str, object]]:
    result: dict[tuple[str, int], dict[str, object]] = {}
    for row in rows:
        key = (_required_text(row, "doc_id"), _required_int(row, "comment_id"))
        if key in result:
            raise ValueError(f"ARIES {label} identity is duplicated")
        result[key] = row
    return result


def _deduplicated_human_rows(
    rows: list[dict[str, object]],
) -> dict[tuple[str, int], dict[str, object]]:
    grouped: dict[tuple[str, int], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        if _required_text(row, "annotation") != "human_eval":
            raise ValueError("ARIES human alignment row has an unknown annotation source")
        grouped[(_required_text(row, "doc_id"), _required_int(row, "comment_id"))].append(row)
    result: dict[tuple[str, int], dict[str, object]] = {}
    for key, values in grouped.items():
        canonical = {_canonical_json(value) for value in values}
        if len(canonical) != 1:
            raise ValueError("ARIES human alignment duplicate rows disagree")
        result[key] = values[0]
    return result


def _positive_edit_ids(row: dict[str, object], *, label: str) -> tuple[int, ...]:
    values = row.get("positive_edits")
    if not isinstance(values, list) or any(type(value) is not int or value < 0 for value in values):
        raise ValueError(f"ARIES {label} positive edits must be non-negative integers")
    if len(values) != len(set(values)):
        raise ValueError(f"ARIES {label} positive edits must be unique")
    return tuple(sorted(values))


def _load_s2orc_members(path: Path, required_ids: set[str]) -> dict[str, dict[str, object]]:
    loaded: dict[str, dict[str, object]] = {}
    expanded_bytes = 0
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        if len(members) > _MAX_TAR_MEMBERS:
            raise ValueError("ARIES S2ORC archive exceeds its member limit")
        for member in members:
            pure = PurePosixPath(member.name)
            if pure.is_absolute() or ".." in pure.parts or member.issym() or member.islnk():
                raise ValueError("ARIES S2ORC archive contains an unsafe member")
            if member.isfile():
                expanded_bytes += member.size
        if expanded_bytes > _MAX_TAR_EXPANDED_BYTES:
            raise ValueError("ARIES S2ORC archive exceeds its expanded-byte limit")
        members_by_name = {member.name: member for member in members if member.isfile()}
        for pdf_id in required_ids:
            name = f"s2orc/{pdf_id}.json"
            member = members_by_name.get(name)
            if member is None or member.size > _MAX_S2ORC_MEMBER_BYTES:
                raise ValueError("ARIES S2ORC document member is unavailable or oversized")
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError("ARIES S2ORC document member cannot be read")
            value = _parse_json(stream.read(_MAX_S2ORC_MEMBER_BYTES + 1))
            if not isinstance(value, dict) or value.get("paper_id") != pdf_id:
                raise ValueError("ARIES S2ORC paper identity differs from its archive member")
            abstract = value.get("abstract")
            parse = value.get("pdf_parse")
            if not isinstance(abstract, str) or not abstract.strip() or not isinstance(parse, dict):
                raise ValueError("ARIES S2ORC document lacks abstract or parse data")
            body = parse.get("body_text")
            if not isinstance(body, list) or any(
                not isinstance(row, dict) or not isinstance(row.get("text"), str) for row in body
            ):
                raise ValueError("ARIES S2ORC body text is invalid")
            loaded[pdf_id] = value
    if set(loaded) != required_ids:
        raise ValueError("ARIES S2ORC archive did not yield every required paper version")
    return loaded


def _validated_edits(
    record: dict[str, object],
    source: dict[str, object],
    target: dict[str, object],
) -> dict[int, AriesObservedEdit]:
    raw_edits = record.get("edits")
    if not isinstance(raw_edits, list):
        raise ValueError("ARIES paper edit inventory must be a list")
    source_body = source["pdf_parse"]["body_text"]  # type: ignore[index]
    target_body = target["pdf_parse"]["body_text"]  # type: ignore[index]
    assert isinstance(source_body, list) and isinstance(target_body, list)
    result: dict[int, AriesObservedEdit] = {}
    for raw in raw_edits:
        if not isinstance(raw, dict):
            raise ValueError("ARIES paper edit must be an object")
        edit_id = _required_int(raw, "edit_id")
        source_indices = _indices(raw, "source_idxs", len(source_body))
        target_indices = _indices(raw, "target_idxs", len(target_body))
        if edit_id in result:
            raise ValueError("ARIES paper edit identity is duplicated")
        result[edit_id] = AriesObservedEdit(
            edit_id=edit_id,
            source_paragraph_indices=source_indices,
            target_paragraph_indices=target_indices,
            source_text=_paragraph_text(source_body, source_indices),
            target_text=_paragraph_text(target_body, target_indices),
        )
    return result


def _indices(row: dict[str, object], key: str, size: int) -> tuple[int, ...]:
    values = row.get(key)
    if not isinstance(values, list) or any(type(value) is not int for value in values):
        raise ValueError(f"ARIES {key} must be integer indices")
    if len(values) != len(set(values)) or any(value < 0 or value >= size for value in values):
        raise ValueError(f"ARIES {key} contains duplicate or out-of-range indices")
    return tuple(values)


def _paragraph_text(rows: list[object], indices: tuple[int, ...]) -> str:
    text = "\n\n".join(str(rows[index]["text"]).strip() for index in indices)  # type: ignore[index]
    return _clean_text(text, maximum=_MAX_EDIT_TEXT_CHARS, allow_empty=True)


def _required_text(row: dict[str, object], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"ARIES field {key} must be non-empty text")
    return value.strip()


def _required_int(row: dict[str, object], key: str) -> int:
    value = row.get(key)
    if type(value) is not int or value < 0:
        raise ValueError(f"ARIES field {key} must be a non-negative integer")
    return value


def _clean_text(value: object, *, maximum: int, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError("ARIES projected text must be a string")
    cleaned = " ".join(_EMAIL.sub("[redacted-email]", value).split())[:maximum].strip()
    if not cleaned and not allow_empty:
        raise ValueError("ARIES projected text cannot be empty")
    return cleaned


def _opaque_id(prefix: str, *values: str) -> str:
    digest = hashlib.sha256("\x1f".join(values).encode()).hexdigest()[:24]
    return f"{prefix}-{digest}"


def _implementation_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _write_new(path: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


__all__ = [
    "AriesObservedEdit",
    "AriesPopulationFinding",
    "AriesTasteCandidate",
    "AriesTastePopulationReport",
    "load_aries_taste_population_report",
    "materialize_aries_taste_population",
    "publish_aries_taste_population_run",
]
