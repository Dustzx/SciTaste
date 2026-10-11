"""Synthetic Route/history projection checks; no model, images, targets or accounts."""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import progress_board as board


def main():
    checks = []
    with tempfile.TemporaryDirectory(prefix="scitaste-public-projection-") as tmp:
        root = Path(tmp)
        study = root / "outputs/projects/fastresearch-cvpr2027/research"
        route = study / "route/runs/synthetic_route"
        history = study / "multimodal_intent/runs/synthetic_history"
        route.mkdir(parents=True)
        history.mkdir(parents=True)

        def write(path, value):
            path.write_text(json.dumps(value))

        write(route / "PROTOCOL.json", {"kind": "route_task2", "model": "qwen3-vl-plus"})
        write(route / "STATUS.json", {"status": "running", "completed_samples": 3,
              "selected_samples": 32, "successful_calls": 3})
        write(history / "PROTOCOL.json", {"mode": "controlled_history_variant",
              "model": "qwen3-vl-plus", "max_tokens_per_call": 2048})
        write(history / "STATUS.json", {"status": "completed", "completed_samples": 32,
              "selected_samples": 32, "successful_calls": 256})
        write(history / "SUMMARY.json", {"status": "completed_scored", "selected_samples": 32,
              "metrics": {"correct": 11, "full_accuracy": 11 / 32}, "actual_calls": 256,
              "scope": "Synthetic fixture only; not a measured scientific result."})
        comparison = {"candidate": history.name, "paired_full_coverage": {"wins": 2,
                      "losses": 7, "N": 32}, "scope": "Synthetic paired fixture only"}
        for name in ("HISTORY_VS_ARCADE.json", "HISTORY_VS_SAMPLING_JUDGE.json"):
            write(history.parent.parent / name, comparison)
        write(study / "route/VISUAL_INPUT_AUDIT_PUBLIC_SUMMARY.json",
              {"summary": "Synthetic aggregate input audit", "mechanism_boundary": "No gain claim"})
        original = board.read

        def safe_read(path, default=None):
            if Path(path).name in {"PREDICTIONS.json", "calls.jsonl", "selected_targets.json",
                                   "selected_labels_sealed.json"}:
                raise AssertionError("Projection attempted a raw or target read")
            return original(path, default)

        with patch.object(board, "ROOT", root), patch.object(board, "REPORT", root / "report"), \
                patch.object(board, "study_runs", return_value=[route, history]), \
                patch.object(board, "read", side_effect=safe_read):
            value = board.snapshot()
            runs = {run["name"]: run for run in value["experiments"]}
            assert runs[route.name]["completed"] == 3 and runs[route.name]["summary"] is None
            checks.append("partial_route_keeps_metrics_absent")
            assert len(runs[history.name]["history_comparisons"]) == 2
            assert runs[history.name]["history_comparisons"][0]["paired"]["losses"] == 7
            checks.append("history_negative_paired_evidence_preserved")
            audit = value["route_candidate"]["visual_input_audit"]
            assert audit["mechanism_boundary"] == "No gain claim"
            checks.append("route_safe_input_audit_is_aggregate")
            assert not runs[history.name]["independent_replication"]
            checks.append("development_not_independent_replication")
            assert value["projects"] == [] and value["experiences"] == []
            checks.append("empty_report_and_experiences")
    print(json.dumps({"checks": checks, "model_calls": 0, "real_images": 0, "real_targets": 0}))


if __name__ == "__main__":
    main()
