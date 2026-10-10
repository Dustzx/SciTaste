"""Ground planning advice in a configured library before scientific design.

Retrieval proposes a closed pool; the existing deliberation node decides whether
transfer is justified. Only its validated control packet reaches the planner.
This does not admit new memory or establish scientific effectiveness.
"""

import hashlib
import json
import shutil

from scitaste.data.store import TasteLibrary
from scitaste.model_nodes.models import NodeContext, NodePolicy, NodeResult, NodeResultStatus
from scitaste.model_nodes.session_exchange import retain_json
from scitaste.schema.actions import ResearchAction
from scitaste.state.research_state import ResearchState
from scitaste.taste.controller import TasteController, TasteMode
from scitaste.taste.deliberation import TasteDeliberationProposal, build_taste_control_packet
from scitaste.taste.retriever import TasteRetriever
from scitaste.taste.semantic import TasteDeliberationNode


def consult_planning_taste(*, packet, library, profile, binding, backend, output, project_id):
    directory = output / "planning-taste"
    directory.mkdir(exist_ok=True)
    context_hash = hashlib.sha256(packet.model_dump_json().encode()).hexdigest()
    retain_json(
        directory / "CONTRACT.json",
        {
            "context_sha256": context_hash,
            "development_taste": binding,
            "policy_update_authorized": False,
            "formal_evidence_eligible": False,
        },
    )
    frozen = directory / "TASTE_LIBRARY.jsonl"
    if not frozen.exists():
        shutil.copyfile(library, frozen)
    if hashlib.sha256(frozen.read_bytes()).hexdigest() != binding["library_sha256"]:
        raise ValueError("Planning Taste library changed while freezing inputs")
    state = ResearchState(
        project_id=project_id,
        research_direction=json.dumps(
            {
                "question": packet.idea.get("research_question", packet.idea.get("title")),
                "objective": packet.objective,
                "workflow_gaps": packet.workflow_gaps,
            },
            ensure_ascii=False,
        ),
        target_domain="autonomous research",
        current_stage="EVIDENCE",
    )
    actions = [
        ResearchAction(
            action_id="prepare-research",
            type="EXPERIMENT",
            description="Design a bounded study using declared task/resource options.",
            parameters={
                "task_options": sorted(packet.task_options),
                "workspace_options": sorted(packet.workspace_resource_options),
            },
        ),
        ResearchAction(
            action_id="complete-workflow",
            type="CORRECT_ERROR",
            description=(
                "Complete a supplied functional gap, using retained outcomes "
                "and bounded validation when necessary."
            ),
            parameters={"workflow_gap_ids": sorted(packet.workflow_gaps)},
        ),
        ResearchAction(
            action_id="defer-research",
            type="STOP",
            description="Defer execution when resources or evidence cannot support a valid study.",
        ),
    ]
    controller = TasteController(
        mode=TasteMode.AUGMENTED,
        retriever=TasteRetriever(TasteLibrary(frozen)),
        utility_enabled=False,
        critics_enabled=False,
    )
    try:
        deliberation = controller.prepare_taste_deliberation(state=state, candidate_actions=actions)
    except ValueError as exc:
        # No eligible grounded pool is an explicit retrieval abstention, not model approval.
        advice = {
            "status": "no-grounded-pool",
            "reason": str(exc),
            "model_consulted": False,
            "control_packet": None,
            **binding,
        }
        retain_json(directory / "ADVICE.json", advice)
        return advice
    retain_json(directory / "INPUT.json", deliberation.model_dump(mode="json"))
    result_path = directory / "RESULT.json"
    if result_path.exists():
        saved = json.loads(result_path.read_bytes())
        fingerprint = saved["request"].pop("fingerprint")
        result = NodeResult[TasteDeliberationProposal].model_validate(saved)
        if (
            result.request.fingerprint != fingerprint
            or result.response.request_fingerprint != fingerprint
            or result.request.input_payload["input"] != deliberation.model_dump(mode="json")
        ):
            raise ValueError("Retained planning Taste input changed")
    else:
        result = TasteDeliberationNode().run(
            deliberation,
            context=NodeContext(
                project_id=project_id,
                stage=deliberation.stage,
                cumulative_api_cost_usd=0,
                state_snapshot_id=deliberation.state_snapshot_id,
                candidate_actions=list(deliberation.current_actions),
            ),
            backend=backend,
            policy=NodePolicy(
                policy_id="planning-taste-v1",
                enabled=True,
                allowed_node_names=["taste-deliberation"],
                expected_backend=profile.provider,
                expected_model=profile.model,
                max_request_bytes=profile.admission.max_request_bytes,
                max_input_tokens=profile.admission.max_input_tokens,
                max_output_tokens=profile.admission.max_output_tokens,
                max_total_tokens=profile.admission.max_total_tokens,
                max_api_cost_usd=profile.admission.max_response_cost_usd,
                max_latency_ms=profile.admission.max_latency_ms,
            ),
            request_id="planning-taste-" + context_hash[:16],
        )
        retain_json(result_path, result.model_dump(mode="json"))
    control = (
        build_taste_control_packet(deliberation, result.proposal)
        if result.status == NodeResultStatus.ACCEPTED and result.proposal is not None
        else None
    )
    advice = {
        "status": result.status.value,
        "model_consulted": True,
        "control_packet": control.model_dump(mode="json") if control else None,
        "result_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest(),
        **binding,
    }
    retain_json(directory / "ADVICE.json", advice)
    return advice
