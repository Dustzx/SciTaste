"""Connect grounded precedent deliberation to the existing action controller."""

import hashlib
import json

from scitaste.model_nodes.facade import (
    ImmutableStateProjection,
    ModelNodeFacade,
    ModelNodeFacadeRequest,
)
from scitaste.model_nodes.models import NodePolicy
from scitaste.model_nodes.profiles import load_model_node_profile
from scitaste.model_nodes.registry import first_party_node_types
from scitaste.model_nodes.runtime import ModelNodeRuntime, ModelNodeTrigger, RuntimeOutcome
from scitaste.model_nodes.session_exchange import retain_json
from scitaste.taste.semantic import taste_deliberation_from_ledger


def workspace_taste_binding(library, profile_path):
    """Bind optional development treatment without admitting observation candidates."""
    if (library is None) != (profile_path is None):
        raise ValueError("Taste library and deliberation profile must be supplied together")
    if library is None:
        return None, None
    profile = load_model_node_profile(profile_path)
    if "taste-deliberation" not in profile.allowed_node_names:
        raise ValueError("Profile does not permit taste-deliberation")
    return {
        "library_sha256": hashlib.sha256(library.read_bytes()).hexdigest(),
        "profile_sha256": profile.fingerprint,
    }, profile


class DeliberativeResearchToolController:
    """No qualified precedent/accepted reasoning means intrinsic selection, not raw RAG."""

    def __init__(
        self,
        *,
        base,
        augmented,
        runtime,
        run_id,
        backend,
        profile,
        output,
        resume=False,
        maintenance=None,
        selection_enabled=True,
    ):
        if type(selection_enabled) is not bool:
            raise ValueError("Taste action-selection switch must be boolean")
        self.base, self.augmented = base, augmented
        self.selection_enabled = selection_enabled
        self.runtime, self.run_id = runtime, run_id
        self.backend, self.profile = backend, profile
        self.maintenance = maintenance
        self.output = output
        self.output.mkdir(parents=True, exist_ok=resume)
        self.facade = ModelNodeFacade(
            ModelNodeRuntime(
                runtime, node_types=first_party_node_types(), allow_unrelated_run_updates=True
            )
        )

    def decide(self, *, state, candidate_actions):
        actions = tuple(candidate_actions)
        session = getattr(self.backend, "session_enabled", False)
        index = len(state.decision_history) if session else len(list(self.output.glob("*.json")))
        record_path = self.output / f"{index:03d}.json"
        binding = {
            "state": state.model_dump(mode="json"),
            "actions": [action.model_dump(mode="json") for action in actions],
        }
        if session:
            bindings = self.output / "bindings"
            bindings.mkdir(exist_ok=True)
            retain_json(bindings / f"{index:03d}.json", binding)
        if not self.selection_enabled:
            # The reviewed retriever can still inform proposal generation, but
            # this arm never requests deliberation or changes intrinsic choice.
            # Explicit routing is not an unsupported-transfer/fallback event.
            record = {
                "intrinsic_fallback": False,
                "intrinsic_selection": True,
                "reason": "taste-action-selection-disabled",
                "runtime_receipt": None,
            }
            retain_json(record_path, record)
            return self.base.decide(state=state, candidate_actions=actions)
        if session and record_path.exists():
            record = json.loads(record_path.read_text())
            if record.get("reason") == "taste-action-selection-disabled":
                raise ValueError("Retained decision has a different Taste selection policy")
            receipt = record.get("runtime_receipt")
            if receipt and receipt["outcome"] == RuntimeOutcome.ACCEPTED.value:
                directory = self.runtime.outputs_root / receipt["ledger_locator"]
                entries = list(directory.glob(f"*__research-taste-{index:03d}.json"))
                if len(entries) != 1:
                    raise ValueError("Expected one retained Taste entry")
                verified = taste_deliberation_from_ledger(
                    entries[0], evidence_root=self.runtime.outputs_root
                )
                if self.maintenance is not None:
                    self.maintenance.observe(state, decision_index=index, verified=verified)
                return self.augmented.decide(
                    state=state, candidate_actions=actions, taste_deliberation=verified
                )
            if self.maintenance is not None:
                self.maintenance.observe(
                    state, decision_index=index, failure_reason=record.get("reason")
                )
            return self.base.decide(state=state, candidate_actions=actions)
        record = {"intrinsic_fallback": True, "reason": None}
        verified = None
        # File inspection does not need a new scientific-precedent inference.
        if all(
            action.parameters.get("tool")
            in {"Read File", "List Files", "Read", "Glob", "Grep", "Final Answer"}
            for action in actions
        ):
            record["reason"] = "inspection-or-report-only"
        else:
            try:
                packet = self.augmented.prepare_taste_deliberation(
                    state=state, candidate_actions=actions
                )
            except ValueError as exc:
                record["reason"] = "no-valid-grounded-transfer-pool"
                record["detail"] = str(exc)
            else:
                profile = self.profile
                policy = NodePolicy(
                    policy_id=profile.profile_id + "-shared-research",
                    enabled=True,
                    allowed_node_names=["taste-deliberation"],
                    expected_backend=profile.provider,
                    expected_model=profile.model,
                    max_request_bytes=profile.admission.max_request_bytes,
                    max_input_tokens=profile.admission.max_input_tokens,
                    max_output_tokens=profile.admission.max_output_tokens,
                    max_total_tokens=profile.admission.max_total_tokens,
                    max_api_cost_usd=profile.cumulative_project.max_api_cost_usd,
                    max_latency_ms=profile.admission.max_latency_ms,
                )
                invocation = f"research-taste-{index:03d}"
                request = ModelNodeFacadeRequest(
                    project_id=state.project_id,
                    run_id=self.run_id,
                    invocation_id=invocation,
                    expected_project_revision=self.runtime.open(state.project_id).revision,
                    node_name="taste-deliberation",
                    node_input=packet.model_dump(mode="json"),
                    state_projection=ImmutableStateProjection(
                        project_id=state.project_id,
                        state_snapshot_id=packet.state_snapshot_id,
                        state_revision=state.revision,
                        stage=packet.stage,
                        candidate_actions=packet.current_actions,
                    ),
                    trigger=ModelNodeTrigger(
                        trigger_id=invocation,
                        reason="Assess grounded scientific precedent applicability before action.",
                    ),
                    profile=profile,
                    policy=policy,
                    backend_mode="session"
                    if getattr(self.backend, "session_enabled", False)
                    else "live",
                )
                resume_request = False
                if session:
                    requests = self.output / "requests"
                    requests.mkdir(exist_ok=True)
                    path = requests / f"{index:03d}.json"
                    if path.exists():
                        payload = json.loads(path.read_bytes())
                        # Historical packets contain nested computed receipts.
                        # Revalidate them rather than accepting them as inputs
                        # or rewriting the original pending request.
                        fingerprints = {
                            name: payload[name].pop("fingerprint", None)
                            for name in ("profile", "policy")
                        }
                        retained = ModelNodeFacadeRequest.model_validate(payload)
                        for name, expected in fingerprints.items():
                            if (
                                expected is not None
                                and getattr(retained, name).fingerprint != expected
                            ):
                                raise ValueError("Retained Taste computed fingerprint changed")
                        if (
                            retained.node_input != request.node_input
                            or retained.profile != request.profile
                        ):
                            raise ValueError("Pending Taste request input changed")
                        request, resume_request = retained, True
                    else:
                        retain_json(
                            path,
                            request.model_dump(mode="json", exclude_computed_fields=True),
                        )
                receipt = self.facade.execute(
                    request, backend=self.backend, allow_live=True, resume=resume_request
                ).receipt
                record["runtime_receipt"] = receipt.model_dump(mode="json")
                if receipt.outcome == RuntimeOutcome.ACCEPTED:
                    directory = self.runtime.outputs_root / receipt.ledger_locator
                    entries = list(directory.glob(f"*__{invocation}.json"))
                    if len(entries) != 1:
                        raise ValueError("Expected one immutable Taste deliberation ledger entry")
                    verified = taste_deliberation_from_ledger(
                        entries[0], evidence_root=self.runtime.outputs_root
                    )
                    record.update(intrinsic_fallback=False, reason="verified-deliberation")
                else:
                    record["reason"] = "deliberation-not-accepted"
        with (self.output / f"{index:03d}.json").open("x") as stream:
            json.dump(record, stream, indent=2)
        if verified is not None:
            if self.maintenance is not None:
                self.maintenance.observe(state, decision_index=index, verified=verified)
            return self.augmented.decide(
                state=state, candidate_actions=actions, taste_deliberation=verified
            )
        if self.maintenance is not None:
            self.maintenance.observe(
                state, decision_index=index, failure_reason=record.get("reason")
            )
        return self.base.decide(state=state, candidate_actions=actions)
