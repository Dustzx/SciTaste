from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from scitaste.backends.base import Usage
from scitaste.cli import main
from scitaste.evaluation import (
    OutcomeInformationAvailability,
    TasteAbstractionCandidate,
    TasteSourceRecord,
    build_taste_abstraction_input,
    inspect_taste_corpus_curation,
    load_taste_corpus_curation_package,
    load_taste_corpus_pair_manifest,
    materialize_taste_corpus_pair,
)
from scitaste.evaluation.taste_corpus_pair import inspect_taste_corpus_pair
from scitaste.model_nodes import (
    CumulativeProjectBudget,
    ModelNodeProfile,
    NodeAdmissionBudget,
    NodeContext,
    NodePolicy,
    ProviderGenerationEnvelope,
    ScriptedStructuredBackend,
    ScriptedStructuredReply,
)
from scitaste.model_nodes.runtime import ModelNodeRuntime, ModelNodeTrigger, RuntimeBackendMode
from scitaste.project import ProjectManifest, ProjectRun, ProjectRuntime
from scitaste.taste.semantic import (
    taste_abstraction_candidate_from_ledger,
    taste_node_types,
)


class _LiveFixtureBackend:
    """Use the live ledger branch while keeping the test offline and deterministic."""

    name = "fixture-provider"
    model = "fixture-model-v1"
    config = SimpleNamespace(live_enabled=True, max_output_tokens=2_000)

    def __init__(self, *, request_id: str, payload: object) -> None:
        self.delegate = ScriptedStructuredBackend(
            name=self.name,
            model=self.model,
            replies={
                request_id: ScriptedStructuredReply(
                    output_payload=payload,
                    usage=Usage(input_tokens=30, output_tokens=40, cost_usd=0.001),
                )
            },
        )

    def complete(self, request):
        return self.delegate.complete(request)


def test_dual_human_curation_materializes_a_qualified_pair(tmp_path: Path) -> None:
    package_path = _write_package(tmp_path)
    inspection = load_taste_corpus_curation_package(package_path)

    report = inspect_taste_corpus_curation(inspection, evidence_root=tmp_path)
    receipt = materialize_taste_corpus_pair(
        inspection,
        evidence_root=tmp_path,
        output_dir="curated/pair-v1",
    )
    pair_report = inspect_taste_corpus_pair(
        load_taste_corpus_pair_manifest(tmp_path / receipt.pair_manifest_path),
        evidence_root=tmp_path,
    )

    assert report.ready_to_materialize is True
    assert report.source_bindings_verified is True
    assert report.quality_evidence_verified is True
    assert report.dual_human_review_verified is True
    assert report.primary_review_count == 4
    assert report.adjudication_count == 0
    assert receipt.pair_qualified is True
    assert receipt.no_external_action_performed is True
    assert receipt.authorizes_execution is False
    assert pair_report.qualified is True
    matched = json.loads((tmp_path / receipt.matched_corpus_path).read_text(encoding="utf-8"))
    case = matched["entries"][0]["case"]
    assert case["human_verified"] is True
    assert case["retrieval_eligible"] is True
    assert case["label_basis"] == "dual_human_verified_external_source"
    assert len(case["provenance"][0]["metadata"]["accepted_review_ids"]) == 2


def test_formal_grounded_curation_preserves_trace_and_transfer_boundary(
    tmp_path: Path,
) -> None:
    package_path = _write_grounded_package(tmp_path)
    inspection = load_taste_corpus_curation_package(package_path)

    report = inspect_taste_corpus_curation(inspection, evidence_root=tmp_path)
    receipt = materialize_taste_corpus_pair(
        inspection,
        evidence_root=tmp_path,
        output_dir="curated/grounded-pair-v1",
    )
    matched = json.loads((tmp_path / receipt.matched_corpus_path).read_text(encoding="utf-8"))
    case = matched["entries"][0]["case"]

    assert report.ready_to_materialize is True
    assert report.ready_for_formal_taste_method is True
    assert report.grounded_candidate_count == 2
    assert report.grounding_traces_verified is True
    assert report.transfer_boundaries_verified is True
    assert case["applicability_conditions"]
    assert case["failure_conditions"]
    assert case["counterfactual_probe"]
    assert len(case["taste_grounding_sha256"]) == 64
    assert case["provenance"][0]["metadata"]["abstraction_contract"] == ("grounded-contrastive-v1")


def test_legacy_no_action_package_migrates_to_explicit_processing_semantics(
    tmp_path: Path,
) -> None:
    package_path = _write_package(tmp_path)
    payload = json.loads(package_path.read_text(encoding="utf-8"))
    payload["schema_version"] = "1.0"
    payload.pop("package_processing_performs_no_external_action")
    payload.update(
        no_dataset_download=True,
        no_api_call=True,
        no_ssh=True,
        no_gpu_or_model_execution=True,
        no_experiment_execution=True,
    )
    package_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    package = load_taste_corpus_curation_package(package_path).package

    assert package.schema_version == "1.1"
    assert package.historical_model_invocation_count == 0
    assert package.package_processing_performs_no_external_action is True


def test_curation_fails_closed_on_source_hash_drift(tmp_path: Path) -> None:
    package_path = _write_package(tmp_path)
    (tmp_path / "sources/matched.txt").write_text("changed\n", encoding="utf-8")

    report = inspect_taste_corpus_curation(
        load_taste_corpus_curation_package(package_path),
        evidence_root=tmp_path,
    )

    assert report.source_bindings_verified is False
    assert report.ready_to_materialize is False
    assert "source:hash_mismatch" in {item.code for item in report.blockers}


def test_split_primary_reviews_require_exactly_one_adjudicator(tmp_path: Path) -> None:
    package_path = _write_package(tmp_path, split_candidate_id="matched-candidate")
    payload = json.loads(package_path.read_text(encoding="utf-8"))
    payload["reviews"] = [
        item
        for item in payload["reviews"]
        if not (item["candidate_id"] == "matched-candidate" and item["role"] == "adjudicator")
    ]
    package_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    report = inspect_taste_corpus_curation(
        load_taste_corpus_curation_package(package_path),
        evidence_root=tmp_path,
    )

    assert report.ready_to_materialize is False
    assert "review:split_requires_one_adjudicator" in {item.code for item in report.blockers}


def test_split_review_with_independent_adjudicator_is_accepted(tmp_path: Path) -> None:
    package_path = _write_package(tmp_path, split_candidate_id="matched-candidate")

    report = inspect_taste_corpus_curation(
        load_taste_corpus_curation_package(package_path),
        evidence_root=tmp_path,
    )

    assert report.ready_to_materialize is True
    assert report.adjudication_count == 1
    assert set(report.accepted_candidate_ids) == {
        "matched-candidate",
        "placebo-candidate",
    }


def test_candidate_author_cannot_verify_their_own_abstraction(tmp_path: Path) -> None:
    package_path = _write_package(tmp_path, author_is_reviewer=True)

    report = inspect_taste_corpus_curation(
        load_taste_corpus_curation_package(package_path),
        evidence_root=tmp_path,
    )

    assert report.ready_to_materialize is False
    assert "review:author_is_reviewer" in {item.code for item in report.blockers}


def test_model_assisted_candidate_requires_content_bound_trace() -> None:
    payload = _candidate_payload("matched")
    payload["origin"] = "model-assisted"

    with pytest.raises(ValidationError, match="requires a bound model trace"):
        TasteAbstractionCandidate.model_validate(payload)


def test_model_assisted_candidate_rejects_arbitrary_trace_bytes(tmp_path: Path) -> None:
    package_path = _write_package(tmp_path)
    payload = json.loads(package_path.read_text(encoding="utf-8"))
    trace = tmp_path / "sources/model-trace.json"
    trace.write_text('{"claimed":"model-assisted"}\n', encoding="utf-8")
    source = next(item for item in payload["sources"] if item["source_id"] == "matched-source")
    source["abstraction_input"] = source["artifact"]
    candidate = next(
        item for item in payload["candidates"] if item["candidate_id"] == "matched-candidate"
    )
    candidate["origin"] = "model-assisted"
    candidate["model_trace"] = {
        "path": "sources/model-trace.json",
        "sha256": _sha(trace),
    }
    payload["historical_model_invocation_count"] = 1
    validated = TasteAbstractionCandidate.model_validate(candidate)
    for review in payload["reviews"]:
        if review["candidate_id"] == candidate["candidate_id"]:
            review["candidate_sha256"] = validated.semantic_sha256
    package_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    report = inspect_taste_corpus_curation(
        load_taste_corpus_curation_package(package_path),
        evidence_root=tmp_path,
    )

    assert report.abstraction_input_bindings_verified is True
    assert report.model_trace_bindings_verified is False
    assert "model_trace:ledger_invalid" in {item.code for item in report.blockers}
    assert report.ready_to_materialize is False


def test_verified_live_model_abstraction_can_pass_the_human_curation_gate(
    tmp_path: Path,
) -> None:
    package_path = _write_package(tmp_path)
    payload = json.loads(package_path.read_text(encoding="utf-8"))
    source_payload = next(
        item for item in payload["sources"] if item["source_id"] == "matched-source"
    )
    source_payload["abstraction_input"] = source_payload["artifact"]
    source = TasteSourceRecord.model_validate(source_payload)
    input_data = build_taste_abstraction_input(
        source,
        candidate_id="matched-candidate",
        case_id="matched-taste-case",
        outcome_information_availability=OutcomeInformationAvailability.AVAILABLE,
        evidence_root=tmp_path,
    )
    project = ProjectRuntime(tmp_path)
    project.create(
        ProjectManifest(
            project_id="taste-curation-project",
            title="Taste curation fixture",
            research_direction="Verify the model-assisted abstraction evidence chain.",
            status="active",
        )
    )
    snapshot = project.begin_run(
        "taste-curation-project",
        ProjectRun(
            run_id="taste-curation-model-run",
            provider="fixture-provider",
            model="fixture-model-v1",
            condition="model-assisted-abstraction-fixture",
            seed=0,
            status="running",
            evidence_scope="engineering-fixture",
        ),
        expected_revision=0,
    )
    profile = _live_profile()
    policy = NodePolicy(
        policy_id="taste-abstraction-live-fixture",
        enabled=True,
        allowed_node_names=["taste-abstraction"],
        expected_backend=profile.provider,
        expected_model=profile.model,
        max_request_bytes=profile.admission.max_request_bytes,
        max_input_tokens=profile.admission.max_input_tokens,
        max_output_tokens=profile.admission.max_output_tokens,
        max_total_tokens=profile.admission.max_total_tokens,
        max_api_cost_usd=profile.cumulative_project.max_api_cost_usd,
        max_latency_ms=profile.admission.max_latency_ms,
    )
    proposal = _candidate_payload("matched")["abstraction"]
    receipt = ModelNodeRuntime(project, node_types=taste_node_types()).execute(
        project_id="taste-curation-project",
        run_id="taste-curation-model-run",
        invocation_id="matched-abstraction",
        request_id="matched-abstraction-request",
        expected_project_revision=snapshot.revision,
        state_revision=0,
        node_name="taste-abstraction",
        node_input=input_data,
        context=NodeContext(
            project_id="taste-curation-project",
            stage=input_data.stage,
            state_snapshot_id=input_data.source_projection_sha256,
            cumulative_api_cost_usd=0,
            evidence_ids=[input_data.source_id],
        ),
        trigger=ModelNodeTrigger(
            trigger_id="curate-matched-source",
            reason="Create one untrusted abstraction for independent review.",
        ),
        profile=profile,
        policy=policy,
        backend_mode=RuntimeBackendMode.LIVE,
        backend=_LiveFixtureBackend(
            request_id="matched-abstraction-request",
            payload=proposal,
        ),
        allow_live=True,
    )
    ledger = next((tmp_path / receipt.ledger_locator).glob("*.json"))
    candidate = taste_abstraction_candidate_from_ledger(
        ledger,
        evidence_root=tmp_path,
        author_id="matched-curator",
        derivation_method="Model proposal pending two independent human reviews.",
    )
    payload["candidates"] = [
        candidate.model_dump(mode="json") if item["candidate_id"] == "matched-candidate" else item
        for item in payload["candidates"]
    ]
    payload["historical_model_invocation_count"] = 1
    for review in payload["reviews"]:
        if review["candidate_id"] == candidate.candidate_id:
            review["candidate_sha256"] = candidate.semantic_sha256
    package_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    report = inspect_taste_corpus_curation(
        load_taste_corpus_curation_package(package_path),
        evidence_root=tmp_path,
    )

    assert report.historical_model_invocation_count == 1
    assert report.abstraction_input_bindings_verified is True
    assert report.model_trace_bindings_verified is True
    assert report.ready_to_materialize is True


def test_failed_retrieval_qualification_rolls_back_all_outputs(tmp_path: Path) -> None:
    package_path = _write_package(tmp_path)
    payload = json.loads(package_path.read_text(encoding="utf-8"))
    payload["qualification_queries"][0]["query"]["text"] = "absent vocabulary"
    payload["qualification_queries"][0]["query"]["stage"] = "REVIEW"
    package_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    inspection = load_taste_corpus_curation_package(package_path)

    assert (
        inspect_taste_corpus_curation(
            inspection,
            evidence_root=tmp_path,
        ).ready_to_materialize
        is True
    )
    with pytest.raises(ValueError, match="did not qualify"):
        materialize_taste_corpus_pair(
            inspection,
            evidence_root=tmp_path,
            output_dir="failed-output",
        )

    assert not (tmp_path / "failed-output").exists()


def test_cli_inspects_and_materializes_without_execution_authority(
    tmp_path: Path,
    capsys,
) -> None:
    package_path = _write_package(tmp_path)

    exit_code = main(
        [
            "evaluation",
            "taste-corpus-curation",
            "--package",
            str(package_path),
            "--evidence-root",
            str(tmp_path),
            "--output-dir",
            "cli-output",
            "--report",
            str(tmp_path / "curation-report.json"),
            "--require-ready",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["ready_to_materialize"] is True
    assert payload["no_external_action_performed"] is True
    assert payload["authorizes_execution"] is False
    assert payload["materialization"]["pair_qualified"] is True
    assert (tmp_path / "curation-report.json").is_file()


def _live_profile() -> ModelNodeProfile:
    return ModelNodeProfile(
        profile_id="taste-abstraction-live-fixture",
        profile_version="1.0.0",
        provider="fixture-provider",
        model="fixture-model-v1",
        allowed_node_names=("taste-abstraction",),
        live_execution_permitted=True,
        generation=ProviderGenerationEnvelope(
            max_request_bytes=1_000_000,
            max_output_tokens=2_000,
            context_window_tokens=20_000,
        ),
        admission=NodeAdmissionBudget(
            max_request_bytes=900_000,
            max_input_tokens=10_000,
            max_output_tokens=1_000,
            max_total_tokens=11_000,
            max_latency_ms=1_000,
            max_response_cost_usd=0.10,
        ),
        cumulative_project=CumulativeProjectBudget(
            max_invocations=4,
            max_total_tokens=40_000,
            max_api_cost_usd=0.40,
        ),
    )


def _write_package(
    root: Path,
    *,
    split_candidate_id: str | None = None,
    author_is_reviewer: bool = False,
) -> Path:
    source_dir = root / "sources"
    source_dir.mkdir()
    matched_source = source_dir / "matched.txt"
    placebo_source = source_dir / "placebo.txt"
    matched_quality = source_dir / "matched-quality.json"
    placebo_quality = source_dir / "placebo-quality.json"
    matched_source.write_text("vision uncertainty probe source\n", encoding="utf-8")
    placebo_source.write_text("language uncertainty probe source\n", encoding="utf-8")
    matched_quality.write_text('{"venue":"ICLR","accepted":true}\n', encoding="utf-8")
    placebo_quality.write_text('{"venue":"ACL","accepted":true}\n', encoding="utf-8")
    sources = [
        _source_payload(
            source_id="matched-source",
            relation="task-domain-matched",
            pair_slot_id="hypothesis-probe",
            domain="vision",
            source_group="external-vision-paper",
            artifact="sources/matched.txt",
            artifact_sha=_sha(matched_source),
            quality_evidence="sources/matched-quality.json",
            quality_evidence_sha=_sha(matched_quality),
            locator="https://example.org/vision-paper",
        ),
        _source_payload(
            source_id="placebo-source",
            relation="source-disjoint-domain-mismatched",
            pair_slot_id="hypothesis-probe",
            domain="nlp",
            source_group="external-nlp-paper",
            artifact="sources/placebo.txt",
            artifact_sha=_sha(placebo_source),
            quality_evidence="sources/placebo-quality.json",
            quality_evidence_sha=_sha(placebo_quality),
            locator="https://example.org/nlp-paper",
        ),
    ]
    candidates = [_candidate_payload("matched"), _candidate_payload("placebo")]
    candidate_models = [TasteAbstractionCandidate.model_validate(item) for item in candidates]
    reviews: list[dict[str, object]] = []
    for candidate in candidate_models:
        first_reviewer = candidate.author_id if author_is_reviewer else "expert-one"
        reviews.append(_review_payload(candidate, first_reviewer, 1, verdict="accept"))
        split = candidate.candidate_id == split_candidate_id
        reviews.append(
            _review_payload(
                candidate,
                "expert-two",
                2,
                verdict="reject" if split else "accept",
            )
        )
        if split:
            reviews.append(
                _review_payload(
                    candidate,
                    "expert-three",
                    3,
                    role="adjudicator",
                    verdict="accept",
                )
            )
    payload = {
        "schema_version": "1.1",
        "package_id": "heldout-vision-taste-v1",
        "task_id": "heldout-vision-task",
        "task_domain_tags": ["vision"],
        "held_out_source_groups": ["heldout-task-source"],
        "forbidden_source_content_sha256": ["f" * 64],
        "provenance_tier": "peer-reviewed-primary",
        "curation_tier": "dual-human-verified",
        "outcome_information_availability": "available",
        "source_selection_frozen": True,
        "sources": sources,
        "candidates": candidates,
        "reviews": reviews,
        "qualification_queries": [
            {
                "query_id": "discovery-hypothesis-probe",
                "decision_role": "hypothesis triage",
                "query": {
                    "text": "uncertainty probe",
                    "policy": "stage_conditioned",
                    "stage": "DISCOVERY",
                    "candidate_action_types": ["PROBE"],
                    "domain_tags": ["vision"],
                },
                "retrieval_limit": 1,
                "context_token_budget": 256,
            }
        ],
        "package_processing_performs_no_external_action": True,
        "authorizes_execution": False,
    }
    package = root / "curation-package.json"
    package.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return package


def _write_grounded_package(root: Path) -> Path:
    package = _write_package(root)
    payload = json.loads(package.read_text(encoding="utf-8"))
    payload["schema_version"] = "1.2"
    payload["curation_tier"] = "grounded-dual-human-verified"
    candidates: list[dict[str, object]] = []
    for prefix in ("matched", "placebo"):
        path = root / f"sources/{prefix}.txt"
        projection = _grounded_projection(prefix)
        path.write_text(projection, encoding="utf-8")
        source = next(
            item for item in payload["sources"] if item["source_id"] == f"{prefix}-source"
        )
        binding = {"path": f"sources/{prefix}.txt", "sha256": _sha(path)}
        source["artifact"] = binding
        source["abstraction_input"] = binding
        candidates.append(_grounded_candidate_payload(prefix))
    payload["candidates"] = candidates
    candidate_models = [TasteAbstractionCandidate.model_validate(item) for item in candidates]
    payload["reviews"] = []
    for candidate in candidate_models:
        for number, reviewer in enumerate(("expert-one", "expert-two"), start=1):
            review = _review_payload(candidate, reviewer, number, verdict="accept")
            review["grounding_trace_supported"] = True
            review["transfer_boundary_supported"] = True
            payload["reviews"].append(review)
    package.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return package


def _grounded_projection(prefix: str) -> str:
    return json.dumps(
        {
            "schema_version": "1.0",
            "outcome_information_availability": "available",
            "fields": {
                "problem": {
                    "semantic_role": "problem_context",
                    "value": f"{prefix} uncertainty remained before expensive scale-up.",
                },
                "evidence": {
                    "semantic_role": "evidence",
                    "value": f"{prefix} aggregate evidence could not separate two explanations.",
                },
                "alternatives": {
                    "semantic_role": "alternative",
                    "value": "Run an uncertainty probe or commit to the full experiment.",
                },
                "action": {
                    "semantic_role": "scientific_action",
                    "value": f"The {prefix} study ran the uncertainty probe first.",
                },
                "justification": {
                    "semantic_role": "justification",
                    "value": "The probe discriminated the explanations at lower cost.",
                },
                "outcome": {
                    "semantic_role": "outcome",
                    "value": f"The {prefix} probe ruled out one explanation.",
                },
            },
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _grounded_candidate_payload(prefix: str) -> dict[str, object]:
    candidate = _candidate_payload(prefix)
    abstraction = candidate["abstraction"]
    abstraction["grounding"] = [
        {
            "target": "context",
            "supports": [
                {
                    "projection_field": "problem",
                    "verbatim_evidence": "uncertainty remained before expensive scale-up",
                }
            ],
            "derivation": "direct",
            "rationale": "The decision context is explicit.",
        },
        {
            "target": "evidence_state",
            "supports": [
                {
                    "projection_field": "evidence",
                    "verbatim_evidence": "could not separate two explanations",
                }
            ],
            "derivation": "direct",
            "rationale": "The uncertainty is explicit.",
        },
        {
            "target": "alternatives",
            "supports": [
                {
                    "projection_field": "alternatives",
                    "verbatim_evidence": "Run an uncertainty probe or commit",
                }
            ],
            "derivation": "direct",
            "rationale": "The alternatives are source-visible.",
        },
        {
            "target": "choice",
            "supports": [
                {
                    "projection_field": "action",
                    "verbatim_evidence": "ran the uncertainty probe first",
                }
            ],
            "derivation": "direct",
            "rationale": "The action is source-visible.",
        },
        {
            "target": "decision_principle",
            "supports": [
                {
                    "projection_field": "action",
                    "verbatim_evidence": "uncertainty probe first",
                },
                {
                    "projection_field": "justification",
                    "verbatim_evidence": "discriminated the explanations at lower cost",
                },
            ],
            "derivation": "contrastive-synthesis",
            "rationale": "Action and justification support value-of-information triage.",
        },
        {
            "target": "outcome",
            "supports": [
                {
                    "projection_field": "outcome",
                    "verbatim_evidence": "ruled out one explanation",
                }
            ],
            "derivation": "direct",
            "rationale": "The outcome is source-visible.",
        },
    ]
    abstraction["transfer_boundary"] = {
        "applies_when": [
            "Candidate explanations predict distinguishable observations.",
            "A diagnostic costs less than the full experiment.",
        ],
        "fails_when": [
            "The diagnostic cannot distinguish the candidates.",
            "The diagnostic consumes the entire budget.",
        ],
        "counterfactual_probe": "Skip the probe if its result cannot change the action.",
        "deliberately_discarded_details": [
            f"The {prefix} dataset identity is not part of the transferable principle."
        ],
    }
    return candidate


def _source_payload(
    *,
    source_id: str,
    relation: str,
    pair_slot_id: str,
    domain: str,
    source_group: str,
    artifact: str,
    artifact_sha: str,
    quality_evidence: str,
    quality_evidence_sha: str,
    locator: str,
) -> dict[str, object]:
    return {
        "source_id": source_id,
        "pair_slot_id": pair_slot_id,
        "relation": relation,
        "stage": "DISCOVERY",
        "decision_role": "hypothesis triage",
        "source_group": source_group,
        "artifact": {"path": artifact, "sha256": artifact_sha},
        "quality_evidence": {
            "path": quality_evidence,
            "sha256": quality_evidence_sha,
        },
        "quality_tier": "peer-reviewed-primary",
        "quality_rationale": "Official venue metadata records archival acceptance.",
        "source_type": "peer_reviewed_paper",
        "locator": locator,
        "title": f"Evidence for {source_id}",
        "accessed_at": "2026-09-12T00:00:00Z",
        "license_id": "CC-BY-4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "redistributable": True,
        "personal_data_removed": True,
        "domain_tags": [domain],
    }


def _candidate_payload(prefix: str) -> dict[str, object]:
    return {
        "candidate_id": f"{prefix}-candidate",
        "source_id": f"{prefix}-source",
        "author_id": f"{prefix}-curator",
        "origin": "human-authored",
        "derivation_method": "Human abstraction of a source-supported research decision.",
        "abstraction": {
            "case_id": f"{prefix}-taste-case",
            "context_summary": "An uncertainty probe can distinguish competing hypotheses.",
            "problem_pattern": "uncertainty probe",
            "evidence_state": "Competing explanations remain open.",
            "candidate_actions": ["PROBE", "IDEATE"],
            "preferred_action": "PROBE",
            "rejected_actions": ["IDEATE"],
            "decision_principle": "Probe uncertainty before expensive commitment.",
            "why_preferred": "The probe resolves decision-relevant uncertainty.",
            "outcome_summary": "The probe distinguished the competing explanations.",
            "confidence": 0.9,
        },
    }


def _review_payload(
    candidate: TasteAbstractionCandidate,
    reviewer_id: str,
    number: int,
    *,
    role: str = "primary",
    verdict: str,
) -> dict[str, object]:
    accepted = verdict == "accept"
    return {
        "review_id": f"{candidate.candidate_id}-review-{number}",
        "candidate_id": candidate.candidate_id,
        "candidate_sha256": candidate.semantic_sha256,
        "reviewer_id": reviewer_id,
        "role": role,
        "verdict": verdict,
        "source_fidelity_supported": accepted,
        "action_grounding_supported": True,
        "principle_generalization_supported": True,
        "scientific_value_supported": True,
        "outcome_handling_supported": True,
        "expertise_scope": "Machine learning research methodology",
        "confidence": 0.9,
        "rationale": "The abstraction is supported." if accepted else "Source fidelity failed.",
        "human_performed": True,
        "conflict_cleared": True,
        "independent_review": True,
        "blinded_to_other_reviews": True,
        "relation_label_blinded": True,
    }


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
