"""Native proposal/preference adapters over the explicit session exchange."""

import hashlib
import json

from scitaste.backends.base import PreferenceResponse
from scitaste.model_nodes.models import StructuredModelRequest


class SessionNativeBridge:
    def __init__(self, backend, *, proposal_count=2):
        self.backend = backend
        self.proposal_count = proposal_count

    def complete_text(self, prompt, log_file, model, **kwargs):
        from scitaste.research_tool_loop import ResearchToolProposal, ResearchToolProposalBatch

        if model != self.backend.model:
            raise ValueError("Session model identity mismatch")
        request = StructuredModelRequest(
            request_id=log_file.stem,
            node_name="native-action-proposal",
            stage="EVIDENCE",
            state_snapshot_id=hashlib.sha256(prompt.encode()).hexdigest(),
            expected_backend=self.backend.name,
            expected_model=self.backend.model,
            policy_id="native-session-proposal-v1",
            policy_fingerprint=hashlib.sha256(
                json.dumps(kwargs, sort_keys=True).encode()
            ).hexdigest(),
            system_instruction="Propose executable alternatives under the supplied tool contract.",
            input_payload={"prompt": prompt, "generation_constraints": kwargs},
            output_schema=(
                ResearchToolProposal if self.proposal_count == 1 else ResearchToolProposalBatch
            ).model_json_schema(),
            prompt_version="native-session-v1",
        )
        response = self.backend.complete(request)
        return json.dumps(response.output_payload, ensure_ascii=False)

    def accounting(self):
        if not getattr(self.backend, "session_enabled", False):
            return self.backend.bridge.accounting()
        return {
            "source": "assistant-session",
            "calls": 0,
            "api_calls": 0,
            "session_responses": len(list(self.backend.directory.glob("*.response.json"))),
            "pending_session_requests": len(list(self.backend.directory.glob("*.request.json")))
            - len(list(self.backend.directory.glob("*.response.json"))),
            "liability_usd": 0,
            "unresolved_reservations": 0,
            "session_cost_usd": None,
            "actual_tokens": None,
            "cost_semantics": "incremental API liability only; session cost unknown",
        }


class SessionPreferenceBackend:
    name = "assistant-session"
    model = "session-authored"

    def __init__(self, backend):
        self.backend = backend
        self.name = backend.name
        self.model = backend.model

    def rank(self, request):
        packet = StructuredModelRequest(
            request_id=request.request_id,
            node_name="native-action-preference",
            stage=request.stage,
            state_snapshot_id=request.fingerprint,
            expected_backend=self.name,
            expected_model=self.model,
            policy_id="native-session-preference-v1",
            policy_fingerprint=hashlib.sha256(b"fixed-candidates-only-v1").hexdigest(),
            system_instruction=(
                "Select one exact candidate_action_id from the supplied alternatives. "
                "Consider the supplied Taste reasoning, research objective and remaining budget. "
                "Return selected_action_id, rationale and confidence (0 to 1)."
            ),
            input_payload=request.model_dump(mode="json"),
            output_schema={
                "type": "object",
                "required": ["selected_action_id", "rationale", "confidence"],
            },
            prompt_version="native-session-v1",
        )
        response = self.backend.complete(packet)
        return PreferenceResponse(
            request_id=request.request_id,
            request_fingerprint=request.fingerprint,
            **response.output_payload,
            backend=self.name,
            model=self.model,
            raw_response=response.raw_response,
            raw_response_sha256=response.raw_response_sha256,
            usage=response.usage,
        )
