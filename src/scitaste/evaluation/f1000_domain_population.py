"""Acquire and compile a small multidisciplinary F1000Research Taste pilot.

The module deliberately separates public-network acquisition from local source
compilation.  Publisher subject queries provide sampling strata, not scientific
quality labels.  Reviewer recommendations, author replies, and later revisions
remain observed outcomes rather than gold actions.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

import yaml
from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from scitaste.evaluation.source_identity import canonical_f1000_source_group_id
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
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_DOI = re.compile(
    r"^(?P<base>10\.12688/f1000research\.(?:[0-9]+(?:-[0-9]+)?))"
    r"\.(?:v)?(?P<version>[1-9][0-9]*)$",
    re.IGNORECASE,
)
_XLINK_HREF = "{http://www.w3.org/1999/xlink}href"
_CC_BY = re.compile(r"^https?://creativecommons\.org/licenses/by/(?:3\.0|4\.0)/?$", re.I)
_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])")
_MAX_CONFIG_BYTES = 256 * 1024
_MAX_XML_NODES = 200_000
_MAX_TEXT_CHARS = 8_000
_FETCH_CHUNK_BYTES = 64 * 1024
_PROJECT_STAGE = "taste_candidate_population"
_PROJECT_PROJECTION = "f1000-multidomain-taste-population-v1"


class F1000DomainStratum(BaseModel):
    """One publisher-subject stratum in the source pilot."""

    model_config = _CONFIG

    domain_id: str = Field(pattern=_ID)
    subject_query: str = Field(min_length=2, max_length=100)
    expected_page_count: int = Field(ge=1, le=20)
    target_source_groups: int = Field(ge=5, le=100)


class F1000DomainAcquisitionPlan(BaseModel):
    """Closed public-network envelope for a two-version source pilot."""

    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1"] = "1.0"
    acquisition_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    source_host: Literal["f1000research.com"] = "f1000research.com"
    strata: tuple[F1000DomainStratum, ...] = Field(min_length=2, max_length=5)
    rows_per_page: Literal[100] = 100
    minimum_latest_version: int = Field(default=2, ge=2, le=20)
    selection_salt: str = Field(min_length=16, max_length=200)
    excluded_canonical_source_group_ids: tuple[str, ...] = Field(
        default=(),
        max_length=100_000,
        exclude_if=lambda value: not value,
    )
    per_search_response_max_bytes: int = Field(ge=16_384, le=4 * 1024 * 1024)
    per_article_xml_max_bytes: int = Field(ge=65_536, le=16 * 1024 * 1024)
    maximum_total_bytes: int = Field(gt=0, le=10_000_000_000)
    timeout_seconds: float = Field(ge=1.0, le=120.0)
    parallel_article_requests: int = Field(ge=1, le=16)
    user_agent: str = Field(min_length=10, max_length=300)
    authorization_ref: str = Field(min_length=1, max_length=500)
    license_identifier: Literal["CC-BY"] = "CC-BY"
    purpose: str = Field(min_length=1, max_length=2_000)
    claim_boundary: str = Field(min_length=1, max_length=2_000)
    redirects_allowed: Literal[False] = False
    credentials_used: Literal[False] = False
    authorizes_model_calls: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False
    authorizes_experiment: Literal[False] = False

    @model_validator(mode="after")
    def acquisition_is_bounded(self) -> F1000DomainAcquisitionPlan:
        domain_ids = [item.domain_id for item in self.strata]
        queries = [" ".join(item.subject_query.casefold().split()) for item in self.strata]
        if len(domain_ids) != len(set(domain_ids)) or len(queries) != len(set(queries)):
            raise ValueError("F1000 domain strata must have unique IDs and queries")
        excluded = self.excluded_canonical_source_group_ids
        if excluded != tuple(sorted(set(excluded))):
            raise ValueError("F1000 excluded canonical source groups must be sorted and unique")
        if any(not item.startswith("f1000-work-") for item in excluded):
            raise ValueError("F1000 exclusions must use canonical work identities")
        if self.schema_version == "1.0" and excluded:
            raise ValueError("F1000 plan schema 1.0 cannot carry cross-receipt exclusions")
        if self.schema_version == "1.1" and not excluded:
            raise ValueError("F1000 plan schema 1.1 requires cross-receipt exclusions")
        search_requests = sum(item.expected_page_count for item in self.strata)
        # Every selected group binds the exact v1 reviewed source and latest revision.
        article_requests = 2 * sum(item.target_source_groups for item in self.strata)
        if search_requests + article_requests > 100:
            raise ValueError("F1000 pilot must remain inside one documented request window")
        expected_ceiling = (
            search_requests * self.per_search_response_max_bytes
            + article_requests * self.per_article_xml_max_bytes
        )
        if self.maximum_total_bytes != expected_ceiling:
            raise ValueError("F1000 total ceiling must equal all response ceilings")
        return self

    @computed_field
    @property
    def plan_sha256(self) -> str:
        return _sha256_json(self.model_dump(mode="json", exclude={"plan_sha256"}))


class F1000ResponseEvidence(BaseModel):
    model_config = _CONFIG

    request_kind: Literal["subject-search", "article-xml"]
    domain_id: str = Field(pattern=_ID)
    request_url: str = Field(min_length=1, max_length=2_000)
    response_locator: str = Field(min_length=1, max_length=500)
    response_sha256: str = Field(pattern=_SHA256)
    response_bytes: int = Field(gt=0)

    @model_validator(mode="after")
    def response_is_from_f1000(self) -> F1000ResponseEvidence:
        parsed = urlsplit(self.request_url)
        if parsed.scheme != "https" or parsed.hostname != "f1000research.com":
            raise ValueError("F1000 response URL must use the official HTTPS host")
        if parsed.port not in {None, 443} or parsed.username or parsed.password:
            raise ValueError("F1000 response URL must be credential-free standard HTTPS")
        _relative_locator(self.response_locator)
        return self


class F1000SelectedSource(BaseModel):
    model_config = _CONFIG

    domain_id: str = Field(pattern=_ID)
    base_doi: str = Field(min_length=10, max_length=200)
    reviewed_doi: str = Field(min_length=10, max_length=200)
    latest_doi: str = Field(min_length=10, max_length=200)
    latest_version: int = Field(ge=2, le=100)
    selection_rank: int = Field(ge=1)
    reviewed_locator: str = Field(min_length=1, max_length=500)
    latest_locator: str = Field(min_length=1, max_length=500)
    reviewed_sha256: str = Field(pattern=_SHA256)
    latest_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def versions_are_exact(self) -> F1000SelectedSource:
        reviewed = _parse_doi(self.reviewed_doi)
        latest = _parse_doi(self.latest_doi)
        if reviewed != (self.base_doi.casefold(), 1):
            raise ValueError("F1000 reviewed DOI must bind version 1")
        if latest != (self.base_doi.casefold(), self.latest_version):
            raise ValueError("F1000 latest DOI identity is inconsistent")
        _relative_locator(self.reviewed_locator)
        _relative_locator(self.latest_locator)
        return self


class F1000DomainAcquisitionReceipt(BaseModel):
    """Self-hashed receipt for the exact search responses and article pairs."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    acquisition_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    plan_sha256: str = Field(pattern=_SHA256)
    plan_locator: Literal["PLAN.json"] = "PLAN.json"
    plan_file_sha256: str = Field(pattern=_SHA256)
    acquired_at: datetime
    authorization_ref: str = Field(min_length=1, max_length=500)
    search_responses: tuple[F1000ResponseEvidence, ...] = Field(min_length=2, max_length=100)
    article_responses: tuple[F1000ResponseEvidence, ...] = Field(min_length=10, max_length=200)
    selected_sources: tuple[F1000SelectedSource, ...] = Field(min_length=10, max_length=100)
    domain_candidate_counts: dict[str, int]
    domain_selected_counts: dict[str, int]
    distinct_source_group_count: int = Field(gt=0)
    cross_domain_overlap_count: Literal[0] = 0
    request_count: int = Field(gt=0, le=100)
    total_bytes: int = Field(gt=0, le=10_000_000_000)
    maximum_total_bytes: int = Field(gt=0, le=10_000_000_000)
    acquisition_complete: Literal[True] = True
    publisher_subjects_are_not_quality_labels: Literal[True] = True
    reviewer_recommendations_are_not_quality_labels: Literal[True] = True
    source_content_read_for_quality: Literal[False] = False
    model_calls_performed: Literal[False] = False
    gpu_work_performed: Literal[False] = False
    experiment_performed: Literal[False] = False
    authorizes_source_admission: Literal[False] = False
    authorizes_model_calls: Literal[False] = False
    authorizes_experiment: Literal[False] = False
    receipt_sha256: str = Field(pattern=_SHA256)

    @field_validator("acquired_at")
    @classmethod
    def time_is_aware(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("F1000 acquisition time must include a timezone")
        return value

    @model_validator(mode="after")
    def receipt_is_closed(self) -> F1000DomainAcquisitionReceipt:
        selected = list(self.selected_sources)
        bases = [item.base_doi for item in selected]
        if self.distinct_source_group_count != len(selected) or len(bases) != len(set(bases)):
            raise ValueError("F1000 selected source groups must be complete and unique")
        if self.domain_selected_counts != dict(Counter(item.domain_id for item in selected)):
            raise ValueError("F1000 selected domain counts are inconsistent")
        if set(self.domain_selected_counts) != set(self.domain_candidate_counts):
            raise ValueError("F1000 receipt domain inventories differ")
        if any(
            self.domain_selected_counts[key] > self.domain_candidate_counts[key]
            for key in self.domain_selected_counts
        ):
            raise ValueError("F1000 selected count exceeds its candidate stratum")
        if len(self.article_responses) != 2 * len(selected):
            raise ValueError("F1000 receipt must bind two article versions per source")
        if self.request_count != len(self.search_responses) + len(self.article_responses):
            raise ValueError("F1000 receipt request count is inconsistent")
        if self.total_bytes != sum(
            item.response_bytes for item in (*self.search_responses, *self.article_responses)
        ):
            raise ValueError("F1000 receipt byte total is inconsistent")
        if self.total_bytes > self.maximum_total_bytes:
            raise ValueError("F1000 acquisition exceeded its total ceiling")
        expected = _sha256_json(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        if self.receipt_sha256 != expected:
            raise ValueError("F1000 acquisition receipt hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> F1000DomainAcquisitionReceipt:
        payload = {"schema_version": "1.0", **values}
        payload.pop("receipt_sha256", None)
        unsigned = cls.model_construct(receipt_sha256="0" * 64, **payload)
        digest = _sha256_json(unsigned.model_dump(mode="json", exclude={"receipt_sha256"}))
        return cls(**payload, receipt_sha256=digest)


class F1000PopulationFinding(BaseModel):
    model_config = _CONFIG

    code: str = Field(pattern=_ID)
    message: str = Field(min_length=1, max_length=2_000)


class F1000TasteCandidate(BaseModel):
    """De-identified review--reply--revision episode; never an admitted Taste case."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    candidate_id: str = Field(pattern=_ID)
    source_group_id: str = Field(pattern=_ID)
    source_domain: str = Field(pattern=_ID)
    domain_basis: Literal["publisher-subject-query-pending-independent-review"]
    reviewed_version: Literal[1] = 1
    latest_version: int = Field(ge=2)
    article_title: str = Field(min_length=1, max_length=_MAX_TEXT_CHARS)
    reviewed_abstract: str = Field(min_length=1, max_length=_MAX_TEXT_CHARS)
    revised_abstract: str = Field(min_length=1, max_length=_MAX_TEXT_CHARS)
    review_comment: str = Field(min_length=1, max_length=_MAX_TEXT_CHARS)
    author_response: str | None = Field(default=None, max_length=_MAX_TEXT_CHARS)
    recommendation: Literal["approved", "approved-with-reservations", "not-approved", "unknown"]
    subsequent_revision_observed: Literal[True] = True
    publisher_domain_is_not_gold: Literal[True] = True
    recommendation_is_not_gold: Literal[True] = True
    author_response_is_not_gold: Literal[True] = True
    observed_revision_is_not_gold: Literal[True] = True
    structured_author_identity_removed: Literal[True] = True
    structured_reviewer_identity_removed: Literal[True] = True
    free_text_privacy_review_pending: Literal[True] = True


class F1000TastePopulationReport(BaseModel):
    """Aggregate boundary for the two-domain source pilot."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    population_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    acquisition_receipt_file_sha256: str = Field(pattern=_SHA256)
    acquisition_receipt_sha256: str = Field(pattern=_SHA256)
    compiler_implementation_sha256: str = Field(pattern=_SHA256)
    compiled_at: datetime
    candidate_file: Literal["CANDIDATES.jsonl"] = "CANDIDATES.jsonl"
    candidate_file_sha256: str = Field(pattern=_SHA256)
    selected_source_group_count: int = Field(gt=0)
    candidate_source_group_count: int = Field(gt=0)
    candidate_count: int = Field(gt=0)
    response_observed_count: int = Field(ge=0)
    domain_source_group_counts: dict[str, int]
    recommendation_counts: dict[str, int]
    prior_domain_count: Literal[1] = 1
    added_domain_count: Literal[2] = 2
    observed_domain_count: Literal[3] = 3
    target_domain_count: Literal[3] = 3
    observed_domain_floor_met: Literal[True] = True
    minimum_groups_per_added_domain: int = Field(default=15, ge=1)
    added_domain_group_floor_met: bool
    independent_domain_review_complete: Literal[False] = False
    independent_quality_review_complete: Literal[False] = False
    decision_family_stratification_complete: Literal[False] = False
    privacy_review_complete: Literal[False] = False
    ready_for_taste_abstraction_review: Literal[False] = False
    ready_for_benchmark_admission: Literal[False] = False
    blockers: tuple[F1000PopulationFinding, ...] = Field(min_length=1)
    verification: VerificationDecision
    standalone_preflight_performed: Literal[False] = False
    inline_integrity_guards_performed: Literal[True] = True
    network_access_performed: Literal[False] = False
    model_calls_performed: Literal[False] = False
    gpu_work_performed: Literal[False] = False
    experiment_performed: Literal[False] = False
    report_sha256: str = Field(pattern=_SHA256)

    @field_validator("compiled_at")
    @classmethod
    def compiled_time_is_aware(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("F1000 population time must include a timezone")
        return value

    @model_validator(mode="after")
    def report_is_closed(self) -> F1000TastePopulationReport:
        if self.candidate_source_group_count != sum(self.domain_source_group_counts.values()):
            raise ValueError("F1000 candidate group counts are inconsistent")
        if self.candidate_source_group_count > self.selected_source_group_count:
            raise ValueError("F1000 candidate groups exceed selected groups")
        expected_floor = all(
            count >= self.minimum_groups_per_added_domain
            for count in self.domain_source_group_counts.values()
        )
        if self.added_domain_group_floor_met != expected_floor:
            raise ValueError("F1000 added-domain group floor is inconsistent")
        if self.candidate_count != sum(self.recommendation_counts.values()):
            raise ValueError("F1000 recommendation counts do not cover candidates")
        if self.verification.route is not VerificationRoute.DIRECT_PATH:
            raise ValueError("F1000 local compilation must use the direct path")
        expected = _sha256_json(self.model_dump(mode="json", exclude={"report_sha256"}))
        if self.report_sha256 != expected:
            raise ValueError("F1000 population report hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> F1000TastePopulationReport:
        payload = {"schema_version": "1.0", **values}
        payload.pop("report_sha256", None)
        unsigned = cls.model_construct(report_sha256="0" * 64, **payload)
        digest = _sha256_json(unsigned.model_dump(mode="json", exclude={"report_sha256"}))
        return cls(**payload, report_sha256=digest)


@dataclass(frozen=True)
class F1000HTTPResponse:
    status_code: int
    url: str
    headers: Mapping[str, str]
    body: bytes


class F1000Transport(Protocol):
    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
        maximum_bytes: int,
    ) -> F1000HTTPResponse: ...


class PublicF1000Transport:
    """Credential-free, redirect-free transport for the official XML API."""

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
        maximum_bytes: int,
    ) -> F1000HTTPResponse:
        _official_url(url)
        opener = build_opener(_RejectRedirects())
        request = Request(url, headers=dict(headers), method="GET")
        try:
            response = opener.open(request, timeout=timeout)
        except HTTPError as exc:
            raise ValueError(f"F1000 request returned HTTP {exc.code}") from exc
        with response:
            status = getattr(response, "status", None)
            final_url = response.geturl()
            if status != 200 or final_url != url:
                raise ValueError("F1000 request must return HTTP 200 without redirect")
            content_type = response.headers.get("Content-Type", "").partition(";")[0].lower()
            if content_type not in {"application/xml", "text/xml"}:
                raise ValueError("F1000 response is not XML")
            declared = response.headers.get("Content-Length")
            if declared is not None and int(declared) > maximum_bytes:
                raise ValueError("F1000 response exceeds its declared byte ceiling")
            body = response.read(maximum_bytes + 1)
        if not body or len(body) > maximum_bytes:
            raise ValueError("F1000 response is empty or exceeds its byte ceiling")
        return F1000HTTPResponse(
            status_code=200,
            url=url,
            headers={"content-type": content_type},
            body=body,
        )


@dataclass(frozen=True)
class MaterializedF1000Acquisition:
    output_dir: Path
    receipt_path: Path
    receipt: F1000DomainAcquisitionReceipt


def load_f1000_domain_acquisition_plan(path: str | Path) -> F1000DomainAcquisitionPlan:
    source = Path(path)
    if source.is_symlink():
        raise ValueError("F1000 acquisition plan must not be a symlink")
    resolved = source.resolve(strict=True)
    if not resolved.is_file() or not 1 <= resolved.stat().st_size <= _MAX_CONFIG_BYTES:
        raise ValueError("F1000 acquisition plan must be a bounded regular file")
    payload = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("F1000 acquisition plan must contain a mapping")
    return F1000DomainAcquisitionPlan.model_validate(payload)


def acquire_f1000_domain_sources(
    plan: F1000DomainAcquisitionPlan,
    *,
    output_dir: str | Path,
    allow_network_download: bool,
    transport: F1000Transport | None = None,
    acquired_at: datetime | None = None,
) -> MaterializedF1000Acquisition:
    """Freeze subject searches plus exact v1/latest XML pairs atomically."""

    if not allow_network_download:
        raise ValueError("F1000 acquisition requires the explicit network-download switch")
    target = Path(output_dir)
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{target.name}.", suffix=".staging", dir=target.parent)
    )
    client = transport or PublicF1000Transport()
    headers = {
        "Accept": "application/xml,text/xml",
        "Accept-Encoding": "identity",
        "User-Agent": plan.user_agent,
    }
    search_evidence: list[F1000ResponseEvidence] = []
    article_evidence: list[F1000ResponseEvidence] = []
    try:
        plan_path = staging / "PLAN.json"
        _write_new(
            plan_path,
            _canonical_json(plan.model_dump(mode="json", exclude_computed_fields=True)) + b"\n",
        )
        search_root = staging / "search"
        article_root = staging / "articles"
        search_root.mkdir()
        article_root.mkdir()
        candidates_by_domain: dict[str, dict[str, tuple[str, int]]] = {}
        for stratum in plan.strata:
            domain_candidates: dict[str, tuple[str, int]] = {}
            for page in range(1, stratum.expected_page_count + 1):
                url = _search_url(stratum.subject_query, page, plan.rows_per_page)
                response = client.get(
                    url,
                    headers=headers,
                    timeout=plan.timeout_seconds,
                    maximum_bytes=plan.per_search_response_max_bytes,
                )
                dois, page_count = _parse_search_response(response.body)
                if page_count != stratum.expected_page_count:
                    raise ValueError("F1000 subject-search page count changed from the plan")
                locator = f"search/{stratum.domain_id}-{page:02d}.xml"
                _write_new(staging / locator, response.body)
                search_evidence.append(
                    F1000ResponseEvidence(
                        request_kind="subject-search",
                        domain_id=stratum.domain_id,
                        request_url=url,
                        response_locator=locator,
                        response_sha256=hashlib.sha256(response.body).hexdigest(),
                        response_bytes=len(response.body),
                    )
                )
                for doi in dois:
                    base, version = _parse_doi(doi)
                    current = domain_candidates.get(base)
                    if current is None or version > current[1]:
                        domain_candidates[base] = (doi.casefold(), version)
            candidates_by_domain[stratum.domain_id] = {
                base: item
                for base, item in domain_candidates.items()
                if item[1] >= plan.minimum_latest_version
            }

        selected = _select_disjoint_sources(plan, candidates_by_domain)

        def fetch_pair(
            position: int,
            domain_id: str,
            base: str,
            latest_doi: str,
            latest_version: int,
        ) -> tuple[
            int,
            str,
            str,
            str,
            int,
            F1000HTTPResponse,
            F1000HTTPResponse,
        ]:
            version_marker = latest_doi.rsplit(".", 1)[1]
            reviewed_doi = f"{base}.v1" if version_marker.startswith("v") else f"{base}.1"
            reviewed_url = _article_url(reviewed_doi)
            latest_url = _article_url(latest_doi)
            reviewed = client.get(
                reviewed_url,
                headers=headers,
                timeout=plan.timeout_seconds,
                maximum_bytes=plan.per_article_xml_max_bytes,
            )
            latest = client.get(
                latest_url,
                headers=headers,
                timeout=plan.timeout_seconds,
                maximum_bytes=plan.per_article_xml_max_bytes,
            )
            _verify_article_identity(reviewed.body, reviewed_doi)
            _verify_article_identity(latest.body, latest_doi)
            return (
                position,
                domain_id,
                reviewed_doi,
                latest_doi,
                latest_version,
                reviewed,
                latest,
            )

        futures = {}
        with ThreadPoolExecutor(max_workers=plan.parallel_article_requests) as pool:
            for position, item in enumerate(selected, start=1):
                domain_id, base, latest_doi, latest_version = item
                future = pool.submit(
                    fetch_pair,
                    position,
                    domain_id,
                    base,
                    latest_doi,
                    latest_version,
                )
                futures[future] = item
            fetched = [future.result() for future in as_completed(futures)]

        selected_sources: list[F1000SelectedSource] = []
        for (
            position,
            domain_id,
            reviewed_doi,
            latest_doi,
            latest_version,
            reviewed,
            latest,
        ) in sorted(fetched):
            base, _ = _parse_doi(reviewed_doi)
            safe_name = base.removeprefix("10.12688/f1000research.").replace("-", "_")
            reviewed_locator = f"articles/{domain_id}-{safe_name}-v1.xml"
            latest_locator = f"articles/{domain_id}-{safe_name}-v{latest_version}.xml"
            _write_new(staging / reviewed_locator, reviewed.body)
            _write_new(staging / latest_locator, latest.body)
            for request_kind, response, doi, locator in (
                ("article-xml", reviewed, reviewed_doi, reviewed_locator),
                ("article-xml", latest, latest_doi, latest_locator),
            ):
                article_evidence.append(
                    F1000ResponseEvidence(
                        request_kind=request_kind,
                        domain_id=domain_id,
                        request_url=_article_url(doi),
                        response_locator=locator,
                        response_sha256=hashlib.sha256(response.body).hexdigest(),
                        response_bytes=len(response.body),
                    )
                )
            selected_sources.append(
                F1000SelectedSource(
                    domain_id=domain_id,
                    base_doi=base,
                    reviewed_doi=reviewed_doi,
                    latest_doi=latest_doi,
                    latest_version=latest_version,
                    selection_rank=position,
                    reviewed_locator=reviewed_locator,
                    latest_locator=latest_locator,
                    reviewed_sha256=hashlib.sha256(reviewed.body).hexdigest(),
                    latest_sha256=hashlib.sha256(latest.body).hexdigest(),
                )
            )
        article_evidence.sort(key=lambda item: item.response_locator)
        total_bytes = sum(item.response_bytes for item in (*search_evidence, *article_evidence))
        if total_bytes > plan.maximum_total_bytes:
            raise ValueError("F1000 acquisition exceeded its aggregate byte ceiling")
        receipt = F1000DomainAcquisitionReceipt.create(
            acquisition_id=plan.acquisition_id,
            project_id=plan.project_id,
            plan_sha256=plan.plan_sha256,
            plan_file_sha256=_sha256_file(plan_path),
            acquired_at=acquired_at or datetime.now(UTC),
            authorization_ref=plan.authorization_ref,
            search_responses=tuple(search_evidence),
            article_responses=tuple(article_evidence),
            selected_sources=tuple(selected_sources),
            domain_candidate_counts={
                key: len(value) for key, value in candidates_by_domain.items()
            },
            domain_selected_counts=dict(Counter(item.domain_id for item in selected_sources)),
            distinct_source_group_count=len(selected_sources),
            request_count=len(search_evidence) + len(article_evidence),
            total_bytes=total_bytes,
            maximum_total_bytes=plan.maximum_total_bytes,
        )
        receipt_path = staging / "RECEIPT.json"
        _write_new(receipt_path, _canonical_json(receipt.model_dump(mode="json")) + b"\n")
        os.rename(staging, target)
        return MaterializedF1000Acquisition(
            output_dir=target,
            receipt_path=target / "RECEIPT.json",
            receipt=receipt,
        )
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def load_f1000_domain_acquisition_receipt(
    path: str | Path,
    *,
    verify_bundle: bool = True,
) -> F1000DomainAcquisitionReceipt:
    source = Path(path)
    if source.is_symlink() or not source.is_file() or source.stat().st_size > _MAX_CONFIG_BYTES:
        raise ValueError("F1000 receipt must be a bounded regular file")
    receipt = F1000DomainAcquisitionReceipt.model_validate_json(source.read_bytes())
    if not verify_bundle:
        return receipt
    root = source.parent.resolve(strict=True)
    expected = {
        receipt.plan_locator: receipt.plan_file_sha256,
        **{
            item.response_locator: item.response_sha256
            for item in (*receipt.search_responses, *receipt.article_responses)
        },
    }
    if len(expected) != 1 + len(receipt.search_responses) + len(receipt.article_responses):
        raise ValueError("F1000 receipt contains duplicate response locators")
    for locator, digest in expected.items():
        candidate = _bound_file(root, locator)
        if _sha256_file(candidate) != digest:
            raise ValueError(f"F1000 acquisition bundle hash mismatch: {locator}")
    plan = F1000DomainAcquisitionPlan.model_validate_json(
        _bound_file(root, receipt.plan_locator).read_bytes()
    )
    if plan.plan_sha256 != receipt.plan_sha256:
        raise ValueError("F1000 acquisition plan identity differs from its receipt")
    return receipt


def materialize_f1000_taste_population(
    *,
    acquisition_receipt_path: str | Path,
    output_directory: str | Path,
    compiled_at: datetime | None = None,
) -> F1000TastePopulationReport:
    """Compile exact local XML pairs into de-identified candidate episodes."""

    receipt_path = Path(acquisition_receipt_path).resolve(strict=True)
    receipt = load_f1000_domain_acquisition_receipt(receipt_path)
    source_root = receipt_path.parent.resolve(strict=True)
    verification = decide_verification_route(
        VerificationDecisionInput(
            action_id="compile-local-f1000-taste-population",
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
        raise ValueError("F1000 local compilation unexpectedly requires a preflight")
    candidates: list[F1000TasteCandidate] = []
    groups_by_domain: dict[str, set[str]] = {key: set() for key in receipt.domain_selected_counts}
    for source in receipt.selected_sources:
        reviewed = _parse_article(
            _bound_file(source_root, source.reviewed_locator).read_bytes(),
            expected_doi=source.reviewed_doi,
        )
        revised = _parse_article(
            _bound_file(source_root, source.latest_locator).read_bytes(),
            expected_doi=source.latest_doi,
        )
        source_group_id = canonical_f1000_source_group_id(source.base_doi)
        group_candidates = _review_candidates(
            reviewed=reviewed,
            revised=revised,
            source=source,
            source_group_id=source_group_id,
            receipt_sha256=receipt.receipt_sha256,
        )
        if group_candidates:
            groups_by_domain[source.domain_id].add(source_group_id)
            candidates.extend(group_candidates)
    if not candidates:
        raise ValueError("F1000 pilot contains no prior-version review episodes")

    target = Path(output_directory)
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{target.name}.", suffix=".staging", dir=target.parent)
    )
    try:
        candidate_bytes = b"".join(
            _canonical_json(item.model_dump(mode="json")) + b"\n"
            for item in sorted(candidates, key=lambda item: item.candidate_id)
        )
        _write_new(staging / "CANDIDATES.jsonl", candidate_bytes)
        domain_counts = {key: len(value) for key, value in groups_by_domain.items()}
        recommendations = dict(Counter(item.recommendation for item in candidates))
        report = F1000TastePopulationReport.create(
            population_id="f1000-multidomain-review-response-v1",
            project_id=receipt.project_id,
            acquisition_receipt_file_sha256=_sha256_file(receipt_path),
            acquisition_receipt_sha256=receipt.receipt_sha256,
            compiler_implementation_sha256=_sha256_file(Path(__file__)),
            compiled_at=compiled_at or datetime.now(UTC),
            candidate_file_sha256=hashlib.sha256(candidate_bytes).hexdigest(),
            selected_source_group_count=receipt.distinct_source_group_count,
            candidate_source_group_count=len(set().union(*groups_by_domain.values())),
            candidate_count=len(candidates),
            response_observed_count=sum(item.author_response is not None for item in candidates),
            domain_source_group_counts=domain_counts,
            recommendation_counts=recommendations,
            added_domain_group_floor_met=all(count >= 15 for count in domain_counts.values()),
            blockers=(
                F1000PopulationFinding(
                    code="independent-domain-review-pending",
                    message=(
                        "Publisher subject strata require independent confirmation before "
                        "formal domain labels are frozen."
                    ),
                ),
                F1000PopulationFinding(
                    code="independent-quality-review-pending",
                    message=(
                        "Two conflict-cleared reviewers have not assessed Scientific Taste "
                        "quality or abstraction suitability."
                    ),
                ),
                F1000PopulationFinding(
                    code="decision-family-stratification-pending",
                    message="Natural episodes have not been assigned to the six frozen families.",
                ),
                F1000PopulationFinding(
                    code="free-text-privacy-review-pending",
                    message=(
                        "Structured identities are removed, but article, review, and reply text "
                        "still requires a release privacy review."
                    ),
                ),
                F1000PopulationFinding(
                    code="taste-abstraction-review-pending",
                    message=(
                        "Observed recommendations, replies, and revisions are non-gold source "
                        "evidence and have not been distilled or reviewed as Taste."
                    ),
                ),
            ),
            verification=verification,
        )
        _write_new(
            staging / "REPORT.json",
            _canonical_json(report.model_dump(mode="json")) + b"\n",
        )
        os.rename(staging, target)
        return report
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def publish_f1000_taste_population_run(
    runtime: ProjectRuntime,
    *,
    project_id: str,
    run_id: str,
    source_report_path: str | Path,
    expected_revision: int,
) -> tuple[ProjectSnapshot, F1000TastePopulationReport]:
    """Register one compiled population as project-owned, non-benchmark evidence."""

    validate_project_id(project_id)
    validate_entry_id(run_id, field_name="run_id")
    source_path = Path(source_report_path).resolve(strict=True)
    source_report = F1000TastePopulationReport.model_validate_json(source_path.read_bytes())
    source_candidates = source_path.parent / source_report.candidate_file
    if (
        source_candidates.is_symlink()
        or not source_candidates.is_file()
        or _sha256_file(source_candidates) != source_report.candidate_file_sha256
    ):
        raise ValueError("F1000 population candidate file is unavailable or changed")
    if source_report.project_id != project_id:
        raise ValueError("F1000 population belongs to another project")
    project_root = runtime.projects_root.joinpath(project_id).resolve(strict=True)
    if not source_path.is_relative_to(project_root):
        raise ValueError("F1000 population source must remain inside its project")

    snapshot = runtime.open(project_id)
    existing = next((item for item in snapshot.manifest.runs if item.run_id == run_id), None)
    artifact = f"runs/{run_id}/{_PROJECT_STAGE}/REPORT.json"
    if existing is not None and existing.status == "complete-taste-domain-expansion":
        observed = F1000TastePopulationReport.model_validate_json(
            (project_root / artifact).read_bytes()
        )
        if observed.report_sha256 != source_report.report_sha256:
            raise ValueError("registered F1000 population differs from its source")
        return snapshot, observed
    if existing is None:
        if snapshot.revision != expected_revision:
            raise ValueError("F1000 population publication uses a stale project revision")
        snapshot = runtime.begin_run(
            project_id,
            ProjectRun(
                run_id=run_id,
                provider="scitaste-native",
                model="f1000-multidomain-taste-population-compiler-v1",
                condition="natural-reference-domain-expansion",
                seed=0,
                status="preparing-taste-domain-expansion",
                evidence_scope=(
                    "publisher-subject-stratified-review-response-revision-episodes-non-gold"
                ),
                stage_path=_PROJECT_STAGE,
                artifact=artifact,
                generative_ui_projection=_PROJECT_PROJECTION,
                population_id=source_report.population_id,
                acquisition_receipt_sha256=(source_report.acquisition_receipt_sha256),
                authorizes_model_calls=False,
                authorizes_experiment=False,
                no_model_call_performed=True,
                no_gpu_work_performed=True,
                no_experiment_performed=True,
            ),
            expected_revision=expected_revision,
        )
    elif existing.status != "preparing-taste-domain-expansion":
        raise ValueError("F1000 population run cannot resume from its current state")

    stage = project_root / "runs" / run_id / _PROJECT_STAGE
    target_report = stage / "REPORT.json"
    target_candidates = stage / source_report.candidate_file
    if not target_report.exists() and not target_candidates.exists():
        _write_new(target_candidates, source_candidates.read_bytes())
        _write_new(target_report, source_path.read_bytes())
    observed = F1000TastePopulationReport.model_validate_json(target_report.read_bytes())
    if (
        observed.report_sha256 != source_report.report_sha256
        or _sha256_file(target_candidates) != observed.candidate_file_sha256
    ):
        raise ValueError("published F1000 population differs from its compiled source")
    snapshot = runtime.update_run(
        project_id,
        run_id,
        expected_revision=snapshot.revision,
        status="complete-taste-domain-expansion",
        population_report_sha256=observed.report_sha256,
        candidate_file_sha256=observed.candidate_file_sha256,
        candidate_count=observed.candidate_count,
        candidate_source_group_count=observed.candidate_source_group_count,
        domain_source_group_counts=observed.domain_source_group_counts,
        observed_domain_count=observed.observed_domain_count,
        observed_domain_floor_met=observed.observed_domain_floor_met,
        added_domain_group_floor_met=observed.added_domain_group_floor_met,
        ready_for_taste_abstraction_review=(observed.ready_for_taste_abstraction_review),
        ready_for_benchmark_admission=observed.ready_for_benchmark_admission,
        blocker_codes=[item.code for item in observed.blockers],
        verification_route=observed.verification.route.value,
        standalone_preflight_performed=observed.standalone_preflight_performed,
        inline_integrity_guards_performed=observed.inline_integrity_guards_performed,
    )
    return snapshot, observed


@dataclass(frozen=True)
class _ParsedArticle:
    doi: str
    version: int
    title: str
    abstract: str
    root: ET.Element


def _parse_article(raw: bytes, *, expected_doi: str) -> _ParsedArticle:
    if len(raw) > 16 * 1024 * 1024 or b"<!ENTITY" in raw.upper():
        raise ValueError("F1000 article XML violates parser bounds")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ValueError("F1000 article XML is invalid") from exc
    if sum(1 for _ in root.iter()) > _MAX_XML_NODES:
        raise ValueError("F1000 article XML exceeds its node ceiling")
    doi_node = root.find("./front/article-meta/article-id[@pub-id-type='doi']")
    doi = _text(doi_node).casefold()
    if doi != expected_doi.casefold():
        raise ValueError("F1000 article XML DOI differs from the selected source")
    base, version = _parse_doi(doi)
    del base
    license_node = root.find("./front/article-meta/permissions/license")
    if license_node is None or not _CC_BY.fullmatch(license_node.attrib.get(_XLINK_HREF, "")):
        raise ValueError("F1000 selected article lacks a supported CC-BY license")
    title = _clean(_text(root.find("./front/article-meta/title-group/article-title")))
    abstract = _clean(_text(root.find("./front/article-meta/abstract")))
    if not title or not abstract:
        raise ValueError("F1000 selected article lacks title or abstract content")
    return _ParsedArticle(doi=doi, version=version, title=title, abstract=abstract, root=root)


def _review_candidates(
    *,
    reviewed: _ParsedArticle,
    revised: _ParsedArticle,
    source: F1000SelectedSource,
    source_group_id: str,
    receipt_sha256: str,
) -> list[F1000TasteCandidate]:
    if reviewed.version != 1 or revised.version != source.latest_version:
        raise ValueError("F1000 article pair versions differ from their receipt")
    result: list[F1000TasteCandidate] = []
    for report in revised.root.findall("./sub-article[@article-type='reviewer-report']"):
        related = report.find("./front-stub/related-article")
        related_doi = related.attrib.get(_XLINK_HREF, "") if related is not None else ""
        if related_doi.casefold() != source.reviewed_doi.casefold():
            continue
        license_node = report.find("./front-stub/permissions/license")
        if license_node is None or not _CC_BY.fullmatch(license_node.attrib.get(_XLINK_HREF, "")):
            raise ValueError("F1000 selected review lacks a supported CC-BY license")
        review_text = _clean(_text(report.find("./body")))
        if not review_text:
            continue
        report_id = report.attrib.get("id", "")
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", report_id):
            raise ValueError("F1000 review report has an unsafe identity")
        responses = [
            _clean(_text(item.find("./body")))
            for item in report.findall("./sub-article[@article-type='response']")
        ]
        response = _clean("\n\n".join(item for item in responses if item)) or None
        recommendation = _recommendation(report)
        result.append(
            F1000TasteCandidate(
                candidate_id=_opaque_id(
                    "f1000-candidate", receipt_sha256, source.base_doi, report_id
                ),
                source_group_id=source_group_id,
                source_domain=source.domain_id,
                domain_basis="publisher-subject-query-pending-independent-review",
                latest_version=source.latest_version,
                article_title=revised.title,
                reviewed_abstract=reviewed.abstract,
                revised_abstract=revised.abstract,
                review_comment=review_text,
                author_response=response,
                recommendation=recommendation,
            )
        )
    return result


def _recommendation(report: ET.Element) -> str:
    raw = ""
    for item in report.findall("./front-stub/custom-meta-group/custom-meta"):
        if _text(item.find("./meta-name")).casefold() == "recommendation":
            raw = " ".join(_text(item.find("./meta-value")).casefold().split())
            break
    mapping = {
        "approved": "approved",
        "approve": "approved",
        "approved with reservations": "approved-with-reservations",
        "approved-with-reservations": "approved-with-reservations",
        "approve-with-reservations": "approved-with-reservations",
        "not approved": "not-approved",
        "not-approved": "not-approved",
        "reject": "not-approved",
    }
    return mapping.get(raw, "unknown")


def _select_disjoint_sources(
    plan: F1000DomainAcquisitionPlan,
    candidates_by_domain: Mapping[str, Mapping[str, tuple[str, int]]],
) -> list[tuple[str, str, str, int]]:
    selected: list[tuple[str, str, str, int]] = []
    used: set[str] = set()
    for stratum in plan.strata:
        candidates = candidates_by_domain[stratum.domain_id]
        ranked = sorted(
            candidates.items(),
            key=lambda item: (
                hashlib.sha256(
                    f"{plan.selection_salt}\0{stratum.domain_id}\0{item[0]}".encode()
                ).hexdigest(),
                item[0],
            ),
        )
        admitted = [
            item
            for item in ranked
            if item[0] not in used
            and canonical_f1000_source_group_id(item[0])
            not in plan.excluded_canonical_source_group_ids
        ][: stratum.target_source_groups]
        if len(admitted) != stratum.target_source_groups:
            raise ValueError(f"F1000 domain {stratum.domain_id} lacks disjoint versioned sources")
        for base, (latest_doi, latest_version) in admitted:
            selected.append((stratum.domain_id, base, latest_doi, latest_version))
            used.add(base)
    return selected


def _parse_search_response(raw: bytes) -> tuple[tuple[str, ...], int]:
    if len(raw) > 4 * 1024 * 1024 or b"<!ENTITY" in raw.upper():
        raise ValueError("F1000 search XML violates parser bounds")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ValueError("F1000 search response is invalid XML") from exc
    if root.tag != "results" or set(root.attrib) != {
        "numberOfResultsInPage",
        "totalNumberOfPages",
    }:
        raise ValueError("F1000 search response schema changed")
    try:
        page_count = int(root.attrib["totalNumberOfPages"])
        result_count = int(root.attrib["numberOfResultsInPage"])
    except ValueError as exc:
        raise ValueError("F1000 search response counts are invalid") from exc
    dois = tuple(_text(item).casefold() for item in root.findall("./doi"))
    if result_count != len(dois) or not 0 <= result_count <= 100 or page_count < 1:
        raise ValueError("F1000 search response item counts are inconsistent")
    for doi in dois:
        _parse_doi(doi)
    return dois, page_count


def _verify_article_identity(raw: bytes, expected_doi: str) -> None:
    parsed = _parse_article(raw, expected_doi=expected_doi)
    if parsed.doi != expected_doi.casefold():
        raise ValueError("F1000 article identity mismatch")


def _parse_doi(value: str) -> tuple[str, int]:
    match = _DOI.fullmatch(value.strip())
    if match is None:
        raise ValueError(f"unsupported F1000 DOI: {value}")
    return match.group("base").casefold(), int(match.group("version"))


def _search_url(subject_query: str, page: int, rows: int) -> str:
    query = urlencode({"q": f'R_SUB:"{subject_query}"', "rows": str(rows), "page": str(page)})
    return f"https://f1000research.com/extapi/search?{query}"


def _article_url(doi: str) -> str:
    return f"https://f1000research.com/extapi/article/xml?{urlencode({'doi': doi})}"


def _official_url(value: str) -> None:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "f1000research.com"
        or parsed.port not in {None, 443}
        or parsed.username
        or parsed.password
        or parsed.fragment
        or parsed.path not in {"/extapi/search", "/extapi/article/xml"}
    ):
        raise ValueError("F1000 request escaped the official API")


def _bound_file(root: Path, locator: str) -> Path:
    _relative_locator(locator)
    candidate = root.joinpath(*Path(locator).parts)
    if candidate.is_symlink() or not candidate.is_file():
        raise ValueError(f"F1000 bundle file is unavailable: {locator}")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise ValueError("F1000 bundle file escaped its transaction")
    return resolved


def _relative_locator(value: str) -> None:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise ValueError("F1000 bundle locator must be normalized and relative")


def _text(element: ET.Element | None) -> str:
    return "" if element is None else " ".join("".join(element.itertext()).split())


def _clean(value: str) -> str:
    return _EMAIL.sub("[redacted-email]", " ".join(value.split()))[:_MAX_TEXT_CHARS].strip()


def _opaque_id(prefix: str, *values: str) -> str:
    payload = "\0".join(values).encode()
    return f"{prefix}-{hashlib.sha256(payload).hexdigest()[:24]}"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_FETCH_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _write_new(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        del req, fp, code, msg, headers, newurl
        return None


__all__ = [
    "F1000DomainAcquisitionPlan",
    "F1000DomainAcquisitionReceipt",
    "F1000DomainStratum",
    "F1000HTTPResponse",
    "F1000TasteCandidate",
    "F1000TastePopulationReport",
    "F1000Transport",
    "MaterializedF1000Acquisition",
    "PublicF1000Transport",
    "acquire_f1000_domain_sources",
    "load_f1000_domain_acquisition_plan",
    "load_f1000_domain_acquisition_receipt",
    "materialize_f1000_taste_population",
    "publish_f1000_taste_population_run",
]
