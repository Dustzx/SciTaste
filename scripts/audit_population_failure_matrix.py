"""One synthetic output-contract check; no real task labels or research result."""

import argparse
import shutil
from pathlib import Path

import numpy as np

from scitaste.benchmark.graph_task_data import digest, retain_json
from scitaste.benchmark.population_shift_task_data import confirm_submission


def audit(output):
    output.mkdir(parents=True, exist_ok=False)
    pack, release, predictions = (output / name for name in ("pack", "release", "predictions"))
    (pack / "private").mkdir(parents=True)
    (release / "frozen_submission").mkdir(parents=True)
    predictions.mkdir()
    contexts = ("fixture_a", "fixture_b")
    methods = ("complete", "declared_failure", "malformed", "corrupt_archive", "missing")
    files = {}
    for context in contexts:
        path = pack / "private" / f"{context}-labels.npz"
        np.savez(
            path,
            person_id=np.arange(3),
            household_id=np.arange(3),
            target=np.array([0, 1, 0]),
            weight=np.ones(3),
            sex=np.array([1, 2, 1]),
            race=np.ones(3, dtype=int),
        )
        files[path.relative_to(pack).as_posix()] = digest(path)
        for method in methods[:-1]:
            if method == "corrupt_archive":
                # A ZIP signature without a central directory reproduces the
                # retained review's uncaught BadZipFile branch.
                (predictions / f"{context}--{method}.npz").write_bytes(b"PK\x03\x04broken")
                continue
            probability = np.array([[0.8, 0.2], [0.2, 0.8], [0.8, 0.2]])
            if method == "malformed":
                probability[0, 0] = np.nan
            np.savez(
                predictions / f"{context}--{method}.npz",
                person_id=np.arange(3),
                probabilities=probability,
                valid=np.full(3, method != "declared_failure", dtype=bool),
                seconds=np.zeros(3),
            )
    retain_json(pack / "PACK.json", {"confirmation_contexts": list(contexts), "files": files})
    source = Path(__file__).parent / "population_shift_reference.py"
    retained = release / "frozen_submission/reference.py"
    shutil.copy2(source, retained)
    submission = release / "frozen_submission/SUBMISSION.json"
    retain_json(submission, {"methods": list(methods), "primary_method": "missing"})
    retain_json(
        release / "RELEASE.json",
        {
            "phase": "transfer",
            "pack_sha256": digest(pack / "PACK.json"),
            "frozen_source": {
                "reference.py": digest(retained),
                "SUBMISSION.json": digest(submission),
            },
        },
    )
    result_path = confirm_submission(pack, release / "RELEASE.json", predictions)
    import json

    result = json.loads(result_path.read_text())
    if (
        len(result["scores"]) != 10
        or result["primary_scores"] != dict.fromkeys(contexts)
        or result["output_contract_valid"]
    ):
        raise ValueError("Failure matrix did not retain the full declared denominator")
    for row in result["scores"]:
        if row["method"] == "complete":
            assert row["metrics"]["weighted_brier"] is not None
        else:
            assert row["metrics"]["weighted_brier"] is None
        if row["method"] in {"missing", "malformed", "corrupt_archive"}:
            assert row["output_failure"] is not None
        if row["method"] == "corrupt_archive":
            assert row["output_failure"]["error_type"] == "BadZipFile"
    receipt = {
        "scope": "One synthetic scorer-only integrity fixture; not a benchmark/task result",
        "records": len(result["scores"]),
        "methods": list(methods),
        "contexts": list(contexts),
        "full_matrix_retained": True,
        "missing_primary_not_imputed": True,
        "result_sha256": digest(result_path),
        "actual_private_task_labels_accessed": False,
        "predictor_executions": 0,
        "formal_evidence_eligible": False,
        "scientific_quality_certified": False,
    }
    retain_json(output / "AUDIT.json", receipt)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    print(audit(parser.parse_args().output))
