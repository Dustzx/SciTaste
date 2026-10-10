"""Run the registered evidence-paper node on a prepared real-result packet."""

import argparse
import hashlib
import json
from pathlib import Path

from scitaste.backends.mlagentbench import MLAgentBenchProviderBridge, provider_ledger_accounting
from scitaste.model_nodes.models import NodeContext, NodePolicy
from scitaste.model_nodes.profiles import ModelNodeProfile, load_model_node_profile
from scitaste.model_nodes.runtime import ModelNodeRuntime, ModelNodeTrigger
from scitaste.model_nodes.shared_ledger_backend import SharedLedgerStructuredBackend
from scitaste.project import ProjectRun, ProjectRuntime
from scitaste.writing.semantic import writing_node_types
from scitaste.writing.semantic_models import EvidencePaperDraftInput
from scripts import run_mlrc_native_development_loop as shared


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--input-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-api", action="store_true")
    parser.add_argument("--json-mode", action="store_true")
    parser.add_argument(
        "--credentials", type=Path, default=Path("outputs/resources/access/credentials.env")
    )
    parser.add_argument(
        "--backend",
        type=Path,
        default=Path("configs/model_nodes/bailian_qwen38max.taste_review_live_20260916.yaml"),
    )
    args = parser.parse_args()
    if not args.allow_api:
        raise ValueError("Explicit API enablement is required")
    project = args.project.resolve(strict=True)
    prepared = args.input_directory.resolve(strict=True)
    prepared.relative_to(project)
    output = args.output.resolve()
    output.relative_to(project)
    raw = (prepared / "INPUT.json").read_bytes()
    binding = json.loads((prepared / "BINDING.json").read_bytes())
    if hashlib.sha256(raw).hexdigest() != binding["input_sha256"]:
        raise ValueError("Prepared manuscript input changed")
    selection = (project / binding["delivery"] / "SELECTION.json").resolve(strict=True)
    selection.relative_to(project)
    if shared._sha256(selection) != binding["selection_sha256"]:
        raise ValueError("Measured delivery changed")
    packet = EvidencePaperDraftInput.model_validate_json(raw)
    config = shared.load_structured_openai_compatible_config(args.backend)
    if args.json_mode:
        config = config.model_copy(
            update={"extra_body": {**config.extra_body, "response_format": {"type": "json_object"}}}
        )
    shared._bind_credential(args.credentials, config.api_key_env)
    template = load_model_node_profile(
        Path("configs/model_nodes/profile_bailian_qwen38max_taste_deliberation_v1.yaml")
    ).model_dump(mode="json", exclude={"fingerprint"})
    template.update(
        profile_id="measured-experiment-paper-draft-v1",
        provider=config.provider,
        model=config.model,
        allowed_node_names=["evidence-paper-draft"],
    )
    template["admission"]["max_response_cost_usd"] = 3.0
    template["cumulative_project"]["max_api_cost_usd"] = 3.0
    profile = ModelNodeProfile.model_validate(template)
    output.mkdir(parents=True, exist_ok=False)
    shared.write_new(
        output / "CONTRACT.json",
        {
            "input_binding": binding,
            "profile": profile.model_dump(mode="json"),
            "max_calls": 1,
            "max_api_liability_usd": 3.0,
            "formal_evidence_eligible": False,
            "current_manuscript_replacement": False,
            "provider_json_mode": args.json_mode,
        },
    )
    bridge = MLAgentBenchProviderBridge(
        config=config,
        log_root=output / "logs",
        max_calls=1,
        max_cost_usd=3,
        max_output_tokens=8192,
        max_request_bytes=100000,
        transport=shared.RecordedTransport(output / "provider.jsonl"),
    )
    runtime = ProjectRuntime(project.parent.parent)
    snapshot = runtime.open(project.name)
    runtime.begin_run(
        project.name,
        ProjectRun(
            run_id=output.name,
            provider=config.provider,
            model=config.model,
            condition="measured-experiment-paper-draft",
            seed=0,
            evidence_scope="development-case-study-not-system-effectiveness",
            formal_evidence_eligible=False,
            status="paper-drafting",
            artifact=str((output / "CONTRACT.json").relative_to(project)),
        ),
        expected_revision=snapshot.revision,
    )
    policy = NodePolicy(
        policy_id=profile.profile_id,
        enabled=True,
        allowed_node_names=["evidence-paper-draft"],
        expected_backend=config.provider,
        expected_model=config.model,
        max_api_cost_usd=3,
        max_request_bytes=100000,
        max_input_tokens=100000,
        max_output_tokens=8192,
        max_total_tokens=108192,
        max_latency_ms=600000,
    )
    receipt = ModelNodeRuntime(runtime, node_types=writing_node_types()).execute(
        backend=SharedLedgerStructuredBackend(bridge, max_output_tokens=8192),
        allow_live=True,
        project_id=project.name,
        run_id=output.name,
        invocation_id="paper-draft",
        expected_project_revision=runtime.open(project.name).revision,
        state_revision=0,
        node_name="evidence-paper-draft",
        node_input=packet,
        context=NodeContext(
            project_id=project.name,
            stage="COMMUNICATION",
            state_snapshot_id=binding["input_sha256"],
            cumulative_api_cost_usd=0,
            evidence_ids=[item.evidence_id for item in packet.evidence],
            claim_ids=[item.claim_id for item in packet.claims],
            section_ids=list(packet.required_sections),
        ),
        trigger=ModelNodeTrigger(
            trigger_id="measured-results-ready",
            reason="Draft from completed measurements, including negative results.",
        ),
        profile=profile,
        policy=policy,
        backend_mode="live",
    )
    shared.write_new(output / "RESULT.json", receipt.model_dump(mode="json"))
    shared.write_new(
        output / "PROVIDER_ACCOUNTING.json", provider_ledger_accounting(bridge.records)
    )
    shared.register_progress(
        project,
        output,
        "paper-draft-" + receipt.outcome.value,
        provider=config.provider,
        model=config.model,
    )
    print(receipt.model_dump_json())
    if receipt.outcome.value != "accepted":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
