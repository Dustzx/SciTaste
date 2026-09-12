"""Bounded, metadata-only execution for Scientific Reference mining queries."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal, Protocol
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

import yaml
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, computed_field, model_validator

from scitaste.taste.reference_mining import (
    ReferenceCandidateMetadata,
    ReferenceIsolationStatus,
    ReferenceMetadataIdentityStatus,
    ReferenceMetadataRelevanceStatus,
    ReferenceMiningBatch,
    ReferenceMiningNeed,
    ReferenceMiningProposal,
    ReferenceMiningReport,
    ReferenceMiningRun,
    ReferenceRightsStatus,
    ReferenceSearchQuery,
    VerifiedReferenceMining,
    compile_reference_mining_report,
)

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_CONFIG_BYTES = 256 * 1024
_MAX_BUNDLE_BYTES = 256 * 1024 * 1024
_FORBIDDEN_WORK_FIELDS = {
    "abstract",
    "abstract_inverted_index",
    "body",
    "content",
    "fulltext",
    "full_text",
}


class ReferenceMetadataProvider(StrEnum):
    """Public scholarly indexes supported by the first-party connector."""

    OPENALEX = "openalex"
    CROSSREF = "crossref"


class ReferenceSearchBatchSpec(BaseModel):
    """One index/page pass over every accepted query."""

    model_config = _CONFIG

    provider: ReferenceMetadataProvider
    page: int = Field(ge=1, le=100)
    minimum_interval_seconds: float = Field(ge=0.0, le=10.0)


class ReferenceSearchExecutionConfig(BaseModel):
    """Closed network and response envelope for metadata-only search."""

    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1"] = "1.1"
    execution_id: str = Field(pattern=_ID)
    batches: tuple[ReferenceSearchBatchSpec, ...] = Field(min_length=3, max_length=30)
    per_query_results: int = Field(ge=1, le=100)
    max_requests: int = Field(ge=3, le=1_000)
    max_response_bytes: int = Field(ge=1_024, le=16 * 1024 * 1024)
    max_total_response_bytes: int = Field(ge=3_072, le=_MAX_BUNDLE_BYTES)
    timeout_seconds: float = Field(ge=1.0, le=120.0)
    user_agent: str = Field(min_length=10, max_length=500)
    held_out_source_group_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=1_000)
    self_development_source_group_ids: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=1_000,
    )
    metadata_relevance_anchor_terms: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=100,
    )
    min_metadata_anchor_matches: int = Field(default=0, ge=0, le=20)
    metadata_domain_anchor_terms: dict[str, tuple[str, ...]] = Field(
        default_factory=dict,
        max_length=20,
    )
    metadata_domain_min_anchor_matches: dict[str, int] = Field(
        default_factory=dict,
        max_length=20,
    )
    credential_free_public_metadata_only: Literal[True] = True
    source_bodies_requested: Literal[False] = False

    @model_validator(mode="after")
    def execution_is_diverse_and_bounded(self) -> ReferenceSearchExecutionConfig:
        identities = [(item.provider, item.page) for item in self.batches]
        if len(identities) != len(set(identities)):
            raise ValueError("reference-search provider/page batches must be unique")
        if {item.provider for item in self.batches} != set(ReferenceMetadataProvider):
            raise ValueError("reference search must use both OpenAlex and Crossref")
        exclusions = (*self.held_out_source_group_ids, *self.self_development_source_group_ids)
        if len(exclusions) != len(set(exclusions)):
            raise ValueError("reference-search source-group exclusions must be disjoint and unique")
        if any(not _safe_id(value) for value in exclusions):
            raise ValueError("reference-search exclusions must be safe source-group IDs")
        normalized_anchors = [
            " ".join(term.casefold().split()) for term in self.metadata_relevance_anchor_terms
        ]
        if any(not term for term in normalized_anchors) or len(normalized_anchors) != len(
            set(normalized_anchors)
        ):
            raise ValueError("reference-search metadata anchors must be nonempty and unique")
        if self.min_metadata_anchor_matches > len(normalized_anchors):
            raise ValueError("reference-search metadata anchor floor exceeds its inventory")
        for facet, terms in self.metadata_domain_anchor_terms.items():
            if not _safe_id(facet) or not terms:
                raise ValueError("reference-search domain anchor map is invalid")
            normalized_terms = [" ".join(term.casefold().split()) for term in terms]
            if any(not term for term in normalized_terms) or len(normalized_terms) != len(
                set(normalized_terms)
            ):
                raise ValueError("reference-search domain anchors must be nonempty and unique")
        if set(self.metadata_domain_min_anchor_matches) != set(self.metadata_domain_anchor_terms):
            raise ValueError("reference-search domain anchor floors must match their facets")
        for facet, minimum in self.metadata_domain_min_anchor_matches.items():
            if not 1 <= minimum <= len(self.metadata_domain_anchor_terms[facet]):
                raise ValueError("reference-search domain anchor floor is outside its inventory")
        return self

    @computed_field
    @property
    def config_sha256(self) -> str:
        return _semantic_sha256(self, exclude={"config_sha256"})


class ReferenceSearchRequestEvidence(BaseModel):
    """One exact public metadata response retained inside the atomic bundle."""

    model_config = _CONFIG

    batch_index: int = Field(ge=1, le=30)
    provider: ReferenceMetadataProvider
    page: int = Field(ge=1, le=100)
    query_id: str = Field(pattern=_ID)
    request_url: HttpUrl
    request_sha256: str = Field(pattern=_SHA256)
    response_locator: str = Field(min_length=1, max_length=2_000)
    response_sha256: str = Field(pattern=_SHA256)
    response_bytes: int = Field(ge=1)
    returned_item_count: int = Field(ge=0)
    parsed_item_count: int = Field(ge=0)
    provider_reported_cost_usd: float | None = Field(default=None, ge=0.0)
    content_type: Literal["application/json"] = "application/json"
    source_body_fields_received: Literal[False] = False

    @model_validator(mode="after")
    def request_identity_is_bound(self) -> ReferenceSearchRequestEvidence:
        expected = hashlib.sha256(str(self.request_url).encode()).hexdigest()
        if self.request_sha256 != expected:
            raise ValueError("reference-search request URL hash mismatch")
        return self


class ReferenceSearchExecutionReceipt(BaseModel):
    """Content-addressed receipt for one metadata-only search transaction."""

    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1", "1.2", "1.3"] = "1.3"
    execution_id: str = Field(pattern=_ID)
    completed_at: datetime
    need_sha256: str = Field(pattern=_SHA256)
    proposal_sha256: str = Field(pattern=_SHA256)
    proposal_ledger_locator: str = Field(min_length=1, max_length=2_000)
    proposal_ledger_sha256: str = Field(pattern=_SHA256)
    proposal_backend: str = Field(min_length=1, max_length=200)
    proposal_model: str = Field(min_length=1, max_length=300)
    config_sha256: str = Field(pattern=_SHA256)
    need_locator: Literal["NEED.json"] | None = None
    need_file_sha256: str | None = Field(default=None, pattern=_SHA256)
    proposal_locator: Literal["PROPOSAL.json"] | None = None
    proposal_file_sha256: str | None = Field(default=None, pattern=_SHA256)
    config_locator: Literal["CONFIG.json"] | None = None
    config_file_sha256: str | None = Field(default=None, pattern=_SHA256)
    run_locator: Literal["RUN.json"] = "RUN.json"
    run_file_sha256: str = Field(pattern=_SHA256)
    run_sha256: str = Field(pattern=_SHA256)
    report_locator: Literal["REPORT.json"] = "REPORT.json"
    report_file_sha256: str = Field(pattern=_SHA256)
    report_sha256: str = Field(pattern=_SHA256)
    requests: tuple[ReferenceSearchRequestEvidence, ...] = Field(min_length=1, max_length=1_000)
    executed_batch_count: int = Field(ge=1, le=30)
    request_count: int = Field(ge=1, le=1_000)
    response_bytes: int = Field(ge=1, le=_MAX_BUNDLE_BYTES)
    parsed_candidate_count: int = Field(ge=0)
    selected_candidate_count: int = Field(ge=0)
    distinct_source_group_count: int = Field(ge=0)
    cohort_ready_for_reference_quality: bool
    source_indexes: tuple[ReferenceMetadataProvider, ...] = Field(min_length=2, max_length=2)
    network_requests_performed: bool = True
    network_request_count: int | None = Field(default=None, ge=0, le=1_000)
    source_bundle_receipt_sha256: str | None = Field(default=None, pattern=_SHA256)
    credential_used: Literal[False] = False
    source_content_requested: Literal[False] = False
    source_content_read: Literal[False] = False
    quality_assessed: Literal[False] = False
    authorizes_download: Literal[False] = False
    authorizes_source_content_access: Literal[False] = False
    authorizes_reference_quality: Literal[False] = False
    authorizes_model_or_gpu_use: Literal[False] = False
    authorizes_experiment: Literal[False] = False

    @model_validator(mode="after")
    def receipt_counts_are_consistent(self) -> ReferenceSearchExecutionReceipt:
        if self.request_count != len(self.requests):
            raise ValueError("reference-search request count differs from its evidence")
        if self.executed_batch_count != len({item.batch_index for item in self.requests}):
            raise ValueError("reference-search batch count differs from its evidence")
        if self.response_bytes != sum(item.response_bytes for item in self.requests):
            raise ValueError("reference-search response bytes differ from request evidence")
        if tuple(sorted(set(self.source_indexes))) != tuple(sorted(ReferenceMetadataProvider)):
            raise ValueError("reference-search receipt must retain both source indexes")
        request_urls = [str(item.request_url) for item in self.requests]
        response_locators = [item.response_locator for item in self.requests]
        if len(request_urls) != len(set(request_urls)):
            raise ValueError("reference-search request URLs must be unique")
        if len(response_locators) != len(set(response_locators)):
            raise ValueError("reference-search response locators must be unique")
        control_pairs = (
            (self.need_locator, self.need_file_sha256),
            (self.proposal_locator, self.proposal_file_sha256),
            (self.config_locator, self.config_file_sha256),
        )
        if any((locator is None) != (digest is None) for locator, digest in control_pairs):
            raise ValueError("reference-search control-file locator and hash must be atomic")
        if self.schema_version == "1.3" and any(
            locator is None or digest is None for locator, digest in control_pairs
        ):
            raise ValueError("reference-search schema 1.3 must bind every control file")
        if self.schema_version == "1.0":
            if (
                not self.network_requests_performed
                or self.network_request_count is not None
                or self.source_bundle_receipt_sha256 is not None
            ):
                raise ValueError("legacy reference-search receipts cannot describe replay")
        elif self.network_requests_performed:
            if self.network_request_count not in {None, self.request_count}:
                raise ValueError("live reference-search network count differs from requests")
            if self.source_bundle_receipt_sha256 is not None:
                raise ValueError("live reference search cannot name a replay source")
        elif self.network_request_count != 0 or self.source_bundle_receipt_sha256 is None:
            raise ValueError(
                "recorded reference search must bind its source and zero network calls"
            )
        return self

    @computed_field
    @property
    def receipt_sha256(self) -> str:
        excluded = {"receipt_sha256"}
        if self.schema_version in {"1.0", "1.1", "1.2"}:
            excluded.update(
                {
                    "config_file_sha256",
                    "config_locator",
                    "need_file_sha256",
                    "need_locator",
                    "proposal_file_sha256",
                    "proposal_locator",
                }
            )
        if self.schema_version == "1.0":
            excluded.update(
                {
                    "network_request_count",
                    "network_requests_performed",
                    "source_bundle_receipt_sha256",
                }
            )
        return _semantic_sha256(self, exclude=excluded)


@dataclass(frozen=True)
class ReferenceMetadataHTTPResponse:
    status_code: int
    url: str
    headers: Mapping[str, str]
    body: bytes


class ReferenceMetadataTransport(Protocol):
    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
        maximum_bytes: int,
    ) -> ReferenceMetadataHTTPResponse: ...


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        del req, fp, code, msg, headers, newurl
        return None


class PublicReferenceMetadataTransport:
    """Credential-free HTTPS transport with redirects and oversized bodies disabled."""

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
        maximum_bytes: int,
    ) -> ReferenceMetadataHTTPResponse:
        opener = build_opener(_NoRedirect())
        request = Request(url, headers=dict(headers), method="GET")
        with opener.open(request, timeout=timeout) as response:
            body = response.read(maximum_bytes + 1)
            if len(body) > maximum_bytes:
                raise ValueError("reference-search response exceeds its byte ceiling")
            return ReferenceMetadataHTTPResponse(
                status_code=response.status,
                url=response.geturl(),
                headers={key.casefold(): value for key, value in response.headers.items()},
                body=body,
            )


@dataclass(frozen=True)
class MaterializedReferenceSearch:
    output_dir: Path
    run_path: Path
    report_path: Path
    receipt_path: Path
    run: ReferenceMiningRun
    report: ReferenceMiningReport
    receipt: ReferenceSearchExecutionReceipt


@dataclass(frozen=True)
class _MetadataHit:
    identity: str
    title: str
    locator: str
    venue: str | None
    citation_count: int | None
    publication_year: int | None


@dataclass
class _CandidateAccumulator:
    hit: _MetadataHit
    query_ids: set[str]
    patterns: set
    roles: set
    domains: set[str]
    provider_titles: dict[ReferenceMetadataProvider, set[str]]
    best_result_rank: int
    observation_count: int


def load_reference_search_config(path: str | Path) -> ReferenceSearchExecutionConfig:
    source = Path(path)
    if source.is_symlink():
        raise ValueError("reference-search config must not be a symlink")
    resolved = source.resolve(strict=True)
    if not resolved.is_file() or not 1 <= resolved.stat().st_size <= _MAX_CONFIG_BYTES:
        raise ValueError("reference-search config must be a bounded regular file")
    try:
        payload = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError("reference-search config must be UTF-8 YAML or JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("reference-search config must contain a mapping")
    return ReferenceSearchExecutionConfig.model_validate(payload)


def execute_reference_search(
    verified: VerifiedReferenceMining,
    config: ReferenceSearchExecutionConfig,
    *,
    output_dir: str | Path,
    allow_network_search: bool,
    transport: ReferenceMetadataTransport | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    network_requests_performed: bool = True,
    source_bundle_receipt_sha256: str | None = None,
) -> MaterializedReferenceSearch:
    """Execute an accepted query plan and atomically publish metadata-only evidence."""

    if network_requests_performed and not allow_network_search:
        raise ValueError("reference search requires --allow-network-search")
    if not network_requests_performed and transport is None:
        raise ValueError("recorded reference search requires an explicit replay transport")
    if network_requests_performed != (source_bundle_receipt_sha256 is None):
        raise ValueError("reference-search replay source does not match its execution mode")
    queries = verified.proposal.queries
    if verified.input.metadata_relevance_anchor_terms and (
        tuple(config.metadata_relevance_anchor_terms)
        != tuple(verified.input.metadata_relevance_anchor_terms)
        or config.min_metadata_anchor_matches != verified.input.min_metadata_anchor_matches
    ):
        raise ValueError("reference-search metadata gate differs from the accepted need")
    if verified.input.metadata_relevance_anchor_terms and set(
        config.metadata_domain_anchor_terms
    ) != set(verified.input.required_domain_facets):
        raise ValueError("reference-search domain anchor map differs from the accepted need")
    if len(config.batches) > verified.input.max_batches:
        raise ValueError("reference-search config exceeds the registered batch budget")
    planned_requests = len(config.batches) * len(queries)
    if planned_requests > config.max_requests:
        raise ValueError("reference-search config exceeds the request budget")
    if config.per_query_results * len(queries) > 500:
        raise ValueError("reference-search batch could exceed the candidate-count schema")

    target = Path(output_dir)
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{target.name}.", suffix=".staging", dir=target.parent)
    )
    client = transport or PublicReferenceMetadataTransport()
    response_total = 0
    request_evidence: list[ReferenceSearchRequestEvidence] = []
    batches: list[ReferenceMiningBatch] = []
    seen: dict[str, str] = {}
    all_accumulators: dict[str, _CandidateAccumulator] = {}
    last_request_at: dict[ReferenceMetadataProvider, float] = {}
    try:
        need_path = staging / "NEED.json"
        proposal_path = staging / "PROPOSAL.json"
        config_path = staging / "CONFIG.json"
        _write_json(
            need_path,
            verified.input.model_dump(mode="json", exclude_computed_fields=True),
        )
        _write_json(
            proposal_path,
            verified.proposal.model_dump(mode="json", exclude_computed_fields=True),
        )
        _write_json(
            config_path,
            config.model_dump(mode="json", exclude_computed_fields=True),
        )
        responses = staging / "responses"
        responses.mkdir()
        report: ReferenceMiningReport | None = None
        for batch_index, spec in enumerate(config.batches, start=1):
            accumulators: dict[str, _CandidateAccumulator] = {}
            duplicate_ids: set[str] = set()
            for query in queries:
                previous = last_request_at.get(spec.provider)
                if previous is not None:
                    elapsed = time.monotonic() - previous
                    wait = spec.minimum_interval_seconds - elapsed
                    if wait > 0:
                        sleeper(wait)
                url = _request_url(spec.provider, query, spec.page, config.per_query_results)
                response = client.get(
                    url,
                    headers={
                        "Accept": "application/json",
                        "Accept-Encoding": "identity",
                        "User-Agent": config.user_agent,
                    },
                    timeout=config.timeout_seconds,
                    maximum_bytes=config.max_response_bytes,
                )
                last_request_at[spec.provider] = time.monotonic()
                payload = _validated_json_response(response, requested_url=url)
                hits, returned_count, cost = _metadata_hits(spec.provider, payload)
                response_total += len(response.body)
                if response_total > config.max_total_response_bytes:
                    raise ValueError("reference-search transaction exceeds total response bytes")
                response_name = f"{batch_index:02d}__{spec.provider.value}__{query.query_id}.json"
                response_path = responses / response_name
                _write_bytes(response_path, response.body)
                locator = response_path.relative_to(staging).as_posix()
                request_evidence.append(
                    ReferenceSearchRequestEvidence(
                        batch_index=batch_index,
                        provider=spec.provider,
                        page=spec.page,
                        query_id=query.query_id,
                        request_url=url,
                        request_sha256=hashlib.sha256(url.encode()).hexdigest(),
                        response_locator=locator,
                        response_sha256=hashlib.sha256(response.body).hexdigest(),
                        response_bytes=len(response.body),
                        returned_item_count=returned_count,
                        parsed_item_count=len(hits),
                        provider_reported_cost_usd=cost,
                    )
                )
                for local_rank, hit in enumerate(hits, start=1):
                    source_group_id = _source_group_id(hit.identity)
                    accumulator = all_accumulators.get(source_group_id)
                    if accumulator is None:
                        accumulator = _CandidateAccumulator(
                            hit=hit,
                            query_ids=set(),
                            patterns=set(),
                            roles=set(),
                            domains=set(),
                            provider_titles={},
                            best_result_rank=(spec.page - 1) * config.per_query_results
                            + local_rank,
                            observation_count=0,
                        )
                        all_accumulators[source_group_id] = accumulator
                        accumulators[source_group_id] = accumulator
                    elif source_group_id in seen:
                        duplicate_ids.add(seen[source_group_id])
                    accumulator.query_ids.add(query.query_id)
                    accumulator.patterns.update(query.targeted_decision_patterns)
                    accumulator.roles.update(query.targeted_evidence_roles)
                    accumulator.domains.update(query.targeted_domain_facets)
                    accumulator.provider_titles.setdefault(spec.provider, set()).add(hit.title)
                    accumulator.best_result_rank = min(
                        accumulator.best_result_rank,
                        (spec.page - 1) * config.per_query_results + local_rank,
                    )
                    accumulator.observation_count += 1

            candidates = tuple(
                _candidate_from_accumulator(group_id, accumulator, config)
                for group_id, accumulator in sorted(accumulators.items())
            )
            for candidate in candidates:
                seen[candidate.source_group_id] = candidate.candidate_id
            batch = ReferenceMiningBatch(
                batch_index=batch_index,
                query_ids=tuple(query.query_id for query in queries),
                candidates=candidates,
                duplicate_candidate_ids=tuple(sorted(duplicate_ids)),
            )
            batches.append(batch)
            enriched_batches = _enriched_batches(batches, all_accumulators, config)
            partial = ReferenceMiningRun(
                schema_version=("1.2" if config.metadata_domain_anchor_terms else "1.1"),
                need=verified.input,
                proposal=verified.proposal,
                batches=enriched_batches,
            )
            report = compile_reference_mining_report(partial)
            if report.search_saturated:
                break

        final_batches = _enriched_batches(batches, all_accumulators, config)
        completion_check = getattr(client, "assert_complete", None)
        if callable(completion_check):
            completion_check()
        run = ReferenceMiningRun(
            schema_version=("1.2" if config.metadata_domain_anchor_terms else "1.1"),
            need=verified.input,
            proposal=verified.proposal,
            batches=final_batches,
        )
        report = compile_reference_mining_report(run)
        run_path = staging / "RUN.json"
        report_path = staging / "REPORT.json"
        _write_json(run_path, run.model_dump(mode="json", exclude_computed_fields=True))
        _write_json(report_path, report.model_dump(mode="json"))
        receipt = ReferenceSearchExecutionReceipt(
            schema_version="1.3",
            execution_id=config.execution_id,
            completed_at=datetime.now(UTC),
            need_sha256=verified.input.need_sha256,
            proposal_sha256=verified.proposal.proposal_sha256,
            proposal_ledger_locator=verified.ledger_locator,
            proposal_ledger_sha256=verified.ledger_sha256,
            proposal_backend=verified.backend,
            proposal_model=verified.model,
            config_sha256=config.config_sha256,
            need_locator="NEED.json",
            need_file_sha256=_sha256_file(need_path),
            proposal_locator="PROPOSAL.json",
            proposal_file_sha256=_sha256_file(proposal_path),
            config_locator="CONFIG.json",
            config_file_sha256=_sha256_file(config_path),
            run_file_sha256=_sha256_file(run_path),
            run_sha256=run.run_sha256,
            report_file_sha256=_sha256_file(report_path),
            report_sha256=report.report_sha256,
            requests=tuple(request_evidence),
            executed_batch_count=len(batches),
            request_count=len(request_evidence),
            response_bytes=response_total,
            parsed_candidate_count=sum(len(batch.candidates) for batch in batches),
            selected_candidate_count=len(report.selected_candidate_ids),
            distinct_source_group_count=len(report.selected_source_group_ids),
            cohort_ready_for_reference_quality=report.cohort_ready_for_reference_quality,
            source_indexes=tuple(sorted(set(item.provider for item in request_evidence))),
            network_requests_performed=network_requests_performed,
            network_request_count=len(request_evidence) if network_requests_performed else 0,
            source_bundle_receipt_sha256=source_bundle_receipt_sha256,
        )
        receipt_path = staging / "RECEIPT.json"
        _write_json(receipt_path, receipt.model_dump(mode="json"))
        os.replace(staging, target)
        return MaterializedReferenceSearch(
            output_dir=target,
            run_path=target / "RUN.json",
            report_path=target / "REPORT.json",
            receipt_path=target / "RECEIPT.json",
            run=run,
            report=report,
            receipt=receipt,
        )
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def load_reference_search_receipt(
    path: str | Path,
    *,
    verify_bundle: bool = True,
) -> ReferenceSearchExecutionReceipt:
    """Load the receipt and optionally rehash every file in its metadata bundle."""

    source = Path(path)
    if source.is_symlink():
        raise ValueError("reference-search receipt must not be a symlink")
    resolved = source.resolve(strict=True)
    payload = _load_json_mapping(resolved, maximum_bytes=_MAX_CONFIG_BYTES)
    recorded_hash = payload.pop("receipt_sha256", None)
    receipt = ReferenceSearchExecutionReceipt.model_validate(payload)
    if recorded_hash != receipt.receipt_sha256:
        raise ValueError("reference-search receipt self-hash mismatch")
    if not verify_bundle:
        return receipt
    root = resolved.parent.resolve(strict=True)
    expected = {
        receipt.run_locator: receipt.run_file_sha256,
        receipt.report_locator: receipt.report_file_sha256,
        **{item.response_locator: item.response_sha256 for item in receipt.requests},
    }
    for locator, digest in (
        (receipt.need_locator, receipt.need_file_sha256),
        (receipt.proposal_locator, receipt.proposal_file_sha256),
        (receipt.config_locator, receipt.config_file_sha256),
    ):
        if locator is not None and digest is not None:
            expected[locator] = digest
    for locator, digest in expected.items():
        candidate = _safe_bound_file(root, locator)
        if _sha256_file(candidate) != digest:
            raise ValueError(f"reference-search bundle hash mismatch: {locator}")
    if receipt.need_locator is not None:
        need = ReferenceMiningNeed.model_validate(
            _load_json_mapping(
                _safe_bound_file(root, receipt.need_locator),
                maximum_bytes=_MAX_CONFIG_BYTES,
            )
        )
        if need.need_sha256 != receipt.need_sha256:
            raise ValueError("reference-search bound need identity mismatch")
    if receipt.proposal_locator is not None:
        proposal = ReferenceMiningProposal.model_validate(
            _load_json_mapping(
                _safe_bound_file(root, receipt.proposal_locator),
                maximum_bytes=_MAX_CONFIG_BYTES,
            )
        )
        if proposal.proposal_sha256 != receipt.proposal_sha256:
            raise ValueError("reference-search bound proposal identity mismatch")
    if receipt.config_locator is not None:
        config = load_reference_search_config(_safe_bound_file(root, receipt.config_locator))
        if config.config_sha256 != receipt.config_sha256:
            raise ValueError("reference-search bound config identity mismatch")
    run = ReferenceMiningRun.model_validate(
        _load_json_mapping(_safe_bound_file(root, receipt.run_locator), maximum_bytes=16 << 20)
    )
    report_payload = _load_json_mapping(
        _safe_bound_file(root, receipt.report_locator),
        maximum_bytes=4 << 20,
    )
    report_payload.pop("report_sha256", None)
    report = ReferenceMiningReport.model_validate(report_payload)
    identities_match = (
        run.run_sha256 == receipt.run_sha256 and report.report_sha256 == receipt.report_sha256
    )
    derivation_matches = (
        receipt.schema_version == "1.0" or compile_reference_mining_report(run) == report
    )
    if not identities_match or not derivation_matches:
        raise ValueError("reference-search derived run or report identity mismatch")
    return receipt


def replay_reference_search(
    source_receipt_path: str | Path,
    verified: VerifiedReferenceMining,
    config: ReferenceSearchExecutionConfig,
    *,
    output_dir: str | Path,
) -> MaterializedReferenceSearch:
    """Recompile a frozen metadata transaction without a network request."""

    source_path = Path(source_receipt_path).resolve(strict=True)
    source = load_reference_search_receipt(source_path)
    if source.need_sha256 != verified.input.need_sha256:
        raise ValueError("recorded reference-search need differs from the verified need")
    if source.proposal_sha256 != verified.proposal.proposal_sha256:
        raise ValueError("recorded reference-search proposal differs from the verified proposal")
    source_root = source_path.parent.resolve(strict=True)
    expected_query_ids = {query.query_id for query in verified.proposal.queries}
    scheduled: list[ReferenceSearchBatchSpec] = []
    responses: dict[str, ReferenceMetadataHTTPResponse] = {}
    by_batch: dict[int, list[ReferenceSearchRequestEvidence]] = {}
    for request in source.requests:
        by_batch.setdefault(request.batch_index, []).append(request)
        url = str(request.request_url)
        if url in responses:
            raise ValueError("recorded reference-search request URL is not unique")
        responses[url] = ReferenceMetadataHTTPResponse(
            status_code=200,
            url=url,
            headers={"content-type": "application/json"},
            body=_safe_bound_file(source_root, request.response_locator).read_bytes(),
        )
    configured_batches = {(item.provider, item.page): item for item in config.batches}
    for batch_index in range(1, source.executed_batch_count + 1):
        requests = by_batch.get(batch_index, [])
        identities = {(item.provider, item.page) for item in requests}
        query_ids = {item.query_id for item in requests}
        if len(identities) != 1 or query_ids != expected_query_ids:
            raise ValueError("recorded reference-search batch does not match the accepted proposal")
        identity = identities.pop()
        if identity not in configured_batches:
            raise ValueError("recorded reference-search batch is outside the supplied config")
        scheduled.append(
            configured_batches[identity].model_copy(update={"minimum_interval_seconds": 0.0})
        )
    replay_payload = config.model_dump(mode="python", exclude_computed_fields=True)
    replay_payload["batches"] = tuple(scheduled)
    replay_payload["max_requests"] = max(len(responses), 3)
    replay_config = ReferenceSearchExecutionConfig.model_validate(replay_payload)
    transport = _RecordedReferenceMetadataTransport(responses)
    return execute_reference_search(
        verified,
        replay_config,
        output_dir=output_dir,
        allow_network_search=False,
        transport=transport,
        sleeper=lambda _: None,
        network_requests_performed=False,
        source_bundle_receipt_sha256=source.receipt_sha256,
    )


class _RecordedReferenceMetadataTransport:
    def __init__(self, responses: Mapping[str, ReferenceMetadataHTTPResponse]) -> None:
        self._responses = dict(responses)
        self._consumed: set[str] = set()

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
        maximum_bytes: int,
    ) -> ReferenceMetadataHTTPResponse:
        del headers, timeout
        if url in self._consumed or url not in self._responses:
            raise ValueError("reference-search replay requested unrecorded metadata")
        response = self._responses[url]
        if len(response.body) > maximum_bytes:
            raise ValueError("recorded reference-search response exceeds the configured ceiling")
        self._consumed.add(url)
        return response

    def assert_complete(self) -> None:
        if self._consumed != set(self._responses):
            raise ValueError(
                "reference-search replay did not consume the complete frozen transaction"
            )


def _candidate_from_accumulator(
    source_group_id: str,
    accumulator: _CandidateAccumulator,
    config: ReferenceSearchExecutionConfig,
) -> ReferenceCandidateMetadata:
    if source_group_id in config.held_out_source_group_ids:
        isolation = ReferenceIsolationStatus.HELD_OUT
    elif source_group_id in config.self_development_source_group_ids:
        isolation = ReferenceIsolationStatus.SELF_DEVELOPMENT
    else:
        isolation = ReferenceIsolationStatus.ELIGIBLE_CANDIDATE
    provider_ids = tuple(sorted(provider.value for provider in accumulator.provider_titles))
    title_variants = tuple(
        sorted({title for titles in accumulator.provider_titles.values() for title in titles})
    )
    if len(accumulator.provider_titles) < 2:
        identity_status = ReferenceMetadataIdentityStatus.SINGLE_INDEX_UNVERIFIED
    elif _provider_titles_agree(accumulator.provider_titles):
        identity_status = ReferenceMetadataIdentityStatus.CROSS_INDEX_CORROBORATED
    else:
        identity_status = ReferenceMetadataIdentityStatus.CROSS_INDEX_CONFLICT
    anchor_matches = _metadata_anchor_matches(title_variants, config)
    grounded_domains = tuple(
        sorted(
            facet
            for facet, terms in config.metadata_domain_anchor_terms.items()
            if facet in accumulator.domains
            and sum(
                any(
                    _normalized_phrase_present(term, _normalized_words(title))
                    for title in title_variants
                )
                for term in terms
            )
            >= config.metadata_domain_min_anchor_matches[facet]
        )
    )
    if _is_administrative_record(title_variants):
        relevance_status = ReferenceMetadataRelevanceStatus.ADMINISTRATIVE_RECORD
    elif len(anchor_matches) < config.min_metadata_anchor_matches:
        relevance_status = ReferenceMetadataRelevanceStatus.INSUFFICIENT_ANCHOR_EVIDENCE
    else:
        relevance_status = ReferenceMetadataRelevanceStatus.ELIGIBLE
    return ReferenceCandidateMetadata(
        candidate_id=_candidate_id(accumulator.hit.identity),
        source_group_id=source_group_id,
        title=accumulator.hit.title,
        locator=accumulator.hit.locator,
        discovery_query_ids=tuple(sorted(accumulator.query_ids)),
        hypothesized_decision_patterns=tuple(sorted(accumulator.patterns)),
        hypothesized_evidence_roles=tuple(sorted(accumulator.roles)),
        domain_facets=tuple(sorted(accumulator.domains)),
        rights_status=ReferenceRightsStatus.COMPATIBLE_METADATA_ONLY,
        isolation_status=isolation,
        venue=accumulator.hit.venue,
        citation_count=accumulator.hit.citation_count,
        publication_year=accumulator.hit.publication_year,
        metadata_provider_ids=provider_ids,
        metadata_identity_status=identity_status,
        metadata_title_variants=title_variants,
        metadata_relevance_status=relevance_status,
        metadata_relevance_anchor_matches=anchor_matches,
        metadata_grounded_domain_facets=grounded_domains,
        best_result_rank=accumulator.best_result_rank,
        retrieval_observation_count=accumulator.observation_count,
    )


def _enriched_batches(
    batches: list[ReferenceMiningBatch],
    accumulators: Mapping[str, _CandidateAccumulator],
    config: ReferenceSearchExecutionConfig,
) -> tuple[ReferenceMiningBatch, ...]:
    """Apply all later index observations to each first-seen candidate."""

    return tuple(
        batch.model_copy(
            update={
                "candidates": tuple(
                    _candidate_from_accumulator(
                        candidate.source_group_id,
                        accumulators[candidate.source_group_id],
                        config,
                    )
                    for candidate in batch.candidates
                )
            }
        )
        for batch in batches
    )


def _provider_titles_agree(
    provider_titles: Mapping[ReferenceMetadataProvider, set[str]],
) -> bool:
    providers = sorted(provider_titles)
    for left_index, left_provider in enumerate(providers):
        for right_provider in providers[left_index + 1 :]:
            if not any(
                _titles_agree(left, right)
                for left in provider_titles[left_provider]
                for right in provider_titles[right_provider]
            ):
                return False
    return True


def _titles_agree(left: str, right: str) -> bool:
    normalized_left = " ".join(left.casefold().split())
    normalized_right = " ".join(right.casefold().split())
    if normalized_left == normalized_right:
        return True
    left_tokens = _title_tokens(left)
    right_tokens = _title_tokens(right)
    shorter = min(len(left_tokens), len(right_tokens))
    return shorter >= 3 and len(left_tokens & right_tokens) / shorter >= 0.75


def _title_tokens(value: str) -> set[str]:
    return {
        token
        for token in "".join(
            character if character.isalnum() else " " for character in value.casefold()
        ).split()
        if len(token) >= 3
    }


def _metadata_anchor_matches(
    title_variants: tuple[str, ...],
    config: ReferenceSearchExecutionConfig,
) -> tuple[str, ...]:
    normalized_titles = [_normalized_words(title) for title in title_variants]
    matches = {
        term
        for term in config.metadata_relevance_anchor_terms
        if any(_normalized_phrase_present(term, title) for title in normalized_titles)
    }
    return tuple(sorted(matches))


def _normalized_phrase_present(term: str, normalized_title: str) -> bool:
    normalized_term = _normalized_words(term)
    if not normalized_term:
        return False
    return f" {normalized_term} " in f" {normalized_title} "


def _normalized_words(value: str) -> str:
    return " ".join(
        "".join(character if character.isalnum() else " " for character in value.casefold()).split()
    )


def _is_administrative_record(title_variants: tuple[str, ...]) -> bool:
    prefixes = (
        "peer review report for",
        "reviewer report for",
        "supplementary material for",
        "supplementary file for",
    )
    return any(
        title.casefold().strip().startswith(prefixes)
        or re.match(r"^abstract\s+\d+\s*:", title.casefold().strip()) is not None
        for title in title_variants
    )


def _request_url(
    provider: ReferenceMetadataProvider,
    query: ReferenceSearchQuery,
    page: int,
    per_page: int,
) -> str:
    if provider is ReferenceMetadataProvider.OPENALEX:
        parameters = {
            "search": query.query_text,
            "page": str(page),
            "per_page": str(per_page),
            "select": "id,doi,title,publication_year,primary_location,cited_by_count",
        }
        return "https://api.openalex.org/works?" + urlencode(parameters, quote_via=quote)
    parameters = {
        "query.bibliographic": query.query_text,
        "rows": str(per_page),
        "offset": str((page - 1) * per_page),
        "select": "DOI,title,container-title,is-referenced-by-count,published,URL",
    }
    return "https://api.crossref.org/works?" + urlencode(parameters, quote_via=quote)


def _validated_json_response(
    response: ReferenceMetadataHTTPResponse,
    *,
    requested_url: str,
) -> dict[str, object]:
    if response.status_code != 200:
        raise ValueError(f"reference-search provider returned HTTP {response.status_code}")
    if response.url != requested_url:
        raise ValueError("reference-search provider redirected or changed the request URL")
    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().casefold()
    if content_type != "application/json":
        raise ValueError("reference-search provider did not return application/json")
    try:
        payload = json.loads(response.body, parse_constant=_reject_non_finite)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("reference-search provider returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("reference-search provider response must be an object")
    return payload


def _metadata_hits(
    provider: ReferenceMetadataProvider,
    payload: dict[str, object],
) -> tuple[list[_MetadataHit], int, float | None]:
    if provider is ReferenceMetadataProvider.OPENALEX:
        raw_items = payload.get("results")
        meta = payload.get("meta")
        cost = meta.get("cost_usd") if isinstance(meta, dict) else None
    else:
        message = payload.get("message")
        if not isinstance(message, dict):
            raise ValueError("Crossref metadata response lacks a message object")
        raw_items = message.get("items")
        cost = None
    if not isinstance(raw_items, list):
        raise ValueError("reference-search metadata response lacks a result array")
    hits: list[_MetadataHit] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            raise ValueError("reference-search work metadata must be an object")
        if _FORBIDDEN_WORK_FIELDS & {str(key).casefold() for key in raw}:
            raise ValueError("reference-search response unexpectedly contains source-body fields")
        hit = (
            _openalex_hit(raw)
            if provider is ReferenceMetadataProvider.OPENALEX
            else _crossref_hit(raw)
        )
        if hit is not None:
            hits.append(hit)
    parsed_cost = float(cost) if isinstance(cost, int | float) and cost >= 0 else None
    return hits, len(raw_items), parsed_cost


def _openalex_hit(item: dict[object, object]) -> _MetadataHit | None:
    identifier = item.get("id")
    title = item.get("title")
    if not isinstance(identifier, str) or not _https_url(identifier) or not isinstance(title, str):
        return None
    title = " ".join(title.split())
    if not title:
        return None
    doi = _normalize_doi(item.get("doi"))
    primary = item.get("primary_location")
    source = primary.get("source") if isinstance(primary, dict) else None
    venue = source.get("display_name") if isinstance(source, dict) else None
    year = item.get("publication_year")
    citations = item.get("cited_by_count")
    return _MetadataHit(
        identity=f"doi:{doi}" if doi else f"openalex:{identifier.rsplit('/', 1)[-1].casefold()}",
        title=title[:1_000],
        locator=f"https://doi.org/{doi}" if doi else identifier,
        venue=str(venue)[:300] if isinstance(venue, str) and venue.strip() else None,
        citation_count=citations if isinstance(citations, int) and citations >= 0 else None,
        publication_year=year if isinstance(year, int) and 1600 <= year <= 2200 else None,
    )


def _crossref_hit(item: dict[object, object]) -> _MetadataHit | None:
    raw_titles = item.get("title")
    title = raw_titles[0] if isinstance(raw_titles, list) and raw_titles else None
    doi = _normalize_doi(item.get("DOI"))
    url = item.get("URL")
    if not isinstance(title, str) or not title.strip():
        return None
    if doi:
        identity = f"doi:{doi}"
        locator = f"https://doi.org/{doi}"
    elif isinstance(url, str) and _https_url(url):
        identity = f"crossref:{url.casefold()}"
        locator = url
    else:
        return None
    raw_venues = item.get("container-title")
    venue = raw_venues[0] if isinstance(raw_venues, list) and raw_venues else None
    citations = item.get("is-referenced-by-count")
    published = item.get("published")
    date_parts = published.get("date-parts") if isinstance(published, dict) else None
    year = (
        date_parts[0][0]
        if isinstance(date_parts, list)
        and date_parts
        and isinstance(date_parts[0], list)
        and date_parts[0]
        and isinstance(date_parts[0][0], int)
        else None
    )
    return _MetadataHit(
        identity=identity,
        title=" ".join(title.split())[:1_000],
        locator=locator,
        venue=str(venue)[:300] if isinstance(venue, str) and venue.strip() else None,
        citation_count=citations if isinstance(citations, int) and citations >= 0 else None,
        publication_year=year if isinstance(year, int) and 1600 <= year <= 2200 else None,
    )


def _normalize_doi(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().casefold()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
            break
    if (
        not normalized.startswith("10.")
        or "/" not in normalized
        or any(ch.isspace() for ch in normalized)
    ):
        return None
    return normalized


def _source_group_id(identity: str) -> str:
    return "source-" + hashlib.sha256(identity.encode()).hexdigest()[:24]


def _candidate_id(identity: str) -> str:
    return "candidate-" + hashlib.sha256(identity.encode()).hexdigest()[:24]


def _https_url(value: str) -> bool:
    parsed = urlsplit(value)
    return parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username


def _safe_id(value: str) -> bool:
    return bool(value) and all(
        character.islower() or character.isdigit() or character in "._-" for character in value
    )


def _safe_bound_file(root: Path, locator: str) -> Path:
    relative = Path(locator)
    if relative.is_absolute() or ".." in relative.parts or "\\" in locator:
        raise ValueError("reference-search bundle locator is unsafe")
    cursor = root
    for part in relative.parts:
        cursor /= part
        if cursor.is_symlink():
            raise ValueError("reference-search bundle contains a symlink")
    resolved = cursor.resolve(strict=True)
    resolved.relative_to(root)
    if not resolved.is_file() or resolved.stat().st_size > _MAX_BUNDLE_BYTES:
        raise ValueError("reference-search bundle file is invalid")
    return resolved


def _write_json(path: Path, value: object) -> None:
    text = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2) + "\n"
    _write_bytes(path, text.encode())


def _write_bytes(path: Path, value: bytes) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _load_json_mapping(path: Path, *, maximum_bytes: int) -> dict[str, object]:
    if not path.is_file() or path.is_symlink() or not 1 <= path.stat().st_size <= maximum_bytes:
        raise ValueError("reference-search JSON is not a bounded regular file")
    try:
        value = json.loads(path.read_bytes(), parse_constant=_reject_non_finite)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("reference-search JSON is invalid") from exc
    if not isinstance(value, dict):
        raise ValueError("reference-search JSON must contain an object")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _semantic_sha256(model: BaseModel, *, exclude: set[str]) -> str:
    payload = model.model_dump(mode="json", exclude=exclude)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _reject_non_finite(value: str) -> None:
    raise ValueError(f"non-finite JSON value is forbidden: {value}")


__all__ = [
    "MaterializedReferenceSearch",
    "PublicReferenceMetadataTransport",
    "ReferenceMetadataHTTPResponse",
    "ReferenceMetadataProvider",
    "ReferenceMetadataTransport",
    "ReferenceSearchBatchSpec",
    "ReferenceSearchExecutionConfig",
    "ReferenceSearchExecutionReceipt",
    "ReferenceSearchRequestEvidence",
    "execute_reference_search",
    "load_reference_search_config",
    "load_reference_search_receipt",
    "replay_reference_search",
]
