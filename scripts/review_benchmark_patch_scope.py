#!/usr/bin/env python3
"""Review exact candidate code without exposing its experimental outcome."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scitaste.evaluation.patch_scope_review import (
    PatchScopeAdjudicationInput,
    PatchScopeAdjudicationNode,
    PatchScopeReviewInput,
    PatchScopeReviewNode,
    PatchScopeReviewOutput,
)
from scitaste.model_nodes.models import NodeContext, NodePolicy, NodeResultStatus
from scitaste.model_nodes.openai_compatible import (
    StructuredOpenAICompatibleBackend,
    load_structured_openai_compatible_config,
)
from scitaste.model_nodes.profiles import load_model_node_profile
from scitaste.model_nodes.replay import RecordingStructuredBackend, ReplayStructuredBackend
from scitaste.project.models import content_sha256

if __package__:
    from .run_scitastebench_decision_baselines import _bind_credential
else:
    from run_scitastebench_decision_baselines import _bind_credential


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proposal", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--backend", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--project-id", default="scitaste-self-development")
    parser.add_argument("--allow-api", action="store_true")
    parser.add_argument("--replay-record", type=Path)
    parser.add_argument("--adjudicate-review", type=Path)
    parser.add_argument(
        "--credentials", type=Path, default=Path("outputs/resources/access/credentials.env")
    )
    args = parser.parse_args()
    raw = json.loads((args.proposal / "PATCH_INPUT.json").read_text())
    generated = json.loads((args.proposal / "NODE_RESULT.json").read_text())
    if generated["status"] != NodeResultStatus.ACCEPTED.value:
        raise ValueError("review requires an admitted patch proposal")
    # Deliberately exclude experiment_feedback and every result file. Reviews
    # of consumed examples remain retrospective development, not blind evaluation.
    data = PatchScopeReviewInput.model_validate(
        {
            "directive": raw["research_action"],
            "source": raw["patch_context"],
            "proposal": generated["proposal"],
            "constraints": raw["constraints"],
        }
    )
    node_type = PatchScopeReviewNode
    if args.adjudicate_review:
        reviewed = json.loads(args.adjudicate_review.read_text())
        if reviewed["status"] != "accepted" or reviewed.get("proposal") is None:
            raise ValueError("adjudication requires a schema-admitted initial review")
        reviewed_input = reviewed["request"]["input_payload"]["input"]
        if reviewed_input != data.model_dump(mode="json"):
            raise ValueError("initial review belongs to a different candidate projection")
        data = PatchScopeAdjudicationInput(
            candidate=data,
            initial_review=PatchScopeReviewOutput.model_validate(reviewed["proposal"]),
        )
        node_type = PatchScopeAdjudicationNode
    profile = load_model_node_profile(args.profile)
    config = load_structured_openai_compatible_config(args.backend)
    if (profile.provider, profile.model) != (config.provider, config.model):
        raise ValueError("review profile/backend identities differ")
    context = NodeContext(
        project_id=args.project_id,
        stage="EXPERIMENTATION",
        state_snapshot_id=content_sha256(data.model_dump(mode="json")),
        cumulative_api_cost_usd=0,
        metadata={"role": "implementation-scope-review", "execution_authority": False},
    )
    policy = NodePolicy(
        policy_id="patch-scope-review-v1",
        enabled=True,
        allowed_node_names=[node_type.node_name],
        expected_backend=profile.provider,
        expected_model=profile.model,
        max_request_bytes=profile.admission.max_request_bytes,
        max_input_tokens=profile.admission.max_input_tokens,
        max_output_tokens=profile.admission.max_output_tokens,
        max_total_tokens=profile.admission.max_total_tokens,
        max_api_cost_usd=profile.cumulative_project.max_api_cost_usd,
        max_latency_ms=profile.admission.max_latency_ms,
    )
    args.output.mkdir(parents=True, exist_ok=True)
    contract = {
        "review_node": {
            "admission_version": "visible-caller-v2",
            "name": node_type.node_name,
            "prompt_version": node_type.prompt_version,
            "system_instruction_sha256": content_sha256(node_type.system_instruction),
        },
        "input": data.model_dump(mode="json"),
        "backend_config": content_sha256(config.model_dump(mode="json")),
        "profile": profile.fingerprint,
    }
    contract_path = args.output / "REVIEW_INPUT.json"
    if contract_path.exists():
        if json.loads(contract_path.read_text()) != contract:
            raise ValueError("review resume inputs changed")
    else:
        with contract_path.open("x") as stream:
            json.dump(contract, stream, indent=2)
    record = args.output / "recordings.jsonl"
    if args.replay_record:
        backend = ReplayStructuredBackend(args.replay_record)
    elif record.exists() and record.stat().st_size:
        backend = ReplayStructuredBackend(record)
    else:
        if not args.allow_api:
            raise ValueError("new scope review requires --allow-api")
        _bind_credential(args.credentials, config.api_key_env)
        backend = RecordingStructuredBackend(StructuredOpenAICompatibleBackend(config), record)
    result = node_type().run(
        data,
        context=context,
        backend=backend,
        policy=policy,
        profile=profile,
        request_id="patch-scope-" + context.state_snapshot_id,
    )
    path = args.output / "NODE_RESULT.json"
    if not path.exists():
        with path.open("x") as stream:
            stream.write(result.model_dump_json(indent=2))
    print(
        json.dumps(
            {
                "status": result.status.value,
                "disposition": result.proposal.disposition if result.proposal else None,
                "rejection_reasons": result.rejection_reasons,
                "usage": result.response.usage.model_dump(mode="json"),
                "execution_authorized": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
