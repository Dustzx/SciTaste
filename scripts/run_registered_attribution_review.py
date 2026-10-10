"""Run durable attribution or outcome-blind decision-family review."""

import argparse
import json
from pathlib import Path

from scitaste.backends.mlagentbench import MLAgentBenchProviderBridge, provider_ledger_accounting
from scitaste.model_nodes.facade import ModelNodeFacade, ModelNodeFacadeRequest
from scitaste.model_nodes.profiles import ModelNodeProfile, load_model_node_profile
from scitaste.model_nodes.registry import first_party_node_types
from scitaste.model_nodes.runtime import ModelNodeRuntime
from scitaste.model_nodes.shared_ledger_backend import SharedLedgerStructuredBackend
from scitaste.project import ProjectRun, ProjectRuntime, inspect_current_idea_revision
from scitaste.taste.ai_attribution import (
    AI_TASTE_ATTRIBUTION_REVIEW_NODE,
    build_ai_taste_attribution_review_material,
    build_ai_taste_attribution_runtime_config,
)
from scitaste.taste.attribution_provenance import attribution_producer
from scitaste.taste.episode_learning import AdmittedTasteEpisode
from scitaste.taste.episodes import TasteEpisodeCandidate
from scitaste.taste.family_review import (
    SCIENTIFIC_DECISION_FAMILY_REVIEW_NODE,
    build_scientific_decision_family_review_material,
    build_scientific_decision_family_runtime_config,
)
from scripts import run_mlrc_native_development_loop as shared


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("project", "candidate", "evidence-root", "output"):
        parser.add_argument(f"--{key}", type=Path, required=True)
    parser.add_argument("--allow-api", action="store_true")
    parser.add_argument("--kind", choices=("attribution", "decision-family"), default="attribution")
    parser.add_argument("--producer-draft", type=Path)
    parser.add_argument(
        "--backend",
        type=Path,
        default=Path("configs/model_nodes/bailian_qwen38max.taste_review_live_20260916.yaml"),
    )
    args = parser.parse_args()
    if not args.allow_api:
        raise ValueError("Explicit API enablement required")
    root, output = args.project.resolve(strict=True), args.output.resolve()
    output.relative_to(root)
    args.candidate.resolve(strict=True).relative_to(root)
    args.evidence_root.resolve(strict=True).relative_to(root)
    episode = (
        AdmittedTasteEpisode.model_validate_json(args.candidate.read_bytes())
        if args.kind == "decision-family"
        else None
    )
    candidate = (
        episode.candidate
        if episode
        else TasteEpisodeCandidate.model_validate_json(args.candidate.read_bytes())
    )
    if candidate.project_id != root.name:
        raise ValueError("Candidate belongs to a different project")
    producer = None
    if args.producer_draft and episode:
        raise ValueError("Family review consumes an admitted episode, not an attribution draft")
    if args.producer_draft:
        args.producer_draft.resolve(strict=True).relative_to(root)
        producer = attribution_producer(args.candidate, args.producer_draft)
    if (
        not episode
        and candidate.attribution_producer_id == "model-attribution-draft"
        and producer is None
    ):
        raise ValueError("Model attribution requires its source producer draft before review")
    runtime = ProjectRuntime(root.parent.parent)
    idea = inspect_current_idea_revision(runtime, root.name).current_binding
    if episode:
        material = build_scientific_decision_family_review_material(
            runtime,
            episode,
            current_idea_revision=idea,
        )
        node_name = SCIENTIFIC_DECISION_FAMILY_REVIEW_NODE
        build_config = build_scientific_decision_family_runtime_config
        packet_sha256 = material.node_input.packet_sha256
    else:
        material = build_ai_taste_attribution_review_material(
            runtime,
            candidate,
            evidence_root=args.evidence_root,
            current_idea_revision=idea,
            seed=0,
        )
        node_name = AI_TASTE_ATTRIBUTION_REVIEW_NODE
        build_config = build_ai_taste_attribution_runtime_config
        packet_sha256 = material.node_input.review_packet_sha256
    backend = shared.load_structured_openai_compatible_config(args.backend)
    if producer and producer["producer_model_id"] == backend.model:
        raise ValueError("Attribution producer model cannot act as its independent reviewer")
    shared._bind_credential(Path("outputs/resources/access/credentials.env"), backend.api_key_env)
    template = load_model_node_profile(
        Path("configs/model_nodes/profile_bailian_qwen38max_taste_deliberation_v1.yaml")
    ).model_dump(mode="json", exclude={"fingerprint"})
    template.update(
        profile_id="registered-" + args.kind + "-review-v1",
        provider=backend.provider,
        model=backend.model,
        allowed_node_names=[node_name],
    )
    template["generation"]["max_output_tokens"] = 4096
    template["admission"].update(
        max_output_tokens=4096, max_total_tokens=104096, max_response_cost_usd=2
    )
    template["cumulative_project"]["max_api_cost_usd"] = 2
    profile = ModelNodeProfile.model_validate(template)
    config = build_config(material, profile=profile, backend_config=backend)
    output.mkdir(parents=True, exist_ok=False)
    shared.write_new(
        output / "CONTRACT.json",
        {
            "candidate_sha256": candidate.candidate_sha256,
            "candidate": str(args.candidate.resolve().relative_to(root)),
            "review_packet_sha256": packet_sha256,
            "review_kind": args.kind,
            "invocation_id": output.name + "-" + args.kind,
            "max_calls": 1,
            "max_api_liability_usd": 2,
            "policy_update_authorized": False,
            "producer": producer,
        },
    )
    runtime.begin_run(
        root.name,
        ProjectRun(
            run_id=output.name,
            provider=backend.provider,
            model=backend.model,
            seed=0,
            condition="registered-experience-" + args.kind + "-review",
            status="running",
            evidence_scope="internal-ai-review-not-human-validation",
            formal_evidence_eligible=False,
            artifact=str((output / "CONTRACT.json").relative_to(root)),
        ),
        expected_revision=runtime.open(root.name).revision,
    )
    bridge = MLAgentBenchProviderBridge(
        config=backend,
        log_root=output / "logs",
        max_calls=1,
        max_cost_usd=2,
        max_output_tokens=4096,
        transport=shared.RecordedTransport(output / "provider.jsonl"),
    )
    receipt = (
        ModelNodeFacade(ModelNodeRuntime(runtime, node_types=first_party_node_types()))
        .execute(
            ModelNodeFacadeRequest(
                project_id=root.name,
                run_id=output.name,
                invocation_id=output.name + "-" + args.kind,
                expected_project_revision=runtime.open(root.name).revision,
                node_name=config.node_name,
                node_input=config.node_input,
                state_projection=config.state_projection,
                trigger=config.trigger,
                profile=profile,
                policy=config.policy,
                backend_mode="live",
            ),
            backend=SharedLedgerStructuredBackend(bridge),
            allow_live=True,
        )
        .receipt
    )
    shared.write_new(output / "RUNTIME_RECEIPT.json", receipt.model_dump(mode="json"))
    accounting = provider_ledger_accounting(bridge.records)
    shared.write_new(
        output / "RESULT.json",
        {
            "result": receipt.result,
            "runtime_receipt": "RUNTIME_RECEIPT.json",
            "accounting": accounting,
            "policy_update_authorized": False,
        },
    )
    shared.register_progress(
        root,
        output,
        args.kind + "-review-" + receipt.outcome.value,
        provider=backend.provider,
        model=backend.model,
    )
    proposal = (receipt.result or {}).get("proposal") or {}
    print(
        json.dumps(
            {
                "runtime_outcome": receipt.outcome.value,
                "verdict": proposal.get("verdict"),
                "decision_family": proposal.get("decision_family"),
                "accounting": accounting,
                "admitted": False,
            }
        )
    )


if __name__ == "__main__":
    main()
