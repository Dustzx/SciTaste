#!/usr/bin/env python3
"""One bounded Native development iteration with real controller feedback.

This composes the existing controller, code node, isolated runtime and Native
executor. It is not Full Taste, an external-agent implementation or formal data.
Use --prepare-only to inspect a proposal before the authorized GPU continuation.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

import httpx

from scitaste.backends.openai_compatible import (
    HttpxTransport,
    OpenAICompatibleBackend,
    OpenAICompatibleConfig,
)
from scitaste.backends.replay import ResumableRecordingBackend
from scitaste.evaluation.task_patch_generation import BenchmarkResearchActionDirective
from scitaste.executor.base import ExecutionResult, ExecutionStatus
from scitaste.executor.native import SciTasteNativeExecutor
from scitaste.executor.native_store import NativeExecutionStore
from scitaste.executor.remote_mlrc import RemoteMLRCActionHandler, RemoteMLRCBinding
from scitaste.model_nodes.openai_compatible import load_structured_openai_compatible_config
from scitaste.model_nodes.profiles import load_model_node_profile
from scitaste.project.models import ProjectRun, content_sha256
from scitaste.project.runtime import ProjectRuntime
from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.schema.decisions import ResearchDecision
from scitaste.state.persistence import StateStore
from scitaste.state.research_state import (
    ResearchObservation,
    ResearchStage,
    ResearchState,
    ResourceBudget,
)
from scitaste.taste.controller import TasteController

if __package__:
    from .mlrc_meta_visual_fork_runtime import _sha256, package_candidate
    from .run_scitastebench_decision_baselines import _bind_credential
    from .score_mlrc_meta_decision import score
else:
    from mlrc_meta_visual_fork_runtime import _sha256, package_candidate
    from run_scitastebench_decision_baselines import _bind_credential
    from score_mlrc_meta_decision import score


def write_new(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        stream.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def register_progress(
    project: Path, output: Path, status: str, *, provider="bailian", model="qwen3.8-max"
) -> None:
    """Expose the real development state in project navigation, not only loose logs."""
    runtime = ProjectRuntime(project.parent.parent)
    snapshot = runtime.open(project.name)
    run_id = output.name
    artifact = output / ("RESULT.json" if (output / "RESULT.json").exists() else "CONTRACT.json")
    changes = {"status": status, "artifact": str(artifact.relative_to(project))}
    existing = next((row for row in snapshot.manifest.runs if row.run_id == run_id), None)
    if existing is None:
        runtime.begin_run(
            project.name,
            ProjectRun(
                run_id=run_id,
                provider=provider,
                model=model,
                condition="native-base-bounded-development-loop",
                seed=98,
                evidence_scope="consumed development task; not formal method evidence",
                formal_evidence_eligible=False,
                **changes,
            ),
            expected_revision=snapshot.manifest.revision,
        )
    elif (existing.provider, existing.model) != (provider, model):
        raise ValueError("Registered run cannot switch provider/model during continuation")
    elif existing.status != status or existing.artifact != changes["artifact"]:
        runtime.update_run(
            project.name, run_id, expected_revision=snapshot.manifest.revision, **changes
        )


class RecordedTransport(HttpxTransport):
    def __init__(self, path: Path):
        self.path = path

    def post(self, url, *, headers, payload, timeout):
        with httpx.Client(timeout=timeout, trust_env=False) as client:
            raw = client.post(url, headers=headers, json=payload)
            raw.raise_for_status()
            response = raw.json()
        # Never serialize Authorization headers. Preserve the actual served identity.
        with self.path.open("a") as stream:
            stream.write(json.dumps({"request": payload, "response": response}) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        return response


def initial_actions(
    candidate_id: str, *, operationally_explicit: bool = False
) -> tuple[ResearchAction, ...]:
    return (
        ResearchAction(
            action_id="native-meta-distinct-mechanism",
            type=MetaAction.EXPERIMENT,
            description=(
                "Investigate one distinct, falsifiable method mechanism using the "
                "unchanged Euclidean baseline. Do not repeat L2 normalization, cosine "
                "logits or a temperature sweep. Preserve seeds, data, training/validation "
                "schedule and official scorer; one 20-minute experiment is available."
                + (
                    " Specify the exact computation and insertion point, which samples define "
                    "each statistic (support/query/training), train versus inference behavior, "
                    "what remains unchanged and the falsifying observation. Do not repeat a "
                    "previously measured intervention under new terminology. If these cannot "
                    "be specified within current files and budget, retain STOP."
                    if operationally_explicit
                    else ""
                )
            ),
            parameters={"candidate_id": candidate_id},
            expected_cost={"experiments": 1, "gpu_hours": 1 / 3, "wall_time_hours": 1 / 3},
        ),
        ResearchAction(
            action_id="native-meta-stop",
            type=MetaAction.STOP,
            description=(
                "Stop this development task; preserve adverse evidence "
                "and spend no further GPU budget."
            ),
        ),
    )


def prior_iteration_feedback(project: Path, previous: Path) -> dict:
    """Import terminal measured feedback, not a summary's unverified score."""
    previous = previous.resolve(strict=True)
    previous.relative_to(project)
    result = ExecutionResult.model_validate_json((previous / "EXECUTION_RESULT.json").read_text())
    if result.status not in {ExecutionStatus.SUCCEEDED, ExecutionStatus.FAILED}:
        raise ValueError("previous Native iteration has no terminal experiment result")
    store = NativeExecutionStore(previous / "native", artifact_root=project)
    entries = store.entries()
    if not any(
        record.result.model_copy(
            update={
                "data": {
                    **record.result.data,
                    "execution_record": locator,
                    "execution_record_sha256": record.record_sha256,
                    "execution_sequence": record.sequence,
                }
            }
        )
        == result
        for locator, record in entries
    ):
        raise ValueError("prior feedback differs from the verified Native record")
    decision = ResearchDecision.model_validate_json((previous / "DECISION.json").read_text())
    if result.action_id != decision.selected_action.action_id:
        raise ValueError("prior result and hypothesis identities differ")
    terminal = json.loads((previous / "RESULT.json").read_text())
    if terminal["status"] != "bounded-development-loop-completed":
        raise ValueError("prior research iteration did not reach a terminal disposition")
    return {
        "source": str(previous.relative_to(project)),
        "native_head_sha256": store.verify().head_record_sha256,
        "hypothesis": decision.selected_action.description,
        "experiment_status": result.status.value,
        "metric": result.data.get("primary_metric"),
        "score": result.data.get("primary_value"),
        "post_action": terminal["post_action"],
        "scope": "one consumed development task; no general mechanism or Taste effect proven",
        "execution_result_sha256": _sha256(previous / "EXECUTION_RESULT.json"),
    }


def api_ceiling(output: Path) -> float:
    """Configured conservative liability ceiling, not an actual invoice."""
    total = 0.0
    wire = output / "provider.jsonl"
    ledger = output / "logs/provider_calls"
    if ledger.exists():
        from scitaste.backends.mlagentbench import provider_ledger_accounting

        total += provider_ledger_accounting(ledger)["liability_usd"]
    elif wire.exists():
        for line in wire.read_text().splitlines():
            usage = json.loads(line)["response"].get("usage")
            if not usage or "prompt_tokens" not in usage or "completion_tokens" not in usage:
                raise ValueError("controller usage unknown; no further spending authorized")
            total += (usage["prompt_tokens"] * 12 + usage["completion_tokens"] * 36) / 1e6
    nodes = list(output.glob("proposal*/NODE_RESULT.json"))
    nodes.extend(output.glob("scope-reviews/*/NODE_RESULT.json"))
    nodes.extend(output.glob("scope-adjudications/*/NODE_RESULT.json"))
    for node in sorted(nodes):
        response = json.loads(node.read_text())["response"]
        if response.get("cached"):
            continue
        cost = response["usage"]["cost_usd"]
        if cost is None:
            raise ValueError("patch usage cost unknown")
        total += cost
    return total


def review_scope(args, output: Path, backend_path: Path) -> bool:
    """Return True only when aligned; one bounded correction may re-enter main."""
    proposal = output / "proposal"
    receipt_sha = _sha256(proposal / "PREPARATION_RECEIPT.json")
    review = output / "scope-reviews" / ("visible-caller-v2-" + receipt_sha)
    old_record = output / "scope-reviews" / receipt_sha / "recordings.jsonl"
    if not (review / "NODE_RESULT.json").exists():
        if api_ceiling(output) > 1.0:
            raise ValueError("insufficient reserved API budget for review and continuation")
        subprocess.run(
            [
                sys.executable,
                "scripts/review_benchmark_patch_scope.py",
                "--proposal",
                str(proposal),
                "--output",
                str(review),
                "--backend",
                str(backend_path),
                "--profile",
                str(args.scope_review_profile),
                "--credentials",
                str(args.credentials),
                "--project-id",
                args.project.name,
                "--allow-api",
            ]
            + (["--replay-record", str(old_record)] if old_record.exists() else []),
            env={
                key: value
                for key, value in os.environ.items()
                if key.lower() not in {"http_proxy", "https_proxy", "all_proxy"}
            },
            check=True,
        )
    result = json.loads((review / "NODE_RESULT.json").read_text())
    advice = result.get("proposal")
    if result["status"] != "accepted" or advice is None:
        finish_scope_stop(args, output, review, "scope-review-response-rejected-no-gpu", result)
        return False
    if advice["disposition"] == "aligned":
        return True
    marker = output / "AUTOMATIC_CORRECTION.json"
    if advice["disposition"] != "revise" or marker.exists():
        if adjudicate_scope(args, output, review, result):
            return True
        finish_scope_stop(args, output, review, "scope-review-unresolved-no-gpu", advice)
        return False
    if (output / "PROPOSAL_REVIEW.json").exists() or (output / "CORRECTION_FEEDBACK.json").exists():
        raise ValueError("automatic correction cannot replace an existing review")
    if api_ceiling(output) > 0.8:
        raise ValueError("insufficient remaining API reserve for one correction and re-review")
    write_new(
        marker,
        {
            "review": str(review.relative_to(output)),
            "proposal_receipt_sha256": receipt_sha,
            "max_corrections": 1,
        },
    )
    write_new(
        output / "PROPOSAL_REVIEW.json",
        {
            "reviewer": "model-node",
            "review_result_sha256": _sha256(review / "NODE_RESULT.json"),
            "required_correction": advice["findings"],
            "rejected_candidate": json.loads((proposal / "PATCH_PROPOSAL.json").read_text()),
            "instruction": (
                "Correct only these implementation deviations; retain the original hypothesis."
            ),
            "formal_evidence_eligible": False,
        },
    )
    proposal.rename(output / "proposal-scope-rejected-001")
    main()  # Resume the same recorded decision; no new hypothesis or GPU launch.
    return False


def adjudicate_scope(args, output: Path, review: Path, initial: dict) -> bool:
    profile_path = getattr(args, "scope_adjudication_profile", None)
    if profile_path is None:
        return False
    # A second opinion cannot replace deterministic scientific-control admission.
    if (
        not getattr(args, "edit_boundary", None)
        or not (output / "proposal/EDIT_BOUNDARY.json").exists()
    ):
        return False
    config = load_structured_openai_compatible_config(args.scope_adjudication_backend)
    if (config.provider, config.model) == (
        initial["response"]["backend"],
        initial["response"]["model"],
    ):
        raise ValueError("scope adjudication requires a distinct configured model identity")
    profile = load_model_node_profile(profile_path)
    adjudication = output / "scope-adjudications" / _sha256(review / "NODE_RESULT.json")
    record = adjudication / "NODE_RESULT.json"
    if not record.exists():
        if api_ceiling(output) + profile.admission.max_response_cost_usd > 1.8:
            return False
        completed = subprocess.run(
            [
                sys.executable,
                "scripts/review_benchmark_patch_scope.py",
                "--proposal",
                str(output / "proposal"),
                "--output",
                str(adjudication),
                "--backend",
                str(args.scope_adjudication_backend),
                "--profile",
                str(profile_path),
                "--adjudicate-review",
                str(review / "NODE_RESULT.json"),
                "--credentials",
                str(args.credentials),
                "--project-id",
                args.project.name,
                "--allow-api",
            ],
            env={
                key: value
                for key, value in os.environ.items()
                if key.lower() not in {"http_proxy", "https_proxy", "all_proxy"}
            },
            capture_output=True,
            text=True,
        )
        if completed.returncode:
            write_new(
                adjudication / "PROCESS_FAILURE.json",
                {
                    "returncode": completed.returncode,
                    "stderr": completed.stderr[-4000:],
                    "no_execution_authorized": True,
                },
            )
            return False
    result = json.loads(record.read_text())
    return (
        result["status"] == "accepted"
        and result.get("proposal", {}).get("disposition") == "aligned"
    )


def finish_scope_stop(args, output: Path, review: Path, status: str, detail: dict) -> None:
    summary = {
        "status": status,
        "experiment_executed": False,
        "candidate_score": None,
        "preparation_admitted": (output / "proposal/PREPARATION_RECEIPT.json").exists(),
        "review": str(review.relative_to(output)),
        "adjudication_results": [
            str(path.relative_to(output))
            for path in sorted(output.glob("scope-adjudications/*/NODE_RESULT.json"))
        ],
        "review_detail": detail,
        "automatic_correction_attempts": int((output / "AUTOMATIC_CORRECTION.json").exists()),
        "formal_evidence_eligible": False,
        "whole_idea_to_paper_loop": False,
        "api_cost_ceiling_usd": api_ceiling(output),
    }
    write_new(output / "RESULT.json", summary)
    register_progress(args.project.resolve(strict=True), output, status)
    print(json.dumps(summary, indent=2))


def recover_preparation_failure(args, project: Path, output: Path, failure: dict) -> None:
    """Compiler/boundary feedback shares the same one-correction allowance."""
    proposal = output / "proposal"
    marker = output / "AUTOMATIC_CORRECTION.json"
    if args.scope_review_profile and not marker.exists() and api_ceiling(output) <= 0.8:
        candidate = proposal / "PATCH_PROPOSAL.json"
        node = proposal / "NODE_RESULT.json"
        if candidate.exists():
            rejected = json.loads(candidate.read_text())
        elif node.exists():
            rejected = json.loads(node.read_text())["response"]["output_payload"]
        else:
            rejected = None
        # A connection failure is not a code defect: do not auto-retry unknown calls.
        if rejected is not None:
            if (output / "PROPOSAL_REVIEW.json").exists():
                raise ValueError("cannot replace an existing preparation review")
            write_new(
                marker,
                {
                    "reason": "deterministic-preparation-rejection",
                    "failure": failure,
                    "max_corrections": 1,
                },
            )
            write_new(
                output / "PROPOSAL_REVIEW.json",
                {
                    "reviewer": "deterministic-code-admission",
                    "required_correction": failure,
                    "rejected_candidate": rejected,
                    "instruction": "Correct only the reported admission failure under the original "
                    "directive and immutable code boundary; preserve the selected hypothesis.",
                    "formal_evidence_eligible": False,
                },
            )
            proposal.rename(output / "proposal-admission-rejected-001")
            main()
            return
    summary = {
        "status": "preparation-failed-no-gpu",
        "failure": failure,
        "formal_evidence_eligible": False,
        "experiment_executed": False,
        "candidate_score": None,
        "api_cost_ceiling_usd": api_ceiling(output),
        "automatic_correction_attempts": int(marker.exists()),
        "whole_idea_to_paper_loop": False,
    }
    write_new(output / "RESULT.json", summary)
    register_progress(project, output, summary["status"])
    print(json.dumps(summary, indent=2))


def execute_and_review(
    *, args, project, output, base, contract_path, state, decision, controller, prior
):
    if api_ceiling(output) > 1.8:
        raise ValueError("insufficient API ceiling for post-experiment decision")
    proposal = output / "proposal"
    provenance = output / "CANDIDATE_PROVENANCE.json"
    if not provenance.exists():
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        write_new(
            provenance,
            {
                "system_id": "scitaste-native-base-development-loop",
                "system_revision": revision + "+recorded-worktree-sources",
                "trajectory_sha256": content_sha256(
                    {
                        "decision": _sha256(output / "DECISION.json"),
                        "proposal": _sha256(proposal / "PREPARATION_RECEIPT.json"),
                        "implementation_review": (
                            _sha256(output / "PROPOSAL_REVIEW.json")
                            if (output / "PROPOSAL_REVIEW.json").exists()
                            else None
                        ),
                        "scope_review_results": {
                            str(path.relative_to(output)): _sha256(path)
                            for path in sorted(output.glob("scope-reviews/*/NODE_RESULT.json"))
                        },
                        "scope_adjudication_results": {
                            str(path.relative_to(output)): _sha256(path)
                            for path in sorted(
                                output.glob("scope-adjudications/*/NODE_RESULT.json")
                            )
                        },
                        "scope": "pre-execution trajectory only",
                    }
                ),
                "budget_contract_sha256": _sha256(contract_path),
                "source_files": {
                    path: _sha256(Path(path))
                    for path in (
                        "src/scitaste/taste/controller.py",
                        "src/scitaste/backends/openai_compatible.py",
                        "src/scitaste/backends/replay.py",
                        "src/scitaste/evaluation/patch_scope_review.py",
                        "src/scitaste/evaluation/python_edit_boundary.py",
                        "scripts/review_benchmark_patch_scope.py",
                        "src/scitaste/executor/native.py",
                        "src/scitaste/executor/remote_mlrc.py",
                        "scripts/mlrc_meta_visual_fork_runtime.py",
                        "scripts/prepare_mlrc_perception_research_arm.py",
                        str(Path(__file__)),
                    )
                },
                "formal_evidence_eligible": False,
                "taste_augmented": False,
            },
        )
    bundle = output / "bundle"
    if not bundle.exists():
        package_candidate(
            base_bundle=base,
            method_source=proposal / "arm_source",
            provenance=provenance,
            output_root=bundle,
        )
    remote_base = "/data/zfx/scitaste/mlrc-meta-dev-20260925"
    remote_root = remote_base + "/native-loops/" + output.name
    binding = RemoteMLRCBinding(
        candidate_id=output.name,
        host="4090-2",
        python=remote_base + "/venv/bin/python",
        bundle=remote_root + "/bundle",
        bundle_manifest_sha256=_sha256(bundle / "MANIFEST.json"),
        data_root=remote_base + "/mlrc-meta-learning-development-v1/data",
        output_root=remote_root + "/experiment",
        gpu_index=3,
    )
    binding_path = output / "BINDING.json"
    if binding_path.exists():
        if json.loads(binding_path.read_text()) != asdict(binding):
            raise ValueError("remote binding changed during resume")
    else:
        write_new(binding_path, asdict(binding))
    ssh_env = {
        "SCITASTE_ASKPASS_CREDENTIAL_FILE": str(args.credentials.resolve(strict=True)),
        "SCITASTE_ASKPASS_CREDENTIAL_NAME": "SCITASTE_GPU_4090_2_SSH_PASSWORD",
        "SSH_ASKPASS": str(Path("scripts/ssh_askpass_resource_registry.py").resolve()),
        "SSH_ASKPASS_REQUIRE": "force",
        "DISPLAY": ":0",
    }
    env = {**os.environ, **ssh_env}
    deployment = output / "DEPLOYED.json"
    if not deployment.exists():
        subprocess.run(
            [
                "ssh",
                "-T",
                "-o",
                "ClearAllForwardings=yes",
                binding.host,
                "mkdir -p " + shlex.quote(remote_root),
            ],
            env=env,
            start_new_session=True,
            check=True,
            timeout=30,
        )
        subprocess.run(
            [
                "rsync",
                "-rt",
                "-e",
                "ssh -T -o ClearAllForwardings=yes",
                str(bundle),
                f"{binding.host}:{remote_root}/",
            ],
            env=env,
            start_new_session=True,
            check=True,
            timeout=120,
        )
        write_new(deployment, {"binding_sha256": content_sha256(asdict(binding))})
    handler = RemoteMLRCActionHandler(
        project_id=project.name,
        binding=binding,
        workspace=output / "remote",
        artifact_root=project,
        ssh_environment=ssh_env,
        allow_launch=True,
    )
    executor = SciTasteNativeExecutor(
        handlers={MetaAction.EXPERIMENT: handler},
        workspace=output / "native",
        artifact_root=project,
        recover_completed_experiment=True,
    )
    state.decision_history.append(decision)
    state.resource_usage.api_cost_usd = api_ceiling(output)
    store = StateStore(output / "state")
    store.save(state)
    register_progress(project, output, "execution-requested")
    result = executor.execute(state, decision.selected_action)
    if result.status == ExecutionStatus.PLANNED:
        register_progress(project, output, "execution-unresolved")
        print(result.model_dump_json(indent=2))
        return  # Resume observes this action; it does not start a second attempt.
    execution_path = output / "EXECUTION_RESULT.json"
    if not execution_path.exists():
        write_new(execution_path, result.model_dump(mode="json"))
    state.resource_usage.experiments = 1
    state.resource_usage.gpu_hours = result.cost.get("gpu_hours", 1 / 3)
    state.resource_usage.wall_time_hours = result.cost.get("wall_time_hours", 1 / 3)
    state.revision += 1
    state.observations.append(
        ResearchObservation(
            observation_id="native-loop-experiment",
            source_result_id=result.result_id,
            statement=(
                f"New selected experiment returned {result.status.value}; objective "
                f"{result.data.get('primary_value')}. Baseline is "
                f"{prior['raw_official_scores']['euclidean-prototypes']}. "
                "The experiment budget is exhausted. One development attempt "
                "cannot establish a general benefit or formal scientific claim."
            ),
        )
    )
    store.save(state)
    post_path = output / "POST_DECISION.json"
    if post_path.exists():
        post = ResearchDecision.model_validate_json(post_path.read_text())
    else:
        # Terminal dispositions need no new hypothesis-generation call.
        controller.candidate_generation_backend = None
        post = controller.decide(
            state=state,
            candidate_actions=(
                ResearchAction(
                    action_id="retain-best-and-stop",
                    type=MetaAction.STOP,
                    description=(
                        "Stop and retain the best measured method on this development task; "
                        "do not claim generality."
                    ),
                ),
                ResearchAction(
                    action_id="record-diagnostic-obligation",
                    type=MetaAction.ANALYZE,
                    description=(
                        "Conclude this iteration with a diagnostic obligation supported by "
                        "the result; no further experiment budget."
                    ),
                ),
            ),
        )
        write_new(post_path, post.model_dump(mode="json"))
    state.decision_history.append(post)
    state.resource_usage.api_cost_usd = api_ceiling(output)
    state.revision += 1
    store.save(state)
    summary = {
        "status": "bounded-development-loop-completed",
        "formal_evidence_eligible": False,
        "taste_augmented": False,
        "experiment_status": result.status.value,
        "baseline_score": prior["raw_official_scores"]["euclidean-prototypes"],
        "candidate_score": result.data.get("primary_value"),
        "post_action": post.selected_action.action_id,
        "post_rationale": post.rationale,
        "api_cost_ceiling_usd": api_ceiling(output),
        "whole_idea_to_paper_loop": False,
    }
    execution_contract = json.loads(contract_path.read_text())
    if execution_contract.get("role") == "adopt-reviewed-development-candidate":
        summary.update(
            uninterrupted_autonomous_trajectory=False,
            execution_role=execution_contract["role"],
            source_run=execution_contract["source_run"],
            imported_api_cost_ceiling_usd=execution_contract["imported_api_cost_ceiling_usd"],
            cost_scope=execution_contract["cost_scope"],
        )
    write_new(output / "RESULT.json", summary)
    register_progress(project, output, summary["status"])
    print(json.dumps(summary, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--project", type=Path, default=Path("outputs/projects/scitaste-self-development")
    )
    parser.add_argument(
        "--credentials", type=Path, default=Path("outputs/resources/access/credentials.env")
    )
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--allow-api", action="store_true")
    parser.add_argument("--allow-execution", action="store_true")
    parser.add_argument("--concretize-candidates", action="store_true")
    parser.add_argument("--scope-review-profile", type=Path)
    parser.add_argument("--prior-native-loop", type=Path)
    parser.add_argument("--edit-boundary", type=Path)
    parser.add_argument("--scope-adjudication-profile", type=Path)
    parser.add_argument("--scope-adjudication-backend", type=Path)
    args = parser.parse_args()
    if bool(args.scope_adjudication_profile) != bool(args.scope_adjudication_backend):
        raise ValueError("adjudication requires both a profile and a backend configuration")
    if not args.allow_api:
        raise ValueError("live development controller requires --allow-api")
    project = args.project.resolve(strict=True)
    output = args.output.resolve()
    output.relative_to(project)
    output.mkdir(parents=True, exist_ok=True)
    evaluations = project / "evaluations"
    base = evaluations / "scitastebench-mlrc-meta-visual-fork-remote-bundle-v4"
    decision_bundle = evaluations / "scitastebench-mlrc-meta-visual-fork-remote-bundle-v3"
    decisions = evaluations / "scitastebench-mlrc-meta-pre-experiment-decision-v1"
    pair = evaluations / "scitastebench-mlrc-meta-remote-4090-pair-v1"
    prior = score(decisions, decision_bundle, base, pair, None)
    previous_feedback = (
        prior_iteration_feedback(project, args.prior_native_loop)
        if args.prior_native_loop
        else None
    )
    candidate_id = output.name
    backend_path = Path("configs/model_nodes/bailian_qwen38max.taste_review_live_20260916.yaml")
    profile_path = Path("configs/model_nodes/profile_bailian_qwen38max_benchmark_patch_v1.yaml")
    backend_config = load_structured_openai_compatible_config(backend_path)
    _bind_credential(args.credentials, backend_config.api_key_env)
    contract = {
        "role": "one-iteration-native-base-development-loop",
        "candidate_id": candidate_id,
        "project_id": project.name,
        "prior_result_sha256": content_sha256(prior),
        "base_bundle_sha256": _sha256(base / "MANIFEST.json"),
        "backend_config_sha256": _sha256(backend_path),
        "profile_sha256": _sha256(profile_path),
        "max_experiments": 1,
        "wall_seconds": 1200,
        "max_api_cost_usd_ceiling": 2.0,
        "formal_evidence_eligible": False,
        "taste_augmented": False,
    }
    contract_path = output / "CONTRACT.json"
    if args.concretize_candidates:
        contract["candidate_concretization"] = True
    if args.scope_review_profile:
        contract["scope_review_profile_sha256"] = _sha256(args.scope_review_profile)
    if args.edit_boundary:
        contract["edit_boundary_sha256"] = _sha256(args.edit_boundary)
    if args.scope_adjudication_profile:
        contract["scope_adjudication_profile_sha256"] = _sha256(args.scope_adjudication_profile)
        contract["scope_adjudication_backend_sha256"] = _sha256(args.scope_adjudication_backend)
    if previous_feedback is not None:
        contract["prior_native_feedback_sha256"] = content_sha256(previous_feedback)
        contract["operationally_explicit_hypotheses"] = True
    if contract_path.exists():
        if json.loads(contract_path.read_text()) != contract:
            raise ValueError("resume inputs differ from the original development contract")
    else:
        write_new(contract_path, contract)
    if (output / "RESULT.json").exists():
        register_progress(
            project, output, json.loads((output / "RESULT.json").read_text())["status"]
        )
        print((output / "RESULT.json").read_text())
        return
    initial_path = output / "INITIAL_STATE.json"
    if not initial_path.exists():
        state = ResearchState(
            project_id=project.name,
            research_direction="Improve autonomous scientific decision making",
            target_domain="cross-domain few-shot classification development",
            target_venue="CVPR 2027",
            current_stage=ResearchStage.EVIDENCE,
            resource_budget=ResourceBudget(
                max_experiments=1, gpu_hours=1 / 3, max_wall_time_hours=1.0, max_api_cost_usd=2.0
            ),
            observations=[
                ResearchObservation(
                    observation_id="actual-prior-fork",
                    reproducible=True,
                    statement=(
                        f"Measured official development scores: {prior['raw_official_scores']}. "
                        "Same 4090, seed and training schedule; one source task. Normalization "
                        "was adverse; a cosine-temperature variant is unexecuted and not selected. "
                        "No causal attribution beyond this development task; no Taste-effect claim."
                    ),
                )
            ],
        )
        if previous_feedback is not None:
            state.observations.append(
                ResearchObservation(
                    observation_id="prior-native-measured-outcome",
                    reproducible=True,
                    statement=json.dumps(previous_feedback, sort_keys=True),
                )
            )
            write_new(output / "PRIOR_NATIVE_EVIDENCE.json", previous_feedback)
        if args.edit_boundary:
            state.observations.append(
                ResearchObservation(
                    observation_id="caller-owned-code-scope",
                    statement="Only inference changes are available under this fixed boundary: "
                    + args.edit_boundary.read_text()
                    + ". All other Python structure stays fixed.",
                )
            )
        write_new(initial_path, state.model_dump(mode="json"))
    state = ResearchState.model_validate_json(initial_path.read_text())
    controller = TasteController(
        utility_enabled=False,
        critics_enabled=False,
        preference_backend=ResumableRecordingBackend(
            OpenAICompatibleBackend(
                OpenAICompatibleConfig(
                    provider=backend_config.provider,
                    model=backend_config.model,
                    base_url=backend_config.base_url,
                    api_key_env=backend_config.api_key_env,
                    timeout_seconds=180,
                    max_retries=0,
                    extra_body={**backend_config.extra_body, "max_tokens": 2048},
                ),
                transport=RecordedTransport(output / "provider.jsonl"),
            ),
            output / "controller.jsonl",
        ),
        expected_preference_backend=backend_config.provider,
        expected_preference_model=backend_config.model,
    )
    if args.concretize_candidates:
        controller.candidate_generation_backend = controller.preference_backend
        controller.expected_candidate_generation_backend = backend_config.provider
        controller.expected_candidate_generation_model = backend_config.model
    decision_path = output / "DECISION.json"
    if decision_path.exists():
        decision = ResearchDecision.model_validate_json(decision_path.read_text())
    else:
        decision = controller.decide(
            state=state,
            candidate_actions=initial_actions(
                candidate_id, operationally_explicit=previous_feedback is not None
            ),
        )
        write_new(decision_path, decision.model_dump(mode="json"))
    if decision.selected_action.type == MetaAction.STOP:
        write_new(
            output / "RESULT.json",
            {
                "status": "controller-stopped-before-experiment",
                "formal_evidence_eligible": False,
                "decision": decision.model_dump(mode="json"),
            },
        )
        print("Controller selected STOP; no GPU work.")
        register_progress(project, output, "controller-stopped-before-experiment")
        return
    directive_path = output / "DIRECTIVE.json"
    if not directive_path.exists():
        directive = BenchmarkResearchActionDirective.create(
            action_id=decision.selected_action.action_id,
            action_type="EXPERIMENT",
            instruction=decision.selected_action.description,
        )
        write_new(directive_path, directive.model_dump(mode="json"))
    proposal = output / "proposal"
    if not (proposal / "PREPARATION_RECEIPT.json").exists():
        if proposal.exists():
            admission_failure = proposal / "ADMISSION_FAILURE.json"
            if admission_failure.is_file():
                recover_preparation_failure(
                    args, project, output, json.loads(admission_failure.read_text())
                )
                return
            raise RuntimeError(
                "a prior proposal attempt is incomplete; retain it, do not re-call automatically"
            )
        feedback_path = pair / "DECISION_RESULT.json"
        if previous_feedback is not None:
            feedback_path = output / "EXPERIMENT_HISTORY.json"
            if not feedback_path.exists():
                write_new(
                    feedback_path,
                    {
                        "initial_fork": json.loads((pair / "DECISION_RESULT.json").read_text()),
                        "prior_native_iteration": previous_feedback,
                    },
                )
        review_path = output / "PROPOSAL_REVIEW.json"
        if review_path.exists():
            feedback_path = output / "CORRECTION_FEEDBACK.json"
            if not feedback_path.exists():
                write_new(
                    feedback_path,
                    {
                        "observed_prior_result": json.loads(
                            (
                                output / "EXPERIMENT_HISTORY.json"
                                if previous_feedback
                                else pair / "DECISION_RESULT.json"
                            ).read_text()
                        ),
                        "unexecuted_code_review": json.loads(review_path.read_text()),
                    },
                )
        completed = subprocess.run(
            [
                sys.executable,
                "scripts/prepare_mlrc_perception_research_arm.py",
                "--task",
                "meta-learning",
                "--condition",
                "native-base",
                "--editable-env",
                str(base / "branches/euclidean-prototypes"),
                "--baseline-score",
                str(prior["raw_official_scores"]["euclidean-prototypes"]),
                "--experiment-feedback-file",
                str(feedback_path),
                "--research-action-directive",
                str(directive_path),
                "--backend",
                str(backend_path),
                "--profile",
                str(profile_path),
                "--output",
                str(proposal),
                "--allow-api",
            ]
            + (["--edit-boundary", str(args.edit_boundary)] if args.edit_boundary else []),
            # Match RecordedTransport's direct connection policy for this child.
            env={
                key: value
                for key, value in os.environ.items()
                if key.lower() not in {"http_proxy", "https_proxy", "all_proxy"}
            },
            capture_output=True,
            text=True,
        )
        write_new(
            proposal / "PROCESS_RESULT.json",
            {
                "returncode": completed.returncode,
                "stdout": completed.stdout[-65536:],
                "stderr": completed.stderr[-65536:],
            },
        )
        if completed.returncode:
            failure_path = proposal / "ADMISSION_FAILURE.json"
            failure = (
                json.loads(failure_path.read_text())
                if failure_path.exists()
                else {
                    "stage": "proposal-preparation",
                    "reason": completed.stderr[-4000:],
                    "returncode": completed.returncode,
                }
            )
            recover_preparation_failure(args, project, output, failure)
            return
        print(completed.stdout)
    if args.scope_review_profile and not review_scope(args, output, backend_path):
        return
    if args.prepare_only or not args.allow_execution:
        register_progress(project, output, "proposal-prepared-no-execution")
        print(json.dumps({"status": "prepared", "proposal": str(proposal), "no_gpu_started": True}))
        return
    execute_and_review(
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


if __name__ == "__main__":
    main()
