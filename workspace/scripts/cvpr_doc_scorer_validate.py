#!/usr/bin/env python3
"""Validate pinned OmniDocBench scoring on synthetic, non-benchmark pages."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "outputs/projects/fastresearch-cvpr2027/research/document"
UPSTREAM = BASE / "sources/upstream"
OUT = BASE / "scorer_validation_v1"
TEXT = [
    "Alpha paragraph describes the first independent observation.",
    "Bravo section records a second distinct laboratory measurement.",
    "Charlie conclusion reports the final experimental comparison.",
]
TABLE = "<table><tr><td>Name</td><td>Value</td></tr><tr><td>Alpha</td><td>7</td></tr></table>"


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def block(category, order, value):
    key = {"text_block": "text", "table": "html", "equation_isolated": "latex"}[category]
    return {"category_type": category, "order": order, "anno_id": order,
            "ignore": False, "poly": [10, 10, 300, 10, 300, 100, 10, 100],
            "attribute": {}, key: value}


def page(name, blocks):
    return {"page_info": {"image_path": name, "page_no": 0, "width": 640,
                          "height": 800, "page_attribute": {"data_source": "synthetic"}},
            "layout_dets": blocks, "extra": {"relation": []}}


def main():
    started = time.monotonic()
    OUT.mkdir(parents=True, exist_ok=True)
    if (OUT / "SUMMARY.json").exists():
        raise RuntimeError("Completed validation is immutable; use a versioned correction")
    receipts = json.loads((BASE / "sources/CODE_RECEIPTS.json").read_text())
    for item in receipts["files"]:
        assert hashlib.sha256((UPSTREAM / item["file"]).read_bytes()).hexdigest() == item["sha256"]
    # Constrain both library math threads and public scorer worker settings.
    for key in ["OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"]:
        os.environ[key] = "1"
    sys.path.insert(0, str(UPSTREAM))
    os.chdir(OUT)
    from src.core.pipeline import run_config
    from src.dataset.end2end_dataset import End2EndDataset
    from src.metrics.cal_metric import call_Edit_dist
    (OUT / "result").mkdir(exist_ok=True)
    pages = [
        page("paragraphs.png", [block("text_block", i + 1, text) for i, text in enumerate(TEXT)]),
        page("order_zero.png", [block("text_block", 0, "Zero order annotation remains visible as text.")]),
        page("table.png", [block("text_block", 1, "Table caption body."), block("table", 2, TABLE)]),
        page("formula.png", [block("text_block", 1, "Equation description."), block("equation_isolated", 2, "x+y=z")]),
    ]
    gt = OUT / "SYNTHETIC_GT.json"
    dump(gt, pages)
    variants = {
        "correct": TEXT,
        "reverse": list(reversed(TEXT)),
        "drop_middle": [TEXT[0], TEXT[2]],
        "wrong_table": TEXT,
        "missing_pages": None,
    }
    results = {}
    for name, paragraphs in variants.items():
        pred = OUT / name
        pred.mkdir(exist_ok=True)
        if paragraphs is not None:
            (pred / "paragraphs.md").write_text("\n\n".join(paragraphs))
            (pred / "order_zero.md").write_text("Zero order annotation remains visible as text.")
            table = TABLE.replace(">7<", ">9<") if name == "wrong_table" else TABLE
            (pred / "table.md").write_text("Table caption body.\n\n" + table)
            (pred / "formula.md").write_text("Equation description.\n\n$$x+y=z$$")
        cfg = {"end2end_eval": {
            "metrics": {"text_block": {"metric": ["Edit_dist"]},
                        "table": {"metric": ["TEDS", "Edit_dist"], "teds_workers": 1},
                        "display_formula": {"metric": ["Edit_dist"]},
                        "reading_order": {"metric": ["Edit_dist"]}},
            "dataset": {"dataset_name": "end2end_dataset",
                        "ground_truth": {"data_path": str(gt)},
                        "prediction": {"data_path": str(pred)},
                        "match_method": "quick_match", "match_workers": 1,
                        "quick_match_truncated_timeout_sec": 300,
                        "match_timeout_sec": 420,
                        "timeout_fallback_max_chunk_span": 10,
                        "timeout_fallback_order_penalty": 0.10}}}
        dump(OUT / (name + "_config.json"), cfg)
        run_config(cfg)
        result_path = OUT / "result" / (name + "_quick_match_metric_result.json")
        results[name] = json.loads(result_path.read_text())

    # Directly execute the original method as well, isolating its zero-order rule
    # from block recognition/matching. This does not replace official scoring.
    obj = object.__new__(End2EndDataset)
    zero = obj.get_order_paired([{"gt_position": [0], "pred_position": 1}], "zero.png")
    omitted = obj.get_order_paired([
        {"gt_position": [1], "pred_position": 10},
        {"gt_position": [2], "pred_position": ""},
        {"gt_position": [3], "pred_position": 30},
    ], "omit.png")
    assert zero == {}, "Pinned zero-order behavior changed"
    assert omitted["gt"] == [1, 2, 3] and omitted["pred"] == [1, 3]
    assert abs(omitted["edit"] - 1 / 3) < 1e-12
    dump(OUT / "ORDER_BOUNDARY_CASES.json", {"zero_order_only": zero, "omitted_block": omitted})
    # This code path averages per-page length-weighted edit distances.
    sample = [{"gt": "a" * 10, "pred": "a" * 10, "img_id": "a.png"},
              {"gt": "b", "pred": "", "img_id": "b.png"}]
    _, ed = call_Edit_dist(sample).evaluate(save_name="synthetic_page_weighting")
    assert abs(ed["Edit_dist"]["ALL_page_avg"] - 0.5) < 1e-12
    assert abs(ed["Edit_dist"]["edit_whole"] - 1 / 11) < 1e-12
    dump(OUT / "PAGE_WEIGHTING.json", ed)
    shutil.copyfile(__file__, OUT / Path(__file__).name)
    summary = {"status": "synthetic_pipeline_executed", "upstream_commit": receipts["commit"],
               "python": platform.python_version(), "source_files_sha_verified": len(receipts["files"]),
               "variants": results, "zero_order_only_excluded_by_pinned_method": True,
               "omission_affects_reading_order": True,
               "edit_distance_aggregation": "Mean of per-page length-weighted edit distances; not global character average",
               "CDM_executed": False, "Overall": None, "benchmark_pages_evaluated": 0,
               "model_calls": 0, "gpu_used": False, "elapsed_seconds": time.monotonic() - started,
               "packages": {n: importlib.metadata.version(n) for n in ["omnidocbench-eval", "numpy", "pandas", "Levenshtein", "lxml", "apted"]},
               "limits": "Synthetic scorer engineering only, no method gain or official benchmark reproduction. No upstream edits. CDM runtime not verified; do not report Overall. Order-zero exclusion does not by itself establish an annotation defect."}
    dump(OUT / "SUMMARY.json", summary)
    print(json.dumps({k: v for k, v in summary.items() if k not in {"variants", "packages"}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
