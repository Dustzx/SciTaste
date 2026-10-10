"""Wait for real task closure, then request independent benchmark assessments."""

import argparse
import json
import sys
import time
from pathlib import Path

from scitaste.benchmark.open_research import digest
from scitaste.benchmark.open_research_results import observe, prepare_assessment, score_assessment
from scitaste.model_nodes.session_exchange import SessionResponsePending, retain_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("project", "campaign", "assignments", "output"):
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument("--resume", action="store_true", help="Reuse the sealed assessment")
    parser.add_argument(
        "--reuse-assessment",
        type=Path,
        help="Reuse an accepted review only when its entire sealed input is unchanged",
    )
    args = parser.parse_args()
    try:
        return run(args)
    except Exception as exc:
        output = args.output.resolve()
        output.relative_to(args.project.resolve(strict=True))
        if output.is_dir():
            failures = output / "failures"
            failures.mkdir(exist_ok=True)
            retain_json(
                failures / f"{time.time_ns()}.json",
                {"error_type": type(exc).__name__, "detail": str(exc), "scores_imputed": False},
            )
            retain_json(
                output / "FAILED.json",
                {"status": "attempt-failed", "receipts": "failures/", "automatic_retry": False},
            )
        raise


def run(args):
    root, campaign = args.project.resolve(strict=True), args.campaign.resolve(strict=True)
    output = args.output.resolve()
    output.relative_to(root)
    assignments = json.loads(args.assignments.read_text())
    contract = json.loads(campaign.read_text())
    output.mkdir(parents=True, exist_ok=args.resume)
    retain_json(
        output / "CONTRACT.json",
        {
            "campaign_sha256": digest(campaign),
            "assignments_sha256": digest(args.assignments),
            "research_budget_reset": False,
            "assessment_model_responses": len(contract["arms"]),
            "assessment_time_seconds": 1800,
            "scope": (
                "Independent text-rubric assessment, not research feedback or official MLRJudge"
            ),
        },
    )
    wait_deadline = time.monotonic() + contract["resource_envelope"]["wall_seconds"] + 120
    while True:
        if (
            digest(args.assignments)
            != json.loads((output / "CONTRACT.json").read_text())["assignments_sha256"]
        ):
            raise ValueError("Assignments changed during execution")
        status = observe(root, campaign, assignments)
        if all(row["terminal"] for row in status["rows"]):
            break
        if time.monotonic() >= wait_deadline:
            retain_json(output / "INCOMPLETE.json", status)
            return 2
        time.sleep(10)
    assessment = output / "assessment"
    if not (args.resume and (assessment / "SUBMISSIONS.json").is_file()):
        prepare_assessment(root, campaign, assignments, assessment)
    deadline = time.monotonic() + 1800
    while True:
        try:
            result = score_assessment(assessment, reuse=args.reuse_assessment)
        except SessionResponsePending:
            if time.monotonic() >= deadline:
                retain_json(
                    output / "INCOMPLETE.json",
                    {
                        "status": "assessment-response-missing",
                        "scientific_scores_imputed": False,
                    },
                )
                return 2
            time.sleep(5)
            continue
        retain_json(output / "RESULT.json", result)
        if __package__ in (None, ""):
            # Direct-file invocation initially exposes scripts/, not its parent.
            # Publish the already sealed result without rerunning assessment.
            sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from scripts.publish_open_research_progress import publish

        publish(root, campaign, args.assignments, assessment_result=output / "RESULT.json")
        print(json.dumps(result, ensure_ascii=False))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
