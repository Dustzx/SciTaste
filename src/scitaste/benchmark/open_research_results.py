"""Failure-inclusive collection and source-rubric session grading of actual runs."""

import hashlib
import json
from pathlib import Path

from scitaste.benchmark.open_research import digest, verified_asset
from scitaste.model_nodes.models import StructuredModelRequest
from scitaste.model_nodes.session_exchange import (
    SessionStructuredBackend,
    load_retained_request,
    retain_json,
)

DIMENSIONS = ("Clarity", "Novelty", "Soundness", "Significance", "Overall")


def merge_sealed_assessment(root, observed, assessed, bindings):
    """Keep live closure and old grades separate unless exact paper bytes match."""
    by_arm = {row["arm"]: row for row in assessed["rows"]}
    hashes = {row["arm"]: row["paper_sha256"] for row in bindings}
    for row in observed["rows"]:
        previous = by_arm[row["arm"]]
        if not all(value is not None for value in previous["scores"].values()):
            continue
        paper = (root / row["paper"]).resolve(strict=True) if row.get("paper") else None
        if paper is not None:
            paper.relative_to(root)
        if (
            paper is not None
            and row["paper"] == previous.get("paper")
            and hashes.get(row["arm"]) == digest(paper)
        ):
            for key in (
                "scores",
                "assessment_request_fingerprint",
                "task_claims",
                "task_claim_judge_calibrated",
            ):
                if key in previous:
                    row[key] = previous[key]
        else:
            row["historical_assessment"] = {
                "paper": previous.get("paper"),
                "paper_sha256": hashes.get(row["arm"]),
                "scores": previous["scores"],
                "request_fingerprint": previous.get("assessment_request_fingerprint"),
                "scope": "sealed earlier manuscript; not the current paper's grade",
            }
    return observed


def _read(path):
    return json.loads(path.read_text()) if path.is_file() else None


def _native_project_delivery(root, lifecycle, run, launch, delivery):
    """Recognize the real project coordinator without conflating paper and project closure."""
    binding = _read(lifecycle / "CONTRACT.json")
    if (
        not binding
        or binding.get("scope") != "native-workspace-project-cycle"
        or binding.get("project") != root.name
        or binding.get("execution") != run.relative_to(root).as_posix()
        or binding.get("plan_sha256") != launch.get("plan_sha256")
        or delivery.get("contract_sha256") != digest(lifecycle / "CONTRACT.json")
        or delivery.get("execution_result_sha256") != digest(run / "RESULT.json")
    ):
        raise ValueError("Project delivery does not bind assigned Native execution")
    plan = (root / binding["plan"]).resolve(strict=True)
    plan.relative_to(root)
    if digest(plan) != binding["plan_sha256"]:
        raise ValueError("Project delivery plan changed")
    report = (root / binding["delivery"] / "RESULT.json").resolve(strict=True)
    report.relative_to(root)
    cycle = (
        root / binding["paper_flow"]
        if binding.get("paper_flow")
        else root / "evaluations" / (binding["paper_prefix"] + "-cycle")
    ).resolve(strict=True)
    cycle.relative_to(root / "evaluations")
    if delivery.get("delivery_result_sha256") != digest(report) or delivery.get(
        "paper_summary_sha256"
    ) != digest(cycle / "SUMMARY.json"):
        raise ValueError("Project paper delivery sources changed")
    expected_paper = binding["paper_prefix"] + "-revised"
    if delivery.get("paper_directory") != expected_paper:
        raise ValueError("Project delivery paper identity mismatch")
    revised = (root / "papers" / expected_paper / "main.md").resolve(strict=True)
    revised.relative_to(root / "papers")
    workflow = _read(lifecycle / "WORKFLOW_STATUS_CURRENT.json")
    terminal = bool(workflow and workflow.get("paper_cycle_delivered"))
    exchange = (lifecycle / "exchange").resolve()
    if binding.get("session_exchange"):
        exchange = Path(binding["session_exchange"]).resolve()
    exchange.relative_to(lifecycle)
    return {
        "terminal": terminal,
        "status": workflow["status"] if terminal else "paper-delivered-project-closure-pending",
        "paper": revised.relative_to(root).as_posix(),
        "paper_cycle_complete": True,
        # A delivered segment explicitly does not certify the entire recursive project.
        "lifecycle_complete": bool(terminal and workflow.get("whole_project_lifecycle_complete")),
        "project_segment_delivered": terminal,
        "lifecycle_scope": "Assigned research-to-revised-paper segment; recursive project separate",
        "whole_project_lifecycle_complete": bool(
            terminal and workflow.get("whole_project_lifecycle_complete")
        ),
        "elapsed_seconds": max(
            0, (lifecycle / "RESULT.json").stat().st_mtime - (run / "CONTRACT.json").stat().st_mtime
        ),
        "elapsed_basis": "retained delivery timestamp minus research launch timestamp",
        "additional_model_responses": len(list(exchange.rglob("*.response.json"))),
    }


def _inherited_arc_confirmation(root, run, launch, owned, inherited_run):
    continuation = launch.get("continuation") or {}
    recovery = continuation.get("feedback_transport_recovery") or {}
    ancestor = (root / inherited_run).resolve(strict=True)
    ancestor.relative_to(root / "evaluations")
    if (
        ancestor != Path(continuation.get("previous_package", "")).resolve()
        or not recovery.get("original_clock_inherited")
        or recovery.get("scientific_source_repair_permitted", True)
        or recovery.get("confirmation_reexecution_permitted", True)
        or verified_asset(root, recovery["original_feedback"]) != owned / "RESULT.json"
        or continuation["previous_contract_sha256"] != digest(ancestor / "EXECUTION_CONTRACT.json")
        or continuation["previous_close_sha256"] != digest(ancestor / "SESSION_CLOSED.json")
    ):
        raise ValueError("Unbound inherited ARC confirmation")
    return ancestor


def observe(project, campaign, assignments):
    """Do not select only successful systems or infer papers from stage counts."""
    root = project.resolve(strict=True)
    contract = json.loads(campaign.read_text())
    if set(assignments) != set(contract["arms"]):
        raise ValueError("Every frozen arm must remain in the comparison")
    rows = []
    for arm in contract["arms"]:
        assignment = assignments[arm]
        manuscript_endpoint = (
            assignment.get("manuscript_endpoint", "native-terminal")
            if isinstance(assignment, dict)
            else "native-terminal"
        )
        if manuscript_endpoint not in {"native-terminal", "first-complete-paper"}:
            raise ValueError("Unknown manuscript assessment endpoint")
        run = (root / (assignment["run"] if isinstance(assignment, dict) else assignment)).resolve()
        run.relative_to(root / "evaluations")
        row = {
            "arm": arm,
            "run": run.relative_to(root).as_posix(),
            "status": "not-started",
            "terminal": False,
            "paper": None,
            "manuscript_timepoint": "unavailable",
            "requested_manuscript_endpoint": manuscript_endpoint,
            "scores": {name: None for name in DIMENSIONS},
            "actual_tokens": None,
            "actual_cost_usd": None,
        }
        if arm == "autoresearchclaw":
            launch = _read(run / "EXECUTION_CONTRACT.json")
            close = _read(run / "SESSION_CLOSED.json")
            native = _read(run / "work/NATIVE_RESULTS.json")
            if launch:
                binding = launch.get("benchmark_campaign")
                if binding is None or verified_asset(root, binding) != campaign.resolve():
                    raise ValueError("External run is not bound to this campaign")
                row.update(
                    status="running-or-awaiting-terminal-receipt",
                    retained_model_responses=sum(
                        _read(p).get("status") == "completed"
                        for p in (run / "exchange").glob("*.receipt.json")
                    ),
                )
            if close:
                complete = bool(
                    close["return_code"] == 0 and native and native["all_native_stages_done"]
                )
                row.update(
                    terminal=True,
                    status="completed-unscored" if complete else "stopped-incomplete",
                    elapsed_seconds=close["wall_seconds"],
                )
                # Retain an incomplete run's paper too, without promoting completion.
                candidates = (
                    run / "work/upstream_run/stage-23/paper_final_verified.md",
                    run / "work/upstream_run/stage-22/paper_final.md",
                    run / "work/upstream_run/stage-19/paper_revised.md",
                    run / "work/upstream_run/stage-17/paper_draft.md",
                )
                if manuscript_endpoint == "first-complete-paper":
                    candidates = (candidates[-1],)
                for candidate in candidates:
                    if candidate.is_file():
                        if candidate.read_text().startswith("# Paper Draft Blocked\n"):
                            row.setdefault("nonpaper_artifacts", []).append(
                                {
                                    "path": candidate.relative_to(root).as_posix(),
                                    "sha256": digest(candidate),
                                    "kind": "upstream-paper-blocked-failure-marker",
                                }
                            )
                            row["paper_missing_reason"] = "upstream-draft-blocked-no-metrics"
                            continue
                        row["paper"] = candidate.relative_to(root).as_posix()
                        row["manuscript_timepoint"] = {
                            "stage-23": "native-final-verified-paper",
                            "stage-22": "native-final-paper",
                            "stage-19": "native-revised-paper",
                            "stage-17": "native-first-draft",
                        }[candidate.parent.name]
                        break
        elif arm == "scitaste-native":
            launch, close = _read(run / "CONTRACT.json"), _read(run / "RESULT.json")
            if launch:
                binding = launch["plan"].get("campaign")
                if binding is None or verified_asset(root, binding) != campaign.resolve():
                    raise ValueError("Native run is not bound to this campaign")
                row.update(
                    status="running-or-awaiting-terminal-receipt",
                    retained_model_responses=sum(
                        len(list((run / directory).glob("*.response.json")))
                        for directory in ("exchange", "session-exchange")
                    )
                    + (launch.get("continuation") or {}).get("inherited_session_requests", 0),
                )
                if launch.get("continuation"):
                    row.update(
                        engineering_recovery=True,
                        replaces_original_run_score=False,
                        inherited_duration_seconds=launch["continuation"].get(
                            "inherited_duration_seconds", 0
                        ),
                    )
            if close:
                row.update(
                    terminal=True,
                    status=close["status"],
                    elapsed_seconds=close["duration_seconds"]
                    + row.get("inherited_duration_seconds", 0),
                    # Native research termination is not whole lifecycle completion.
                    lifecycle_complete=close.get("whole_project_lifecycle_complete", False),
                )
                paper = run / "workspace/report/report.md"
                if paper.is_file():
                    row["paper"] = paper.relative_to(root).as_posix()
                    row["manuscript_timepoint"] = "research-report-before-paper-cycle"
                if isinstance(assignment, dict) and assignment.get("lifecycle"):
                    lifecycle = (root / assignment["lifecycle"]).resolve()
                    lifecycle.relative_to(root / "evaluations")
                    delivery = _read(lifecycle / "RESULT.json")
                    resumed = _read(lifecycle / "RESUMED_RESULT.json")
                    recovery_attempts = sorted((lifecycle / "resumes").glob("*.result.json"))
                    recovery_logs = sorted((lifecycle / "resumes").glob("*.log"))
                    pending_recovery = bool(
                        recovery_logs and not recovery_logs[-1].with_suffix(".result.json").exists()
                    )
                    if recovery_attempts and manuscript_endpoint != "first-complete-paper":
                        resumed = _read(recovery_attempts[-1])
                    if resumed and manuscript_endpoint != "first-complete-paper":
                        if not delivery or resumed["original_failure_sha256"] != digest(
                            lifecycle / "RESULT.json"
                        ):
                            raise ValueError("Lifecycle recovery does not bind original failure")
                        row["original_lifecycle"] = {
                            "result": (lifecycle / "RESULT.json").relative_to(root).as_posix(),
                            "sha256": digest(lifecycle / "RESULT.json"),
                            "status": delivery["status"],
                            "elapsed_seconds": delivery.get(
                                "elapsed_seconds_since_research_launch"
                            ),
                        }
                        delivery = resumed
                        row.update(engineering_recovery=True, replaces_original_run_score=False)
                    if delivery is None:
                        row.update(terminal=False, status="research-closed-paper-cycle-pending")
                    elif delivery.get("status") == "native-workspace-cycle-delivered":
                        observed_delivery = _native_project_delivery(
                            root, lifecycle, run, launch, delivery
                        )
                        additional = observed_delivery.pop("additional_model_responses")
                        row.update(observed_delivery)
                        row["manuscript_timepoint"] = "post-review-revised-paper"
                        row["retained_model_responses"] += additional
                    else:
                        binding = _read(lifecycle / "CONTRACT.json")
                        if (
                            not binding
                            or binding["campaign_sha256"] != digest(campaign)
                            or binding["source_contract_sha256"] != digest(run / "CONTRACT.json")
                            or delivery["source_run"] != row["run"]
                        ):
                            raise ValueError("Paper cycle does not belong to assigned research run")
                        row.update(
                            status=delivery["status"],
                            lifecycle_complete=delivery["status"] == "paper-cycle-completed",
                            paper_cycle_complete=delivery["status"] == "paper-cycle-completed",
                            lifecycle_scope=(
                                "Assigned research-to-revised-paper segment; "
                                "recursive project separate"
                            ),
                            elapsed_seconds=delivery["elapsed_seconds_since_research_launch"],
                            retained_model_responses=delivery.get(
                                "observed_requests",
                                row["retained_model_responses"]
                                + len(list((lifecycle / "exchange").rglob("*.response.json"))),
                            ),
                        )
                        if row["lifecycle_complete"]:
                            revised = (
                                root / "papers" / (delivery["paper_prefix"] + "-revised/main.md")
                            )
                            revised.resolve(strict=True).relative_to(root / "papers")
                            row["paper"] = revised.relative_to(root).as_posix()
                            row["manuscript_timepoint"] = "post-review-revised-paper"
                    if manuscript_endpoint == "first-complete-paper":
                        binding = _read(lifecycle / "CONTRACT.json")
                        if binding and binding.get("paper_prefix"):
                            initial = root / "papers" / binding["paper_prefix"] / "main.md"
                            if initial.is_file():
                                initial.resolve(strict=True).relative_to(root / "papers")
                                imported = _read(initial.parent / "REPORT_IMPORT.json")
                                if not imported or imported.get("task_result_sha256") != digest(
                                    lifecycle / "delivery/RESULT.json"
                                ):
                                    raise ValueError(
                                        "First paper does not bind original report delivery"
                                    )
                                row["paper"] = initial.relative_to(root).as_posix()
                                row["manuscript_timepoint"] = "first-complete-paper"
                    if pending_recovery and manuscript_endpoint != "first-complete-paper":
                        row.update(
                            terminal=False,
                            status="paper-recovery-awaiting-terminal-receipt",
                            original_lifecycle_status=(delivery or {}).get("status"),
                        )
        elif arm == "mlr-agent":
            launch, close = _read(run / "CONTRACT.json"), _read(run / "RESULT.json")
            if launch:
                brief = verified_asset(root, contract["execution_brief"])
                public_assets = contract.get("researcher_assets", {})
                if contract.get("benchmark") == "SciTasteBench" and not public_assets:
                    raise ValueError("Authored SciTasteBench requires its frozen public assets")
                expected_assets = {
                    name: digest(verified_asset(root, binding))
                    for name, binding in public_assets.items()
                }
                if public_assets:
                    public_directory = verified_asset(
                        root, next(iter(public_assets.values()))
                    ).parent
                    public_release = public_directory / "RELEASE.json"
                    if public_release.is_file() and not public_release.is_symlink():
                        expected_assets["RELEASE.json"] = digest(public_release)
                if (
                    launch.get("framework") != arm
                    or launch.get("source_commit") != "f728d571a992d71c8b526eeb4d9ab6bb5c8cc824"
                    or not launch.get("source_tree_clean")
                    or not launch.get("coding_cli_is_real")
                    or launch.get("task_sha256") != digest(brief)
                    or launch.get("public_assets") != expected_assets
                ):
                    raise ValueError("MLR-Agent run is not bound to the frozen task and source")
                row.update(
                    status="running-or-awaiting-terminal-receipt",
                    retained_model_responses=sum(
                        _read(path).get("status") == "completed"
                        for path in (run / "exchange").glob("*.receipt.json")
                    ),
                    native_review_revision_available=False,
                    comparison_scope=contract.get("comparison_scope"),
                    inherited_duration_seconds=launch.get("inherited_wall_seconds", 0),
                    engineering_recovery=bool(launch.get("inherited_wall_seconds", 0)),
                    replaces_original_run_score=False,
                )
            if close:
                if launch is None:
                    raise ValueError("MLR-Agent terminal receipt has no launch contract")
                paper = run / "workspace/results/paper.md"
                finished = _read(run / "workspace/UPSTREAM_FINISHED.json")
                complete = bool(
                    close.get("exit_code") == 0
                    and finished
                    and finished.get("native_pipeline_returned")
                    and paper.is_file()
                )
                row.update(
                    terminal=True,
                    status="completed-unscored" if complete else "stopped-incomplete",
                    lifecycle_complete=complete,
                    lifecycle_scope="Native idea-to-paper; no upstream review/revision",
                    elapsed_seconds=close["wall_seconds"]
                    + row.get("inherited_duration_seconds", 0),
                    stop_reason=close.get("stop_reason"),
                )
                if paper.is_file():
                    row["paper"] = paper.relative_to(root).as_posix()
                    row["manuscript_timepoint"] = "first-native-complete-paper"
        else:
            raise ValueError("Unknown real-framework collection route")
        if contract.get("pack") and contract.get("researcher_assets"):
            from scitaste.benchmark.confirmation_binding import confirmation_directory

            owned = confirmation_directory(root, campaign, arm, assignment)
            feedback = _read(owned / "RESULT.json")
            recovered_confirmation = _read(owned / "RECOVERED_RESULT.json")
            if recovered_confirmation is not None:
                if feedback is None or recovered_confirmation["original_failure_sha256"] != digest(
                    owned / "RESULT.json"
                ):
                    raise ValueError("Confirmation recovery does not retain original failure")
                feedback = recovered_confirmation
            execution = _read(owned / "EXECUTION_CONTRACT.json")
            row["confirmation"] = None
            if feedback is not None:
                if feedback["arm"] != arm:
                    raise ValueError("Confirmation belongs to a different arm")
                executed = feedback.get("executed_frozen_source", False)
                execution_hash = feedback.get("execution_contract_sha256")
                failed_inference = None
                if executed and execution_hash is None and feedback["status"] == "failed":
                    # A post-inference collection failure is not successful
                    # confirmation. Its real pre-score process receipt may still
                    # prove source execution without rewriting the failed result.
                    failed_inference = _read(owned / "INFERENCE_RESULT.json")
                    if (
                        not execution
                        or not failed_inference
                        or failed_inference.get("return_code") != 0
                        or not failed_inference.get("before_private_scoring")
                        or failed_inference.get("execution_contract_sha256")
                        != digest(owned / "EXECUTION_CONTRACT.json")
                        or failed_inference.get("release_sha256")
                        != digest(owned / "release/RELEASE.json")
                    ):
                        raise ValueError("Reported failed-arm inference lacks its process binding")
                    execution_hash = failed_inference["execution_contract_sha256"]
                if executed and (
                    not execution
                    or execution["campaign_sha256"] != digest(campaign)
                    or execution_hash != digest(owned / "EXECUTION_CONTRACT.json")
                ):
                    raise ValueError("Confirmation execution is not bound to campaign")
                explicit_confirmation = isinstance(assignment, dict) and assignment.get(
                    "confirmation"
                )
                if executed and (explicit_confirmation or execution.get("source_run")):
                    confirmation_run = run
                    inherited_run = assignment.get("confirmation_source_run")
                    if inherited_run:
                        # A reporting continuation can inherit already executed
                        # source, but must never fabricate a new execution receipt.
                        if (
                            arm not in {"autoresearchclaw", "scitaste-native"}
                            or not explicit_confirmation
                        ):
                            raise ValueError(
                                "Only explicitly bound reporting continuations inherit execution"
                            )
                        if arm == "scitaste-native":
                            from scitaste.benchmark.confirmation_binding import (
                                native_confirmation_source,
                            )

                            confirmation_run = native_confirmation_source(
                                root, campaign, run, assignment
                            )
                            row["confirmation_inherited_from_original_execution"] = {
                                "source_run": inherited_run,
                                "continuation_contract_sha256": digest(run / "CONTRACT.json"),
                                "original_failure_replaced": False,
                                "new_confirmation_execution": False,
                            }
                        else:
                            confirmation_run = _inherited_arc_confirmation(
                                root, run, launch, owned, inherited_run
                            )
                            row["confirmation_inherited_from_original_execution"] = {
                                "source_run": inherited_run,
                                "continuation_contract_sha256": digest(
                                    run / "EXECUTION_CONTRACT.json"
                                ),
                                "original_failure_replaced": False,
                                "new_confirmation_execution": False,
                            }
                    origin = confirmation_run / (
                        "EXECUTION_CONTRACT.json" if arm == "autoresearchclaw" else "CONTRACT.json"
                    )
                    if execution.get("source_run") != confirmation_run.relative_to(
                        root
                    ).as_posix() or execution.get("source_contract_sha256") != digest(origin):
                        raise ValueError("Confirmation belongs to a different research run")
                row["confirmation"] = {
                    "status": feedback["status"],
                    "executed_frozen_source": executed,
                    "elapsed_seconds": feedback["elapsed_seconds"],
                    "metrics": [
                        {
                            key: item[key]
                            for key in (
                                "method",
                                "graph",
                                "context",
                                "training_block",
                                "lineage",
                                "accuracy",
                                "nll",
                                "query_images",
                                "molecule",
                                "modality",
                                "input_capture_count",
                                "fov_count",
                                "mean_fov_psnr_db",
                                "mean_fov_ssim",
                                "mean_fov_mse",
                                "mean_fov_bandpass_mse",
                                "fovs",
                                "endpoint",
                                "partition",
                                "metrics",
                            )
                            if key in item
                        }
                        for item in feedback.get("result", {}).get("scores", [])
                    ],
                    "failure": feedback.get("error"),
                    "engineering_recovery": feedback.get("engineering_recovery", False),
                    "scope": "Frozen-program confirmation, not novelty or paper-quality scoring",
                }
                if feedback.get("inference_result_sha256") or failed_inference is not None:
                    inference_path = owned / "INFERENCE_RESULT.json"
                    inference = _read(inference_path)
                    pre_score_bound = bool(inference and inference.get("before_private_scoring"))
                    if inference and inference.get("pre_score_inference_sha256"):
                        joint_path = owned / "execution/INFERENCE_RESULT.json"
                        joint = _read(joint_path)
                        pre_score_bound = bool(
                            joint
                            and digest(joint_path) == inference["pre_score_inference_sha256"]
                            and joint.get("before_private_scoring")
                            and joint.get("budget_isolation_verified")
                            and joint.get("return_code") == 0
                            and joint.get("release_sha256") == inference["release_sha256"]
                            and joint.get("output_sha256") == inference["output_sha256"]
                        )
                    if (
                        not inference
                        or (
                            feedback.get("inference_result_sha256") is not None
                            and digest(inference_path) != feedback["inference_result_sha256"]
                        )
                        or inference["execution_contract_sha256"]
                        != digest(owned / "EXECUTION_CONTRACT.json")
                        or inference["release_sha256"] != digest(owned / "release/RELEASE.json")
                        or inference["return_code"] != 0
                        or not pre_score_bound
                    ):
                        raise ValueError("Frozen inference receipt binding differs")
                    prediction_root = (owned / "execution/predictions").resolve(strict=True)
                    for name, expected in inference["output_sha256"].items():
                        path = prediction_root / name
                        path.resolve(strict=True).relative_to(prediction_root)
                        if path.is_symlink() or digest(path) != expected:
                            raise ValueError("Frozen inference output changed")
                    row["confirmation"]["inference_receipt"] = inference
                    if failed_inference is not None:
                        row["confirmation"]["execution_evidence_scope"] = (
                            "Actual pre-score inference only; original confirmation remains failed"
                        )
        rows.append(row)
    return {
        "campaign_sha256": digest(campaign),
        "task_id": contract["task_id"],
        "assigned_systems": len(rows),
        "rows": rows,
        "formal_evidence_eligible": False,
        "official_mlrjudge_execution": False,
    }


def prepare_assessment(project, campaign, assignments, output, *, partial_terminal=False):
    """Seal actual terminal submissions; unsubmitted arms retain null scores."""
    root = project.resolve(strict=True)
    status = observe(root, campaign, assignments)
    incomplete = any(not row["terminal"] for row in status["rows"])
    if incomplete and not partial_terminal:
        raise ValueError("Wait for terminal receipts; do not grade changing papers")
    if partial_terminal and not any(row["terminal"] and row["paper"] for row in status["rows"]):
        raise ValueError("No sealed terminal manuscript is available for early assessment")
    output.resolve().relative_to(root)
    output.mkdir(parents=True, exist_ok=False)
    contract = json.loads(campaign.read_text())
    rubric = verified_asset(root, contract["rubric"]).read_text()
    task = verified_asset(root, contract["brief"]).read_text()
    requests = []
    for index, row in enumerate(status["rows"]):
        if not row["terminal"] or row["paper"] is None:
            continue
        paper = (root / row["paper"]).resolve(strict=True)
        paper.relative_to(root)
        run = root / row["run"]
        workspace = run / ("work/upstream_run" if row["arm"] == "autoresearchclaw" else "workspace")
        files, excluded = {}, []
        remaining = 220_000
        for path in sorted(workspace.rglob("*")):
            if path.is_symlink() or not path.is_file() or path == paper:
                continue
            # Do not expose system identities, internal reviews or model prompts.
            graph_measurement = contract.get("benchmark") == "SciTasteBench" and (
                path.name.endswith("--summary.json")
                or path.name in {"RUN.json", "development_table.json", "diagnostics.json"}
            )
            native_result_text = row["arm"] == "mlr-agent" and (
                path.relative_to(workspace).as_posix() == "results/results.md"
            )
            if (
                not graph_measurement
                and not native_result_text
                and path.suffix not in {".py", ".csv"}
                and path.name
                not in {
                    "results.json",
                    "metrics.json",
                    "run-1.json",
                    "refinement_log.json",
                }
            ):
                continue
            path.resolve(strict=True).relative_to(workspace.resolve())
            if path.stat().st_size > min(remaining, 80_000):
                excluded.append(path.relative_to(workspace).as_posix())
                continue
            raw = path.read_text(errors="replace")
            files[path.relative_to(workspace).as_posix()] = raw
            remaining -= len(raw.encode())
        visible = {
            "task": task,
            "paper": paper.read_text(),
            "artifact_text": files,
            "artifact_exclusions": excluded,
            "limits": (
                "Text-rubric session adaptation; figures not visually assessed. "
                "Code text and result files do not alone prove independent reproduction. "
                "Report uncertainty and exclusions; no other systems' results supplied."
            ),
        }
        if row.get("confirmation") is not None:
            visible["independent_confirmation"] = row["confirmation"]
        output_schema = {"type": "object", "required": [*DIMENSIONS, "Confidence"]}
        if contract.get("benchmark") == "SciTasteBench" and contract.get("researcher_assets"):
            protocol = json.loads(
                verified_asset(root, contract["researcher_assets"]["PROTOCOL.json"]).read_text()
            )
            claims = (
                json.loads(verified_asset(root, contract["claim_rubric"]).read_text())["claims"]
                if contract.get("claim_rubric")
                else protocol["claim_rubric"]
            )
            visible["required_scientific_claims"] = claims
            visible["claim_assessment_instructions"] = (
                "In addition to the original paper rubric, return task_claims: exactly one "
                "entry for every required claim_id, with status supported, partial, contradicted, "
                "insufficient or missing, an evidence-grounded reason, and evidence IDs from "
                "allowed_claim_evidence. Locate passages in reason. Missing claims are not "
                "automatically true. No target confirmation receipt means no verified transfer. "
                "These AI judgments are uncalibrated and separate from objective metrics."
            )
            from scitaste.benchmark.confirmation_binding import confirmation_directory

            frozen = (
                confirmation_directory(root, campaign, row["arm"], assignments[row["arm"]])
                / "release/frozen_submission"
            )
            if (frozen / "SUBMISSION.json").is_file():
                visible["frozen_research_contract"] = json.loads(
                    (frozen / "SUBMISSION.json").read_text()
                )
                frozen_text, frozen_exclusions = {}, []
                allowance = 100_000
                for name in visible["frozen_research_contract"]["files"]:
                    path = (frozen / name).resolve(strict=True)
                    path.relative_to(frozen.resolve(strict=True))
                    if path.suffix != ".py" or path.stat().st_size > allowance:
                        frozen_exclusions.append(name)
                        continue
                    frozen_text[name] = path.read_text(errors="replace")
                    allowance -= path.stat().st_size
                visible["confirmation_source"] = frozen_text
                visible["confirmation_source_exclusions"] = frozen_exclusions
            visible["allowed_claim_evidence"] = [
                "paper",
                *files,
                *(["independent_confirmation"] if row.get("confirmation") is not None else []),
                *(["frozen_research_contract"] if "frozen_research_contract" in visible else []),
                *("confirmation_source/" + name for name in visible.get("confirmation_source", {})),
            ]
            output_schema["required"].append("task_claims")
            output_schema["properties"] = {
                "task_claims": {
                    "type": "array",
                    "minItems": len(claims),
                    "maxItems": len(claims),
                    "items": {
                        "type": "object",
                        "required": ["claim_id", "status", "reason", "evidence"],
                        "properties": {
                            "claim_id": {"type": "string"},
                            "status": {
                                "enum": [
                                    "supported",
                                    "partial",
                                    "contradicted",
                                    "insufficient",
                                    "missing",
                                ]
                            },
                            "reason": {"type": "string"},
                            "evidence": {
                                "type": "array",
                                "items": {"enum": visible["allowed_claim_evidence"]},
                            },
                        },
                    },
                }
            }
        snapshot = hashlib.sha256(json.dumps(visible, sort_keys=True).encode()).hexdigest()
        request = StructuredModelRequest(
            request_id=f"submission-{index + 1}",
            node_name="external-benchmark-paper-assessment",
            stage="REVIEW",
            state_snapshot_id=snapshot,
            expected_backend="assistant-session",
            expected_model="session-authored",
            policy_id="mlrbench-original-text-rubric-session-v1",
            policy_fingerprint=hashlib.sha256(rubric.encode()).hexdigest(),
            system_instruction=rubric,
            input_payload=visible,
            output_schema=output_schema,
            prompt_version="mlrbench-pinned-original-rubric-v1",
        )
        retain_json(output / f"submission-{index + 1}.json", request.model_dump(mode="json"))
        requests.append(
            {
                "arm": row["arm"],
                "request": f"submission-{index + 1}.json",
                "paper_sha256": digest(paper),
                "snapshot_sha256": snapshot,
                "blinding": "system label withheld; content/style may reveal implementation",
            }
        )
    retain_json(
        output / "SUBMISSIONS.json",
        {
            "observed": status,
            "assessments": requests,
            **(
                {"partial_terminal_assessment": True, "full_campaign_complete": False}
                if incomplete
                else {}
            ),
        },
    )
    return requests


def _claim_identifier(claim):
    """Normalize existing rubric ID spellings without changing the frozen claim."""
    primary, alias = claim.get("claim_id"), claim.get("id")
    if primary is not None and alias is not None and primary != alias:
        raise ValueError("Conflicting frozen scientific claim identifiers")
    value = primary if primary is not None else alias
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Frozen scientific claim has no valid identifier")
    return value


def score_assessment(output, *, reuse=None):
    """Consume bound reviews, never infer absent benchmark scores."""
    submissions = json.loads((output / "SUBMISSIONS.json").read_text())
    result = submissions["observed"]
    if submissions.get("partial_terminal_assessment"):
        result["partial_terminal_assessment"] = True
        result["full_campaign_complete"] = False
    backend = SessionStructuredBackend(output / "exchange", wait_seconds=0)
    for row in submissions["assessments"]:
        request = load_retained_request(output / row["request"])
        if reuse is not None:
            source = reuse / "exchange" / (request.fingerprint + ".request.json")
            response_path = source.with_name(request.fingerprint + ".response.json")
            if source.is_file() and response_path.is_file():
                if load_retained_request(source) != request:
                    raise ValueError("Reusable assessment input changed")
                previous = SessionStructuredBackend(reuse / "exchange").complete(request)
                if previous.model_dump(mode="json") != json.loads(response_path.read_text()):
                    raise ValueError("Reusable assessment response changed")
                retain_json(
                    backend.directory / (request.fingerprint + ".reply.json"),
                    json.loads(previous.raw_response),
                )
                retain_json(
                    backend.directory / (request.fingerprint + ".reuse.json"),
                    {
                        "source_response": str(response_path.resolve()),
                        "source_sha256": digest(response_path),
                        "new_model_generation": False,
                    },
                )
        response = backend.complete(request)
        payload = response.output_payload
        for name in DIMENSIONS:
            score = payload.get(name, {}).get("score")
            if type(score) not in (int, float) or not 1 <= score <= 10:
                raise ValueError("MLR rubric score must be a number between 1 and 10")
        if type(payload.get("Confidence")) is not int or not 1 <= payload["Confidence"] <= 5:
            raise ValueError("MLR review confidence must be an integer between 1 and 5")
        target = next(item for item in result["rows"] if item["arm"] == row["arm"])
        if "required_scientific_claims" in request.input_payload:
            claims = payload.get("task_claims", [])
            required = request.input_payload["required_scientific_claims"]
            expected = {_claim_identifier(item) for item in required}
            if len(expected) != len(required):
                raise ValueError("Duplicate frozen scientific claim identifier")
            if (
                len(claims) != len(expected)
                or {item.get("claim_id") for item in claims} != expected
                or any(
                    item.get("status")
                    not in {"supported", "partial", "contradicted", "insufficient", "missing"}
                    or not isinstance(item.get("reason"), str)
                    or not item["reason"].strip()
                    or not isinstance(item.get("evidence"), list)
                    or any(not isinstance(ref, str) for ref in item["evidence"])
                    or not set(item["evidence"]).issubset(
                        request.input_payload["allowed_claim_evidence"]
                    )
                    or (
                        item["status"] in {"supported", "partial", "contradicted"}
                        and not item["evidence"]
                    )
                    for item in claims
                )
            ):
                raise ValueError("Every predefined scientific claim needs an explicit judgment")
            target["task_claims"] = claims
            target["task_claim_judge_calibrated"] = False
        target["scores"] = {name: payload[name]["score"] for name in DIMENSIONS}
        target["assessment_request_fingerprint"] = request.fingerprint
    retain_json(output / "RESULTS.json", result)
    return result
