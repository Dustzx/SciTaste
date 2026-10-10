"""Run bounded AI attribution review on collected experience; never auto-admit."""

import argparse
import json
from pathlib import Path

from scitaste.backends.mlagentbench import MLAgentBenchProviderBridge, provider_ledger_accounting
from scitaste.model_nodes.experience_attribution import (
    ExperienceAttributionInput,
    ExperienceAttributionNode,
)
from scitaste.model_nodes.models import NodeContext, NodePolicy
from scitaste.model_nodes.shared_ledger_backend import SharedLedgerStructuredBackend
from scitaste.project import ProjectRuntime, inspect_current_idea_revision
from scitaste.taste.ai_attribution import (
    AITasteAttributionReviewNode,
    build_ai_taste_attribution_review_material,
)
from scitaste.taste.episodes import TasteEpisodeCandidate
from scripts import run_mlrc_native_development_loop as shared


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-api", action="store_true")
    parser.add_argument("--draft-attribution", action="store_true")
    parser.add_argument("--revision-review", type=Path)
    parser.add_argument(
        "--backend",
        type=Path,
        default=Path("configs/model_nodes/bailian_qwen38max.taste_review_live_20260916.yaml"),
    )
    parser.add_argument(
        "--credentials", type=Path, default=Path("outputs/resources/access/credentials.env")
    )
    args = parser.parse_args()
    if args.revision_review and not args.draft_attribution:
        raise ValueError("Revision feedback applies only to attribution drafting")
    if not args.allow_api:
        raise ValueError("Explicit API enablement required")
    candidate = TasteEpisodeCandidate.model_validate_json(args.candidate.read_bytes())
    runtime = ProjectRuntime(Path("outputs"))
    idea = inspect_current_idea_revision(runtime, candidate.project_id).current_binding
    if args.draft_attribution:
        root = args.evidence_root.resolve(strict=True)
        evidence = {}
        for item in candidate.evidence:
            path = (root / item.locator).resolve(strict=True)
            if not path.is_relative_to(root) or path.stat().st_size > 256_000:
                raise ValueError("Evidence escapes source or exceeds limit")
            evidence[item.evidence_id] = path.read_bytes().decode("utf-8")
        feedback = None
        if args.revision_review:
            from scitaste.taste.attribution_feedback import load_attribution_feedback

            feedback = load_attribution_feedback(args.revision_review.read_bytes(), candidate)
        packet = ExperienceAttributionInput(
            candidate=candidate, evidence=evidence, review_feedback=feedback
        )
        packet_id = candidate.candidate_sha256
        node = ExperienceAttributionNode()
    else:
        material = build_ai_taste_attribution_review_material(
            runtime,
            candidate,
            evidence_root=args.evidence_root,
            current_idea_revision=idea,
            seed=0,
        )
        packet = material.node_input
        packet_id = packet.review_packet_sha256
        node = AITasteAttributionReviewNode()
    args.output.mkdir(parents=True, exist_ok=False)
    config = shared.load_structured_openai_compatible_config(args.backend)
    config = config.model_copy(
        update={"extra_body": {**config.extra_body, "response_format": {"type": "json_object"}}}
    )
    shared._bind_credential(args.credentials, config.api_key_env)
    bridge = MLAgentBenchProviderBridge(
        config=config,
        log_root=args.output / "logs",
        max_cost_usd=2,
        max_calls=1,
        max_request_bytes=300_000,
        transport=shared.RecordedTransport(args.output / "provider.jsonl"),
    )
    context = NodeContext(
        project_id=candidate.project_id,
        stage="TASTE_ATTRIBUTION_REVIEW",
        state_snapshot_id=packet_id,
        cumulative_api_cost_usd=0,
        evidence_ids=sorted(item.evidence_id for item in candidate.evidence),
    )
    policy = NodePolicy(
        policy_id="prospective-experience-review-v1",
        enabled=True,
        allowed_node_names=[node.node_name],
        expected_backend=config.provider,
        expected_model=config.model,
        max_api_cost_usd=2,
        max_output_tokens=4096,
        max_request_bytes=300_000,
        max_input_tokens=80_000,
        max_total_tokens=84_096,
    )
    shared.write_new(
        args.output / "CONTRACT.json",
        {
            "candidate_sha256": candidate.candidate_sha256,
            "requested_provider": config.provider,
            "requested_model": config.model,
            "backend_config_sha256": shared._sha256(args.backend),
            "max_calls": 1,
            "max_api_liability_usd": 2,
            "policy_update_authorized": False,
            "formal_evidence_eligible": False,
            "reviewer_kind": "ai",
            "panel_complete": False,
            "draft_attribution": args.draft_attribution,
            "revision_review_sha256": (
                packet.review_feedback.review_result_sha256
                if args.draft_attribution and packet.review_feedback
                else None
            ),
        },
    )
    shared.write_new(args.output / "INPUT.json", packet.model_dump(mode="json"))
    failure = None
    result = None
    try:
        result = node.run(
            packet,
            context=context,
            backend=SharedLedgerStructuredBackend(bridge),
            policy=policy,
            request_id="experience-review-" + candidate.candidate_sha256[:16],
        )
    except Exception as exc:
        failure = {"error_type": type(exc).__name__}
    report = {
        "result": result.model_dump(mode="json") if result else None,
        "failure": failure,
        "policy_update_authorized": False,
        "accounting": provider_ledger_accounting(bridge.records),
        "acceptance_scope": "model-node schema and provenance, not scientific truth or admission",
    }
    shared.write_new(args.output / "RESULT.json", report)
    print(
        json.dumps(
            {
                "status": result.status.value if result else "interrupted",
                "accounting": report["accounting"],
            }
        )
    )
    if failure:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
