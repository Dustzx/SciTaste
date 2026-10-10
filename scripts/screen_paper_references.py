#!/usr/bin/env python3
"""Screen prepared sources through the real project ledger; never auto-admit Taste."""

import argparse
import json
from pathlib import Path

from scitaste.backends.mlagentbench import MLAgentBenchProviderBridge, provider_ledger_accounting
from scitaste.model_nodes.facade import (
    ImmutableStateProjection,
    ModelNodeFacade,
    ModelNodeFacadeRequest,
)
from scitaste.model_nodes.models import NodePolicy
from scitaste.model_nodes.profiles import ModelNodeProfile, load_model_node_profile
from scitaste.model_nodes.registry import first_party_node_types
from scitaste.model_nodes.runtime import (
    ModelNodeRuntime,
    ModelNodeTrigger,
    RuntimeInvocationReceipt,
    RuntimeOutcome,
)
from scitaste.model_nodes.shared_ledger_backend import SharedLedgerStructuredBackend
from scitaste.project import ProjectRuntime
from scitaste.project.models import ProjectRun
from scitaste.taste.reference_quality import (
    ReferenceQualityInput,
    compile_reference_quality_qualification,
    save_reference_quality_qualification,
)
from scitaste.taste.semantic import (
    reference_quality_from_ledger,
    taste_abstraction_candidate_from_ledger,
)
from scitaste.taste.semantic_models import TasteAbstractionInput
from scripts import run_mlrc_native_development_loop as shared


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--allow-api", action="store_true")
    parser.add_argument("--generate-abstraction-candidates", action="store_true")
    parser.add_argument("--reuse-quality-result", type=Path)
    parser.add_argument("--review-protocol", type=Path)
    parser.add_argument("--revision-review-final", type=Path)
    args = parser.parse_args()
    if not args.allow_api:
        raise ValueError("Explicit API enablement required")
    if args.review_protocol and not args.generate_abstraction_candidates:
        raise ValueError("Review preparation requires abstraction candidate generation")
    if args.review_protocol:
        from scitaste.evaluation.ai_taste_abstraction_review import (
            load_ai_taste_abstraction_review_protocol,
        )

        load_ai_taste_abstraction_review_protocol(args.review_protocol)
    inputs = [
        ReferenceQualityInput.model_validate_json(path.read_bytes())
        for path in sorted(args.input_root.glob("*/INPUT.json"))
    ]
    if not 1 <= len(inputs) <= 3 or len({p.source_id for p in inputs}) != len(inputs):
        raise ValueError("Expected one to three distinct prepared source inputs")
    reused_receipt = None
    if args.reuse_quality_result:
        if len(inputs) != 1 or not args.generate_abstraction_candidates:
            raise ValueError("Quality reuse requires one source and abstraction drafting")
        reused_receipt = RuntimeInvocationReceipt.model_validate(
            json.loads(args.reuse_quality_result.read_text())["receipt"]
        )
        if reused_receipt.outcome != RuntimeOutcome.ACCEPTED:
            raise ValueError("Only accepted quality invocations can be reused")
        prior_entries = list(
            (Path("outputs") / reused_receipt.ledger_locator).glob(
                f"*__{reused_receipt.invocation_id}.json"
            )
        )
        if len(prior_entries) != 1:
            raise ValueError("Expected one original quality ledger entry")
        prior = reference_quality_from_ledger(
            prior_entries[0].resolve(), evidence_root=Path("outputs")
        )
        if prior.input != inputs[0] or prior.proposal.verdict.value != "qualify":
            raise ValueError("Reused quality must qualify this exact source projection")
    project = Path("outputs/projects/scitaste-self-development").resolve(strict=True)
    revision_input = None
    if args.revision_review_final:
        if reused_receipt is None:
            raise ValueError("Revision requires reuse of the unchanged source quality result")
        from scitaste.taste.revision import prepare_grounded_revision

        revision_input = prepare_grounded_revision(
            evidence_root=Path.cwd(), review_final=args.revision_review_final, source=inputs[0]
        )
    output = args.output.resolve()
    output.relative_to(project)
    config = shared.load_structured_openai_compatible_config(
        Path("configs/model_nodes/bailian_qwen38max.taste_review_live_20260916.yaml")
    )
    config = config.model_copy(
        update={"extra_body": {**config.extra_body, "response_format": {"type": "json_object"}}}
    )
    profile_data = load_model_node_profile(
        "configs/model_nodes/profile_bailian_qwen38max_taste_review_v1.yaml"
    ).model_dump(mode="json", exclude={"fingerprint"})
    node_names = ["reference-quality"]
    if args.generate_abstraction_candidates:
        node_names.append(
            "grounded-taste-revision" if revision_input else "grounded-taste-abstraction"
        )
    profile_data.update(
        profile_id="bailian-qwen38max-reference-quality-development",
        allowed_node_names=node_names,
    )
    profile_data["admission"]["max_request_bytes"] = 100_000
    profile = ModelNodeProfile.model_validate(profile_data)
    output.mkdir(parents=True, exist_ok=False)
    shared._bind_credential(Path("outputs/resources/access/credentials.env"), config.api_key_env)
    bridge = MLAgentBenchProviderBridge(
        config=config,
        log_root=output / "logs",
        max_cost_usd=3,
        max_calls=len(inputs) * (2 if args.generate_abstraction_candidates else 1)
        - int(reused_receipt is not None),
        max_request_bytes=100_000,
        max_output_tokens=8192,
        transport=shared.RecordedTransport(output / "provider.jsonl"),
    )
    backend = SharedLedgerStructuredBackend(bridge, max_output_tokens=8192)
    runtime = ProjectRuntime(project.parent.parent)
    shared.write_new(
        output / "CONTRACT.json",
        {
            "scope": "development-posthoc",
            "max_provider_calls": len(inputs) * (2 if args.generate_abstraction_candidates else 1)
            - int(reused_receipt is not None),
            "reused_quality_result_sha256": shared._sha256(args.reuse_quality_result)
            if args.reuse_quality_result
            else None,
            "max_api_liability_usd": 3,
            "profile": profile.model_dump(mode="json"),
            "source_ids": [p.source_id for p in inputs],
            "taste_library_admitted": False,
            "generate_untrusted_abstraction_candidates": args.generate_abstraction_candidates,
            "review_protocol_sha256": shared._sha256(args.review_protocol)
            if args.review_protocol
            else None,
            "revision_review_final_sha256": revision_input.review_final_sha256
            if revision_input
            else None,
        },
    )
    runtime.begin_run(
        project.name,
        ProjectRun(
            run_id=output.name,
            provider=config.provider,
            model=config.model,
            condition="paper-reference-quality-development",
            seed=0,
            status="running",
            artifact=(output / "CONTRACT.json").relative_to(project).as_posix(),
            evidence_scope="post-hoc source screening, not effectiveness or library admission",
            formal_evidence_eligible=False,
        ),
        expected_revision=runtime.open(project.name).revision,
    )
    facade = ModelNodeFacade(ModelNodeRuntime(runtime, node_types=first_party_node_types()))
    policy = NodePolicy(
        policy_id="paper-reference-quality-development",
        enabled=True,
        allowed_node_names=node_names,
        expected_backend=config.provider,
        expected_model=config.model,
        max_request_bytes=100_000,
        max_input_tokens=100_000,
        max_output_tokens=8192,
        max_total_tokens=108192,
        max_latency_ms=600_000,
        max_api_cost_usd=profile.cumulative_project.max_api_cost_usd,
    )
    results = []
    for packet in inputs:
        target = output / packet.source_id
        target.mkdir()
        shared.write_new(target / "INPUT.json", packet.model_dump(mode="json"))
        invocation = packet.screening_id
        request = ModelNodeFacadeRequest(
            project_id=project.name,
            run_id=output.name,
            invocation_id=invocation,
            expected_project_revision=runtime.open(project.name).revision,
            node_name="reference-quality",
            node_input=packet.model_dump(mode="json"),
            state_projection=ImmutableStateProjection(
                project_id=project.name,
                state_snapshot_id=packet.source_projection_sha256,
                state_revision=0,
                stage=packet.decision_stage,
                evidence_ids=(packet.source_id,),
            ),
            trigger=ModelNodeTrigger(
                trigger_id=invocation, reason="Qualify source decision evidence before abstraction."
            ),
            profile=profile,
            policy=policy,
            backend_mode="live",
        )
        try:
            receipt = (
                reused_receipt or facade.execute(request, backend=backend, allow_live=True).receipt
            )
            row = {"source_id": packet.source_id, "receipt": receipt.model_dump(mode="json")}
            row["quality_invocation_reused"] = reused_receipt is not None
            if receipt.outcome == RuntimeOutcome.ACCEPTED:
                entries = list(
                    (runtime.outputs_root / receipt.ledger_locator).glob(f"*__{invocation}.json")
                )
                if len(entries) != 1:
                    raise ValueError("Expected one source quality ledger entry")
                verified = reference_quality_from_ledger(
                    entries[0], evidence_root=runtime.outputs_root
                )
                qualification = compile_reference_quality_qualification(verified)
                save_reference_quality_qualification(qualification, target / "QUALIFICATION.json")
                row["verdict"] = qualification.verdict.value
                if args.generate_abstraction_candidates and row["verdict"] == "qualify":
                    abstraction_input = revision_input or TasteAbstractionInput(
                        source_id=packet.source_id,
                        candidate_id=packet.source_id + "-candidate-v1",
                        case_id=packet.source_id + "-case-v1",
                        stage=packet.decision_stage,
                        decision_role=packet.decision_role,
                        source_projection=packet.source_projection,
                        source_projection_sha256=packet.source_projection_sha256,
                        domain_tags=("machine-unlearning",),
                        outcome_information_availability=packet.outcome_information_availability,
                    )
                    abstraction_id = (
                        revision_input.candidate_id
                        if revision_input
                        else packet.source_id + "-abstraction-v1"
                    )
                    abstraction_request = ModelNodeFacadeRequest(
                        project_id=project.name,
                        run_id=output.name,
                        invocation_id=abstraction_id,
                        expected_project_revision=runtime.open(project.name).revision,
                        node_name="grounded-taste-revision"
                        if revision_input
                        else "grounded-taste-abstraction",
                        node_input=abstraction_input.model_dump(mode="json"),
                        state_projection=request.state_projection,
                        trigger=ModelNodeTrigger(
                            trigger_id=abstraction_id,
                            reason="Draft a source-grounded candidate, not admit or execute it.",
                        ),
                        profile=profile,
                        policy=policy,
                        backend_mode="live",
                    )
                    abstraction = facade.execute(
                        abstraction_request, backend=backend, allow_live=True
                    ).receipt
                    shared.write_new(
                        target / "ABSTRACTION_RESULT.json", abstraction.model_dump(mode="json")
                    )
                    row["abstraction_outcome"] = abstraction.outcome.value
                    if abstraction.outcome == RuntimeOutcome.ACCEPTED:
                        paths = list(
                            (runtime.outputs_root / abstraction.ledger_locator).glob(
                                f"*__{abstraction_id}.json"
                            )
                        )
                        if len(paths) != 1:
                            raise ValueError("Expected one abstraction ledger entry")
                        candidate = taste_abstraction_candidate_from_ledger(
                            paths[0],
                            evidence_root=runtime.outputs_root,
                            author_id="qwen38max-development-abstraction",
                            derivation_method="grounded-source-proposal-not-admitted",
                        )
                        shared.write_new(
                            target / "CANDIDATE.json", candidate.model_dump(mode="json")
                        )
            shared.write_new(target / "RESULT.json", row)
            results.append(row)
            print(
                json.dumps(
                    {
                        "source": packet.source_id,
                        "outcome": receipt.outcome.value,
                        "quality_outcome": receipt.outcome.value,
                        "verdict": row.get("verdict"),
                        "abstraction_outcome": row.get("abstraction_outcome"),
                        "taste_library_admitted": False,
                    }
                ),
                flush=True,
            )
        except Exception as exc:
            row = {"source_id": packet.source_id, "failure_type": type(exc).__name__}
            shared.write_new(target / "FAILURE.json", row)
            results.append(row)
            break  # No retries or additional calls after uncertain failure.
    review_pack = None
    if args.review_protocol:
        from scitaste.evaluation.ai_taste_abstraction_review import (
            compile_ai_taste_abstraction_review_requests,
        )

        accepted_receipts = [
            output / row["source_id"] / "ABSTRACTION_RESULT.json"
            for row in results
            if row.get("abstraction_outcome") == "accepted"
        ]
        if accepted_receipts:
            pack = compile_ai_taste_abstraction_review_requests(
                evidence_root=Path.cwd(),
                runtime_receipt_paths=accepted_receipts,
                protocol_path=args.review_protocol.resolve(),
                output_dir=output / "independent_review",
            )
            review_pack = {
                "locator": "independent_review/PACK.json",
                "pack_sha256": pack.pack_sha256,
                "candidate_count": pack.candidate_count,
                "review_calls_performed": False,
            }
    shared.write_new(
        output / "RESULT.json",
        {
            "sources": results,
            "accounting": provider_ledger_accounting(bridge.records),
            "taste_library_admitted": False,
            "formal_evidence_eligible": False,
            "independent_review_pack": review_pack,
        },
    )
    complete = len(results) == len(inputs) and all(
        row.get("receipt", {}).get("outcome") in {"accepted", "rejected", "not_applicable"}
        for row in results
    )
    runtime.update_run(
        project.name,
        output.name,
        expected_revision=runtime.open(project.name).revision,
        status="completed" if complete else "interrupted",
        artifact=(output / "RESULT.json").relative_to(project).as_posix(),
    )
    if not complete:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
