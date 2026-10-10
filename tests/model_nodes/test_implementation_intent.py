import hashlib

from scitaste.model_nodes.backends import ScriptedStructuredBackend, ScriptedStructuredReply
from scitaste.model_nodes.implementation_intent import (
    ImplementationIntentInput,
    ImplementationIntentReviewNode,
    ImplementationSource,
)
from scitaste.model_nodes.models import NodeContext, NodePolicy, NodeResultStatus


def test_source_cited_advisory_uses_existing_authority_boundary():
    code = "(-loss).backward()\nparam.data += lr * param.grad\n"
    node = ImplementationIntentReviewNode()
    inputs = ImplementationIntentInput(
        research_objective="Unlearn examples",
        proposed_method="Gradient ascent on CE",
        sources=(
            ImplementationSource(
                evidence_id="source-1",
                relative_path="method.py",
                sha256=hashlib.sha256(code.encode()).hexdigest(),
                source=code,
            ),
        ),
    )
    context = NodeContext(
        project_id="fixture",
        stage="EVIDENCE",
        state_snapshot_id="fixture",
        cumulative_api_cost_usd=0,
        evidence_ids=["source-1"],
    )
    policy = NodePolicy(
        policy_id="fixture",
        enabled=True,
        allowed_node_names=[node.node_name],
        expected_backend="scripted",
        expected_model="fixture",
    )
    payload = {
        "threats": [
            {
                "threat_id": "sign",
                "kind": "implementation_artifact",
                "statement": "Adding the negative loss gradient reverses the stated ascent.",
                "evidence_ids": ["source-1"],
                "confidence": 0.9,
            }
        ],
        "alternative_explanations": [],
        "recommended_action_type": None,
        "rationale": "Source discrepancy, not a claim about measured effectiveness.",
        "confidence": 0.9,
    }
    backend = ScriptedStructuredBackend(
        name="scripted",
        model="fixture",
        replies={
            "review": ScriptedStructuredReply(output_payload=payload),
        },
    )
    result = node.run(inputs, context=context, backend=backend, policy=policy, request_id="review")
    assert result.status == NodeResultStatus.ACCEPTED
    assert result.proposal.threats[0].evidence_ids == ["source-1"]
    assert "patch" not in result.proposal.model_dump()
    payload["threats"][0]["evidence_ids"] = ["invented-source"]
    backend.replies["bad"] = ScriptedStructuredReply(output_payload=payload)
    rejected = node.run(inputs, context=context, backend=backend, policy=policy, request_id="bad")
    assert rejected.status == NodeResultStatus.REJECTED
