"""Deterministic, quarantine-first projections of external corpus records."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import Any


class CurationFormat(StrEnum):
    ARIES_ALIGNMENT = "aries-alignment"
    CASIMIR_MAPPING = "casimir-mapping"
    CASIMIR_METADATA = "casimir-metadata"


def curate_snapshot(
    source_format: CurationFormat | str,
    input_path: str | Path,
    output_dir: str | Path,
    *,
    limit: int | None = None,
    write: bool = True,
) -> dict[str, Any]:
    """Project source records into ingestion inputs without granting retrieval trust."""

    format_value = CurationFormat(source_format)
    if limit is not None and limit < 1:
        raise ValueError("curation limit must be positive")
    source = Path(input_path).resolve()
    records = _load_jsonl(source, limit=limit)
    projector: Callable[[dict[str, Any]], dict[str, Any]] = {
        CurationFormat.ARIES_ALIGNMENT: _curate_aries_alignment,
        CurationFormat.CASIMIR_MAPPING: _curate_casimir_mapping,
        CurationFormat.CASIMIR_METADATA: _curate_casimir_metadata,
    }[format_value]
    curated: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for index, record in enumerate(records, 1):
        try:
            curated.append(projector(record))
        except (TypeError, ValueError) as exc:
            rejected.append({"record_index": index, "reason": str(exc)[:500]})
    root = Path(output_dir)
    records_path = root / "curated_records.jsonl"
    report_path = root / "curation_manifest.json"
    report: dict[str, Any] = {
        "schema_version": "1.0",
        "source_format": format_value.value,
        "source_path": str(source),
        "input_record_count": len(records),
        "curated_record_count": len(curated),
        "rejected_count": len(rejected),
        "retrieval_eligible_count": sum(
            bool(record.get("retrieval_eligible")) for record in curated
        ),
        "records_path": str(records_path),
        "rejections": rejected,
    }
    if write:
        _atomic_jsonl(records_path, curated)
        _atomic_json(report_path, report)
    return report


def _curate_aries_alignment(raw: dict[str, Any]) -> dict[str, Any]:
    doc_id = _required_text(raw, "doc_id")
    comment_id = raw.get("comment_id")
    if comment_id is None:
        raise ValueError("ARIES alignment requires comment_id")
    comment = _required_text(raw, "comment")
    positive_edits = raw.get("positive_edits")
    if not isinstance(positive_edits, list):
        raise ValueError("ARIES alignment requires positive_edits list")
    addressed = bool(positive_edits)
    preferred = "ADDRESS_REVIEW_COMMENT" if addressed else "NO_ALIGNED_EDIT"
    alternative = "NO_ALIGNED_EDIT" if addressed else "ADDRESS_REVIEW_COMMENT"
    return {
        "record_kind": "taste",
        "content_scope": "derived_annotation",
        "case_id": f"aries-{doc_id}-{comment_id}",
        "stage": "REVIEW",
        "context_summary": comment,
        "reviewer_context": comment,
        "candidate_actions": ["ADDRESS_REVIEW_COMMENT", "NO_ALIGNED_EDIT"],
        "preferred_action": preferred,
        "rejected_actions": [alternative],
        "decision_principle": (
            "Treat a released review-to-edit alignment as an observed author action, "
            "not as proof that the action was scientifically optimal."
        ),
        "why_preferred": (
            f"The ARIES human alignment records {len(positive_edits)} linked edit(s) "
            "for this review comment."
        ),
        "outcome_summary": f"Observed {len(positive_edits)} aligned paper edit(s).",
        "confidence": 0.5,
        "label_basis": "observed_revision_alignment",
        "extractor_version": "scitaste-aries-projection-v1",
        "human_verified": False,
        "retrieval_eligible": False,
        "source_action_id": f"{doc_id}:{comment_id}",
        "derivation_method": "deterministic projection of released ARIES human alignment",
        "source_locator": (
            "https://ai2-s2-research-public.s3.us-west-2.amazonaws.com/"
            f"aries/alignment_human_eval.jsonl#doc={doc_id}&comment={comment_id}"
        ),
    }


def _curate_casimir_mapping(raw: dict[str, Any]) -> dict[str, Any]:
    forum = _required_text(raw, "id_forum")
    references = raw.get("references")
    if not isinstance(references, list) or not all(isinstance(item, str) for item in references):
        raise ValueError("CASIMIR mapping requires references list")
    return {
        "record_kind": "knowledge",
        "content_scope": "derived_annotation",
        "document_id": f"casimir-revisions-{forum}",
        "title": f"CASIMIR revision chain {forum}",
        "content": (
            f"CASIMIR maps OpenReview forum {forum} to {len(references)} revision "
            f"record(s): {', '.join(references)}."
        ),
        "domain_tags": ["scientific-revision"],
        "method_tags": ["revision-history"],
        "derivation_method": "metadata-only projection of CASIMIR revision mapping",
        "personal_data_removed": True,
        "source_locator": (f"https://huggingface.co/datasets/taln-ls2n/CASIMIR#forum={forum}"),
    }


def _curate_casimir_metadata(raw: dict[str, Any]) -> dict[str, Any]:
    forum = _required_text(raw, "forum")
    content = raw.get("content")
    if not isinstance(content, dict):
        raise ValueError("CASIMIR metadata requires content object")
    title = _required_text(content, "title")
    venue = _required_text(content, "venue")
    return {
        "record_kind": "knowledge",
        "content_scope": "metadata",
        "document_id": f"accepted-paper-metadata-{forum}",
        "title": title,
        "content": f"OpenReview forum {forum} is recorded with venue: {venue}.",
        "domain_tags": ["accepted-paper-metadata"],
        "method_tags": ["bibliographic-metadata"],
        "derivation_method": "metadata-only CASIMIR projection; article text excluded",
        "personal_data_removed": True,
        "source_locator": f"https://openreview.net/forum?id={forum}",
    }


def _required_text(raw: dict[str, Any], field: str) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"required field {field!r} is missing")
    return " ".join(value.split())


def _load_jsonl(path: Path, *, limit: int | None) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path} line {line_number} must be an object")
            records.append(value)
            if limit is not None and len(records) >= limit:
                break
    return records


def _atomic_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    contents = "".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records
    )
    _atomic_text(path, contents)


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    _atomic_text(path, json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def _atomic_text(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
        Path(temporary).replace(path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
