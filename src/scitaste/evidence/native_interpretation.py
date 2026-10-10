"""Ground model interpretation proposals in committed Native execution results."""

import hashlib
import json
import math
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from scitaste.evidence.claim_graph import ClaimGraph, ScientificClaim
from scitaste.evidence.evidence_graph import EvidenceGraph, EvidenceItem
from scitaste.evidence.interpretation import (
    InterpretationContext,
    InterpretationCritic,
    ResultRecord,
)
from scitaste.evidence.loop import EvidenceLoop
from scitaste.state.research_state import ResearchState


class ExplicitContext(InterpretationContext):
    statistical_uncertainty: float = Field(ge=0, le=1)


class NativeInterpretation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_result_id: str = Field(min_length=1)
    source_quote: str = Field(min_length=8, max_length=4000)
    context: ExplicitContext
    new_claim: ScientificClaim | None = None


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def interpret_native_results(state, history, submissions):
    """Return an atomic derived state; interpretation never executes/recharges tools.

    Model-authored context is a proposal, not independent evidence. Without a
    structured measured source and retained replication metadata it stays uncertain.
    """
    if not submissions:
        return state
    payload = state.model_dump(mode="json")
    # Canonical states may also contain incomplete conceptual claims and unlinked
    # observations. Preserve them verbatim, rather than inventing scientific fields
    # or requiring unrelated old records to satisfy the stricter assessment schema.
    claims = ClaimGraph()
    omitted_claims, omitted_evidence = [], []
    for item in payload["claims"]:
        try:
            claims.add(ScientificClaim.model_validate(item))
        except ValidationError:
            omitted_claims.append(item["claim_id"])
    known = {item.claim_id for item in claims.claims}
    eligible = []
    for item in payload["evidence_graph"]["items"]:
        try:
            parsed = EvidenceItem.model_validate(item)
            targets = {
                *parsed.supports_claim_ids,
                *parsed.contradicts_claim_ids,
                *parsed.relates_to_claim_ids,
            }
            if targets - known:
                omitted_evidence.append(item)
            else:
                eligible.append(parsed)
        except ValidationError:
            omitted_evidence.append(item)
    evidence = EvidenceGraph(items=eligible)
    loop = EvidenceLoop(claims, evidence=evidence)
    sources = {}
    for row in history:
        key = row["result"]["result_id"]
        if key in sources:
            raise ValueError("Ambiguous committed result identity")
        sources[key] = row
    receipts = payload["executor_context"].setdefault("native_interpretations", {})
    reviews = []
    for submission in submissions:
        source = sources.get(submission.source_result_id)
        if source is None or source["result"]["status"] != "SUCCEEDED":
            raise ValueError("Interpretation requires a committed successful source result")
        result = source["result"]
        observations = json.dumps(result["observations"], ensure_ascii=False)
        # Quotes target observation text, not JSON transport escaping. Preserve
        # the serialized value for provenance but match original string values.
        if not any(
            submission.source_quote
            in (value if isinstance(value, str) else json.dumps(value, ensure_ascii=False))
            for value in result["observations"]
        ):
            raise ValueError("Interpretation quote is absent from source observations")
        identity = submission.source_result_id + ":" + submission.context.claim_id
        binding = {
            "source_sha256": _digest(source),
            "proposal_sha256": _digest(submission.model_dump(mode="json")),
            "authority": "model-proposed-development-interpretation",
            "formal_evidence_eligible": False,
        }
        if identity in receipts:
            if receipts[identity] != binding:
                raise ValueError("Conflicting interpretation replay")
            continue
        if submission.new_claim is not None:
            claim = submission.new_claim
            if claim.claim_id in omitted_claims:
                raise ValueError(
                    "Cannot replace an incomplete inherited claim through interpretation"
                )
            if (
                claim.claim_id != submission.context.claim_id
                or claim.status.value != "unsupported"
                or claim.supporting_evidence_ids
                or claim.contradicting_evidence_ids
            ):
                raise ValueError("New claims must be unsupported scientific definitions")
            claims.add(claim.model_copy(deep=True))
        if submission.context.claim_id in omitted_claims:
            raise ValueError(
                "Target claim needs a scientific type and evidence contract before interpretation"
            )
        claims.get(submission.context.claim_id)
        data = result.get("data", {})
        metrics = (
            {
                k: v
                for k, v in data.get("metrics", {}).items()
                if type(v) in (int, float) and math.isfinite(v)
            }
            if isinstance(data.get("metrics", {}), dict)
            else {}
        )
        primary = data.get("primary_value")
        if type(primary) in (int, float) and math.isfinite(primary):
            metrics["primary_value"] = primary
        context = submission.context.model_dump(mode="json")
        if any(
            context["claim_id"]
            in (
                item["supports_claim_ids"]
                + item["contradicts_claim_ids"]
                + item["relates_to_claim_ids"]
            )
            for item in omitted_evidence
        ):
            context["confounders"].append(
                "Some inherited evidence cannot enter the typed claim assessment"
            )
        # Exit status, rendered text and a model's confidence do not establish
        # experimental replication. Keep such submissions as related evidence.
        measured = source["selected"]["parameters"]["tool"] in {"Run Experiment", "Run Remote"}
        replicated = data.get("result_basis") == "sandbox-measured-replicates"
        if not measured or not metrics or not replicated:
            context["confounders"] = [
                *context["confounders"],
                "Native source lacks independently identified measured replication",
            ]
            context["reproducible"] = False
        review = InterpretationCritic().review(
            ResultRecord(
                result_id=result["result_id"],
                experiment_id=data.get("experiment_id") or result["result_id"],
                summary=observations,
                metrics=metrics,
                cost=result.get("cost", {}),
            ),
            InterpretationContext.model_validate(context),
        )
        loop.add_review(review)
        reviews.append(review)
        payload["interpretation_history"].append(review.model_dump(mode="json"))
        receipts[identity] = binding
    if not reviews:
        return state
    assessment = loop.assess(reviews=reviews)
    updated_claims = {item.claim_id: item.model_dump(mode="json") for item in claims.claims}
    incompletely_assessed = {
        claim_id
        for item in omitted_evidence
        for claim_id in (
            *item["supports_claim_ids"],
            *item["contradicts_claim_ids"],
            *item["relates_to_claim_ids"],
        )
    }
    for original in payload["claims"]:
        if original["claim_id"] in incompletely_assessed and original["claim_id"] in updated_claims:
            updated_claims[original["claim_id"]]["status"] = original["status"]
    payload["claims"] = [updated_claims.pop(item["claim_id"], item) for item in payload["claims"]]
    payload["claims"].extend(updated_claims.values())
    updated_evidence = {item.evidence_id: item.model_dump(mode="json") for item in evidence.items}
    payload["evidence_graph"]["items"] = [
        updated_evidence.pop(item["evidence_id"], item)
        for item in payload["evidence_graph"]["items"]
    ]
    payload["evidence_graph"]["items"].extend(updated_evidence.values())
    payload["executor_context"]["evidence_route_advice"] = assessment.model_dump(mode="json")
    payload["executor_context"]["evidence_projection_scope"] = {
        "unassessed_claim_ids": sorted(set(omitted_claims) | incompletely_assessed),
        "unassessed_evidence_ids": [item["evidence_id"] for item in omitted_evidence],
        "whole_graph_assessed": not (omitted_claims or omitted_evidence),
        "execution_authorized": False,
    }
    payload["revision"] += 1
    return ResearchState.model_validate(payload)


def recover_session_interpretation(*, project, execution, session_reply, output):
    """Materialize a separate derived state from a consumed session response.

    No tool or model is recalled, and the original execution status is immutable.
    """
    from scitaste.model_nodes.session_exchange import SessionReply, retain_json
    from scitaste.state.persistence import StateStore, snapshot_id

    root = project.resolve(strict=True)
    run = execution.resolve(strict=True)
    reply_path = session_reply.resolve(strict=True)
    output = output.resolve()
    run.relative_to(root)
    output.relative_to(root)
    if output.is_relative_to(run) or run.is_relative_to(output):
        raise ValueError("Recovery output must be separate from the original execution")
    reply_path.relative_to(run / "session-exchange")
    terminal = json.loads((run / "RESULT.json").read_text())
    if terminal["controller_owner"] != "scitaste-native":
        raise ValueError("Interpretation recovery requires Native execution")
    reply = SessionReply.model_validate_json(reply_path.read_bytes())
    response_path = reply_path.with_name(reply.request_fingerprint + ".response.json")
    consumed = json.loads(response_path.read_text())
    if (
        consumed.get("output_payload") != reply.output_payload
        or consumed.get("request_fingerprint") != reply.request_fingerprint
    ):
        raise ValueError("Reply was not the retained consumed response")
    state_path = (root / terminal["research_state"]).resolve(strict=True)
    state_path.relative_to(run)

    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    if digest(state_path) != terminal["research_state_sha256"]:
        raise ValueError("Execution state changed")
    trajectory = run / "loop/TRAJECTORY.jsonl"
    history = [json.loads(line) for line in trajectory.read_text().splitlines()]
    state = ResearchState.model_validate_json(state_path.read_bytes())
    submissions = [
        NativeInterpretation.model_validate(value)
        for value in reply.output_payload.get("interpretations", [])
    ]
    if not submissions:
        raise ValueError("Consumed response contains no interpretations")
    derived = interpret_native_results(state, history, submissions)
    contract = {
        "source_execution": run.relative_to(root).as_posix(),
        "original_execution_status": terminal["status"],
        "terminal_sha256": digest(run / "RESULT.json"),
        "trajectory_sha256": digest(trajectory),
        "state_sha256": digest(state_path),
        "response_sha256": digest(response_path),
        "reply_sha256": digest(reply_path),
        "bridge_sha256": digest(Path(__file__)),
    }
    output.mkdir(parents=True, exist_ok=True)
    retain_json(output / "CONTRACT.json", contract)
    if (output / "state/research_state.json").exists():
        if StateStore(output / "state").load() != derived:
            raise ValueError("Retained derived state differs; do not overwrite it")
    StateStore(output / "state").save(derived)
    result = {
        "status": "interpretation-materialized-original-execution-unchanged",
        "contract_sha256": digest(output / "CONTRACT.json"),
        "research_state": (output / "state/research_state.json").relative_to(root).as_posix(),
        "state_id": snapshot_id(derived),
        "claim_statuses": {claim.claim_id: claim.status for claim in derived.claims},
        "new_model_calls": 0,
        "new_experiments": 0,
        "new_tool_calls": 0,
        "formal_evidence_eligible": False,
    }
    retain_json(output / "RESULT.json", result)
    return result


if __name__ == "__main__":
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Recover consumed Native interpretation only")
    for key in ("project", "execution", "session-reply", "output"):
        parser.add_argument("--" + key, type=Path, required=True)
    print(json.dumps(recover_session_interpretation(**vars(parser.parse_args()))))
