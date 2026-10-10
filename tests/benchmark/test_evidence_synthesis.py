import copy
import json

import pytest

from scitaste.benchmark.evidence_synthesis import binding, synthesize_research_evidence


@pytest.fixture
def frozen_source(tmp_path):
    directory = tmp_path / "evaluations" / "cohort"
    directory.mkdir(parents=True)

    def save(name, value):
        path = directory / name
        path.write_text(json.dumps(value))
        return binding(tmp_path, path)

    campaign = save(
        "CAMPAIGN.json",
        {
            "arms": ["scitaste-native", "autoresearchclaw"],
            "task_id": "research-a",
            "benchmark": "SciTasteBench",
            "resource_envelope": {"wall_seconds": 100},
            "formal_evidence_eligible": False,
        },
    )
    assignments = save(
        "ASSIGNMENTS.json",
        {
            "scitaste-native": {"run": "evaluations/native"},
            "autoresearchclaw": {"run": "evaluations/arc"},
        },
    )
    observed = {
        "campaign_sha256": campaign["sha256"],
        "task_id": "research-a",
        "assigned_systems": 2,
        "rows": [
            {
                "arm": arm,
                "run": run,
                "status": "failed",
                "terminal": True,
                "paper": None,
                "scores": {"Overall": None},
            }
            for arm, run in (
                ("scitaste-native", "evaluations/native"),
                ("autoresearchclaw", "evaluations/arc"),
            )
        ],
        "formal_evidence_eligible": False,
    }
    result = save("RESULTS.json", observed)
    submissions = save("SUBMISSIONS.json", {"observed": observed, "assessments": []})
    spec = {
        "schema_version": "1.0",
        "selection_rule": "all assignments",
        "sources": [
            {
                "campaign": campaign,
                "assignments": assignments,
                "result": result,
                "submissions": submissions,
                "scope": "development",
            }
        ],
    }
    return tmp_path, spec, save


def test_retains_failed_denominator_without_imputation(frozen_source):
    root, spec, _ = frozen_source
    result = synthesize_research_evidence(root, spec)
    assert result["assigned_episodes"] == 2
    assert result["formal_task_assignments"] == 0
    assert all(r["confirmation_metrics"] == [] for r in result["tasks"][0]["rows"])
    assert all(r["actual_tokens"] is None for r in result["tasks"][0]["rows"])


def test_forbids_formal_promotion_and_duplicate_tasks(frozen_source):
    root, spec, _ = frozen_source
    upgraded = copy.deepcopy(spec)
    upgraded["sources"][0]["scope"] = "formal"
    with pytest.raises(ValueError, match="cannot promote"):
        synthesize_research_evidence(root, upgraded)
    spec["sources"].append(copy.deepcopy(spec["sources"][0]))
    with pytest.raises(ValueError, match="cannot add a task"):
        synthesize_research_evidence(root, spec)


def test_forbids_survivor_only_selection(frozen_source):
    root, spec, save = frozen_source
    result = json.loads((root / spec["sources"][0]["result"]["locator"]).read_text())
    result["rows"].pop()
    spec["sources"][0]["result"] = save("SHORT_RESULT.json", result)
    with pytest.raises(ValueError, match="omitted or duplicated"):
        synthesize_research_evidence(root, spec)


def test_recovery_cannot_replace_original_assignment(frozen_source):
    root, spec, save = frozen_source
    item = spec["sources"][0]
    item["recovery_index"] = save(
        "RECOVERY.json",
        {
            "campaign_sha256": item["campaign"]["sha256"],
            "assignments_sha256": item["assignments"]["sha256"],
            "original_assignment_replaced": True,
            "recoveries": [],
        },
    )
    with pytest.raises(ValueError, match="exact original"):
        synthesize_research_evidence(root, spec)
