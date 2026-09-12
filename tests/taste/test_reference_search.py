from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from scitaste.taste.reference_mining import (
    ReferenceMiningNeed,
    ReferenceMiningProposal,
    VerifiedReferenceMining,
)
from scitaste.taste.reference_search import (
    ReferenceMetadataHTTPResponse,
    ReferenceSearchBatchSpec,
    ReferenceSearchExecutionConfig,
    execute_reference_search,
    load_reference_search_receipt,
    replay_reference_search,
)


def _need() -> ReferenceMiningNeed:
    return ReferenceMiningNeed(
        schema_version="1.0",
        mining_id="real-metadata-search",
        stage="experiment",
        decision_question="Which evidence distinguishes a real mechanism from a confounded gain?",
        candidate_actions=("run a diagnostic intervention", "retain the observational result"),
        evidence_gap_ids=("mechanism-gap", "confound-gap"),
        required_decision_patterns=(
            "hypothesis-discrimination",
            "diagnostic-experiment",
            "confound-control",
        ),
        required_evidence_roles=("support", "challenge", "boundary", "alternative"),
        required_domain_facets=("causal-inference", "representation-learning"),
        max_query_count=12,
        max_batches=4,
        saturation_window=2,
        min_distinct_source_groups=2,
        max_per_source_group=1,
        max_cohort_size=6,
    )


def _proposal() -> ReferenceMiningProposal:
    families = (
        "direct-decision",
        "alternative-or-comparator",
        "negative-or-null",
        "failure-or-limitation",
        "replication-or-reappraisal",
        "cross-domain-transfer",
    )
    return ReferenceMiningProposal(
        mining_id="real-metadata-search",
        queries=tuple(
            {
                "query_id": f"query-{index}",
                "family": family,
                "query_text": f"mechanism evidence {family}",
                "targeted_decision_patterns": [
                    "hypothesis-discrimination",
                    "diagnostic-experiment",
                    "confound-control",
                ],
                "targeted_evidence_roles": [
                    "support",
                    "challenge",
                    "boundary",
                    "alternative",
                ],
                "targeted_domain_facets": [
                    "causal-inference",
                    "representation-learning",
                ],
            }
            for index, family in enumerate(families, 1)
        ),
        rationale="Cover contrastive evidence across two independent scholarly indexes.",
    )


def _verified() -> VerifiedReferenceMining:
    return VerifiedReferenceMining(
        invocation_id="reference-query-plan-one",
        backend="live-fixture",
        model="fixture-model-v1",
        ledger_locator="projects/reference-project/runs/run-one/model_nodes/ledger/entry.json",
        ledger_sha256="a" * 64,
        input=_need(),
        proposal=_proposal(),
    )


def _config() -> ReferenceSearchExecutionConfig:
    return ReferenceSearchExecutionConfig(
        execution_id="reference-search-one",
        batches=(
            ReferenceSearchBatchSpec(provider="openalex", page=1, minimum_interval_seconds=0),
            ReferenceSearchBatchSpec(provider="crossref", page=1, minimum_interval_seconds=0),
            ReferenceSearchBatchSpec(provider="openalex", page=2, minimum_interval_seconds=0),
            ReferenceSearchBatchSpec(provider="crossref", page=2, minimum_interval_seconds=0),
        ),
        per_query_results=2,
        max_requests=24,
        max_response_bytes=100_000,
        max_total_response_bytes=1_000_000,
        timeout_seconds=5,
        user_agent="SciTaste reference-search deterministic fixture",
    )


class _MetadataTransport:
    def __init__(
        self,
        *,
        include_body_field: bool = False,
        conflicting_title: bool = False,
        administrative_title: bool = False,
    ) -> None:
        self.urls: list[str] = []
        self.include_body_field = include_body_field
        self.conflicting_title = conflicting_title
        self.administrative_title = administrative_title

    def get(self, url, *, headers, timeout, maximum_bytes):  # type: ignore[no-untyped-def]
        del headers, timeout, maximum_bytes
        self.urls.append(url)
        parsed = urlsplit(url)
        query = parse_qs(parsed.query)
        page = int(query.get("page", ["1"])[0])
        if parsed.hostname == "api.openalex.org":
            item = {
                "id": f"https://openalex.org/W{page}",
                "doi": "https://doi.org/10.1000/shared" if page == 1 else "10.1000/open-two",
                "title": ("Shared decision study" if page == 1 else "OpenAlex decision study two"),
                "publication_year": 2025,
                "primary_location": {"source": {"display_name": "Journal A"}},
                "cited_by_count": 12,
            }
            if self.include_body_field:
                item["abstract_inverted_index"] = {"forbidden": [0]}
            second = {
                "id": "https://openalex.org/W99",
                "doi": "10.1000/open-extra",
                "title": (
                    "Peer Review Report For: Shared decision study"
                    if self.administrative_title
                    else "A second source group"
                ),
                "publication_year": 2023,
                "primary_location": {"source": {"display_name": "Journal C"}},
                "cited_by_count": 0,
            }
            payload = {"meta": {"cost_usd": 0.001}, "results": [item, second]}
        else:
            payload = {
                "message": {
                    "items": [
                        {
                            "DOI": "10.1000/shared",
                            "title": [
                                "Unrelated DOI identity"
                                if self.conflicting_title
                                else "Shared decision study"
                            ],
                            "container-title": ["Journal B"],
                            "is-referenced-by-count": 3,
                            "published": {"date-parts": [[2024]]},
                            "URL": "https://doi.org/10.1000/shared",
                        }
                    ]
                }
            }
        body = json.dumps(payload).encode()
        return ReferenceMetadataHTTPResponse(
            status_code=200,
            url=url,
            headers={"content-type": "application/json; charset=utf-8"},
            body=body,
        )


def test_live_metadata_search_atomically_freezes_a_dual_index_cohort(tmp_path: Path) -> None:
    transport = _MetadataTransport()
    output = tmp_path / "reference-search"

    result = execute_reference_search(
        _verified(),
        _config(),
        output_dir=output,
        allow_network_search=True,
        transport=transport,
    )

    assert result.report.cohort_ready_for_reference_quality is True
    assert result.report.search_saturated is True
    assert result.receipt.executed_batch_count == 3
    assert result.receipt.request_count == 18
    assert result.receipt.schema_version == "1.3"
    assert result.receipt.need_file_sha256 is not None
    assert result.receipt.proposal_file_sha256 is not None
    assert result.receipt.config_file_sha256 is not None
    assert len(transport.urls) == 18
    assert result.receipt.source_content_read is False
    assert result.receipt.authorizes_reference_quality is False
    assert load_reference_search_receipt(result.receipt_path) == result.receipt
    assert len(tuple((output / "responses").glob("*.json"))) == 18


def test_control_files_and_request_urls_are_content_bound(tmp_path: Path) -> None:
    result = execute_reference_search(
        _verified(),
        _config(),
        output_dir=tmp_path / "source",
        allow_network_search=True,
        transport=_MetadataTransport(),
    )
    payload = json.loads(result.receipt_path.read_text(encoding="utf-8"))
    payload["requests"][0]["request_sha256"] = "0" * 64
    result.receipt_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="request URL hash mismatch"):
        load_reference_search_receipt(result.receipt_path, verify_bundle=False)


def test_control_file_tampering_is_rejected(tmp_path: Path) -> None:
    result = execute_reference_search(
        _verified(),
        _config(),
        output_dir=tmp_path / "source",
        allow_network_search=True,
        transport=_MetadataTransport(),
    )
    (result.output_dir / "CONFIG.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match=r"bundle hash mismatch: CONFIG\.json"):
        load_reference_search_receipt(result.receipt_path)


def test_frozen_metadata_transaction_can_be_replayed_without_network(tmp_path: Path) -> None:
    source = execute_reference_search(
        _verified(),
        _config(),
        output_dir=tmp_path / "source",
        allow_network_search=True,
        transport=_MetadataTransport(),
    )

    replay = replay_reference_search(
        source.receipt_path,
        _verified(),
        _config().model_copy(update={"execution_id": "reference-search-replay"}),
        output_dir=tmp_path / "replay",
    )

    assert replay.receipt.network_requests_performed is False
    assert replay.receipt.network_request_count == 0
    assert replay.receipt.source_bundle_receipt_sha256 == source.receipt.receipt_sha256
    assert replay.report.selected_candidate_ids == source.report.selected_candidate_ids
    assert load_reference_search_receipt(replay.receipt_path) == replay.receipt


def test_frozen_replay_must_match_the_verified_need_and_proposal(tmp_path: Path) -> None:
    source = execute_reference_search(
        _verified(),
        _config(),
        output_dir=tmp_path / "source",
        allow_network_search=True,
        transport=_MetadataTransport(),
    )
    changed_need = _verified().model_copy(
        update={
            "input": _need().model_copy(
                update={"decision_question": "A different registered scientific decision?"}
            )
        }
    )
    with pytest.raises(ValueError, match="differs from the verified need"):
        replay_reference_search(
            source.receipt_path,
            changed_need,
            _config().model_copy(update={"execution_id": "mismatched-need"}),
            output_dir=tmp_path / "mismatched-need",
        )

    changed_proposal = _verified().model_copy(
        update={
            "proposal": _proposal().model_copy(
                update={"rationale": "A different accepted proposal."}
            )
        }
    )
    with pytest.raises(ValueError, match="differs from the verified proposal"):
        replay_reference_search(
            source.receipt_path,
            changed_proposal,
            _config().model_copy(update={"execution_id": "mismatched-proposal"}),
            output_dir=tmp_path / "mismatched-proposal",
        )


def test_cross_index_title_conflict_is_excluded_from_the_cohort(tmp_path: Path) -> None:
    result = execute_reference_search(
        _verified(),
        _config(),
        output_dir=tmp_path / "conflict",
        allow_network_search=True,
        transport=_MetadataTransport(conflicting_title=True),
    )

    shared = next(
        candidate
        for batch in result.run.batches
        for candidate in batch.candidates
        if str(candidate.locator) == "https://doi.org/10.1000/shared"
    )
    assert shared.metadata_identity_status == "cross-index-conflict"
    assert shared.candidate_id not in result.report.selected_candidate_ids


def test_registered_metadata_anchors_and_record_type_gate_admission(tmp_path: Path) -> None:
    config_payload = _config().model_dump(mode="python", exclude_computed_fields=True)
    config_payload.update(
        metadata_relevance_anchor_terms=("shared", "decision"),
        min_metadata_anchor_matches=2,
        metadata_domain_anchor_terms={
            "causal-inference": ("shared", "decision"),
            "representation-learning": ("openalex", "study"),
        },
        metadata_domain_min_anchor_matches={
            "causal-inference": 2,
            "representation-learning": 2,
        },
    )
    result = execute_reference_search(
        _verified(),
        ReferenceSearchExecutionConfig.model_validate(config_payload),
        output_dir=tmp_path / "gated",
        allow_network_search=True,
        transport=_MetadataTransport(administrative_title=True),
    )

    candidates = [candidate for batch in result.run.batches for candidate in batch.candidates]
    shared = next(item for item in candidates if item.title == "Shared decision study")
    administrative = next(item for item in candidates if item.title.startswith("Peer Review"))
    insufficient = next(item for item in candidates if item.title.endswith("two"))
    assert shared.metadata_relevance_status == "eligible"
    assert shared.metadata_grounded_domain_facets == ("causal-inference",)
    assert administrative.metadata_relevance_status == "administrative-record"
    assert insufficient.metadata_relevance_status == "insufficient-anchor-evidence"
    assert result.report.selected_candidate_ids == (shared.candidate_id,)


def test_network_search_requires_explicit_switch_and_leaves_no_output(tmp_path: Path) -> None:
    output = tmp_path / "reference-search"

    with pytest.raises(ValueError, match="allow-network-search"):
        execute_reference_search(
            _verified(),
            _config(),
            output_dir=output,
            allow_network_search=False,
            transport=_MetadataTransport(),
        )

    assert not output.exists()


def test_unexpected_source_body_metadata_fails_atomically(tmp_path: Path) -> None:
    output = tmp_path / "reference-search"

    with pytest.raises(ValueError, match="source-body fields"):
        execute_reference_search(
            _verified(),
            _config(),
            output_dir=output,
            allow_network_search=True,
            transport=_MetadataTransport(include_body_field=True),
        )

    assert not output.exists()
    assert not tuple(tmp_path.glob(".reference-search.*.staging"))
