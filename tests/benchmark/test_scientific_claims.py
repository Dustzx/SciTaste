"""Synthetic protocol checks, never evidence of real model scientific quality."""

import json

import pytest

from scitaste.benchmark.evidence_synthesis import binding
from scitaste.benchmark.scientific_claims import (
    _additional_passage_binding,
    _additional_quote_provenance,
    additional_assertion_budget,
    prepare,
    score,
)
from scitaste.model_nodes.session_exchange import (
    SessionReply,
    load_retained_request,
    retain_json,
)


def test_prospective_assertion_budget_is_closed_without_changing_legacy_default():
    spec = {"atomic_inventory": [{}] * 18, "limitations": {"total_assertion_budget": 24}}
    assert additional_assertion_budget(spec) == 6
    assert additional_assertion_budget({"atomic_inventory": []}) == 100
    assert additional_assertion_budget({"atomic_inventory": [], "limitations": ["Legacy"]}) == 100
    spec["limitations"]["total_assertion_budget"] = 17
    with pytest.raises(ValueError, match="smaller than"):
        additional_assertion_budget(spec)


def _package(tmp_path):
    root = tmp_path / "project"
    evaluation = root / "evaluations/example"
    evaluation.mkdir(parents=True)
    paper = root / "paper.md"
    paper.write_text("The primary error is 0.2. This proves a universal mechanism.")
    evidence = evaluation / "public.json"
    retain_json(evidence, {"public": {"error": 0.2}, "not_released": {"error": 0.1}})
    spec = {
        "schema_version": "scientific-claims.v1",
        "scope": "development",
        "formal_evidence_eligible": False,
        "manuscript": binding(root, paper),
        "evidence_assets": [
            {
                "asset_id": "measurement",
                "binding": binding(root, evidence),
                "kind": "json",
                "visible_pointers": ["/public"],
            }
        ],
        "required_conclusions": [
            {
                "obligation_id": "outcome",
                "question": "Report the primary measured error.",
                "inventory_claim_ids": ["c1"],
            }
        ],
        "atomic_inventory": [
            {
                "claim_id": "c1",
                "quote": "The primary error is 0.2.",
                "proposition": "The primary error is 0.2.",
                "obligation_ids": ["outcome"],
            }
        ],
        "separate_dimensions": {
            "task_native_confirmation": {
                "scope": "Native score only",
                "evidence_fields": [{"asset_id": "measurement", "pointer": "/public/error"}],
            },
            "reproduction": {"scope": "Independent reproduction unknown", "unknowns": ["replay"]},
            "resource_accounting": {"scope": "Unknown, not zero", "unknowns": ["session cost"]},
            "novelty": {"scope": "Not calibrated"},
        },
        "diagnostics": [
            {
                "case_id": "a",
                "kind": "baseline",
                "required_conclusion": "Report the measured primary error.",
                "asserted_text": "The primary error is 0.2.",
                "expected_status": "supported",
                "anchor_evidence": [{"asset_id": "measurement", "pointer": "/public/error"}],
            },
            {
                "case_id": "b",
                "kind": "style",
                "baseline_case_id": "a",
                "required_conclusion": "Report the measured primary error.",
                "asserted_text": "We obtain an error of 0.2.",
                "expected_status": "supported",
                "anchor_evidence": [{"asset_id": "measurement", "pointer": "/public/error"}],
            },
        ],
        "limitations": ["Synthetic unit fixture only"],
    }
    specification = evaluation / "SPECIFICATION.json"
    retain_json(specification, spec)
    return root, specification, evaluation / "study", evidence


def _reply(root, record, payload):
    path = root / record["request"]["locator"]
    request = load_retained_request(path)
    reply = SessionReply(
        request_id=request.request_id,
        request_fingerprint=request.fingerprint,
        source="assistant-session",
        author_reference="synthetic-unit-test-not-real-model-evidence",
        declared_model_label=None,
        output_payload=payload,
    )
    retain_json(path.with_name(request.fingerprint + ".reply.json"), reply.model_dump(mode="json"))


def _payload():
    citation = {"asset_id": "measurement", "pointer": "/public/error", "quote": "0.2"}
    return {
        "required_judgments": [
            {
                "obligation_id": "outcome",
                "status": "supported",
                "claim_ids": ["c1"],
                "reason": "Fixture published measurement.",
                "evidence": [citation],
            }
        ],
        "atomic_claims": [
            {"claim_id": "c1", "status": "supported", "reason": "Fixture.", "evidence": [citation]}
        ],
        "additional_claims": [
            {
                "claim_id": "extra1",
                "quote": "This proves a universal mechanism.",
                "proposition": "A universal mechanism is established.",
                "status": "insufficient",
                "reason": "A point estimate cannot identify a universal mechanism.",
                "evidence": [citation],
            }
        ],
        "extraction_limits": "This fixture tests counting, not inventory completeness.",
    }


def test_fixed_obligations_extra_unsupported_and_separate_dimensions(tmp_path):
    root, spec, output, _ = _package(tmp_path)
    contract = prepare(root, spec, output)
    _reply(root, contract["requests"][0], _payload())
    diagnostic_request = load_retained_request(root / contract["requests"][1]["request"]["locator"])
    assert "expected_status" not in json.dumps(diagnostic_request.input_payload)
    _reply(
        root,
        contract["requests"][1],
        {
            "judgments": [
                {
                    "case_id": c,
                    "status": "supported",
                    "reason": "Fixture numerical statement.",
                    "evidence": [
                        {"asset_id": "measurement", "pointer": "/public/error", "quote": "0.2"}
                    ],
                }
                for c in ("a", "b")
            ]
        },
    )
    result = score(root, output)
    claims = result["scientific_claim_support"]
    assert claims["required_conclusion_denominator"] == 1
    assert claims["supported_required_fraction"] == 1
    assert claims["extra_unsupported_count"] == 1
    assert (
        result["separate_dimensions"]["task_native_confirmation"]["evidence_fields"][0]["value"]
        == 0.2
    )
    assert result["diagnostics"]["style_status_flips"] == 0
    assert result["diagnostics"]["new_independent_research_tasks"] == 0
    assert not result["formal_evidence_eligible"]
    assert not result["human_novelty_calibrated"]
    assert result["actual_tokens"] is None


def test_changed_bound_evidence_fails_before_preparing_model_request(tmp_path):
    root, spec, output, evidence = _package(tmp_path)
    evidence.write_text('{"public": {"error": 0.1}}')
    with pytest.raises(ValueError, match="Bound benchmark input changed"):
        prepare(root, spec, output)
    assert not output.exists()


def test_citation_cannot_escape_released_view(tmp_path):
    root, spec, output, _ = _package(tmp_path)
    contract = prepare(root, spec, output)
    payload = _payload()
    payload["atomic_claims"][0]["evidence"] = [
        {"asset_id": "measurement", "pointer": "/not_released/error", "quote": "0.1"}
    ]
    _reply(root, contract["requests"][0], payload)
    # Score consumes responses only after all roles are present. Supply the
    # diagnostic fixture as well; there is no real model work in this test.
    _reply(
        root,
        contract["requests"][1],
        {
            "judgments": [
                {
                    "case_id": c,
                    "status": "supported",
                    "reason": "Fixture.",
                    "evidence": [
                        {"asset_id": "measurement", "pointer": "/public/error", "quote": "0.2"}
                    ],
                }
                for c in ("a", "b")
            ]
        },
    )
    with pytest.raises(ValueError, match="escapes the released evidence view"):
        score(root, output)


def test_additional_quote_binds_exact_blinded_view_without_relaxing_science():
    manuscript = "Source /home/example/system/paper.svg supports seven observations."
    quote = "Source [local-artifact-path-withheld] supports seven observations."
    original_binding = {"locator": "paper.md", "sha256": "a" * 64}
    provenance = _additional_quote_provenance(quote, manuscript, original_binding)
    assert provenance["quotation_source"] == "bound_blinded_manuscript_view"
    assert provenance["manuscript_binding"] == original_binding
    assert _additional_quote_provenance("seven observations", manuscript, original_binding) == {}
    with pytest.raises(ValueError, match="absent"):
        _additional_quote_provenance(quote.replace("seven", "eight"), manuscript, original_binding)


def test_shared_sentence_can_contain_two_distinct_atomic_assertions():
    sentence = "The error is 0.2 and improves in nine of ten cases."
    inventory = {"c1": {"claim_id": "c1", "quote": sentence, "proposition": "The error is 0.2."}}
    additional = {"quote": sentence, "proposition": "Nine of ten paired cases improve."}
    assert _additional_passage_binding(additional, inventory) == {
        "shares_passage_with_frozen_claims": ["c1"]
    }
    with pytest.raises(ValueError, match="duplicates"):
        _additional_passage_binding({**additional, "proposition": "The error is 0.2."}, inventory)
