"""Explicit optional scientific-code advice; never a mandatory experiment gate."""

import hashlib
import json

from scitaste.executor.research_tools import ToolInfo
from scitaste.model_nodes.implementation_intent import (
    ImplementationIntentInput,
    ImplementationIntentReviewNode,
    ImplementationSource,
)
from scitaste.model_nodes.models import NodeContext, NodePolicy


def install_implementation_review(environment, *, backend, project_id, budget_usd, spent):
    """Install before freezing the interface contract; caller owns shared accounting."""
    if environment.trace.steps or "Review Implementation" in environment.action_infos:
        raise ValueError("Review must be configured once before trajectory execution")
    node = ImplementationIntentReviewNode()
    policy = NodePolicy(
        policy_id="shared-tools-optional-intent-v1",
        enabled=True,
        allowed_node_names=[node.node_name],
        expected_backend=backend.name,
        expected_model=backend.model,
        max_api_cost_usd=budget_usd,
        max_output_tokens=4096,
    )

    def review(file_name, proposed_method):
        source = environment.read_file(file_name)
        digest = hashlib.sha256(source.encode()).hexdigest()
        evidence_id = "candidate-source-" + digest
        inputs = ImplementationIntentInput(
            research_objective=environment.research_problem,
            proposed_method=proposed_method,
            sources=(
                ImplementationSource(
                    evidence_id=evidence_id,
                    relative_path=file_name,
                    sha256=digest,
                    source=source,
                ),
            ),
        )
        directory = environment.log_root / "implementation_reviews"
        directory.mkdir(exist_ok=True)
        index = len(list(directory.glob("*.request.json")))
        prefix = directory / f"{index:05d}"
        context = NodeContext(
            project_id=project_id,
            stage="EVIDENCE",
            state_snapshot_id="source-" + digest,
            cumulative_api_cost_usd=spent(),
            evidence_ids=[evidence_id],
        )
        with prefix.with_suffix(".request.json").open("x") as stream:
            json.dump(
                {
                    "input": inputs.model_dump(mode="json"),
                    "context": context.model_dump(mode="json"),
                    "policy": policy.model_dump(mode="json"),
                },
                stream,
            )
        result = node.run(
            inputs,
            context=context,
            backend=backend,
            policy=policy,
            request_id=f"implementation-review-{index}-{digest[:16]}",
        )
        with prefix.with_suffix(".result.json").open("x") as stream:
            stream.write(result.model_dump_json(indent=2))
        return json.dumps(
            {
                "advisory_only": True,
                "acceptance_scope": "schema, provenance and policy only",
                "semantic_correctness_verified": False,
                "source_sha256": digest,
                "valid_only_for_reviewed_source": True,
                "result": {
                    "status": result.status.value,
                    "proposal": result.proposal.model_dump(mode="json")
                    if result.proposal
                    else None,
                    "rejection_reasons": result.rejection_reasons,
                },
                "record": str(prefix.with_suffix(".result.json").relative_to(environment.log_root)),
                "instruction": "Decide whether to revise or investigate; this is not permission, "
                "a measured result, or a correctness certificate.",
            }
        )

    environment.action_infos["Review Implementation"] = ToolInfo(
        "Review Implementation",
        "Optional model review of one source file against the proposed method. Shares the "
        "agent API budget. Use when likely useful, not before every experiment. Findings "
        "are source-bound advice; they neither edit code nor authorize execution.",
        {"file_name": "relative candidate path", "proposed_method": "intended scientific method"},
        "source-cited advisory findings",
        review,
    )
