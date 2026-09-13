"""Prestige-blind projections of receipt-bound AAAR experiment-design records."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from scitaste.evaluation.acquisition import (
    AcquisitionReceiptInspection,
    AcquisitionRequestInspection,
)
from scitaste.evaluation.json_content_audit import JsonContentAuditReport
from scitaste.taste.reference_quality import ReferenceQualityInput

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_CONTROL_BYTES = 16 * 1_048_576
_SUGGESTION_FIELD = "What experiments do you suggest doing?"
_RATIONALE_FIELD = "Why do you suggest these experiments?"
_VENUE_PATTERN = re.compile(
    r"\b(?:aaai|acl|aistats|cvpr|emnlp|iclr|icml|kdd|neurips|nips|sigir)"
    r"(?:[_ -]?(?:19|20)?\d{2}|[_-](?:conference|natbib|style))?\b",
    re.IGNORECASE,
)
_URL_PATTERN = re.compile(r"https?://[^\s{}\\]+", re.IGNORECASE)
_EMAIL_PATTERN = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])")
_BIBLIOGRAPHY_BOUNDARY = re.compile(
    r"\\(?:(?:sub)*section)\*?\s*\{\s*"
    r"(?:acknowledg(?:e)?ments?|references|bibliography)\s*\}"
    r"|\\(?:paragraph|textbf)\s*\{\s*acknowledg(?:e)?ments?\.?\s*\}"
    r"|\\begin\s*\{\s*thebibliography\s*\}|\\bibliography\s*\{",
    re.IGNORECASE,
)


class AaarQualityProjectionItem(BaseModel):
    """Private source-to-opaque-input binding for one materialized projection."""

    model_config = _CONFIG

    item_id: str = Field(pattern=_ID)
    source_id: str = Field(pattern=_ID)
    screening_id: str = Field(pattern=_ID)
    source_content_sha256: str = Field(pattern=_SHA256)
    projection_locator: str = Field(min_length=1, max_length=1_000)
    projection_file_sha256: str = Field(pattern=_SHA256)
    source_projection_sha256: str = Field(pattern=_SHA256)
    observed_semantic_roles: tuple[str, ...] = Field(min_length=1, max_length=20)
    required_role_gaps: tuple[str, ...] = Field(max_length=20)
    redaction_count: int = Field(ge=0)
    residual_prestige_leak_count: Literal[0] = 0
    ready_for_reference_quality_screen: Literal[True] = True


class AaarQualityProjectionReport(BaseModel):
    """Content-free receipt for model-visible AAAR quality projections."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    projection_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    request_id: str = Field(pattern=_ID)
    request_sha256: str = Field(pattern=_SHA256)
    receipt_sha256: str = Field(pattern=_SHA256)
    content_audit_report_sha256: str = Field(pattern=_SHA256)
    projector_implementation_sha256: str = Field(pattern=_SHA256)
    materialized_at: datetime
    item_count: int = Field(gt=0)
    ready_item_count: int = Field(ge=0)
    role_complete_item_count: int = Field(ge=0)
    items: tuple[AaarQualityProjectionItem, ...] = Field(min_length=1, max_length=500)
    source_projection_policy: Literal[
        "problem-context-plus-annotated-alternatives-and-observed-experiment"
    ] = "problem-context-plus-annotated-alternatives-and-observed-experiment"
    observed_paper_experiment_is_not_gold: Literal[True] = True
    annotation_is_not_gold: Literal[True] = True
    explicit_prestige_signals_hidden: Literal[True] = True
    author_identity_hidden: Literal[True] = True
    venue_identity_hidden: Literal[True] = True
    citation_count_hidden: Literal[True] = True
    downstream_task_content_excluded: Literal[True] = True
    local_content_read_performed: Literal[True] = True
    network_access_performed: Literal[False] = False
    model_calls_performed: Literal[False] = False
    human_review_performed: Literal[False] = False
    source_admission_performed: Literal[False] = False
    taste_abstraction_performed: Literal[False] = False
    experiment_performed: Literal[False] = False
    authorizes_model_calls: Literal[False] = False
    authorizes_source_admission: Literal[False] = False
    authorizes_experiment: Literal[False] = False

    @field_validator("materialized_at")
    @classmethod
    def materialized_time_is_aware(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("AAAR quality-projection timestamp must include a timezone")
        return value

    @model_validator(mode="after")
    def population_is_closed(self) -> AaarQualityProjectionReport:
        if self.item_count != len(self.items):
            raise ValueError("AAAR projection item count differs from its inventory")
        if self.ready_item_count != sum(
            item.ready_for_reference_quality_screen for item in self.items
        ):
            raise ValueError("AAAR projection ready count differs from its inventory")
        if self.role_complete_item_count != sum(not item.required_role_gaps for item in self.items):
            raise ValueError("AAAR projection role-complete count differs from its inventory")
        if len({item.item_id for item in self.items}) != len(self.items):
            raise ValueError("AAAR projection item IDs must be unique")
        if len({item.source_id for item in self.items}) != len(self.items):
            raise ValueError("AAAR opaque source IDs must be unique")
        return self

    @computed_field
    @property
    def report_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"report_sha256"}))


def materialize_aaar_quality_projections(
    request: AcquisitionRequestInspection,
    receipt: AcquisitionReceiptInspection,
    *,
    content_audit_report_path: str | Path,
    workspace_root: str | Path,
    output_directory: str | Path,
    projection_id: str,
    materialized_at: datetime,
) -> AaarQualityProjectionReport:
    """Create blinded model inputs from exact, already-audited local AAAR bytes."""

    if materialized_at.utcoffset() is None:
        raise ValueError("AAAR quality-projection timestamp must include a timezone")
    root = Path(workspace_root).resolve(strict=True)
    audit = _load_content_audit_report(content_audit_report_path)
    source_request = request.request
    source_receipt = receipt.receipt
    _verify_chain(source_request, source_receipt, audit)
    raw_root = _resolve_beneath(root, source_receipt.destination_root)
    if raw_root is None or raw_root.is_symlink() or not raw_root.is_dir():
        raise ValueError("AAAR acquired-content root is unavailable")

    target = Path(output_directory)
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    try:
        audit_items = {item.item_id: item for item in audit.items}
        projected: list[AaarQualityProjectionItem] = []
        for receipt_item in source_receipt.items:
            source_path = _resolve_beneath(raw_root, receipt_item.destination)
            if source_path is None or source_path.is_symlink() or not source_path.is_file():
                raise ValueError(f"AAAR source file is unavailable: {receipt_item.item_id}")
            raw = source_path.read_bytes()
            if len(raw) != receipt_item.size_bytes:
                raise ValueError(f"AAAR source byte count drifted: {receipt_item.item_id}")
            if hashlib.sha256(raw).hexdigest() != receipt_item.sha256:
                raise ValueError(f"AAAR source hash drifted: {receipt_item.item_id}")
            audit_item = audit_items[receipt_item.item_id]
            if (
                not audit_item.exact_bytes_verified
                or audit_item.observed_sha256 != receipt_item.sha256
                or audit_item.receipt_sha256 != receipt_item.sha256
            ):
                raise ValueError(f"AAAR audit binding failed: {receipt_item.item_id}")
            record = _load_aaar_record(raw, receipt_item.item_id)
            input_data, redaction_count = _project_record(
                record,
                source_content_sha256=receipt_item.sha256,
            )
            relative = PurePosixPath("items", input_data.source_id, "INPUT.json")
            destination = staging.joinpath(*relative.parts)
            destination.parent.mkdir(parents=True)
            body = input_data.model_dump_json(indent=2) + "\n"
            destination.write_text(body, encoding="utf-8")
            roles = _observed_roles(input_data.source_projection)
            required = {
                "alternative",
                "evidence",
                "limitation",
                "scientific_action",
            }
            projected.append(
                AaarQualityProjectionItem(
                    item_id=receipt_item.item_id,
                    source_id=input_data.source_id,
                    screening_id=input_data.screening_id,
                    source_content_sha256=receipt_item.sha256,
                    projection_locator=relative.as_posix(),
                    projection_file_sha256=hashlib.sha256(body.encode()).hexdigest(),
                    source_projection_sha256=input_data.source_projection_sha256,
                    observed_semantic_roles=tuple(sorted(roles)),
                    required_role_gaps=tuple(sorted(required - roles)),
                    redaction_count=redaction_count,
                )
            )
        report = AaarQualityProjectionReport(
            projection_id=projection_id,
            project_id=source_request.project_id,
            request_id=source_request.request_id,
            request_sha256=source_request.request_sha256,
            receipt_sha256=source_receipt.receipt_sha256,
            content_audit_report_sha256=audit.report_sha256,
            projector_implementation_sha256=_module_sha256(),
            materialized_at=materialized_at,
            item_count=len(projected),
            ready_item_count=len(projected),
            role_complete_item_count=sum(not item.required_role_gaps for item in projected),
            items=tuple(projected),
        )
        (staging / "REPORT.json").write_text(report.model_dump_json(indent=2) + "\n")
        os.rename(staging, target)
        return report
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _project_record(
    record: dict[str, object],
    *,
    source_content_sha256: str,
) -> tuple[ReferenceQualityInput, int]:
    paper_info = record["paper_info"]
    output = record["output"]
    raw_data = record["raw_data"]
    assert isinstance(paper_info, dict)
    assert isinstance(output, dict)
    assert isinstance(raw_data, dict)
    abstract = paper_info["abstract"]
    authors = paper_info["authors"]
    title = paper_info["title"]
    annotator = record["annotator"]
    experiments = output[_SUGGESTION_FIELD]
    rationales = output[_RATIONALE_FIELD]
    observed_experiment = raw_data["context_after_exp"]
    assert isinstance(abstract, str)
    assert isinstance(authors, list)
    assert isinstance(title, str)
    assert isinstance(annotator, str)
    assert isinstance(experiments, list)
    assert isinstance(rationales, list)
    assert isinstance(observed_experiment, list)

    sensitive = [title, annotator, *authors]
    context, context_redactions = _blind_text(abstract, sensitive)
    action_record, experiment_redactions = _blind_text(
        _strip_bibliography("".join(observed_experiment)),
        sensitive,
    )
    alternatives: list[str] = []
    reasons: list[str] = []
    redactions = context_redactions + experiment_redactions
    for value in experiments:
        cleaned, count = _blind_text(value, sensitive)
        alternatives.append(cleaned)
        redactions += count
    for value in rationales:
        cleaned, count = _blind_text(value, sensitive)
        reasons.append(cleaned)
        redactions += count

    projection = json.dumps(
        {
            "fields": {
                "problem_context": {
                    "semantic_role": "problem_context",
                    "value": context,
                },
                "annotated_experiment_alternatives": {
                    "semantic_role": "alternative",
                    "value": alternatives,
                },
                "annotated_rationales": {
                    "semantic_role": "justification",
                    "value": reasons,
                },
                "observed_experiment_record": {
                    "semantic_roles": [
                        "scientific_action",
                        "evidence",
                        "limitation",
                        "outcome",
                    ],
                    "value": action_record,
                },
            },
            "outcome_information_availability": "available",
            "schema_version": "1.0",
        },
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    _assert_blind_projection(projection, sensitive, record_id=str(record["id"]))
    opaque = hashlib.sha256(f"aaar-quality-v1\0{source_content_sha256}".encode()).hexdigest()[:20]
    return (
        ReferenceQualityInput(
            screening_id=f"quality-{opaque}",
            source_id=f"source-{opaque}",
            source_content_sha256=source_content_sha256,
            decision_stage="EXPERIMENT",
            decision_role=(
                "assess whether an observed experiment and annotated alternatives expose "
                "transferable scientific judgment"
            ),
            source_projection=projection,
            source_projection_sha256=hashlib.sha256(projection.encode()).hexdigest(),
            outcome_information_availability="available",
        ),
        redactions,
    )


def _load_aaar_record(raw: bytes, expected_id: str) -> dict[str, object]:
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"AAAR record is not UTF-8 JSON: {expected_id}") from exc
    if not isinstance(payload, dict) or set(payload) != {
        "annotator",
        "id",
        "input",
        "output",
        "paper_info",
        "raw_data",
    }:
        raise ValueError(f"AAAR record schema differs: {expected_id}")
    if payload.get("id") != expected_id:
        raise ValueError(f"AAAR record identity differs: {expected_id}")
    paper_info = payload.get("paper_info")
    output = payload.get("output")
    raw_data = payload.get("raw_data")
    if not isinstance(paper_info, dict) or set(paper_info) != {
        "abstract",
        "authors",
        "comments",
        "title",
    }:
        raise ValueError(f"AAAR paper-info schema differs: {expected_id}")
    if not isinstance(output, dict) or set(output) != {_SUGGESTION_FIELD, _RATIONALE_FIELD}:
        raise ValueError(f"AAAR annotation schema differs: {expected_id}")
    if not isinstance(raw_data, dict) or set(raw_data) != {
        "context_after_exp",
        "context_before_exp",
        "del_percentage",
    }:
        raise ValueError(f"AAAR raw-data schema differs: {expected_id}")
    authors = paper_info.get("authors")
    experiments = output.get(_SUGGESTION_FIELD)
    rationales = output.get(_RATIONALE_FIELD)
    observed = raw_data.get("context_after_exp")
    if (
        not isinstance(paper_info.get("abstract"), str)
        or not paper_info["abstract"].strip()
        or not isinstance(paper_info.get("title"), str)
        or not isinstance(authors, list)
        or not authors
        or any(not isinstance(item, str) or not item.strip() for item in authors)
        or not isinstance(payload.get("annotator"), str)
        or not isinstance(experiments, list)
        or not isinstance(rationales, list)
        or not experiments
        or len(experiments) != len(rationales)
        or any(not isinstance(item, str) or not item.strip() for item in experiments + rationales)
        or not isinstance(observed, list)
        or not observed
        or any(not isinstance(item, str) for item in observed)
    ):
        raise ValueError(f"AAAR record content contract differs: {expected_id}")
    return payload


def _blind_text(value: str, sensitive: list[str]) -> tuple[str, int]:
    text = value
    replacements = 0
    for pattern, placeholder in (
        (_URL_PATTERN, "[redacted-external-locator]"),
        (_EMAIL_PATTERN, "[redacted-email]"),
        (_VENUE_PATTERN, "[redacted-venue]"),
    ):
        text, count = pattern.subn(placeholder, text)
        replacements += count
    sensitive_values = {item.strip() for item in sensitive if len(item.strip()) >= 4}
    for item in sorted(sensitive_values, key=len, reverse=True):
        text, count = re.subn(re.escape(item), "[redacted-source-identity]", text, flags=re.I)
        replacements += count
    return text.strip(), replacements


def _strip_bibliography(value: str) -> str:
    match = _BIBLIOGRAPHY_BOUNDARY.search(value)
    return value[: match.start()] if match else value


def _assert_blind_projection(projection: str, sensitive: list[str], *, record_id: str) -> None:
    if _URL_PATTERN.search(projection) or _EMAIL_PATTERN.search(projection):
        raise ValueError("AAAR projection retains an external identity locator")
    if _VENUE_PATTERN.search(projection):
        raise ValueError("AAAR projection retains an explicit venue signal")
    if record_id.casefold() in projection.casefold():
        raise ValueError("AAAR projection retains the source record identity")
    for item in sensitive:
        if len(item.strip()) >= 4 and item.casefold() in projection.casefold():
            raise ValueError("AAAR projection retains an explicit source identity")


def _observed_roles(projection: str) -> set[str]:
    fields = json.loads(projection)["fields"]
    roles: set[str] = set()
    for record in fields.values():
        singular = record.get("semantic_role")
        plural = record.get("semantic_roles")
        if isinstance(singular, str):
            roles.add(singular)
        if isinstance(plural, list):
            roles.update(item for item in plural if isinstance(item, str))
    return roles


def _verify_chain(source_request, source_receipt, audit: JsonContentAuditReport) -> None:
    if (
        source_receipt.request_id != source_request.request_id
        or source_receipt.request_sha256 != source_request.request_sha256
        or source_receipt.destination_root != source_request.destination_root
        or audit.project_id != source_request.project_id
        or audit.request_id != source_request.request_id
        or audit.request_sha256 != source_request.request_sha256
        or audit.receipt_sha256 != source_receipt.receipt_sha256
    ):
        raise ValueError("AAAR projection chain bindings have drifted")
    if not audit.ready_for_source_admission_proposal:
        raise ValueError("AAAR projection requires a passing content audit")
    receipt_ids = tuple(item.item_id for item in source_receipt.items)
    audit_ids = tuple(item.item_id for item in audit.items)
    if receipt_ids != audit_ids:
        raise ValueError("AAAR projection population differs from the content audit")


def _load_content_audit_report(path: str | Path) -> JsonContentAuditReport:
    source = Path(path)
    if source.is_symlink():
        raise ValueError("JSON content-audit report cannot be a symlink")
    resolved = source.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size > _MAX_CONTROL_BYTES:
        raise ValueError("JSON content-audit report must be a bounded regular file")
    try:
        payload = json.loads(resolved.read_bytes())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("JSON content-audit report must be valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("JSON content-audit report must contain an object")
    recorded = payload.pop("report_sha256", None)
    report = JsonContentAuditReport.model_validate(payload)
    if recorded != report.report_sha256:
        raise ValueError("JSON content-audit report hash mismatch")
    return report


def _resolve_beneath(root: Path, locator: str) -> Path | None:
    pure = PurePosixPath(locator)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        return None
    current = root
    for part in pure.parts:
        current /= part
        if current.is_symlink():
            return None
    resolved = current.resolve(strict=False)
    return resolved if resolved.is_relative_to(root) else None


def _canonical_sha256(value: object) -> str:
    canonical = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _module_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


__all__ = [
    "AaarQualityProjectionItem",
    "AaarQualityProjectionReport",
    "materialize_aaar_quality_projections",
]
