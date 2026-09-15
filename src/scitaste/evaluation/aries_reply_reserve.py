"""Compile source-group-disjoint ARIES review/reply validation candidates.

The released ARIES test alignment is useful development evidence, but it is too
small to support both repeated calibration and an independent validation set.
This module uses a separately acquired official ``review_replies.jsonl`` object
to select natural review/author-response trajectories from the upstream dev
split.  The association is explicitly heuristic and is never represented as a
human label or a scientifically correct action.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scitaste.evaluation.acquisition import (
    DatasetAcquisitionReceipt,
    DatasetAcquisitionRequest,
    load_dataset_acquisition_receipt,
    load_dataset_acquisition_request,
)
from scitaste.evaluation.aries_population import _load_s2orc_members
from scitaste.evaluation.source_identity import canonical_openreview_source_group_id
from scitaste.project.models import content_sha256

_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_BASE_REQUEST_ID = "aries-review-edit-population-v1"
_REPLY_REQUEST_ID = "aries-validation-reserve-v1"
_POPULATION_ID = "aries-dev-review-reply-validation-reserve-v1"
_SELECTION_SALT = "aries-validation-reserve-v1-20260915"
_DEFAULT_TARGET_GROUPS = 7
_MAX_JSON_LINE_BYTES = 4 * 1024 * 1024
_MAX_TEXT_CHARS = 8_000

AriesReplyReserveBlocker = Literal[
    "independent-ai-quality-review-pending",
    "independent-ai-privacy-review-pending",
    "heuristic-reply-to-edit-provenance",
    "validation-execution-pending",
]


class AriesReplyReserveCandidate(BaseModel):
    """One de-identified natural review/reply trajectory from the ARIES dev split."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    candidate_id: str = Field(pattern=_ID)
    source_group_id: str = Field(pattern=_ID)
    source_split: Literal["dev"] = "dev"
    source_domain: Literal["computing"] = "computing"
    decision_family: Literal["review-guided-revision"] = "review-guided-revision"
    article_title: Literal["De-identified computing manuscript"] = (
        "De-identified computing manuscript"
    )
    reviewed_abstract: str = Field(min_length=1, max_length=_MAX_TEXT_CHARS)
    revised_abstract: str = Field(min_length=1, max_length=_MAX_TEXT_CHARS)
    review_comment: str = Field(min_length=1, max_length=_MAX_TEXT_CHARS)
    author_response: str = Field(min_length=1, max_length=_MAX_TEXT_CHARS)
    observed_edit_count: int = Field(ge=0)
    natural_public_review: Literal[True] = True
    natural_public_author_response: Literal[True] = True
    reply_to_edit_association: Literal["heuristic"] = "heuristic"
    heuristic_association_is_not_human_gold: Literal[True] = True
    observed_response_is_not_preferred_action: Literal[True] = True
    observed_revision_is_not_scientific_quality: Literal[True] = True
    author_identity_hidden: Literal[True] = True
    reviewer_identity_hidden: Literal[True] = True
    source_document_identity_hidden: Literal[True] = True


class AriesReplyReservePrivateMapItem(BaseModel):
    """Project-private raw identities that never enter model-visible candidates."""

    model_config = _CONFIG

    candidate_id: str = Field(pattern=_ID)
    source_group_id: str = Field(pattern=_ID)
    raw_forum_id: str = Field(min_length=1, max_length=200)
    raw_review_id: str = Field(min_length=1, max_length=200)
    raw_response_id: str = Field(min_length=1, max_length=200)
    source_pdf_id: str = Field(min_length=1, max_length=200)
    target_pdf_id: str = Field(min_length=1, max_length=200)


class AriesReplyReserveReport(BaseModel):
    """Content-addressed population receipt; it grants no experiment authority."""

    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1"] = "1.0"
    population_id: str = Field(default=_POPULATION_ID, pattern=_ID)
    project_id: str = Field(pattern=_ID)
    base_request_file_sha256: str = Field(pattern=_SHA256)
    base_request_sha256: str = Field(pattern=_SHA256)
    base_receipt_file_sha256: str = Field(pattern=_SHA256)
    base_receipt_sha256: str = Field(pattern=_SHA256)
    reply_request_file_sha256: str = Field(pattern=_SHA256)
    reply_request_sha256: str = Field(pattern=_SHA256)
    reply_receipt_file_sha256: str = Field(pattern=_SHA256)
    reply_receipt_sha256: str = Field(pattern=_SHA256)
    compiler_implementation_sha256: str = Field(pattern=_SHA256)
    compiled_at: datetime
    candidate_file: Literal["CANDIDATES.jsonl"] = "CANDIDATES.jsonl"
    candidate_file_sha256: str = Field(pattern=_SHA256)
    private_map_file: Literal["PRIVATE_SOURCE_MAP.json"] = "PRIVATE_SOURCE_MAP.json"
    private_map_file_sha256: str = Field(pattern=_SHA256)
    origin_split: Literal["dev"] = "dev"
    selection_algorithm: Literal["sha256-ranked-source-group-and-review-v1"] = (
        "sha256-ranked-source-group-and-review-v1"
    )
    selection_salt_sha256: str = Field(pattern=_SHA256)
    target_source_group_count: int = Field(default=7, ge=1, le=100_000)
    eligible_source_group_count: int = Field(ge=1)
    eligible_review_row_count: int = Field(ge=1)
    candidate_count: int = Field(default=7, ge=1, le=100_000)
    source_group_count: int = Field(default=7, ge=1, le=100_000)
    maximum_items_per_source_group: Literal[1] = 1
    source_group_overlap_with_upstream_test: Literal[0] = 0
    exact_acquisition_verified: Literal[True] = True
    deterministic_selection_verified: Literal[True] = True
    structured_identities_removed_from_candidates: Literal[True] = True
    heuristic_reply_to_edit_association: Literal[True] = True
    human_alignment_created: Literal[False] = False
    human_review_performed: Literal[False] = False
    model_calls_performed: Literal[False] = False
    gpu_work_performed: Literal[False] = False
    experiment_performed: Literal[False] = False
    ready_for_ai_source_review: Literal[True] = True
    ready_for_benchmark_admission: Literal[False] = False
    authorizes_model_calls: Literal[False] = False
    authorizes_experiment: Literal[False] = False
    blockers: tuple[AriesReplyReserveBlocker, ...] = Field(min_length=4, max_length=4)
    report_sha256: str = Field(pattern=_SHA256)

    @field_validator("compiled_at")
    @classmethod
    def time_is_aware(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("ARIES reply reserve time must include a timezone")
        return value

    @model_validator(mode="after")
    def report_is_closed(self) -> AriesReplyReserveReport:
        if (
            self.candidate_count != self.target_source_group_count
            or self.source_group_count != self.target_source_group_count
            or self.eligible_source_group_count < self.target_source_group_count
            or self.eligible_review_row_count < self.target_source_group_count
        ):
            raise ValueError("ARIES reply reserve counts are inconsistent")
        if self.schema_version == "1.0" and (
            self.population_id != _POPULATION_ID
            or self.target_source_group_count != _DEFAULT_TARGET_GROUPS
        ):
            raise ValueError("ARIES reply reserve schema 1.0 identity drifted")
        if self.schema_version == "1.1" and self.population_id != (
            f"aries-dev-review-reply-validation-reserve-"
            f"{self.target_source_group_count}-v2"
        ):
            raise ValueError("ARIES reply reserve schema 1.1 identity drifted")
        if len(set(self.blockers)) != 4:
            raise ValueError("ARIES reply reserve blockers must be complete and unique")
        expected = content_sha256(self.model_dump(mode="json", exclude={"report_sha256"}))
        if self.report_sha256 != expected:
            raise ValueError("ARIES reply reserve report hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> AriesReplyReserveReport:
        payload = {"schema_version": "1.0", **values}
        payload.pop("report_sha256", None)
        unsigned = cls.model_construct(report_sha256="0" * 64, **payload)
        return cls(
            **payload,
            report_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"report_sha256"})
            ),
        )


def materialize_aries_reply_validation_reserve(
    *,
    base_request_path: str | Path,
    base_receipt_path: str | Path,
    reply_request_path: str | Path,
    reply_receipt_path: str | Path,
    workspace_root: str | Path,
    output_directory: str | Path,
    target_source_group_count: int = _DEFAULT_TARGET_GROUPS,
    compiled_at: datetime | None = None,
) -> AriesReplyReserveReport:
    """Select ranked dev trajectories and publish an immutable local population."""

    if not 1 <= target_source_group_count <= 100_000:
        raise ValueError("ARIES reserve target source-group count is out of bounds")

    root = Path(workspace_root).resolve(strict=True)
    base_request_inspection = load_dataset_acquisition_request(base_request_path)
    base_receipt_inspection = load_dataset_acquisition_receipt(base_receipt_path)
    reply_request_inspection = load_dataset_acquisition_request(reply_request_path)
    reply_receipt_inspection = load_dataset_acquisition_receipt(reply_receipt_path)
    base_request = base_request_inspection.request
    base_receipt = base_receipt_inspection.receipt
    reply_request = reply_request_inspection.request
    reply_receipt = reply_receipt_inspection.receipt
    _verify_request_receipt(base_request, base_receipt, expected_request_id=_BASE_REQUEST_ID)
    _verify_request_receipt(reply_request, reply_receipt, expected_request_id=_REPLY_REQUEST_ID)
    if base_request.project_id != reply_request.project_id:
        raise ValueError("ARIES reserve acquisitions belong to different projects")

    base_files = _verified_acquisition_files(root, base_request, base_receipt)
    reply_files = _verified_acquisition_files(root, reply_request, reply_receipt)
    required_base = {"split_ids", "paper_edits", "s2orc"}
    if not required_base.issubset(base_files) or set(reply_files) != {"review_replies"}:
        raise ValueError("ARIES reserve acquisition inventory is incomplete")

    split_payload = json.loads(base_files["split_ids"].read_bytes())
    if not isinstance(split_payload, dict) or set(split_payload) != {"train", "dev", "test"}:
        raise ValueError("ARIES reserve split inventory is invalid")
    split_groups = {
        split: {_required_text(row, "doc_id") for row in rows}
        for split, rows in split_payload.items()
    }
    if any(
        split_groups[left] & split_groups[right]
        for left, right in (("train", "dev"), ("train", "test"), ("dev", "test"))
    ):
        raise ValueError("ARIES reserve upstream splits overlap")

    edits = {
        _required_text(row, "doc_id"): row
        for row in _read_jsonl(base_files["paper_edits"])
    }
    eligible: dict[str, list[dict[str, object]]] = defaultdict(list)
    eligible_rows = 0
    for row in _read_jsonl(reply_files["review_replies"]):
        forum = _optional_text(row.get("forum"))
        content = row.get("content")
        replies = row.get("author_replies")
        if (
            forum not in split_groups["dev"]
            or forum not in edits
            or not isinstance(content, dict)
            or not _optional_text(content.get("review"))
            or not isinstance(replies, list)
        ):
            continue
        usable_replies = [item for item in replies if _response_text(item)]
        if not usable_replies:
            continue
        normalized = dict(row)
        normalized["author_replies"] = usable_replies
        eligible[forum].append(normalized)
        eligible_rows += 1
    if len(eligible) < target_source_group_count:
        raise ValueError("ARIES reply reserve lacks enough eligible dev source groups")

    ranked_forums = sorted(
        eligible,
        key=lambda forum: (
            _rank(_SELECTION_SALT, canonical_openreview_source_group_id(forum)),
            canonical_openreview_source_group_id(forum),
        ),
    )[:target_source_group_count]
    selected_rows: list[tuple[str, dict[str, object], dict[str, object]]] = []
    for forum in ranked_forums:
        group = canonical_openreview_source_group_id(forum)
        review = min(
            eligible[forum],
            key=lambda row: (
                _rank(_SELECTION_SALT, group, _required_text(row, "id")),
                _required_text(row, "id"),
            ),
        )
        replies = review["author_replies"]
        assert isinstance(replies, list)
        response = min(
            replies,
            key=lambda row: (
                _rank(
                    _SELECTION_SALT,
                    group,
                    _required_text(review, "id"),
                    _required_text(row, "id"),
                ),
                _required_text(row, "id"),
            ),
        )
        selected_rows.append((forum, review, response))

    pdf_ids = {
        _required_text(edits[forum], key)
        for forum, _, _ in selected_rows
        for key in ("source_pdf_id", "target_pdf_id")
    }
    documents = _load_s2orc_members(base_files["s2orc"], pdf_ids)
    candidates: list[AriesReplyReserveCandidate] = []
    private_items: list[AriesReplyReservePrivateMapItem] = []
    for forum, review, response in selected_rows:
        edit = edits[forum]
        source_pdf_id = _required_text(edit, "source_pdf_id")
        target_pdf_id = _required_text(edit, "target_pdf_id")
        group = canonical_openreview_source_group_id(forum)
        review_id = _required_text(review, "id")
        response_id = _required_text(response, "id")
        candidate_id = "aries-reply-candidate-" + _rank(
            reply_receipt.receipt_sha256,
            base_receipt.receipt_sha256,
            forum,
            review_id,
            response_id,
        )[:24]
        review_content = review["content"]
        assert isinstance(review_content, dict)
        raw_edits = edit.get("edits")
        if not isinstance(raw_edits, list):
            raise ValueError("ARIES reserve paper edit inventory is invalid")
        candidates.append(
            AriesReplyReserveCandidate(
                candidate_id=candidate_id,
                source_group_id=group,
                reviewed_abstract=_clean_text(documents[source_pdf_id].get("abstract")),
                revised_abstract=_clean_text(documents[target_pdf_id].get("abstract")),
                review_comment=_clean_text(review_content.get("review")),
                author_response=_clean_text(_response_text(response)),
                observed_edit_count=len(raw_edits),
            )
        )
        private_items.append(
            AriesReplyReservePrivateMapItem(
                candidate_id=candidate_id,
                source_group_id=group,
                raw_forum_id=forum,
                raw_review_id=review_id,
                raw_response_id=response_id,
                source_pdf_id=source_pdf_id,
                target_pdf_id=target_pdf_id,
            )
        )

    candidates.sort(key=lambda item: item.candidate_id)
    private_items.sort(key=lambda item: item.candidate_id)
    candidate_bytes = b"".join(
        _canonical_json(item.model_dump(mode="json")) + b"\n" for item in candidates
    )
    private_bytes = _canonical_json(
        {
            "schema_version": "1.0",
            "private": True,
            "items": [item.model_dump(mode="json") for item in private_items],
        }
    ) + b"\n"
    target = Path(output_directory)
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{target.name}.", suffix=".staging", dir=target.parent)
    )
    try:
        _write_new(staging / "CANDIDATES.jsonl", candidate_bytes)
        _write_new(staging / "PRIVATE_SOURCE_MAP.json", private_bytes)
        report = AriesReplyReserveReport.create(
            schema_version=("1.0" if target_source_group_count == 7 else "1.1"),
            population_id=(
                _POPULATION_ID
                if target_source_group_count == 7
                else f"aries-dev-review-reply-validation-reserve-"
                f"{target_source_group_count}-v2"
            ),
            project_id=base_request.project_id,
            base_request_file_sha256=base_request_inspection.file_sha256,
            base_request_sha256=base_request.request_sha256,
            base_receipt_file_sha256=base_receipt_inspection.file_sha256,
            base_receipt_sha256=base_receipt.receipt_sha256,
            reply_request_file_sha256=reply_request_inspection.file_sha256,
            reply_request_sha256=reply_request.request_sha256,
            reply_receipt_file_sha256=reply_receipt_inspection.file_sha256,
            reply_receipt_sha256=reply_receipt.receipt_sha256,
            compiler_implementation_sha256=_sha256_file(Path(__file__)),
            compiled_at=compiled_at or datetime.now(UTC),
            candidate_file_sha256=hashlib.sha256(candidate_bytes).hexdigest(),
            private_map_file_sha256=hashlib.sha256(private_bytes).hexdigest(),
            selection_salt_sha256=hashlib.sha256(_SELECTION_SALT.encode()).hexdigest(),
            eligible_source_group_count=len(eligible),
            eligible_review_row_count=eligible_rows,
            target_source_group_count=target_source_group_count,
            candidate_count=target_source_group_count,
            source_group_count=target_source_group_count,
            blockers=(
                "independent-ai-quality-review-pending",
                "independent-ai-privacy-review-pending",
                "heuristic-reply-to-edit-provenance",
                "validation-execution-pending",
            ),
        )
        _write_new(staging / "REPORT.json", report.model_dump_json(indent=2).encode() + b"\n")
        os.rename(staging, target)
        return report
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def load_aries_reply_reserve_report(path: str | Path) -> AriesReplyReserveReport:
    source = Path(path)
    if source.is_symlink() or not source.is_file() or source.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("ARIES reply reserve report must be a bounded regular file")
    report = AriesReplyReserveReport.model_validate_json(source.read_bytes())
    root = source.parent
    if _sha256_file(root / report.candidate_file) != report.candidate_file_sha256:
        raise ValueError("ARIES reply reserve candidates changed")
    if _sha256_file(root / report.private_map_file) != report.private_map_file_sha256:
        raise ValueError("ARIES reply reserve private map changed")
    return report


def _verify_request_receipt(
    request: DatasetAcquisitionRequest,
    receipt: DatasetAcquisitionReceipt,
    *,
    expected_request_id: str,
) -> None:
    if request.request_id != expected_request_id or receipt.request_id != expected_request_id:
        raise ValueError("ARIES reserve acquisition identity differs")
    if request.request_sha256 != receipt.request_sha256:
        raise ValueError("ARIES reserve request and receipt hashes differ")
    if request.destination_root != receipt.destination_root:
        raise ValueError("ARIES reserve destination differs from its receipt")
    if (
        not receipt.acquisition_complete
        or receipt.authorizes_ingestion
        or receipt.authorizes_execution
    ):
        raise ValueError("ARIES reserve receipt has invalid authority")


def _verified_acquisition_files(
    root: Path,
    request: DatasetAcquisitionRequest,
    receipt: DatasetAcquisitionReceipt,
) -> dict[str, Path]:
    raw_root = root.joinpath(*Path(receipt.destination_root).parts).resolve(strict=True)
    if not raw_root.is_relative_to(root):
        raise ValueError("ARIES reserve acquisition escaped the workspace")
    request_items = {item.item_id: item for item in request.items}
    receipt_items = {item.item_id: item for item in receipt.items}
    if set(request_items) != set(receipt_items):
        raise ValueError("ARIES reserve receipt inventory differs")
    result: dict[str, Path] = {}
    for item_id, acquired in receipt_items.items():
        path = (raw_root / acquired.destination).resolve(strict=True)
        if not path.is_relative_to(raw_root) or path.is_symlink() or not path.is_file():
            raise ValueError("ARIES reserve acquired file is unavailable")
        if path.stat().st_size != acquired.size_bytes or _sha256_file(path) != acquired.sha256:
            raise ValueError("ARIES reserve acquired bytes changed")
        result[item_id] = path
    return result


def _read_jsonl(path: Path):  # type: ignore[no-untyped-def]
    with path.open("rb") as handle:
        for line_number, raw in enumerate(handle, 1):
            if len(raw) > _MAX_JSON_LINE_BYTES:
                raise ValueError(f"ARIES reserve JSONL line {line_number} exceeds its bound")
            try:
                value = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError(f"ARIES reserve JSONL line {line_number} is invalid") from exc
            if not isinstance(value, dict):
                raise ValueError("ARIES reserve JSONL rows must be objects")
            yield value


def _response_text(value: object) -> str:
    if not isinstance(value, dict):
        return ""
    content = value.get("content")
    if not isinstance(content, dict):
        return ""
    return _optional_text(content.get("comment"))


def _required_text(row: object, key: str) -> str:
    if not isinstance(row, dict):
        raise ValueError("ARIES reserve row must be an object")
    value = _optional_text(row.get(key))
    if not value:
        raise ValueError(f"ARIES reserve field {key} must be non-empty text")
    return value


def _optional_text(value: object) -> str:
    if isinstance(value, dict) and set(value) >= {"value"}:
        value = value["value"]
    return value.strip() if isinstance(value, str) else ""


def _clean_text(value: object) -> str:
    text = " ".join(_optional_text(value).split())
    if not text:
        raise ValueError("ARIES reserve projected text is empty")
    return text[:_MAX_TEXT_CHARS]


def _rank(*values: str) -> str:
    return hashlib.sha256("\0".join(values).encode()).hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_new(path: Path, data: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


__all__ = [
    "AriesReplyReserveCandidate",
    "AriesReplyReservePrivateMapItem",
    "AriesReplyReserveReport",
    "load_aries_reply_reserve_report",
    "materialize_aries_reply_validation_reserve",
]
