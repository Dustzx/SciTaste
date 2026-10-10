"""Benchmark-owned open research briefs, without preselecting agents' hypotheses.

These are external benchmark runs, not newly authored SciTasteBench tasks. A
frozen resource-limited subset is not the official benchmark leaderboard setup.
"""

import ast
import hashlib
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from scitaste.model_nodes.session_exchange import retain_json

MLR_PIN = "f728d571a992d71c8b526eeb4d9ab6bb5c8cc824"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verified_asset(root, row):
    path = (root / row["locator"]).resolve(strict=True)
    path.relative_to(root.resolve())
    if not path.is_file() or digest(path) != row["sha256"]:
        raise ValueError("Bound benchmark input changed")
    return path


def prepare_campaign(
    project,
    output,
    *,
    task_id,
    wall_seconds,
    max_requests,
    arms=("scitaste-native", "autoresearchclaw"),
    native_paper_reserve_seconds=0,
    development_taste_library=None,
    taste_profile=None,
    research_title=None,
    metadata_timeout_seconds=None,
    taste_proposal_context="reviewed-conditional-v1",
):
    """Freeze source, native rubric and both assignments before any results exist."""
    root = project.resolve(strict=True)
    output = output.resolve()
    output.relative_to(root / "evaluations")
    if Path(task_id).name != task_id or not task_id.startswith("iclr2025_"):
        raise ValueError("Expected an acquired official MLR-Bench task identifier")
    if not 1 <= wall_seconds <= 86400 or not 1 <= max_requests <= 200:
        raise ValueError("Explicit task budget required")
    if arms not in {
        ("scitaste-native",),
        ("scitaste-native", "autoresearchclaw"),
        ("scitaste-native", "autoresearchclaw", "mlr-agent"),
    }:
        raise ValueError("Declare actual Native-only development or the actual framework pair")
    if (development_taste_library is None) != (taste_profile is None):
        raise ValueError("Reviewed experience requires both library and profile")
    if taste_proposal_context not in {"reviewed-conditional-v1", "reviewed-inquiry-v1"}:
        raise ValueError("Unknown frozen reviewed proposal-context version")
    if taste_proposal_context == "reviewed-inquiry-v1" and development_taste_library is None:
        raise ValueError("Inquiry transfer requires its source-reviewed frozen library")
    if research_title is not None and (
        not research_title.strip() or len(research_title) > 240 or "\n" in research_title
    ):
        raise ValueError("Research title must be one bounded line")
    if metadata_timeout_seconds is not None and not 0 < metadata_timeout_seconds <= 900:
        raise ValueError("Metadata timeout must be in (0, 900]")
    if (
        type(native_paper_reserve_seconds) is not int
        or not 0 <= native_paper_reserve_seconds < wall_seconds
    ):
        raise ValueError("Native paper reserve must fit within the shared lifecycle ceiling")
    acquired = root / "evaluations/acquisitions"
    brief = acquired / "mlr-bench-official-ten-briefs-v1/raw" / (task_id + ".md")
    source = acquired / "mlr-agent-native-source-v1"
    rubric_source = source / "mlrbench/evals/overall_review.py"
    observed_pin = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip()
    if observed_pin != MLR_PIN:
        raise ValueError("MLR-Bench source pin changed")
    for relative, path in (
        (f"tasks/{task_id}.md", brief),
        ("mlrbench/evals/overall_review.py", rubric_source),
    ):
        original = subprocess.check_output(["git", "-C", str(source), "show", f"HEAD:{relative}"])
        if original != path.read_bytes():
            raise ValueError("Task or rubric differs from official pinned bytes")
    # Read the rubric as data; never import upstream evaluators/provider clients.
    tree = ast.parse(rubric_source.read_text())
    rubric = next(
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "OVERALL_RUBRIC" for t in node.targets)
    )
    brief_bytes = brief.read_bytes()
    output.mkdir(parents=True, exist_ok=False)
    (output / "TASK.md").write_bytes(brief_bytes)
    (output / "RUBRIC.md").write_text(rubric)
    resource_text = (
        "\n\n# Shared execution envelope (our resource-limited configuration)\n"
        "The official topic above is unchanged. Choose your own research question, "
        "hypotheses, datasets, methods and experimental design within that topic. "
        "No result, dataset, positive effect or preferred method is prescribed. "
        "CPU-only Python 3.12; two compute threads; installed numpy, scipy, "
        "scikit-learn, torch (CPU), pandas and matplotlib. Public literature access "
        "is allowed. Do not access other projects, prior runs, credentials, private "
        "data or GPUs. External dataset/model acquisition is not enabled in this "
        "cohort; use installed public datasets or clearly identified synthetic "
        "experiments. Do not represent synthetic results as real-world validation. "
        f"Total lifecycle budget: {wall_seconds} elapsed seconds and {max_requests} "
        "model responses, including planning, experiments, writing and revision. "
        "These are our limits, not official MLR-Bench defaults. Preserve executed "
        "code, raw results, experimental settings and a research paper. A negative "
        "or inconclusive finding is acceptable. No fabricated measurements or "
        "citations. Separate measurements from predictions and limitations. "
        "Do not run model APIs or another research agent inside experiments.\n"
    )
    (output / "EXECUTION_BRIEF.md").write_text(brief_bytes.decode() + resource_text)

    def binding(path):
        return {"locator": path.relative_to(root).as_posix(), "sha256": digest(path)}

    contract = {
        "schema_version": "1.0",
        "campaign_id": output.name,
        "frozen_at": datetime.now(UTC).isoformat(),
        "benchmark": "MLR-Bench",
        "source_commit": MLR_PIN,
        "task_id": task_id,
        "source_brief": binding(brief),
        "brief": binding(output / "TASK.md"),
        "execution_brief": binding(output / "EXECUTION_BRIEF.md"),
        "rubric": binding(output / "RUBRIC.md"),
        "rubric_source": binding(rubric_source),
        "paper_target": "external full-research benchmark comparison",
        "primary_scitastebench_comparison_replaced": False,
        "population": "one preselected, previously acquired development brief",
        "selection_reason": (
            "Preselected open-ended research topic supporting competing mechanisms "
            "and empirical falsification; no outcome-based task selection."
        ),
        "arms": list(arms),
        "unavailable_not_assigned": [] if "mlr-agent" in arms else ["mlr-agent"],
        "resource_envelope": {
            "wall_seconds": wall_seconds,
            "max_requests": max_requests,
            "cpu_threads": 2,
            "gpu_enabled": False,
            "experiment_seconds": 1800,
            "budget_basis": (
                "Prospective resource-limited CPU slice: target half the allocation for "
                "research/experiments, a quarter for writing/revision and a quarter for "
                "transport/retrieval headroom. Stage shares are guidance, not enforced "
                "stage deadlines. Not an official default or validated sufficiency estimate."
            ),
        },
        "endpoints": ["Clarity", "Novelty", "Soundness", "Significance", "Overall"],
        "additional_checks": [
            "executed artifacts",
            "claim-to-result consistency",
            "completion over both assigned arms",
        ],
        "grading": (
            "Blinded session assessment using the exact upstream text rubric; not an "
            "official MLRJudge execution or human gold. Artifact checks reported separately."
        ),
        "missing_policy": (
            "Keep assigned failures and missing papers; never manufacture scores "
            "or rank only survivors."
        ),
        "comparison_scope": (
            "Resource-limited adapted configurations; tool parity and equal token cost "
            "not established"
        ),
        "model_source": "role-isolated session replies",
        "model_identity_verified": False,
        "actual_tokens": None,
        "actual_cost_usd": None,
        "formal_evidence_eligible": False,
    }
    if native_paper_reserve_seconds:
        contract["resource_envelope"]["native_paper_reserve_seconds"] = native_paper_reserve_seconds
    if "mlr-agent" in arms:
        contract["mlr_agent_configuration"] = {
            "source_commit": MLR_PIN,
            "coding_cli": "actual installed Codex CLI; launch records version and digest",
            "native_review_revision_available": False,
            "model_alias_is_not_backbone_identity": True,
        }
    if development_taste_library is not None:
        from scitaste.taste.research_tool_deliberation import workspace_taste_binding

        library = development_taste_library.resolve(strict=True)
        profile = taste_profile.resolve(strict=True)
        for path in (library, profile):
            path.relative_to(root)
        frozen_binding, _ = workspace_taste_binding(library, profile)
        contract["native_taste"] = {
            "mode": "reviewed-development",
            "library": binding(library),
            "profile": binding(profile),
            "binding": frozen_binding,
            "decision_context": "bounded-research-source-v1",
            "proposal_context": taste_proposal_context,
        }
        contract["taste_scope"] = (
            "Previously source-reviewed conditional experience. Applicability is assessed "
            "on this new topic, not guaranteed by source prestige; abstention is legal. "
            "Source overlap and session-model uncertainty preclude a formal causal claim."
        )
    if research_title is not None:
        contract["external_research_title"] = research_title
        contract["external_task_mapping"] = "short title plus identical task in native stage extras"
    if metadata_timeout_seconds is not None:
        contract["metadata_timeout_seconds"] = metadata_timeout_seconds
    if len(arms) == 1:
        contract["comparison_scope"] = "one-arm Native development; not a framework comparison"
        contract["paper_target"] = "Native research-harness and full-lifecycle development evidence"
        contract["unassigned_available_arms"] = ["autoresearchclaw"]
        contract["selection_reason"] = (
            "Previously acquired official topic; full-task follow-through for the new bound "
            "Native harness. Previously exposed topic, not untouched benchmark evidence."
        )
    retain_json(output / "CAMPAIGN.json", contract)
    return contract


def prepare_native(
    project, campaign, harness, output, *, research_harness_binding=None, source_bound_handoff=None
):
    root = project.resolve(strict=True)
    contract = json.loads(campaign.read_text())
    for key in ("source_brief", "brief", "execution_brief", "rubric", "rubric_source"):
        verified_asset(root, contract[key])
    harness = harness.resolve(strict=True)
    harness.relative_to(root)
    runtime = {p.relative_to(root).as_posix(): digest(p) for p in harness.rglob("*.py")}
    if not (harness / "agent_base/tools/tool_file.py").is_file():
        raise ValueError("Missing research workspace tools")
    output.resolve().relative_to(root)
    plan = {
        "schema_version": "1.0",
        "workspace_kind": "open-research-benchmark",
        "project_id": root.name,
        "executor_id": "scitaste-native-workspace",
        "controller_owner": "scitaste-native",
        "task_id": contract["task_id"],
        "harness": harness.relative_to(root).as_posix(),
        "runtime_sources": runtime,
        "campaign": {"locator": campaign.relative_to(root).as_posix(), "sha256": digest(campaign)},
        "resource_envelope": {
            **contract["resource_envelope"],
            "max_rounds": contract["resource_envelope"]["max_requests"] // 2,
            "max_api_liability_usd": 8,
            "report_reserve_usd": 0,
        },
        "split_role": "development",
        "formal_evidence_eligible": False,
    }
    from scitaste.executor.research_harness import default_harness_binding, load_harness_binding

    plan["research_harness"] = research_harness_binding or default_harness_binding()
    load_harness_binding(plan["research_harness"])
    plan["isolate_workspace_commands"] = True
    if source_bound_handoff is not None:
        plan["source_bound_handoff"] = source_bound_handoff
    output.mkdir(parents=True, exist_ok=False)
    retain_json(output / "PLAN.json", plan)
    return plan


def load_plan(project, plan):
    root = project.resolve(strict=True)
    if (plan["project_id"], plan["executor_id"], plan["controller_owner"]) != (
        root.name,
        "scitaste-native-workspace",
        "scitaste-native",
    ):
        raise ValueError("Open research plan identity mismatch")
    contract = json.loads(verified_asset(root, plan["campaign"]).read_text())
    for key in ("source_brief", "brief", "execution_brief", "rubric", "rubric_source"):
        verified_asset(root, contract[key])
    for locator, value in plan["runtime_sources"].items():
        verified_asset(root, {"locator": locator, "sha256": value})
    for key, value in contract["resource_envelope"].items():
        if plan["resource_envelope"].get(key) != value:
            raise ValueError("Native budget differs from frozen comparison")
    return plan


def initialize_workspace(project, plan, workspace):
    load_plan(project, plan)
    contract = json.loads(verified_asset(project, plan["campaign"]).read_text())
    workspace.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(
        verified_asset(project, contract["execution_brief"]), workspace / "INSTRUCTIONS.md"
    )
    for name in ("code", "outputs", "report/images"):
        (workspace / name).mkdir(parents=True, exist_ok=True)
    if contract.get("researcher_assets"):
        copy_campaign_assets(project, contract, workspace / "data")
    return workspace / "INSTRUCTIONS.md"


def copy_campaign_assets(project, contract, destination):
    """Only the frozen public allowlist, never an entire authoring directory."""
    destination.mkdir(parents=True, exist_ok=False)
    for name, binding in contract["researcher_assets"].items():
        if Path(name).name != name:
            raise ValueError("Campaign asset names must be flat")
        shutil.copyfile(verified_asset(project, binding), destination / name)
        if digest(destination / name) != binding["sha256"]:
            raise ValueError("Copied campaign asset changed")
