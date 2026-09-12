from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from scitaste.backends.base import Usage
from scitaste.cli import main
from scitaste.model_nodes import (
    NodeContext,
    NodePolicy,
    NodeResultStatus,
    ScriptedStructuredBackend,
    ScriptedStructuredReply,
)
from scitaste.model_nodes.profiles import load_model_node_profile_set
from scitaste.taste.reference_mining import (
    ReferenceMiningNeed,
    ReferenceMiningProposal,
    ReferenceMiningRun,
    compile_reference_mining_report,
    validate_reference_mining_proposal,
)
from scitaste.taste.semantic import ReferenceMiningNode, taste_node_types


def _need() -> ReferenceMiningNeed:
    return ReferenceMiningNeed(
        schema_version="1.0",
        mining_id="experiment-gap-one",
        stage="experiment",
        decision_question="Which probe distinguishes the two live mechanisms?",
        candidate_actions=("run an intervention", "run an observational control"),
        evidence_gap_ids=("gap-confound", "gap-boundary"),
        required_decision_patterns=(
            "hypothesis-discrimination",
            "diagnostic-experiment",
            "confound-control",
        ),
        required_evidence_roles=("support", "challenge", "boundary", "alternative"),
        required_domain_facets=("causal-inference", "representation-learning"),
        max_query_count=12,
        max_batches=5,
        saturation_window=2,
        min_distinct_source_groups=3,
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
    roles = ("support", "alternative", "challenge", "boundary", "challenge", "boundary")
    patterns = (
        "diagnostic-experiment",
        "hypothesis-discrimination",
        "confound-control",
        "diagnostic-experiment",
        "confound-control",
        "hypothesis-discrimination",
    )
    return ReferenceMiningProposal(
        mining_id="experiment-gap-one",
        queries=tuple(
            {
                "query_id": f"query-{index}",
                "family": family,
                "query_text": f"decision evidence search family {family}",
                "targeted_decision_patterns": [patterns[index - 1]],
                "targeted_evidence_roles": [roles[index - 1]],
                "targeted_domain_facets": [
                    "causal-inference" if index % 2 else "representation-learning"
                ],
            }
            for index, family in enumerate(families, 1)
        ),
        rationale="Search complementary evidence rather than one relevance-ranked list.",
    )


def _candidate(
    candidate_id: str,
    group: str,
    *,
    patterns: tuple[str, ...],
    roles: tuple[str, ...],
    domains: tuple[str, ...],
    query: str,
    venue: str = "Venue A",
    citations: int = 1,
) -> dict:
    return {
        "candidate_id": candidate_id,
        "source_group_id": group,
        "title": f"Metadata title for {candidate_id}",
        "locator": f"https://example.org/{candidate_id}",
        "discovery_query_ids": [query],
        "hypothesized_decision_patterns": list(patterns),
        "hypothesized_evidence_roles": list(roles),
        "domain_facets": list(domains),
        "rights_status": "compatible-metadata-only",
        "isolation_status": "eligible-candidate",
        "venue": venue,
        "citation_count": citations,
        "publication_year": 2025,
        "source_body_read": False,
        "quality_assessed": False,
    }


def _run_payload() -> dict:
    need = _need().model_dump(mode="json", exclude={"need_sha256"})
    proposal = _proposal().model_dump(mode="json", exclude={"proposal_sha256"})
    return {
        "schema_version": "1.0",
        "need": need,
        "proposal": proposal,
        "batches": [
            {
                "batch_index": 1,
                "query_ids": ["query-1", "query-2"],
                "candidates": [
                    _candidate(
                        "candidate-a",
                        "source-a",
                        patterns=("diagnostic-experiment", "hypothesis-discrimination"),
                        roles=("support", "alternative"),
                        domains=("causal-inference",),
                        query="query-1",
                        venue="Unknown workshop",
                        citations=0,
                    )
                ],
                "duplicate_candidate_ids": [],
            },
            {
                "batch_index": 2,
                "query_ids": ["query-3", "query-4"],
                "candidates": [
                    _candidate(
                        "candidate-b",
                        "source-b",
                        patterns=("confound-control",),
                        roles=("challenge", "boundary"),
                        domains=("representation-learning",),
                        query="query-3",
                    ),
                    _candidate(
                        "candidate-c",
                        "source-c",
                        patterns=("diagnostic-experiment",),
                        roles=("alternative",),
                        domains=("causal-inference",),
                        query="query-4",
                    ),
                ],
                "duplicate_candidate_ids": [],
            },
            {
                "batch_index": 3,
                "query_ids": ["query-5"],
                "candidates": [],
                "duplicate_candidate_ids": ["candidate-a"],
            },
            {
                "batch_index": 4,
                "query_ids": ["query-6"],
                "candidates": [],
                "duplicate_candidate_ids": ["candidate-b"],
            },
        ],
    }


def test_reference_mining_freezes_a_saturated_coverage_cohort_without_quality_claim() -> None:
    report = compile_reference_mining_report(ReferenceMiningRun.model_validate(_run_payload()))

    assert report.stopping_reason == "coverage-and-saturation"
    assert report.evaluated_batch_count == 4
    assert report.search_saturated is True
    assert set(report.selected_candidate_ids) == {"candidate-a", "candidate-b", "candidate-c"}
    assert len(report.selected_source_group_ids) == 3
    assert report.missing_decision_patterns == ()
    assert report.missing_evidence_roles == ()
    assert report.missing_domain_facets == ()
    assert report.cohort_ready_for_reference_quality is True
    assert report.selection_uses_prestige_signals is False
    assert report.source_content_read is False
    assert report.source_quality_assessed is False
    assert report.authorizes_reference_quality is False


def test_prestige_metadata_cannot_change_the_selected_cohort() -> None:
    payload = _run_payload()
    baseline = compile_reference_mining_report(ReferenceMiningRun.model_validate(payload))
    changed = deepcopy(payload)
    changed["batches"][0]["candidates"][0]["venue"] = "Most prestigious venue"
    changed["batches"][0]["candidates"][0]["citation_count"] = 999_999
    changed["batches"][1]["candidates"][0]["venue"] = "Unranked"
    changed["batches"][1]["candidates"][0]["citation_count"] = 0
    reranked = compile_reference_mining_report(ReferenceMiningRun.model_validate(changed))

    assert reranked.selected_candidate_ids == baseline.selected_candidate_ids


def test_metadata_cohort_fills_its_ceiling_and_prefers_query_grounded_titles() -> None:
    payload = _run_payload()
    payload["need"]["max_cohort_size"] = 4
    relevant = _candidate(
        "candidate-relevant",
        "source-relevant",
        patterns=("diagnostic-experiment",),
        roles=("support",),
        domains=("causal-inference",),
        query="query-1",
    )
    relevant["title"] = "Decision evidence for direct experiments"
    irrelevant = _candidate(
        "candidate-irrelevant",
        "source-irrelevant",
        patterns=("diagnostic-experiment",),
        roles=("support",),
        domains=("causal-inference",),
        query="query-1",
    )
    irrelevant["title"] = "Unrelated culinary report"
    payload["batches"][1]["query_ids"].append("query-1")
    payload["batches"][1]["candidates"].extend((relevant, irrelevant))

    report = compile_reference_mining_report(ReferenceMiningRun.model_validate(payload))

    assert len(report.selected_candidate_ids) == 4
    assert "candidate-relevant" in report.selected_candidate_ids
    assert "candidate-irrelevant" not in report.selected_candidate_ids


def test_reference_mining_does_not_claim_readiness_before_saturation() -> None:
    payload = _run_payload()
    payload["batches"] = payload["batches"][:2]
    report = compile_reference_mining_report(ReferenceMiningRun.model_validate(payload))

    assert report.stopping_reason == "search-incomplete"
    assert report.search_saturated is False
    assert report.cohort_ready_for_reference_quality is False


def test_schema_v11_requires_anchored_queries_and_all_query_families_in_cohort() -> None:
    payload = _run_payload()
    payload["schema_version"] = "1.1"
    payload["need"].update(
        schema_version="1.1",
        metadata_relevance_anchor_terms=["decision", "evidence"],
        min_metadata_anchor_matches=2,
        max_query_terms=12,
    )

    report = compile_reference_mining_report(ReferenceMiningRun.model_validate(payload))

    assert set(report.missing_query_families) == {
        "alternative-or-comparator",
        "replication-or-reappraisal",
        "cross-domain-transfer",
    }
    assert report.cohort_ready_for_reference_quality is False

    unanchored = _proposal().model_dump(mode="json", exclude={"proposal_sha256"})
    unanchored["queries"][0]["query_text"] = "unrelated bibliography"
    findings = validate_reference_mining_proposal(
        ReferenceMiningNeed.model_validate(payload["need"]),
        ReferenceMiningProposal.model_validate(unanchored),
    )
    assert any("lacks registered metadata anchors" in finding for finding in findings)


def test_reference_mining_node_accepts_only_a_closed_contrastive_plan() -> None:
    need = _need()
    proposal = _proposal()
    backend = ScriptedStructuredBackend(
        name="scripted",
        model="scripted-v1",
        replies={
            "mining-one": ScriptedStructuredReply(
                output_payload=proposal.model_dump(mode="json", exclude={"proposal_sha256"}),
                usage=Usage(input_tokens=300, output_tokens=200, cost_usd=0),
            )
        },
    )
    result = ReferenceMiningNode().run(
        need,
        context=NodeContext(
            project_id="reference-project",
            stage=need.stage.value,
            state_snapshot_id=need.need_sha256,
            cumulative_api_cost_usd=0,
            evidence_ids=list(need.evidence_gap_ids),
        ),
        backend=backend,
        policy=NodePolicy(
            policy_id="reference-mining-fixture",
            enabled=True,
            allowed_node_names=["reference-mining"],
            expected_backend="scripted",
            expected_model="scripted-v1",
            max_input_tokens=8_000,
            max_output_tokens=8_000,
            max_total_tokens=16_000,
            max_api_cost_usd=0.1,
            max_latency_ms=1_000,
        ),
        request_id="mining-one",
    )

    assert validate_reference_mining_proposal(need, proposal) == ()
    assert result.status is NodeResultStatus.ACCEPTED
    assert result.proposal == proposal
    assert taste_node_types()["reference-mining"].output_type is ReferenceMiningProposal


def test_reference_mining_rejects_prestige_ranking_and_content_read() -> None:
    proposal = _proposal().model_dump(mode="json", exclude={"proposal_sha256"})
    proposal["queries"][0]["query_text"] = "Find highly cited papers about the decision"
    findings = validate_reference_mining_proposal(
        _need(),
        ReferenceMiningProposal.model_validate(proposal),
    )
    assert any("ranks by prestige" in finding for finding in findings)

    payload = _run_payload()
    payload["batches"][0]["candidates"][0]["source_body_read"] = True
    with pytest.raises(ValidationError):
        ReferenceMiningRun.model_validate(payload)


def test_reference_mining_cli_writes_content_free_receipt(tmp_path: Path, capsys) -> None:
    source = tmp_path / "run.yaml"
    output = tmp_path / "report.json"
    source.write_text(yaml.safe_dump(_run_payload(), sort_keys=False), encoding="utf-8")

    assert (
        main(["evaluation", "reference-mining", "--run", str(source), "--output", str(output)]) == 0
    )
    emitted = json.loads(capsys.readouterr().out)
    saved = json.loads(output.read_text(encoding="utf-8"))

    assert emitted["status"] == "reference-mining-cohort-frozen"
    assert emitted["report_sha256"] == saved["report_sha256"]
    assert saved["cohort_ready_for_reference_quality"] is True
    assert saved["source_content_read"] is False


def test_reference_mining_provider_profiles_are_content_addressed_and_tool_free() -> None:
    loaded = load_model_node_profile_set(
        "configs/model_nodes/runtime_profiles.reference_mining_v1.yaml"
    )

    assert set(loaded.profiles) == {
        "deepseek-v41flash-reference-mining",
        "zhipu-glm53-reference-mining",
    }
    assert all(
        profile.allowed_node_names == ("reference-mining",) for profile in loaded.profiles.values()
    )
    assert all(profile.admission.allowed_tool_names == [] for profile in loaded.profiles.values())
