"""Seal failure-inclusive whole-task ablation outcomes, not a formal ranking."""
# ruff: noqa: E501 -- Scientific scope and retained contract literals.

import argparse
import json
from pathlib import Path

from scitaste.benchmark.open_research import digest, verified_asset
from scitaste.model_nodes.session_exchange import retain_json


def collect(project, study):
    root, study = project.resolve(strict=True), study.resolve(strict=True)
    study.relative_to(root)
    protocol = json.loads((study / "STUDY.json").read_text())
    outcomes = {}
    for condition, bound in protocol["campaigns"].items():
        campaign = verified_asset(root, bound)
        assignments = json.loads((campaign.parent / "ASSIGNMENTS.json").read_text())
        original = assignments["scitaste-native"]
        startup = campaign.parent / "STARTUP_FAILURE.json"
        recovered = startup.is_file()
        if recovered:
            assignment = json.loads((campaign.parent / "RECOVERY_ASSIGNMENTS.json").read_text())[
                "scitaste-native"
            ]
        else:
            assignment = original
        run, lifecycle = root / assignment["run"], root / assignment["lifecycle"]
        if not (run / "RESULT.json").is_file() or not (lifecycle / "RESULT.json").is_file():
            raise ValueError(
                f"{condition} still active; do not seal a growing research/paper cohort"
            )
        launch = json.loads((run / "CONTRACT.json").read_text())
        if launch["plan"]["campaign"] != bound:
            raise ValueError("Run does not consume its assigned campaign")
        research = json.loads((run / "RESULT.json").read_text())
        paper = json.loads((lifecycle / "RESULT.json").read_text())
        for command in (lifecycle / "resumes").glob("*.command.json"):
            receipt = command.with_name(command.name.replace(".command.json", ".result.json"))
            if not receipt.is_file():
                raise ValueError(f"{condition} paper recovery still active; do not seal")
        paper_recoveries = [
            {
                "binding": {"locator": path.relative_to(root).as_posix(), "sha256": digest(path)},
                "result": json.loads(path.read_text()),
            }
            for path in sorted((lifecycle / "resumes").glob("*.result.json"))
        ]
        confirmation_dir = campaign.parent / (
            "confirmation" if not recovered else "confirmation-recovery"
        )
        # Confirmation directory identity is derived by the shared service, not
        # guessed from a successful file elsewhere in the project.
        from scitaste.benchmark.confirmation_binding import confirmation_directory

        confirmation_dir = confirmation_directory(root, campaign, "scitaste-native", assignment)
        confirmation = confirmation_dir / "RESULT.json"
        feedback = json.loads(confirmation.read_text()) if confirmation.is_file() else None
        scores, frozen_submission = [], None
        if feedback and feedback["status"] == "completed":
            execution = json.loads((confirmation_dir / "EXECUTION_CONTRACT.json").read_text())
            if (
                not feedback.get("executed_frozen_source")
                or execution["campaign_sha256"] != digest(campaign)
                or execution["source_contract_sha256"] != digest(run / "CONTRACT.json")
                or not execution.get("budget_process_isolation")
                or feedback["execution_contract_sha256"]
                != digest(confirmation_dir / "EXECUTION_CONTRACT.json")
                or feedback["inference_result_sha256"]
                != digest(confirmation_dir / "INFERENCE_RESULT.json")
            ):
                raise ValueError(
                    "Confirmation execution is not bound to this original/recovered assignment"
                )
            frozen = confirmation_dir / "release/frozen_submission/SUBMISSION.json"
            submission = json.loads(frozen.read_text())
            frozen_submission = {
                "locator": frozen.relative_to(root).as_posix(),
                "sha256": digest(frozen),
            }
            scores = [
                {
                    key: row[key]
                    for key in (
                        "method",
                        "input_capture_count",
                        "fov_count",
                        "mean_fov_psnr_db",
                        "mean_fov_ssim",
                        "mean_fov_bandpass_mse",
                        "fovs",
                    )
                }
                for row in feedback["result"]["scores"]
            ]
            keys = {(row["method"], row["input_capture_count"]) for row in scores}
            if len(keys) != len(scores) or keys != {
                (method, budget) for method in submission["methods"] for budget in (1, 2, 4, 8, 16)
            }:
                raise ValueError(
                    "Every declared method/control must have all five budget endpoints"
                )
            if any(
                row["fov_count"] != 6 or {f["fov_id"] for f in row["fovs"]} != set(range(15, 21))
                for row in scores
            ):
                raise ValueError("Confirmation fields differ across procedures")
        trajectory = run / "loop/TRAJECTORY.jsonl"
        actions = (
            [json.loads(line) for line in trajectory.read_text().splitlines()]
            if trajectory.exists()
            else []
        )
        outcomes[condition] = {
            "original_assignment": original,
            "original_completion": "pre-model-startup-failed" if recovered else paper["status"],
            "original_confirmation": "not-started"
            if recovered
            else feedback["status"]
            if feedback
            else "missing",
            "secondary_recovery": assignment if recovered else None,
            "recovery_budget_warning": "Fresh recovery clock; not uninterrupted primary allocation"
            if recovered
            else None,
            "research_result": {
                "locator": (run / "RESULT.json").relative_to(root).as_posix(),
                "sha256": digest(run / "RESULT.json"),
            },
            "research_status": research.get("status"),
            "paper_result": {
                "locator": (lifecycle / "RESULT.json").relative_to(root).as_posix(),
                "sha256": digest(lifecycle / "RESULT.json"),
            },
            "paper_status": paper["status"],
            "paper_only_recoveries": paper_recoveries,
            "confirmation": {
                "locator": confirmation.relative_to(root).as_posix(),
                "sha256": digest(confirmation),
            }
            if confirmation.is_file()
            else None,
            "confirmation_status": feedback["status"] if feedback else "missing",
            "frozen_submission": frozen_submission,
            "all_declared_procedures": scores,
            "primary_selection_rule": "Do not post-select the highest confirming method; all declared method/control curves retained. Ambiguous primary designation is reported, not inferred from success.",
            "committed_actions": len(actions),
            "research_model_responses": len(list((run / "exchange").glob("*.reply.json"))),
            "terminal_lifecycle_responses": paper.get("observed_requests"),
            "scientific_approval": False,
        }
    result = {
        "study_sha256": digest(study / "STUDY.json"),
        "status": "sealed-terminal-development-study",
        "task_families": 1,
        "original_assignments": 3,
        "formal_evidence_eligible": False,
        "provider_backbone_verified": False,
        "gain_established": False,
        "outcomes": outcomes,
        "analysis_scope": "Failure-inclusive original completion plus explicitly secondary recovered scientific curves. One exposed microscopy family, six fields and five capture budgets; none are additional research tasks. Scientific explanation requires source-assumption/probe audit; calls alone do not measure Taste.",
    }
    retain_json(study / "RESULTS.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--study", type=Path, required=True)
    args = parser.parse_args()
    result = collect(args.project, args.study)
    print(json.dumps({"status": result["status"], "conditions": list(result["outcomes"])}))


if __name__ == "__main__":
    main()
