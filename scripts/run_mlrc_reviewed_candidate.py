#!/usr/bin/env python3
"""Execute an exactly bound, previously adjudicated development candidate.

This is an explicit adoption, not reopening a terminal autonomous trajectory.
Imported generation/review costs stay in their original runs.
"""

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from scitaste.evaluation.patch_scope_review import (
    PatchScopeAdjudicationInput,
    PatchScopeAdjudicationNode,
    PatchScopeAdjudicationOutput,
    PatchScopeReviewInput,
)
from scitaste.evaluation.python_edit_boundary import PythonEditBoundary
from scripts import run_mlrc_native_development_loop as loop


def read(path):
    return json.loads(path.read_text())


def tree(root):
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("symlinks are not admitted in adopted method trees")
        if path.is_file():
            result[str(path.relative_to(root))] = path.read_bytes()
    return result


def write_report(output):
    """Expose the execution outcome without erasing the manual adoption boundary."""
    result_path = output / "RESULT.json"
    if not result_path.exists():
        return
    result = read(result_path)
    contract = read(output / "CONTRACT.json")
    execution_path = output / "EXECUTION_RESULT.json"
    execution = read(execution_path)
    if result["candidate_score"] != execution["data"].get("primary_value"):
        raise ValueError("summary score differs from Native execution evidence")
    summary = {
        "status": result["status"],
        "execution_role": contract["role"],
        "execution_result_sha256": loop._sha256(execution_path),
        "contract_sha256": loop._sha256(output / "CONTRACT.json"),
        "source_run": contract["source_run"],
        "candidate_score": result["candidate_score"],
        "baseline_score": result["baseline_score"],
        "new_api_cost_ceiling_usd": result["api_cost_ceiling_usd"],
        "imported_api_cost_ceiling_usd": contract["imported_api_cost_ceiling_usd"],
        "uninterrupted_autonomous_trajectory": False,
        "formal_evidence_eligible": False,
        "post_action": result["post_action"],
    }
    report_data = output / "ADOPTION_RESULT.json"
    if report_data.exists():
        if read(report_data) != summary:
            raise ValueError("adoption result changed")
    else:
        loop.write_new(report_data, summary)
    report = output / "REPORT.md"
    if not report.exists():
        with report.open("x") as stream:
            stream.write(
                "# Reviewed candidate execution — development only\n\n"
                f"Execution status: {result['experiment_status']}.\n\n"
                f"Official candidate score: {result['candidate_score']}; "
                f"previous Euclidean baseline: {result['baseline_score']}.\n\n"
                f"Post-experiment disposition: {result['post_action']}. "
                f"{result['post_rationale']}\n\n"
                "The original stopped trajectory remains unchanged. This run adopted "
                "its exact corrected code after a separately recorded cross-model "
                "adjudication. It is not an uninterrupted autonomous trajectory, "
                "an independent task, a Taste comparison, or formal paper evidence.\n\n"
                f"New API liability ceiling: {result['api_cost_ceiling_usd']} USD; "
                f"upstream ceiling: {contract['imported_api_cost_ceiling_usd']} USD "
                "(already incurred, not charged again). These are conservative "
                "accounting ceilings, not provider invoices.\n\n"
                "Evidence: CONTRACT.json, ADOPTION_RESULT.json, EXECUTION_RESULT.json, "
                "POST_DECISION.json and the Native execution store.\n"
            )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--adjudication", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-execution", action="store_true")
    parser.add_argument("--allow-api", action="store_true")
    parser.add_argument(
        "--credentials", type=Path, default=Path("outputs/resources/access/credentials.env")
    )
    args = parser.parse_args()
    project = Path("outputs/projects/scitaste-self-development").resolve(strict=True)
    source = args.source.resolve(strict=True)
    adjudication = args.adjudication.resolve(strict=True)
    output = args.output.resolve()
    for path in (source, adjudication, output):
        path.relative_to(project / "evaluations")
    if output == source or output.is_relative_to(source):
        raise ValueError("adoption must use a separate run")
    if read(source / "RESULT.json")["status"] != "scope-review-unresolved-no-gpu":
        raise ValueError("only a terminal, unexecuted reviewed candidate can be adopted")
    if any((source / name).exists() for name in ("DEPLOYED.json", "EXECUTION_RESULT.json")):
        raise ValueError("source already has execution evidence")
    proposal = source / "proposal"
    raw = read(proposal / "PATCH_INPUT.json")
    generated = read(proposal / "NODE_RESULT.json")
    if generated["status"] != "accepted":
        raise ValueError("unadmitted source proposal")
    candidate = PatchScopeReviewInput.model_validate(
        dict(
            directive=raw["research_action"],
            source=raw["patch_context"],
            proposal=generated["proposal"],
            constraints=raw["constraints"],
        )
    )
    reviewed = read(adjudication / "NODE_RESULT.json")
    data = PatchScopeAdjudicationInput.model_validate(reviewed["request"]["input_payload"]["input"])
    verdict = PatchScopeAdjudicationOutput.model_validate(reviewed["proposal"])
    if reviewed["status"] != "accepted" or verdict.disposition != "aligned":
        raise ValueError("adjudication did not admit alignment")
    if data.candidate != candidate:
        raise ValueError("adjudication belongs to a different candidate")
    reasons = PatchScopeAdjudicationNode()._proposal_rejections(
        verdict,
        input_data=data,
        context=None,
        policy=None,
    )
    if reasons:
        raise ValueError(reasons)
    sources = {row.path: row.content for row in candidate.source.files}
    replacements = candidate.proposal.resolve_files(sources)
    PythonEditBoundary.model_validate(read(proposal / "EDIT_BOUNDARY.json")).validate_candidate(
        sources,
        replacements,
    )
    evaluations = project / "evaluations"
    base = evaluations / "scitastebench-mlrc-meta-visual-fork-remote-bundle-v4"
    expected = tree(base / "branches" / "euclidean-prototypes")
    for path, text in sources.items():
        if expected.get(path) != text.encode():
            raise ValueError("review original differs from frozen baseline: " + path)
    expected.update({path: text.encode() for path, text in replacements.items()})
    if tree(proposal / "arm_source") != expected:
        raise ValueError("materialized candidate differs from reviewed code or baseline")
    prior = loop.score(
        evaluations / "scitastebench-mlrc-meta-pre-experiment-decision-v1",
        evaluations / "scitastebench-mlrc-meta-visual-fork-remote-bundle-v3",
        base,
        evaluations / "scitastebench-mlrc-meta-remote-4090-pair-v1",
        None,
    )
    contract = dict(
        role="adopt-reviewed-development-candidate",
        candidate_id=output.name,
        source_run=str(source.relative_to(project)),
        source_decision_sha256=loop._sha256(source / "DECISION.json"),
        proposal_receipt_sha256=loop._sha256(proposal / "PREPARATION_RECEIPT.json"),
        generation_sha256=loop._sha256(proposal / "NODE_RESULT.json"),
        adjudication=str(adjudication.relative_to(project)),
        adjudication_sha256=loop._sha256(adjudication / "NODE_RESULT.json"),
        boundary_sha256=loop._sha256(proposal / "EDIT_BOUNDARY.json"),
        method_files={path: hashlib.sha256(value).hexdigest() for path, value in expected.items()},
        max_experiments=1,
        wall_seconds=1200,
        formal_evidence_eligible=False,
        uninterrupted_autonomous_trajectory=False,
        imported_api_cost_ceiling_usd=(
            read(source / "RESULT.json")["api_cost_ceiling_usd"]
            + read(adjudication / "RESULT.json")["api_cost_ceiling_usd"]
        ),
        cost_scope="new run counts only new post-experiment API calls",
    )
    output.mkdir(parents=True, exist_ok=True)
    contract_path = output / "CONTRACT.json"
    if contract_path.exists():
        if read(contract_path) != contract:
            raise ValueError("adoption contract changed")
    else:
        loop.write_new(contract_path, contract)
    if (output / "RESULT.json").exists():
        write_report(output)
        print((output / "RESULT.json").read_text())
        return
    destination = output / "proposal"
    destination.mkdir(exist_ok=True)
    if not (destination / "arm_source").exists():
        shutil.copytree(proposal / "arm_source", destination / "arm_source")
    if tree(destination / "arm_source") != expected:
        raise ValueError("adopted copy differs")
    receipt = destination / "PREPARATION_RECEIPT.json"
    if not receipt.exists():
        shutil.copyfile(proposal / receipt.name, receipt)
    if loop._sha256(receipt) != contract["proposal_receipt_sha256"]:
        raise ValueError("copied receipt changed")
    decision = loop.ResearchDecision.model_validate(read(source / "DECISION.json"))
    action = decision.selected_action.model_copy(
        update={
            "parameters": {**decision.selected_action.parameters, "candidate_id": output.name},
        }
    )
    decision = decision.model_copy(update={"selected_action": action})
    decision_path = output / "DECISION.json"
    if decision_path.exists():
        if read(decision_path) != decision.model_dump(mode="json"):
            raise ValueError("execution binding changed")
    else:
        loop.write_new(decision_path, decision.model_dump(mode="json"))
    if not args.allow_execution or not args.allow_api:
        print("Adoption bound; execution and API flags required to continue.")
        return
    config = loop.load_structured_openai_compatible_config(
        Path("configs/model_nodes/bailian_qwen38max.taste_review_live_20260916.yaml")
    )
    loop._bind_credential(args.credentials, config.api_key_env)
    controller = loop.TasteController(
        utility_enabled=False,
        critics_enabled=False,
        preference_backend=loop.ResumableRecordingBackend(
            loop.OpenAICompatibleBackend(
                loop.OpenAICompatibleConfig(
                    provider=config.provider,
                    model=config.model,
                    base_url=config.base_url,
                    api_key_env=config.api_key_env,
                    timeout_seconds=180,
                    max_retries=0,
                    extra_body={**config.extra_body, "max_tokens": 2048},
                ),
                transport=loop.RecordedTransport(output / "provider.jsonl"),
            ),
            output / "controller.jsonl",
        ),
        expected_preference_backend=config.provider,
        expected_preference_model=config.model,
    )
    state = loop.ResearchState.model_validate(read(source / "INITIAL_STATE.json"))
    loop.execute_and_review(
        args=args,
        project=project,
        output=output,
        base=base,
        contract_path=contract_path,
        state=state,
        decision=decision,
        controller=controller,
        prior=prior,
    )
    write_report(output)


if __name__ == "__main__":
    main()
