"""Run an actual source-quality node using session responses, never a provider API."""

import argparse
import hashlib
import json
from pathlib import Path

from scitaste.model_nodes.facade import (
    ImmutableStateProjection,
    ModelNodeFacade,
    ModelNodeFacadeRequest,
)
from scitaste.model_nodes.models import NodePolicy
from scitaste.model_nodes.profiles import load_model_node_profile
from scitaste.model_nodes.registry import first_party_node_types
from scitaste.model_nodes.runtime import ModelNodeRuntime, ModelNodeTrigger
from scitaste.model_nodes.session_exchange import SessionStructuredBackend, retain_json
from scitaste.project import ProjectRun, ProjectRuntime
from scitaste.taste.reference_quality import ReferenceQualityInput


class RetainedSourceSessionBackend:
    """Revalidate identical source advice after a metadata-only concurrency reject.

    This is not another model call. Exact request equality and the original
    response binding remain mandatory; no scientific rejection is recoverable.
    """

    name = "assistant-session"
    model = "session-authored"
    session_enabled = True

    def __init__(self, previous, output, source):
        result = json.loads((previous / "RESULT.json").read_text())
        receipt = result["receipt"]
        node = receipt["result"]
        identity = node["request"]["input_payload"]["input"]
        node_name = node["request"]["node_name"]
        same_source = (
            ReferenceQualityInput.model_validate(identity) == source
            if node_name == "reference-quality"
            else node_name == "grounded-taste-abstraction"
            and all(
                identity.get(key) == getattr(source, key)
                for key in (
                    "source_id",
                    "source_projection",
                    "source_projection_sha256",
                    "decision_role",
                    "outcome_information_availability",
                )
            )
            and identity.get("stage") == source.decision_stage
        )
        if (
            receipt["outcome"] != "rejected"
            or node["rejection_reasons"]
            != ["project revision changed while the model-node backend was running"]
            or not same_source
        ):
            raise ValueError("Only identical source-advice concurrency rejects can be reused")
        self.previous, self.output, self.request = previous, output, node["request"]

    def complete(self, request):
        if request.model_dump(mode="json", exclude_computed_fields=True) != self.request:
            raise ValueError("Retained source response belongs to a different exact request")
        prefix = self.previous / "exchange" / request.fingerprint
        request_path = prefix.with_suffix(".request.json")
        response_path = prefix.with_suffix(".response.json")
        old = json.loads(response_path.read_text())
        backend = SessionStructuredBackend(self.previous / "exchange", max_requests=1)
        response = backend.complete(request)
        if response.model_dump(mode="json") != old:
            raise ValueError("Retained session response changed before revalidation")
        retain_json(
            self.output / "REUSED_SESSION.json",
            {
                "source_request": str(request_path),
                "source_request_sha256": hashlib.sha256(request_path.read_bytes()).hexdigest(),
                "source_response": str(response_path),
                "source_response_sha256": hashlib.sha256(response_path.read_bytes()).hexdigest(),
                "source_result_sha256": hashlib.sha256(
                    (self.previous / "RESULT.json").read_bytes()
                ).hexdigest(),
                "exact_request_equal": True,
                "new_model_responses": 0,
                "scientific_advice_changed": False,
                "original_rejection_preserved": True,
            },
        )
        return response.model_copy(update={"cached": True})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--abstract-after-quality", type=Path)
    parser.add_argument("--backend-config", type=Path)
    parser.add_argument("--allow-api-execution", action="store_true")
    parser.add_argument("--repair-abstraction-from", type=Path)
    parser.add_argument("--reuse-session-from", type=Path)
    args = parser.parse_args()
    source = ReferenceQualityInput.model_validate_json(args.input.read_text())
    metadata = {}
    if args.repair_abstraction_from:
        from scitaste.taste.semantic_models import GroundedTasteCaseAbstraction

        previous = json.loads(args.repair_abstraction_from.read_text())
        if previous["receipt"]["outcome"] != "rejected":
            raise ValueError("Format recovery requires a retained rejected abstraction")
        responses = list(
            (args.repair_abstraction_from.parent / "provider/structured_requests").glob(
                "*.response.json"
            )
        )
        if len(responses) != 1:
            raise ValueError("Ambiguous prior provider response")
        proposal = json.loads(responses[0].read_text())["output_payload"]
        try:
            GroundedTasteCaseAbstraction.model_validate(proposal)
        except ValueError as exc:
            metadata = {
                "format_repair": {
                    "previous_output": proposal,
                    "error": str(exc),
                    "instruction": "Repair schema consistency using only the unchanged source. "
                    "Keep outcome_summary and outcome grounding consistent. "
                    "Do not invent an outcome.",
                }
            }
        else:
            raise ValueError("Semantic rejection cannot use schema-only recovery")
    profile = load_model_node_profile(args.profile)
    live = args.backend_config is not None
    if args.reuse_session_from and (live or args.repair_abstraction_from):
        raise ValueError("Source revalidation cannot enable API or change rejected advice")
    if live != args.allow_api_execution:
        raise ValueError("Provider execution requires config and explicit opt-in")
    if not live and (profile.provider, profile.model) != ("assistant-session", "session-authored"):
        raise ValueError("This entry point permits only session responses")
    if not live and args.abstract_after_quality:
        # Qualification is intentionally closed to all contextual metadata.
        # Its byte limit remains enforced by the profile/runtime; source-only
        # screening must not fail because the coordinator added admission advice.
        metadata["session_admission"] = {
            "response_json_utf8_byte_limit": profile.admission.max_output_tokens,
            "actual_token_count": None,
            "instruction": "Return concise schema-conformant JSON within the declared byte bound; "
            "it is an admission limit, not a measured tokenizer count. "
            "Retain scientific qualifications and do not omit adverse evidence to fit.",
        }
    if live:
        from scitaste.model_nodes.profiles import ModelNodeProfile

        values = profile.model_dump(mode="json", exclude={"fingerprint"})
        values["generation"]["max_output_tokens"] = 8192
        values["admission"].update(max_output_tokens=8192, max_total_tokens=208192)
        profile = ModelNodeProfile.model_validate(values)
    project = args.project.resolve(strict=True)
    node_name = "reference-quality"
    node_input = source.model_dump(mode="json")
    if args.abstract_after_quality:
        from scitaste.taste.semantic import reference_quality_from_ledger
        from scitaste.taste.semantic_models import TasteAbstractionInput

        receipt = json.loads(args.abstract_after_quality.read_text())["receipt"]
        ledger = (project.parent.parent / receipt["ledger_locator"]).resolve(strict=True)
        ledger.relative_to(project.parent.parent)
        entries = list(ledger.glob(f"*__{receipt['invocation_id']}.json"))
        if len(entries) != 1:
            raise ValueError("Expected exactly one source-quality ledger entry")
        quality = reference_quality_from_ledger(
            entries[0], evidence_root=project.parent.parent, allow_development_session=True
        )
        if quality.proposal.verdict.value != "qualify" or quality.input != source:
            raise ValueError("Source is not the qualified source")
        node_name = "grounded-taste-abstraction"
        profile = profile.model_copy(
            update={
                "profile_id": "grounded-source-abstraction-v1",
                "allowed_node_names": (node_name,),
            }
        )
        node_input = TasteAbstractionInput(
            source_id=source.source_id,
            candidate_id=source.source_id + "-candidate-v1",
            case_id=source.source_id + "-case-v1",
            stage=source.decision_stage,
            decision_role=source.decision_role,
            source_projection=source.source_projection,
            source_projection_sha256=source.source_projection_sha256,
            domain_tags=("research-methodology",),
            outcome_information_availability=source.outcome_information_availability,
        ).model_dump(mode="json")
    output = args.output.resolve()
    output.relative_to(project / "evaluations")
    # Different sources commonly use the same phase name (quality/abstraction).
    # Registration and node ledgers must not collide on that leaf directory name.
    run_id = "--".join(output.relative_to(project / "evaluations").parts)
    output.mkdir()
    retain_json(output / "INPUT.json", node_input)
    runtime = ProjectRuntime(project.parent.parent)
    runtime.begin_run(
        project.name,
        ProjectRun(
            run_id=run_id,
            provider=profile.provider,
            model=profile.model,
            condition=node_name,
            seed=0,
            status="screening",
            evidence_scope=(
                "Development source qualification only; no experiment or formal admission"
            ),
            artifact=(output / "INPUT.json").relative_to(project).as_posix(),
            formal_evidence_eligible=False,
        ),
        expected_revision=runtime.open(project.name).revision,
    )
    request = ModelNodeFacadeRequest(
        project_id=project.name,
        run_id=run_id,
        invocation_id=node_name,
        expected_project_revision=runtime.open(project.name).revision,
        node_name=node_name,
        node_input=node_input,
        state_projection=ImmutableStateProjection(
            project_id=project.name,
            state_snapshot_id=source.source_projection_sha256,
            state_revision=0,
            stage=source.decision_stage,
            evidence_ids=(source.source_id,),
            metadata=metadata,
        ),
        trigger=ModelNodeTrigger(
            trigger_id="qualify-source", reason="Assess source decision evidence"
        ),
        profile=profile,
        policy=NodePolicy(
            policy_id="source-quality-session-v1",
            enabled=True,
            allowed_node_names=[node_name],
            expected_backend=profile.provider,
            expected_model=profile.model,
            max_request_bytes=profile.admission.max_request_bytes,
            max_input_tokens=profile.admission.max_input_tokens,
            max_output_tokens=profile.admission.max_output_tokens,
            max_total_tokens=profile.admission.max_total_tokens,
            max_api_cost_usd=profile.cumulative_project.max_api_cost_usd,
            max_latency_ms=profile.admission.max_latency_ms,
            allowed_tool_names=list(profile.admission.allowed_tool_names),
        ),
        backend_mode="live" if live else "session",
    )
    retain_json(output / "REQUEST.json", request.model_dump(mode="json", exclude={"fingerprint"}))
    if live:
        from scitaste.backends.research_provider import research_provider

        _, backend = research_provider(args.backend_config, output / "provider", max_calls=1)
    elif args.reuse_session_from:
        previous = args.reuse_session_from.resolve(strict=True)
        previous.relative_to(project / "evaluations")
        backend = RetainedSourceSessionBackend(previous, output, source)
    else:
        backend = SessionStructuredBackend(output / "exchange", wait_seconds=600, max_requests=1)
    result = ModelNodeFacade(
        ModelNodeRuntime(
            runtime, node_types=first_party_node_types(), allow_unrelated_run_updates=True
        )
    ).execute(
        request,
        backend=backend,
        allow_live=True,
    )
    accepted = result.receipt.outcome.value == "accepted"
    proposal = (result.receipt.result or {}).get("proposal") or {}
    quality_verdict = proposal.get("verdict") if node_name == "reference-quality" else None
    untrusted_verdict = None
    if node_name == "reference-quality" and not accepted:
        raw_response = (result.receipt.result or {}).get("response") or {}
        raw_proposal = raw_response.get("output_payload") or {}
        if raw_proposal.get("verdict") in {"qualify", "reject"}:
            untrusted_verdict = raw_proposal["verdict"]
    phase_status = result.receipt.outcome.value
    if accepted and quality_verdict in {"qualify", "reject"}:
        phase_status = "source-qualified" if quality_verdict == "qualify" else "source-rejected"
    retain_json(
        output / "RESULT.json",
        {
            "receipt": result.receipt.model_dump(mode="json"),
            "source_quality_verdict": quality_verdict,
            "untrusted_source_quality_verdict": untrusted_verdict,
            "source_qualified": accepted and quality_verdict == "qualify",
            "abstraction_produced": accepted and node_name == "grounded-taste-abstraction",
            "library_admitted": False,
            "input_sha256": hashlib.sha256(args.input.read_bytes()).hexdigest(),
            "usage_semantics": (
                "Provider-reported tokens; conservative liability, not invoice"
                if live
                else "session byte admission bounds; real tokens/cost unknown"
            ),
        },
    )
    retain_json(output / "RUNTIME_RECEIPT.json", result.receipt.model_dump(mode="json"))
    runtime.update_run(
        project.name,
        run_id,
        expected_revision=runtime.open(project.name).revision,
        status=phase_status,
        artifact=(output / "RESULT.json").relative_to(project).as_posix(),
    )
    print(
        json.dumps(
            {"outcome": result.receipt.outcome.value, "status": phase_status, "output": str(output)}
        )
    )


if __name__ == "__main__":
    main()
