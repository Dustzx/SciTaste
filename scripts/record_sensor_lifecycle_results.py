"""Bind actual review/revision delivery without replacing sealed scientific results."""

import argparse
import json
from pathlib import Path

from scitaste.benchmark.open_research import digest
from scitaste.model_nodes.session_exchange import retain_json


def collect(project, study):
    project, study = project.resolve(strict=True), study.resolve(strict=True)
    sealed = json.loads((study / "RESULTS.json").read_text())
    rows = {}
    for name in ("off", "raw", "taste"):
        prefix = f"sensor-drift-{name}-20261009-v1"
        cycle = project / "evaluations" / (prefix + "-cycle")
        summary_path, feedback_path = cycle / "SUMMARY.json", cycle / "PAPER_FEEDBACK.json"
        summary, feedback = (
            json.loads(summary_path.read_text()),
            json.loads(feedback_path.read_text()),
        )
        source = (
            sealed["separately_charged_recoveries"]["off"]
            if name == "off"
            else sealed["conditions"][name]
        )
        if summary["source_sha256"] != source["first_report_sha256"]:
            raise ValueError("Paper flow does not target its sealed first manuscript")
        original = project / "papers" / prefix / "main.md"
        revised_root = project / "papers" / (prefix + "-revised")
        if (
            summary["status"] != "artifact-flow-complete"
            or digest(original) != summary["source_sha256"]
            or digest(revised_root / "main.md") != summary["revised_sha256"]
            or digest(revised_root / "main.pdf") != summary["pdf_sha256"]
        ):
            raise ValueError("Actual revised-paper artifact binding changed")
        rows[name] = {
            "source_run": source["run"],
            "first_manuscript_sha256": summary["source_sha256"],
            "revised_paper": revised_root.relative_to(project).as_posix(),
            "revised_manuscript_sha256": summary["revised_sha256"],
            "pdf_sha256": summary["pdf_sha256"],
            "cycle": {
                "locator": summary_path.relative_to(project).as_posix(),
                "sha256": digest(summary_path),
            },
            "feedback": {
                "locator": feedback_path.relative_to(project).as_posix(),
                "sha256": digest(feedback_path),
            },
            "review_closed": summary["review_closed"],
            "scientific_quality_established": feedback["scientific_quality_established"],
            "unresolved_work_items": feedback["work_items"],
            "original_failure_replaced": False,
            "new_scientific_experiments_from_prose_revision": False,
        }
    value = {
        "schema_version": "1.0",
        "scientific_results_sha256": digest(study / "RESULTS.json"),
        "scope": "Actual Native first-paper review/revision/PDF delivery; OFF recovery separate",
        "native_conditions": rows,
        "formal_evidence_eligible": False,
        "human_expert_review": False,
        "independent_reproduction_certified": False,
        "publication_ready": False,
        "supplier_api_calls": 0,
        "actual_tokens": None,
        "session_cost_usd": None,
    }
    retain_json(study / "DELIVERY_RESULTS.json", value)
    return value


def collect_claims(project, study):
    """Keep whole-system first papers, Native ablations and recoveries separate."""
    project, study = project.resolve(strict=True), study.resolve(strict=True)
    protocol = json.loads((study / "CLAIM_ASSESSMENT_PROTOCOL.json").read_text())
    obligations = {item["obligation_id"] for item in protocol["required_conclusions"]}
    sources = {
        name: study / name / "claim-assessment/assessment/RESULTS.json"
        for name in ("off", "raw", "taste")
    }
    sources.update(
        {
            "autoresearchclaw": study
            / "external/autoresearchclaw-claim-assessment/assessment-budget-recovery/RESULTS.json",
            "mlr-agent-recovery": study
            / "external/mlr-agent-recovery-claim-assessment"
            / "assessment-consistency-recovery/RESULTS.json",
        }
    )
    rows = {}
    for name, path in sources.items():
        result = json.loads(path.read_text())
        evidence = result["scientific_claim_support"]
        required = evidence["required_judgments"]
        if {item["obligation_id"] for item in required} != obligations:
            raise ValueError("Required scientific-obligation identities changed")
        claims = [*evidence["frozen_atomic_claims"], *evidence["additional_claims"]]
        if not claims or len(claims) > 24:
            raise ValueError("Common bounded assertion budget exceeded")
        manuscript = result["manuscript"]
        if digest(project / manuscript["locator"]) != manuscript["sha256"]:
            raise ValueError("Assessed manuscript changed")
        rows[name] = {
            "result": {"locator": path.relative_to(project).as_posix(), "sha256": digest(path)},
            "manuscript": manuscript,
            "required_scientific_obligations": evidence["counts"],
            "required_denominator": len(obligations),
            "inventory_assertions": len(evidence["frozen_atomic_claims"]),
            "additional_assertions": len(evidence["additional_claims"]),
            "assessed_atomic_assertions": len(claims),
            "unsupported_atomic_assertions": sum(item["status"] != "supported" for item in claims),
            "assertion_status_counts": {
                status: sum(item["status"] == status for item in claims)
                for status in ("supported", "contradicted", "insufficient", "missing")
            },
            "independent_reproduction_certified": False,
            "assessment_admission_failures": [
                {"locator": failure.relative_to(project).as_posix(), "sha256": digest(failure)}
                for failure in sorted(path.parent.parent.glob("*/ADMISSION_FAILURE.json"))
            ],
            "assessment_recovery_does_not_replace_manuscript": True,
        }
    value = {
        "schema_version": "1.0",
        "protocol_sha256": digest(study / "CLAIM_ASSESSMENT_PROTOCOL.json"),
        "original_complete_system_first_papers": {
            "autoresearchclaw": rows["autoresearchclaw"],
            "scitaste-native": rows["taste"],
            "mlr-agent": None,
        },
        "native_experience_ablations": {"raw": rows["raw"], "taste": rows["taste"]},
        "separate_delivery_recovery_papers": {
            "native-off": rows["off"],
            "mlr-agent": rows["mlr-agent-recovery"],
        },
        "original_missing_first_paper_is_not_zero_or_replaced": True,
        "extraction_budget": 18,
        "total_assertion_budget": 24,
        "whole_paper_error_rate_or_system_ranking_established": False,
        "inventory_exhaustiveness_verified": False,
        "human_expert_calibration": False,
        "formal_evidence_eligible": False,
        "supplier_api_calls": 0,
        "actual_tokens": None,
        "session_cost_usd": None,
    }
    retain_json(study / "CLAIM_RESULTS.json", value)
    return value


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("project", "study"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--claims", action="store_true")
    args = parser.parse_args()
    result = (collect_claims if args.claims else collect)(args.project, args.study)
    print(
        json.dumps(
            {
                "record": "CLAIM_RESULTS.json" if args.claims else "DELIVERY_RESULTS.json",
                "formal_evidence_eligible": result["formal_evidence_eligible"],
            }
        )
    )
