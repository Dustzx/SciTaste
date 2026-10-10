"""Two isolated provider reviews of a grounded abstraction; no Qwen adjudication."""

import argparse
import concurrent.futures
import json
from datetime import UTC, datetime
from pathlib import Path

import yaml

from scitaste.backends.research_provider import research_provider
from scitaste.evaluation.ai_taste_abstraction_review import (
    AIAbstractionPrimaryRequest,
    AIAbstractionRawReviewResponse,
    AIAbstractionReviewExecutionReceipt,
    _binding,
    _canonical_sha256,
    compile_ai_taste_abstraction_review_requests,
    finalize_ai_taste_abstraction_reviews,
    lock_ai_taste_abstraction_primary_reviews,
)
from scitaste.model_nodes.models import StructuredModelRequest
from scitaste.model_nodes.session_exchange import retain_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--abstraction-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-api-execution", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if not args.allow_api_execution:
        raise ValueError("Explicit API authority required")
    root = Path.cwd()
    args.output.mkdir(exist_ok=args.resume)
    configs = {
        "primary-a": Path("configs/model_nodes/deepseek_v41flash.interactive_live_20260917.yaml"),
        "primary-b": Path("configs/model_nodes/zhipu_glm53_flash.scitastebench_live_20260916.yaml"),
    }
    protocol = yaml.safe_load(
        Path(
            "configs/evaluation/pilots/scitastebench_track_a_ai_abstraction_review_v1.yaml"
        ).read_text()
    )
    protocol["protocol_id"] = "nist-source-independent-provider-review-v1"
    for reviewer in [*protocol["primary_reviewers"], protocol["adjudicator"]]:
        role = reviewer["role"]
        config = (
            yaml.safe_load(configs[role].read_text())
            if role in configs
            else {"provider": "unavailable-third-reviewer", "model": "not-configured"}
        )
        reviewer.update(
            provider=config["provider"],
            model=config["model"],
            reviewer_id=f"nist-{role}",
            model_revision="provider-returned-alias-no-weight-snapshot-attestation",
        )
        reviewer["identity_sha256"] = _canonical_sha256(
            {k: reviewer[k] for k in ("provider", "model", "model_revision")}
        )
    retain_json(args.output / "PROTOCOL.json", protocol)
    if not args.resume:
        compile_ai_taste_abstraction_review_requests(
            evidence_root=root,
            runtime_receipt_paths=[args.abstraction_receipt],
            protocol_path=args.output / "PROTOCOL.json",
            output_dir=args.output / "prepared",
            planned_source_count=1,
            eligible_source_count=1,
            runtime_rejected_source_count=0,
        )

    def review(role):
        if args.resume and (args.output / f"{role}-execution.json").is_file():
            return role
        request_path = args.output / "prepared/requests" / f"{role}.json"
        request = AIAbstractionPrimaryRequest.model_validate_json(request_path.read_text())
        bridge, backend = research_provider(
            configs[role], args.output / role, max_calls=2 if args.resume else 1, max_cost_usd=2
        )
        packet = StructuredModelRequest(
            request_id=request.request_id + ("-format-recovery" if args.resume else ""),
            node_name="source-independent-review",
            stage="EVIDENCE",
            state_snapshot_id=request.request_sha256,
            expected_backend=backend.name,
            expected_model=backend.model,
            policy_id="independent-source-review-v1",
            policy_fingerprint=request.protocol_sha256,
            system_instruction="Independently review the exact source and abstraction. Follow the "
            "criteria, not a preference for acceptance. Return the required response schema and "
            "copy reviewer/request identity fields exactly. "
            "No other reviewers' outputs are visible.",
            input_payload=request.model_dump(mode="json"),
            output_schema=AIAbstractionRawReviewResponse.model_json_schema(),
            prompt_version="source-review-v1",
        )
        started = datetime.now(UTC)
        response = backend.complete(packet)
        if response.model != request.reviewer.model:
            raise ValueError("Served model alias differs from frozen reviewer identity")
        payload = json.loads(json.dumps(response.output_payload))
        removed = []
        for index, item in enumerate(payload.get("responses", [])):
            if "confidence" in item:
                removed.append({"index": index, "unscored_confidence": item.pop("confidence")})
        if removed:
            retain_json(
                args.output / f"{role}-normalization.json",
                {
                    "operation": "Drop optional confidence not used by the review protocol",
                    "removed": removed,
                    "provider_response_sha256": response.raw_response_sha256,
                    "disposition_assessment_rationale_unchanged": True,
                },
            )
        raw = AIAbstractionRawReviewResponse.model_validate(payload)
        raw_path = args.output / f"{role}-response.json"
        retain_json(raw_path, raw.model_dump(mode="json"))
        wire = json.loads(sorted(bridge.records.glob("*.response"))[-1].read_text())
        receipt = AIAbstractionReviewExecutionReceipt(
            invocation_id=f"nist-review-{role}",
            reviewer_id=request.reviewer.reviewer_id,
            provider=backend.name,
            model=response.model,
            model_revision=request.reviewer.model_revision,
            reviewer_identity_sha256=request.reviewer.identity_sha256,
            request=_binding(root, request_path.resolve()),
            request_sha256=request.request_sha256,
            raw_response=_binding(root, raw_path.resolve()),
            started_at=started,
            completed_at=datetime.now(UTC),
            provider_request_id=wire["id"],
            http_status=bridge.transport.last_status_code,
            model_call_observed=True,
        )
        retain_json(args.output / f"{role}-execution.json", receipt.model_dump(mode="json"))
        return role

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(review, configs))
    receipt_paths = []
    for role in configs:
        original = args.output / f"{role}-execution.json"
        payload = json.loads(original.read_text())
        declared = payload.pop("receipt_sha256", None)
        parsed = AIAbstractionReviewExecutionReceipt.model_validate(payload)
        if declared is not None and declared != parsed.receipt_sha256:
            raise ValueError("Retained receipt hash mismatch")
        path = args.output / f"{role}-execution-input.json"
        retain_json(path, payload)
        receipt_paths.append(path)
    locked = lock_ai_taste_abstraction_primary_reviews(
        evidence_root=root,
        request_pack_path_or_dir=args.output / "prepared",
        raw_response_paths=tuple(args.output / f"{role}-response.json" for role in configs),
        execution_receipt_paths=tuple(receipt_paths),
        output_dir=args.output / "locked",
    )
    if locked.disputes:
        retain_json(
            args.output / "UNRESOLVED.json",
            {
                "disputes": len(locked.disputes),
                "reason": "No third independent provider configured",
                "candidate_admitted": False,
                "qwen_called": False,
            },
        )
    else:
        final = finalize_ai_taste_abstraction_reviews(
            evidence_root=root,
            locked_primary_reviews_path_or_dir=args.output / "locked",
            output_path=args.output / "FINAL.json",
        )
        print(json.dumps({"accepted": final.accepted_count, "rejected": final.rejected_count}))


if __name__ == "__main__":
    main()
