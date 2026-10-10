"""Carry a frozen development package through report, independent review and revision.

This produces evidence-buffer artifacts, never promotes findings into a paper or
changes experiment results. Each role has stateless inputs and a one-call budget.
"""

import argparse
import hashlib
import json
from pathlib import Path

from scitaste.backends.research_provider import research_provider
from scitaste.model_nodes.models import StructuredModelRequest
from scitaste.model_nodes.session_exchange import SessionStructuredBackend, retain_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--allow-api-execution", action="store_true")
    parser.add_argument("--session", action="store_true")
    parser.add_argument("--session-wait-seconds", type=int, default=600)
    args = parser.parse_args()
    if args.session == args.allow_api_execution:
        raise ValueError("Select exactly one of session execution or explicit API execution")
    if not 1 <= args.session_wait_seconds <= 3600:
        raise ValueError("Session wait must be between 1 and 3600 seconds")
    report = args.package / "FINAL_REPORT.json"
    raw = report.read_bytes()
    evidence = json.loads(raw)
    if evidence.get("formal_evidence_eligible") is not False:
        raise ValueError("This development synthesis cannot consume formal results")
    supporting = {}
    for relative, expected in evidence.get("result_sha256", {}).items():
        path = (args.package.parent / relative).resolve(strict=True)
        path.relative_to(args.package.parent.resolve())
        artifact = path.read_bytes()
        if hashlib.sha256(artifact).hexdigest() != expected:
            raise ValueError("Frozen supporting evidence hash mismatch")
        supporting[relative] = (
            [json.loads(line) for line in artifact.splitlines() if line.strip()]
            if path.suffix == ".jsonl"
            else artifact.decode("utf-8")
            if path.suffix in {".py", ".md"}
            else json.loads(artifact)
        )
    output = args.package / "synthesis"
    output.mkdir(exist_ok=False)
    digest = hashlib.sha256(raw).hexdigest()
    retain_json(
        output / "PLAN.json",
        {
            "evidence_sha256": digest,
            "stages": ["report", "review", "revision"],
            "calls_per_stage": 1,
            "conservative_liability_cap_per_stage_usd": 0 if args.session else 2,
            "model_source": "assistant-session" if args.session else "provider-api",
            "session_tokens_and_cost": "unknown" if args.session else None,
            "automatic_paper_promotion": False,
            "extra_experiments": 0,
        },
    )
    contexts = {
        "frozen_results": evidence,
        "evidence_sha256": digest,
        "supporting_artifacts": supporting,
    }
    configs = {
        "research": Path("configs/model_nodes/deepseek_v41flash.interactive_live_20260917.yaml"),
        "review": Path("configs/model_nodes/zhipu_glm53_flash.scitastebench_live_20260916.yaml"),
    }
    instructions = {
        "report": "Write a compact scientific evidence-buffer report, not a submission paper. "
        "Distinguish original-controller completion, common terminal delivery and scoring. "
        "Only use distinctions present in this task's evidence; ML experiments may instead "
        "contain multiple code revisions with separate measured forgetting/utility components. "
        "Do not infer efficacy from consultation counts or correctness from small RMSLE. "
        "Null submission alone cannot identify the failure cause. Include every planned row, "
        "scientific limits, and concrete next decisions without repeating tasks for wins. "
        "Use actual tool measurements to explain the research question, candidate hypotheses, "
        "intervention strategy and discovered or unresolved relation. Do not reduce the report "
        "to a status ledger. Start with a '# Title' section followed by a scientific title. "
        "Keep result tables narrow and separate scientific results from cost/provenance.",
        "review": "Independently review the report against frozen results. Identify unsupported "
        "claims, missing controls, metric pitfalls and any premature readiness conclusion. "
        "Prioritize consequential scientific/execution issues; do not demand cosmetic tests.",
        "revision": "Revise the evidence-buffer report using the independent review. Include "
        "a concise criticism-to-change record and prioritized next execution package. Preserve "
        "failures and all result values. Do not invent experiments or claim full-chain "
        "scientific success merely because a report and review now exist.",
    }
    for stage in ("report", "review", "revision"):
        if args.session:
            backend = SessionStructuredBackend(
                output / stage, wait_seconds=args.session_wait_seconds, max_requests=1
            )
        else:
            _bridge, backend = research_provider(
                configs["review" if stage == "review" else "research"],
                output / stage,
                max_calls=1,
                max_cost_usd=2,
            )
        packet = StructuredModelRequest(
            request_id=f"package-{stage}",
            node_name=f"package-{stage}",
            stage="EVIDENCE",
            state_snapshot_id=digest,
            expected_backend=backend.name,
            expected_model=backend.model,
            policy_id="development-package-synthesis-v1",
            policy_fingerprint=digest,
            system_instruction=instructions[stage]
            + " Task labels are not physical ground truth: complex-system variants may differ "
            "from textbook laws. Never declare a formula correct or a scorer defective from "
            "its familiar name. Common terminal used means attempted, not delivered. Identical "
            "small terminal status objects alone do not establish copied trajectories. "
            "Do not discard failed rows or rerun them to replace scores."
            + ' Return JSON with exactly one key "markdown", containing the document.',
            input_payload=dict(contexts),
            output_schema={
                "type": "object",
                "required": ["markdown"],
                "properties": {"markdown": {"type": "string"}},
                "additionalProperties": False,
            },
            prompt_version="package-synthesis-v1",
        )
        response = backend.complete(packet)
        text = response.output_payload.get("markdown")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Model did not deliver a document; retained call is not replayed")
        with (output / f"{stage.upper()}.md").open("x") as stream:
            stream.write(text + "\n")
        retain_json(output / f"{stage.upper()}_RECEIPT.json", response.model_dump(mode="json"))
        contexts[stage] = text
        print(json.dumps({"stage": stage, "status": "retained"}), flush=True)
    if hashlib.sha256(report.read_bytes()).hexdigest() != digest:
        raise ValueError("Evidence changed during synthesis")
    retain_json(
        output / "COMPLETE.json",
        {
            "evidence_sha256": digest,
            "stages_completed": 3,
            "scientific_success_established": False,
            "formal_evidence_eligible": False,
            "adoption_status": "unadopted-model-candidate",
        },
    )


if __name__ == "__main__":
    main()
