"""Explicit stateless provider transport for shared-tool research comparisons."""

import hashlib
import json
from pathlib import Path

from scitaste.backends.mlagentbench import MLAgentBenchProviderBridge, provider_ledger_accounting
from scitaste.executor.native_support import _bind_credential
from scitaste.model_nodes.models import StructuredModelResponse
from scitaste.model_nodes.openai_compatible import load_structured_openai_compatible_config
from scitaste.model_nodes.shared_ledger_backend import SharedLedgerStructuredBackend


def terminal_proposal(payload):
    """Identical final submissions are one terminal action, not fake alternatives."""
    proposals = payload.get("proposals", []) if isinstance(payload, dict) else []
    if not proposals or not all(
        isinstance(p, dict) and p.get("tool") == "Final Answer" for p in proposals
    ):
        return None
    arguments = proposals[0].get("arguments")
    if all(p.get("arguments") == arguments for p in proposals):
        return proposals[0]
    return None


class ResearchProviderBridge(MLAgentBenchProviderBridge):
    def accounting(self):
        result = provider_ledger_accounting(self.records)
        usages = [
            json.loads(p.read_text()).get("usage", {}) for p in self.records.glob("*.response")
        ]
        result.update(
            api_calls=result["calls"],
            input_tokens=sum(u.get("prompt_tokens", 0) for u in usages),
            output_tokens=sum(u.get("completion_tokens", 0) for u in usages),
            usage_reporting="provider-reported tokens; liability is not invoiced cost",
        )
        return result


class RetainedResearchBackend(SharedLedgerStructuredBackend):
    recover_unqueried = False

    def complete(self, request):
        prefix = self.bridge.root / "structured_requests" / request.fingerprint
        response_path = prefix.with_suffix(".response.json")
        if self.recover_unqueried and prefix.with_suffix(".request.json").exists():
            if response_path.exists():
                response = StructuredModelResponse.model_validate_json(response_path.read_text())
                if response.request_fingerprint != request.fingerprint:
                    raise ValueError("Retained response differs from frozen request")
                if hashlib.sha256(response.raw_response.encode()).hexdigest() != (
                    response.raw_response_sha256
                ):
                    raise ValueError("Retained response hash mismatch")
                return response
            request = request.model_copy(
                update={
                    "request_id": request.request_id + "-format-recovery",
                    "system_instruction": request.system_instruction
                    + " Prior output was not valid JSON. Return exactly one JSON object, "
                    "with no trailing brackets or text. This is a charged format-recovery attempt.",
                }
            )
        return super().complete(request)


def research_provider(config_path, root, *, max_calls=32, max_cost_usd=8.0):
    config = load_structured_openai_compatible_config(config_path)
    if config.provider not in {"deepseek", "zhipu-direct"}:
        raise ValueError("Research execution currently permits only DeepSeek and GLM providers")
    if "qwen" in config.model.lower() or not config.live_enabled:
        raise ValueError("Disabled or prohibited research model")
    _bind_credential(Path("outputs/resources/access/credentials.env"), config.api_key_env)
    bridge = ResearchProviderBridge(
        config=config,
        log_root=root,
        max_calls=max_calls,
        max_cost_usd=max_cost_usd,
        max_output_tokens=config.max_output_tokens,
        max_request_bytes=100_000,
    )
    return bridge, RetainedResearchBackend(bridge, max_output_tokens=config.max_output_tokens)
