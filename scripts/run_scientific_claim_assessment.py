"""Prepare/consume manuscript-bound scientific claims, without model API calls."""

# ruff: noqa: E501 -- Literal scientific quotations must remain byte-exact.

import argparse
import json
from pathlib import Path

from scitaste.benchmark.evidence_synthesis import binding
from scitaste.benchmark.open_research import verified_asset
from scitaste.benchmark.scientific_claims import prepare, score
from scitaste.model_nodes.session_exchange import SessionResponsePending, retain_json


def build_perturbation_package(project, output):
    """Bind retained public evidence; never load targets or rerun a research method."""
    root = project.resolve(strict=True)
    output = output.resolve()
    output.relative_to(root / "evaluations")
    campaign_name = "scitastebench-perturbation-three-systems-20261008-v1"
    campaign = root / "evaluations" / campaign_name
    seals_path = campaign / "first-paper-assessment/SUBMISSIONS.json"
    seals = json.loads(seals_path.read_bytes())
    rows = {r["arm"]: r for r in seals["observed"]["rows"]}
    expected_hashes = {r["arm"]: r["paper_sha256"] for r in seals["assessments"]}
    # These obligations are the same across all three papers. Positive findings
    # are not demanded: scientifically warranted uncertainty can answer them.
    questions = [
        (
            "primary-outcome",
            "Report the publicly frozen primary's complete confirmation outcome without replacing it by a better secondary.",
        ),
        (
            "ordinary-calibration",
            "Determine whether ordinary amplitude calibration improves over addition and whether correlation changes; do not equate calibration with interaction.",
        ),
        (
            "pair-specificity",
            "Determine whether pair-conditioned residuals improve over shared/global correction and a matched shuffled control across public and confirmation splits; retain contrary results.",
        ),
        (
            "directional-evidence",
            "Explain what the actual projection/orthogonal-residual controls do and do not establish about condition-specific or biological structure.",
        ),
        (
            "transfer-scope",
            "State the actual known-single, same-assay transfer boundary; unseen combinations are not unseen genes, assays or cell types.",
        ),
        (
            "measurement-identifiability",
            "Distinguish observed alternating-cell variability from independent biological replication or a certified noise ceiling, and retain unresolved biological explanations.",
        ),
    ]
    claim_definitions = {
        "scitaste-native": [
            (
                "primary-outcome",
                "Its all28-condition endpoint is0.06788955386570503.",
                "The frozen global_shift primary has confirmation mean condition RMSE 0.06788955386570503 across all 28 conditions.",
            ),
            (
                "primary-outcome",
                "Every method has28validconditions,1000readouts, failure=null and declared_failure_fraction=0.",
                "All seven predeclared procedures have complete valid 28-condition confirmation outcomes.",
            ),
            (
                "ordinary-calibration",
                "scalar_amplitude improves by0.008291447282209085 (17/28wins); its Pearson delta again agrees with additive to numerical precision.",
                "Scalar amplitude reduces confirmation mean RMSE relative to additive while preserving its control-centered Pearson delta.",
            ),
            (
                "pair-specificity",
                "True ridge beats additive by0.007403635 but is worse than global_shift by0.002399511, winning only10/24paired conditions versus global_shift.",
                "On validation, true residual ridge is worse than global_shift in mean condition RMSE.",
            ),
            (
                "pair-specificity",
                "Secondary residual_ridge improves over global_shift by0.003172897732498298 (18/28wins) and over the one shuffled residual fit by0.008409852554640504 (22/28wins).",
                "On confirmation, the predeclared secondary ridge improves over both global_shift and the one shuffled correspondence control.",
            ),
            (
                "directional-evidence",
                "The contrasts suggest much of this model's incremental RMSE gain is lost when its residual correction parallel to D is removed.",
                "Removing the predicted residual's additive-direction component largely reduces this model's incremental confirmation RMSE gain.",
            ),
            (
                "directional-evidence",
                "This is an intervention on predictions, not a unique causal decomposition: projection can remove useful signal and changes estimator calibration.",
                "The prediction projection does not identify a unique causal biological decomposition.",
            ),
            (
                "transfer-scope",
                "This is unseen combinations of known genes, not unseen genes, cell types, batches or assays.",
                "The evaluation is known-single combination transfer within the same assay, not unseen-gene or cross-assay transfer.",
            ),
            (
                "measurement-identifiability",
                "It is not a randomized independent assay replicate, ideal prediction floor or certified biological noise ceiling.",
                "Alternating-cell split-half discrepancy does not establish an independent assay replicate or certified biological noise ceiling.",
            ),
            (
                "measurement-identifiability",
                "H_noise remains unresolved.",
                "The experiment does not identify noise as the unique explanation of residual errors.",
            ),
        ],
        "autoresearchclaw": [
            (
                "primary-outcome",
                "The frozen primary remains Scalar, even though a predeclared secondary obtains the lowest confirmation point estimate.",
                "The publicly selected scalar primary is retained rather than replaced by the lower-error confirmation secondary.",
            ),
            (
                "primary-outcome",
                "All procedures are valid on 24/24 validation and 28/28 confirmation conditions.",
                "Every predeclared procedure has complete valid public validation and confirmation predictions.",
            ),
            (
                "ordinary-calibration",
                "Relative to addition, its mean RMSE reduction is 10.67% on validation and 10.79% on confirmation.",
                "Scalar amplitude reduces mean condition RMSE relative to addition on both reported splits.",
            ),
            (
                "ordinary-calibration",
                "The confirmation centered delta correlation is 0.8735 for both procedures, so the improved error is compatible with correcting magnitude without changing centered response direction.",
                "Scalar amplitude's confirmation error reduction accompanies unchanged control-centered correlation, supporting a magnitude-correction explanation.",
            ),
            (
                "pair-specificity",
                "On confirmation, Ridge lowers Offset mean RMSE by 3.66%.",
                "The predeclared residual ridge secondary has lower confirmation mean RMSE than the matched amplitude-plus-offset model.",
            ),
            (
                "pair-specificity",
                "validation Ridge is worse than Offset in the complete mean endpoint.",
                "The residual ridge advantage against offset does not persist on validation.",
            ),
            (
                "directional-evidence",
                "Orthog confirmation residual correlation is 0.4742, and its mean RMSE advantage over Offset is about 0.43%, below the practical error threshold.",
                "The orthogonal prediction control has only a small confirmation mean-RMSE advantage over offset despite higher residual correlation.",
            ),
            (
                "directional-evidence",
                "Projection removes amplitude-dependent useful structure as well as potential nuisance.",
                "Projection does not exclusively remove biological interaction or exclusively remove nuisance.",
            ),
            (
                "transfer-scope",
                "It does not test an unseen gene or a change of assay.",
                "The task is not unseen-gene or changed-assay generalization.",
            ),
            (
                "measurement-identifiability",
                "Alternating-cell split-half errors supplied by the trusted evaluator characterize within-condition measurement variability, not independent biological replication or a certified noise ceiling.",
                "Alternating-cell variability is not independent biological replication or a certified noise ceiling.",
            ),
        ],
        "mlr-agent": [
            (
                "primary-outcome",
                "The complete primary endpoint is 0.06750258925748806; there is no survivor average.",
                "The publicly selected orth_d8_q1_l100 primary has complete confirmation mean condition RMSE 0.06750258925748806.",
            ),
            (
                "primary-outcome",
                "Trusted feedback retains all nine methods and all 28 conditions with zero declared failure fraction.",
                "All nine frozen methods have complete 28-condition confirmation outcomes without declared failures.",
            ),
            (
                "ordinary-calibration",
                "Scalar amplitude alone reduces it by 0.008291447, accounting descriptively for 89.03% of the primary's absolute gain.",
                "Scalar calibration's measured RMSE reduction is descriptively 89.03% of the primary's absolute additive-relative RMSE reduction, not a causal proportion of interaction.",
            ),
            (
                "ordinary-calibration",
                "Additive and amplitude control-centered Pearson are equal to numerical precision: 0.873503080 in both cases.",
                "The additive and scalar amplitude controls have equal confirmation control-centered Pearson correlation to numerical precision.",
            ),
            (
                "pair-specificity",
                "Its permutation control is better: 0.072053918 versus 0.072345580.",
                "On validation, the primary's matched permutation control has lower mean RMSE than the primary.",
            ),
            (
                "pair-specificity",
                "It beats the matched permutation by 0.000782108, with 19 of 28 wins, and residual Pearson 0.448892 versus 0.421765.",
                "On confirmation, the primary improves over its matched permutation control, reversing the validation ordering.",
            ),
            (
                "directional-evidence",
                "It does not exclude all global-profile or measurement explanations.",
                "The projected predictor does not eliminate all global-profile or measurement explanations.",
            ),
            (
                "directional-evidence",
                "The primary loses to it by 0.002785933 RMSE and wins on only 9 of 28 paired conditions.",
                "The projected primary is worse on confirmation than the retained ordinary full-residual ridge control.",
            ),
            (
                "transfer-scope",
                "It does not test unseen genes, assay/batch transfer, new cell types, raw-count reconstruction, cell-level heterogeneity or clinical prediction.",
                "The evaluation does not establish unseen-gene, changed-assay, changed-cell-type or clinical transfer.",
            ),
            (
                "measurement-identifiability",
                "These halves are neither new datasets nor independent biological replicates.",
                "The alternating-cell halves do not constitute independent datasets or biological replicates.",
            ),
        ],
    }
    output.mkdir(parents=True, exist_ok=True)
    assignments = []
    for index, arm in enumerate(("scitaste-native", "autoresearchclaw", "mlr-agent"), 1):
        opaque = f"submission-{index}"
        paper = root / rows[arm]["paper"]
        paper_binding = binding(root, paper)
        if paper_binding["sha256"] != expected_hashes[arm]:
            raise ValueError("Original first-complete manuscript changed after assessment seal")
        frozen = campaign / "confirmation" / arm / "release/frozen_submission"
        confirmation = campaign / "confirmation" / arm / "RESULT.json"
        feedback = json.loads(confirmation.read_bytes())
        manifest = json.loads((frozen / "SUBMISSION.json").read_bytes())
        views = [
            "/status",
            "/elapsed_seconds",
            "/executed_frozen_source",
            "/formal_evidence_eligible",
            "/result/status",
            "/result/primary_method",
            "/result/primary_endpoint",
            "/result/primary_scores",
            "/result/source_execution_verified",
            "/result/scope",
            "/result/output_contract_valid",
            "/result/missing_prediction_files",
            "/result/undeclared_npz_files",
            "/result/all_predeclared_method_context_records_retained",
        ]
        for i, _ in enumerate(feedback["result"]["scores"]):
            views.extend([f"/result/scores/{i}/method", f"/result/scores/{i}/context"])
            for key in (
                "mean_condition_rmse",
                "mean_pearson_delta",
                "defined_pearson_delta_conditions",
                "mean_additive_residual_correlation",
                "conditions",
                "readout_genes",
                "declared_failure_fraction",
                "metric_scope",
            ):
                views.append(f"/result/scores/{i}/metrics/{key}")
        assets = [
            {
                "asset_id": "task",
                "binding": binding(root, campaign / "discovery/TASK.md"),
                "kind": "text",
            },
            {
                "asset_id": "confirmation",
                "binding": binding(root, confirmation),
                "kind": "json",
                "visible_pointers": views,
            },
            {
                "asset_id": "frozen-contract",
                "binding": binding(root, frozen / "SUBMISSION.json"),
                "kind": "json",
            },
        ]
        for i, name in enumerate(manifest["files"]):
            path = (frozen / name).resolve(strict=True)
            path.relative_to(frozen.resolve(strict=True))
            assets.append(
                {
                    "asset_id": f"frozen-file-{i}",
                    "binding": binding(root, path),
                    "kind": "json" if path.suffix == ".json" else "text",
                }
            )
        if arm == "scitaste-native":
            research = root / rows[arm]["run"] / "workspace/research"
            public_result = research / "public/SUMMARY.json"
            assets.extend(
                [
                    {
                        "asset_id": "public-results",
                        "binding": binding(root, public_result),
                        "kind": "json",
                    },
                    {
                        "asset_id": "replay-audit",
                        "binding": binding(root, research / "REPLAY_AUDIT.json"),
                        "kind": "json",
                    },
                ]
            )
        elif arm == "autoresearchclaw":
            public_result = (
                root
                / rows[arm]["run"]
                / "work/upstream_run/stage-12/runs/sandbox/_project_1/public_diagnostics/results.json"
            )
            assets.append(
                {
                    "asset_id": "public-results",
                    "binding": binding(root, public_result),
                    "kind": "json",
                }
            )
        else:
            public_result = root / rows[arm]["run"] / "workspace/results/public_results.json"
            assets.append(
                {
                    "asset_id": "public-results",
                    "binding": binding(root, public_result),
                    "kind": "json",
                }
            )
        inventory = [
            {
                "claim_id": f"c-{i:02d}",
                "quote": quote,
                "proposition": proposition,
                "obligation_ids": [obligation],
            }
            for i, (obligation, quote, proposition) in enumerate(claim_definitions[arm], 1)
        ]
        obligations = [
            {
                "obligation_id": obligation,
                "question": question,
                "inventory_claim_ids": [
                    c["claim_id"] for c in inventory if obligation in c["obligation_ids"]
                ],
            }
            for obligation, question in questions
        ]
        spec = {
            "schema_version": "scientific-claims.v1",
            "scope": "development",
            "formal_evidence_eligible": False,
            "task_id": "combinatorial-perturbation",
            "manuscript": paper_binding,
            "original_seal": binding(root, seals_path),
            "evidence_assets": assets,
            "required_conclusions": obligations,
            "atomic_inventory": inventory,
            "separate_dimensions": {
                "task_native_confirmation": {
                    "scope": "Original publicly selected complete endpoint in native units; no secondary winner replacement",
                    "evidence_fields": [
                        {"asset_id": "confirmation", "pointer": p}
                        for p in (
                            "/result/primary_method",
                            "/result/primary_endpoint",
                            "/result/primary_scores",
                            "/result/output_contract_valid",
                        )
                    ],
                },
                "reproduction": {
                    "scope": "Frozen source and helper inventory plus actual service execution; no independent upstream reconstruction certificate",
                    "evidence_fields": [
                        {"asset_id": "confirmation", "pointer": p}
                        for p in ("/executed_frozen_source", "/result/source_execution_verified")
                    ],
                    "unknowns": [
                        "Independent raw-source preprocessing audit and complete environmental reproduction"
                    ],
                },
                "resource_accounting": {
                    "scope": "Measured confirmation-service wall time only; it is not full autonomous lifecycle time or CPU seconds",
                    "evidence_fields": [
                        {"asset_id": "confirmation", "pointer": "/elapsed_seconds"}
                    ],
                    "unknowns": [
                        "Verified backbone identity",
                        "Actual model tokens and session cost",
                        "Complete lifecycle CPU accounting",
                    ],
                },
                "novelty": {
                    "scope": "Not measured by this evidence-consistency evaluator; prior uncalibrated ordinal ratings remain separate historical evidence",
                    "unknowns": [
                        "Human-agreement/novelty validity",
                        "Matched modern subject-model comparison",
                        "Original scientific contribution beyond ordinary controls",
                    ],
                },
            },
            "limitations": [
                "Post-outcome author-constructed development evaluation, not prospective formal benchmark scoring.",
                "Six identical task obligations are frozen before these model judgments but after original research outcomes; do not claim preregistration.",
                "Ten author-enumerated assertions per manuscript are not an independently exhaustive atomic claim inventory; model-added omissions remain possible.",
                "Exact bound evidence citation verifies grounding location, not semantic truth or independent evaluator identity.",
                "Fresh session assessors have unverified backbone identity; no human novelty calibration, venue certification, model-parity ranking or additional research task.",
                "The same task/source family remains one research task; additional assertions and diagnostic variants are not independent task samples.",
                "Original 15 first-paper grades and the old 12-statement/48-rating C28 diagnostic are preserved, not replaced or counted again.",
            ],
        }
        if arm == "scitaste-native":
            conclusion = "Identify the publicly frozen primary method and its complete confirmation mean condition RMSE; do not replace the primary with a secondary winner."
            baseline_text = "The publicly selected and frozen primary remains global_shift: confirmation mean condition RMSE=0.06788955386570503 on all28conditions."
            anchors = [
                {"asset_id": "confirmation", "pointer": p}
                for p in ("/result/primary_method", "/result/primary_scores")
            ]
            spec["diagnostics"] = [
                {
                    "case_id": "r-a471",
                    "kind": "baseline",
                    "required_conclusion": conclusion,
                    "asserted_text": baseline_text,
                    "expected_status": "supported",
                    "anchor_evidence": anchors,
                    "source_quote": baseline_text,
                },
                {
                    "case_id": "r-19bc",
                    "kind": "style",
                    "baseline_case_id": "r-a471",
                    "required_conclusion": conclusion,
                    "asserted_text": "Across all 28 confirmation conditions, the publicly selected global_shift primary attained a mean condition RMSE of 0.06788955386570503.",
                    "expected_status": "supported",
                    "anchor_evidence": anchors,
                    "source_quote": baseline_text,
                },
                {
                    "case_id": "r-dd83",
                    "kind": "known-corruption",
                    "baseline_case_id": "r-a471",
                    "required_conclusion": conclusion,
                    "asserted_text": "The publicly selected and frozen primary was residual_ridge: confirmation mean condition RMSE=0.06471665613320672 on all28conditions.",
                    "expected_status": "contradicted",
                    "anchor_evidence": anchors,
                    "source_quote": baseline_text,
                },
                {
                    "case_id": "r-307e",
                    "kind": "omission",
                    "baseline_case_id": "r-a471",
                    "required_conclusion": conclusion,
                    "asserted_text": "All seven declared procedures were evaluated on the confirmation conditions.",
                    "expected_status": "missing",
                    "anchor_evidence": anchors,
                    "source_quote": baseline_text,
                },
            ]
        directory = output / opaque
        directory.mkdir(exist_ok=True)
        retain_json(directory / "SPECIFICATION.json", spec)
        contract_path = directory / "study/CONTRACT.json"
        if contract_path.exists():
            contract = json.loads(contract_path.read_bytes())
            if contract["specification"] != binding(root, directory / "SPECIFICATION.json"):
                raise ValueError("Existing assessment contract has a different specification")
        else:
            contract = prepare(root, directory / "SPECIFICATION.json", directory / "study")
        assignments.append(
            {
                "submission_id": opaque,
                "arm": arm,
                "manuscript": paper_binding,
                "specification": binding(root, directory / "SPECIFICATION.json"),
                "contract": binding(root, directory / "study/CONTRACT.json"),
                "requests": contract["requests"],
            }
        )
    retain_json(
        output / "ASSIGNMENTS.json",
        {
            "scope": "development",
            "task_families": 1,
            "research_tasks": 1,
            "assigned_systems": 3,
            "assessments": assignments,
            "formal_evidence_eligible": False,
        },
    )
    retained = []
    assessment_paths = [
        root / "evaluations" / name / relative
        for name, relative in (
            (
                "scitastebench-qm9-gap-three-systems-20261007-v2",
                "first-paper-assessment/RESULTS.json",
            ),
            (
                "scitastebench-hpatches-three-systems-20261008-v1",
                "first-paper-assessment-flow/assessment/RESULTS.json",
            ),
            (
                "scitastebench-burgers-three-systems-20261008-v1",
                "first-paper-assessment/RESULTS.json",
            ),
            (
                "scitastebench-m4-monthly-three-systems-20261008-v2",
                "first-paper-assessment/RESULTS.json",
            ),
            (
                "scitastebench-acs-population-three-systems-20261008-v1",
                "first-paper-assessment/RESULTS.json",
            ),
            (campaign_name, "first-paper-assessment/RESULTS.json"),
        )
    ]
    for path in assessment_paths:
        previous = json.loads(path.read_bytes())
        retained.append(
            {
                "binding": binding(root, path),
                "task_id": previous["task_id"],
                "rows": [
                    {
                        "arm": r["arm"],
                        "paper": r["paper"],
                        "requirement_categories": len(r.get("task_claims", [])),
                        "rubric_judge_calibrated": r.get("task_claim_judge_calibrated", False),
                    }
                    for r in previous["rows"]
                ],
            }
        )
    previous_diagnostic = (
        root / "evaluations/claim-consistency-diagnostic-20261004-v1/study/RESULTS.json"
    )
    c28 = json.loads(previous_diagnostic.read_bytes())
    retain_json(
        output / "EVIDENCE_INDEX.json",
        {
            "scope": "development",
            "deliverable": "New manuscript-bound atomic assertions with fixed question obligations; not relabeled old rubric counts",
            "old_assigned_framework_tasks": sum(len(r["rows"]) for r in retained),
            "old_first_paper_assessments": sum(
                bool(row["paper"]) for r in retained for row in r["rows"]
            ),
            "old_rubric_assessments": retained,
            "prior_C28": {
                "binding": binding(root, previous_diagnostic),
                "base_statements": c28["base_statements"],
                "ratings": c28["judgments"],
                "reused_as_new_evidence": False,
            },
            "new_assessed_original_manuscripts": 3,
            "new_frozen_scientific_assertions": 30,
            "same_required_scientific_questions_per_paper": 6,
            "new_diagnostic_cases": 4,
            "research_tasks": 1,
            "formal_evidence_eligible": False,
            "private_target_labels_loaded": False,
            "public_task_brief_loaded": True,
            "supplier_api_calls": 0,
            "gpu_calls": 0,
            "next_action": "Use fresh role-isolated model responses, then score each study; no outcome claimed before response consumption.",
        },
    )
    return assignments


def score_package(project, output):
    """Retain a three-system summary only after each original bound review exists."""
    root = project.resolve(strict=True)
    output = output.resolve(strict=True)
    output.relative_to(root / "evaluations")
    assignment_path = output / "BLIND_ASSIGNMENTS.json"
    if not assignment_path.exists():
        assignment_path = output / "ASSIGNMENTS.json"
    assignments = json.loads(assignment_path.read_bytes())
    if assignments["assigned_systems"] != len(assignments["assessments"]):
        raise ValueError("Frozen system denominator changed")
    shared_questions = None
    rows = []
    for item in assignments["assessments"]:
        contract = verified_asset(root, item["contract"])
        specification = verified_asset(root, item["specification"])
        spec = json.loads(specification.read_bytes())
        questions = [(r["obligation_id"], r["question"]) for r in spec["required_conclusions"]]
        if shared_questions is None:
            shared_questions = questions
        if questions != shared_questions:
            raise ValueError("Systems were not assessed against identical scientific questions")
        result = score(root, contract.parent)
        claims = result["scientific_claim_support"]
        rows.append(
            {
                "submission_id": item["submission_id"],
                "arm": item["arm"],
                "manuscript": item["manuscript"],
                "result": binding(root, contract.parent / "RESULTS.json"),
                "required_conclusions": claims["required_conclusion_denominator"],
                "required_status_counts": claims["counts"],
                "supported_required_fraction": claims["supported_required_fraction"],
                "frozen_assertion_count": len(claims["frozen_atomic_claims"]),
                "frozen_assertion_status_counts": {
                    name: sum(c["status"] == name for c in claims["frozen_atomic_claims"])
                    for name in ("supported", "contradicted", "insufficient", "missing")
                },
                "additional_assertion_count": len(claims["additional_claims"]),
                "extra_unsupported_count": claims["extra_unsupported_count"],
                "separate_dimensions": result["separate_dimensions"],
            }
        )
    result = {
        "schema_version": "scientific-claims-comparison.v1",
        "scope": "development",
        "task_id": "combinatorial-perturbation",
        "research_tasks": 1,
        "assigned_systems": assignments["assigned_systems"],
        "shared_required_questions": shared_questions,
        "rows": rows,
        "formal_evidence_eligible": False,
        "human_novelty_calibrated": False,
        "overall_score": None,
        "scope_limits": "Post-outcome author-enumerated claim inventory, not a complete benchmark or matched-backbone causal ranking. Extra assertions cannot improve the fixed required-conclusion denominator. Native score, scientific support, reproduction, resource accounting and novelty are not pooled.",
    }
    retain_json(output / "RESULTS.json", result)
    return result


def prepare_blind_successor(project, output):
    """Retain the initial unconsumed inputs; issue path-redacted successor requests."""
    root = project.resolve(strict=True)
    output = output.resolve(strict=True)
    output.relative_to(root / "evaluations")
    original = json.loads((output / "ASSIGNMENTS.json").read_bytes())
    records = []
    for item in original["assessments"]:
        specification = verified_asset(root, item["specification"])
        study = specification.parent / "study-blind"
        contract = prepare(root, specification, study)
        records.append(
            {
                **item,
                "contract": binding(root, study / "CONTRACT.json"),
                "requests": contract["requests"],
            }
        )
    successor = {
        **original,
        "assessments": records,
        "predecessor": binding(root, output / "ASSIGNMENTS.json"),
        "input_revision_reason": "Initial binding locators reveal framework assignments. New path-redacted inputs precede fresh assessment; no original manuscript, scientific claim, obligation or evidence is changed.",
        "original_requests_retained_not_consumed": True,
        "identity_blinding_certified": False,
    }
    retain_json(output / "BLIND_ASSIGNMENTS.json", successor)
    return successor


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=(
            "prepare",
            "score",
            "build-perturbation-package",
            "score-package",
            "prepare-blind-successor",
        ),
    )
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--specification", type=Path)
    args = parser.parse_args()
    try:
        if args.action == "build-perturbation-package":
            result = build_perturbation_package(args.project, args.output)
        elif args.action == "score-package":
            result = score_package(args.project, args.output)
        elif args.action == "prepare-blind-successor":
            result = prepare_blind_successor(args.project, args.output)
        elif args.action == "prepare":
            if args.specification is None:
                parser.error("prepare needs an explicit bound scientific-claim specification")
            result = prepare(args.project, args.specification, args.output)
        else:
            result = score(args.project, args.output)
    except SessionResponsePending as exc:
        print(json.dumps({"status": "awaiting-session-response", "request": str(exc)}))
        return 75
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
