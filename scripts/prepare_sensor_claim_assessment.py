"""Extract a bounded claim inventory, then reuse the evidence-bound claim assessor.

The inventory model never sees outcomes outside the first manuscript. A separate
fresh-context assessor receives own-arm public evidence. Neither is expert gold.
"""

import argparse
import hashlib
import json
from pathlib import Path

from scitaste.benchmark.evidence_synthesis import binding
from scitaste.benchmark.scientific_claims import prepare, score
from scitaste.model_nodes.models import StructuredModelRequest
from scitaste.model_nodes.session_exchange import (
    SessionResponsePending,
    SessionStructuredBackend,
    retain_json,
)
from scitaste.writing.confirmation_evidence import native_confirmation_evidence


def inventory_request(project, study, condition, output):
    project, study = project.resolve(strict=True), study.resolve(strict=True)
    frozen = json.loads((study / "STUDY.json").read_text())
    external_arm = {
        "autoresearchclaw": "autoresearchclaw",
        "mlr-agent-recovery": "mlr-agent",
    }.get(condition)
    if external_arm:
        systems = json.loads((study / "external/SCIENTIFIC_RESULTS.json").read_text())
        original = systems["original_methods"][external_arm]
        run = project / original["run"]
        source_result = run / (
            "SESSION_CLOSED.json" if external_arm == "autoresearchclaw" else "RESULT.json"
        )
        if condition == "mlr-agent-recovery":
            recovery = systems["separately_charged_delivery_recoveries"][external_arm]
            source_result = project / recovery["result"]["locator"]
            run = source_result.parent
            paper = project / recovery["paper"]["locator"]
        else:
            paper = project / original["first_paper"]["locator"]
        assignment = {"run": run.relative_to(project).as_posix()}
        workspace = run / ("work" if external_arm == "autoresearchclaw" else "workspace")
        campaign = study / "external/CAMPAIGN.json"
        confirmation = campaign.parent / "confirmation" / external_arm
    else:
        assignment = frozen["allocations"][condition]
        if condition == "off":
            registry = study / "off/RECOVERY_ASSIGNMENTS.json"
            assignment = json.loads(registry.read_text())["scitaste-native"]
        run = project / assignment["run"]
        workspace = run / "workspace"
        paper = workspace / "report/report.md"
        source_result = run / "RESULT.json"
        campaign = project / frozen["allocations"][condition]["campaign"]["locator"]
        confirmation = (
            project / assignment["confirmation"]
            if condition == "off"
            else campaign.parent / "confirmation/scitaste-native"
        )
    # A delivered report must already be terminal; never extract from a draft
    # that the framework is still editing.
    terminal = json.loads(source_result.read_text())
    if not external_arm and not terminal.get("report_exists"):
        raise ValueError("No terminal first manuscript exists")
    protocol = study / "CLAIM_ASSESSMENT_PROTOCOL.json"
    obligations = json.loads(protocol.read_text())["required_conclusions"]
    ids = [row["obligation_id"] for row in obligations]
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["claims", "extraction_limits"],
        "properties": {
            "claims": {
                "type": "array",
                "minItems": 1,
                "maxItems": 18,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["claim_id", "quote", "proposition", "obligation_ids"],
                    "properties": {
                        "claim_id": {"type": "string", "minLength": 1},
                        "quote": {"type": "string", "minLength": 1, "maxLength": 3000},
                        "proposition": {"type": "string", "minLength": 1, "maxLength": 1000},
                        "obligation_ids": {
                            "type": "array",
                            "uniqueItems": True,
                            "items": {"enum": ids},
                        },
                    },
                },
            },
            "extraction_limits": {"type": "string", "minLength": 1},
        },
    }
    inputs = {
        "manuscript": {"sha256": binding(project, paper)["sha256"], "text": paper.read_text()},
        "required_conclusions": obligations,
        "inventory_budget": 18,
        "total_assessment_budget": 24,
        "scope": (
            "One first complete manuscript; same protocol and extraction budget for all conditions"
        ),
    }
    request = StructuredModelRequest(
        request_id="first-manuscript-claim-inventory",
        node_name="benchmark-scientific-claim-inventory",
        stage="REVIEW",
        state_snapshot_id=hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest(),
        expected_backend="assistant-session",
        expected_model="session-authored",
        policy_id="sensor-first-manuscript-claims-v1",
        policy_fingerprint=binding(project, protocol)["sha256"],
        system_instruction=(
            "Extract at most 18 consequential atomic scientific assertions from this manuscript. "
            "Use exact verbatim quotes and distinct propositions. Cover primary outcomes, control "
            "comparisons, claimed mechanisms, fitting boundaries, composition "
            "and scientific scope. "
            "Retain strong or dubious claims as well as warranted uncertainty; do not select only "
            "easy numeric or cautious statements. No judging, correcting, external search or "
            "invented assertion. Do not infer an omitted conclusion from data. No evidence beyond "
            "the manuscript is supplied. State inventory limitations; not an exhaustive error rate."
        ),
        input_payload=inputs,
        output_schema=schema,
        prompt_version="sensor-first-manuscript-claims-v1",
    )
    output.mkdir(parents=True, exist_ok=True)
    retain_json(
        output / "INVENTORY_CONTRACT.json",
        {
            "manuscript": binding(project, paper),
            "protocol": binding(project, protocol),
            "source_run": assignment["run"],
            "source_result": binding(project, source_result),
            "inventory_budget": 18,
            "total_assessment_budget": 24,
            "independent_inventory_completeness_verified": False,
            "original_off_failure_replaced": False,
            **(
                {
                    "actual_framework": external_arm,
                    "timepoint": "separately-charged-delivery-recovery"
                    if condition == "mlr-agent-recovery"
                    else "original-first-complete-paper",
                    "original_failure_replaced": False,
                    "whole_system_results": binding(
                        project, study / "external/SCIENTIFIC_RESULTS.json"
                    ),
                }
                if external_arm
                else {}
            ),
        },
    )
    exchange = output / "inventory/exchange"
    try:
        response = SessionStructuredBackend(exchange, max_requests=1).complete(request)
    except SessionResponsePending:
        return {"status": "inventory-response-pending", "exchange": str(exchange)}
    claims = response.output_payload["claims"]
    manuscript = paper.read_text()
    if any(row["quote"] not in manuscript for row in claims):
        raise ValueError("Inventory quote absent from unchanged first manuscript")
    if len({row["claim_id"] for row in claims}) != len(claims):
        raise ValueError("Duplicate atomic claim identifier")
    conclusions = [
        {
            **row,
            "inventory_claim_ids": [
                c["claim_id"] for c in claims if row["obligation_id"] in c["obligation_ids"]
            ],
        }
        for row in obligations
    ]
    if external_arm:
        from scripts.summarize_sensor_external_systems import confirmation as verify_confirmation

        original_run = project / systems["original_methods"][external_arm]["run"]
        verified = verify_confirmation(project, campaign, external_arm, original_run)
        retain_json(
            output / "CONFIRMATION_EVIDENCE.json",
            {
                "scope": "Actual unchanged-source execution, not independent reproduction",
                "receipt": verified["receipt"],
                "executed_frozen_source": verified["executed_frozen_source"],
                "execution": binding(project, confirmation / "EXECUTION_CONTRACT.json"),
                "inference": binding(project, confirmation / "INFERENCE_RESULT.json"),
                "independent_reproduction_certified": False,
                "formal_evidence_eligible": False,
                "original_failure_replaced": False,
            },
        )
    else:
        native_confirmation_evidence(project, run, output / "CONFIRMATION_EVIDENCE.json")
    recipe = json.loads((confirmation / "release/frozen_submission/SUBMISSION.json").read_text())
    execution_task = (
        project / json.loads(campaign.read_text())["execution_brief"]["locator"]
        if external_arm
        else workspace / "data/TASK.md"
    )
    protocol_path = (
        confirmation / "release/PROTOCOL.json" if external_arm else workspace / "data/PROTOCOL.json"
    )
    assets = [
        ("task", execution_task, "text"),
        ("protocol", protocol_path, "json"),
        ("confirmation", confirmation / "RESULT.json", "json"),
        (
            "frozen-procedure",
            confirmation / "release/frozen_submission" / recipe["entrypoint"],
            "text",
        ),
        ("submission", confirmation / "release/frozen_submission/SUBMISSION.json", "json"),
        ("execution-provenance", output / "CONFIRMATION_EVIDENCE.json", "json"),
    ]
    for index, name in enumerate(recipe.get("files", [])):
        if name != recipe["entrypoint"]:
            helper = (confirmation / "release/frozen_submission" / name).resolve(strict=True)
            helper.relative_to(confirmation / "release/frozen_submission")
            assets.append((f"frozen-helper-{index}", helper, "text"))
    public_paths = sorted(
        {
            path
            for name in (
                "results/public",
                "experiments/public",
                "results/floor-probe",
                "results/interface-floor",
                "report",
            )
            for path in (workspace / name).rglob("*.json")
        }
    )
    for index, path in enumerate(public_paths):
        if path.stat().st_size <= 600_000:
            assets.append((f"public-{index}", path, "json"))
    if external_arm == "mlr-agent":
        summary = original_run / "workspace/results/results.md"
        if summary.is_file():
            assets.append(("original-public-research-summary", summary, "text"))
    spec = {
        "schema_version": "scientific-claims.v1",
        "scope": "development",
        "formal_evidence_eligible": False,
        "manuscript": binding(project, paper),
        "required_conclusions": conclusions,
        "atomic_inventory": claims,
        "inventory_origin": binding(project, output / "INVENTORY_CONTRACT.json"),
        "inventory_extraction_limits": response.output_payload["extraction_limits"],
        "evidence_assets": [
            {"asset_id": name, "binding": binding(project, path), "kind": kind}
            for name, path, kind in assets
        ],
        "separate_dimensions": {
            name: {"scope": "Separate, not inferred from paper fluency or point estimates"}
            for name in (
                "task_native_confirmation",
                "reproduction",
                "resource_accounting",
                "novelty",
            )
        },
        "limitations": {
            "inventory": response.output_payload["extraction_limits"],
            "total_assertion_budget": 24,
            "inventory_completeness_independently_verified": False,
            "human_gold": False,
            "formal_evidence_eligible": False,
        },
    }
    specification = output / "SPECIFICATION.json"
    retain_json(specification, spec)
    assessment = output / "assessment"
    if not (assessment / "CONTRACT.json").is_file():
        prepare(project, specification, assessment)
    return {
        "status": "fresh-assessment-response-pending",
        "assessment": str(assessment),
        "additional_claim_budget": 24 - len(claims),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("project", "study", "output"):
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument(
        "--condition",
        choices=("off", "raw", "taste", "autoresearchclaw", "mlr-agent-recovery"),
        required=True,
    )
    parser.add_argument("--score", action="store_true")
    args = parser.parse_args()
    if args.score:
        specification = json.loads((args.output / "SPECIFICATION.json").read_text())
        request_dir = args.output / "assessment/original-manuscript/exchange"
        replies = list(request_dir.glob("*.reply.json"))
        if len(replies) != 1:
            raise ValueError("One explicit independent assessment reply required")
        payload = json.loads(replies[0].read_text())["output_payload"]
        if len(specification["atomic_inventory"]) + len(payload["additional_claims"]) > 24:
            raise ValueError("Prospective total atomic assessment budget exceeded")
        result = score(args.project, args.output / "assessment")
    else:
        result = inventory_request(args.project, args.study, args.condition, args.output)
    print(json.dumps(result, ensure_ascii=False))
