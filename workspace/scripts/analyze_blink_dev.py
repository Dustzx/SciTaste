"""Read-only analysis of the exposed development panel; no API calls."""
import json
import random
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports/bailian_blink_dev_v3"


def main():
    summary = json.loads((OUT / "SUMMARY.json").read_text())
    samples = {x["id"]: x for x in json.loads((OUT / "samples.json").read_text())}
    parent = {key: key for key in samples}

    def find(key):
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    owners = {}
    for key, sample in samples.items():
        for entry in sample["images"]:
            digest = entry["sha256"]
            if digest in owners:
                parent[find(key)] = find(owners[digest])
            else:
                owners[digest] = key
    comparisons = []
    grouped = {(x["model"], x["arm"]): {p["id"]:p for p in x["predictions"]} for x in summary["groups"]}
    for model in sorted({m for m,a in grouped}):
        for other, base in [("visual_evidence", "reason_review"), ("reason_review", "direct"),
                            ("visual_evidence", "direct"), ("thinking", "direct")]:
            if (model, other) not in grouped or (model, base) not in grouped:
                continue
            first, second = grouped[(model, other)], grouped[(model, base)]
            ids = sorted(first.keys() & second.keys())
            if not ids:
                continue
            clusters = defaultdict(list)
            for key in ids:
                clusters[find(key)].append(int(first[key]["correct"])-int(second[key]["correct"]))
            values = list(clusters.values())
            rng = random.Random(20261008)
            draws = []
            for _ in range(5000):
                draw = [v for cluster in rng.choices(values,k=len(values)) for v in cluster]
                draws.append(sum(draw)/len(draw))
            draws.sort()
            comparisons.append({"model": model, "comparison": other+" minus "+base,
                "n_paired": len(ids), "n_image_clusters": len(values),
                "other_correct": sum(first[key]["correct"] for key in ids),
                "base_correct": sum(second[key]["correct"] for key in ids),
                "wrong_to_correct": sum(first[key]["correct"] and not second[key]["correct"] for key in ids),
                "correct_to_wrong": sum(second[key]["correct"] and not first[key]["correct"] for key in ids),
                "mean_difference": sum(sum(x) for x in values)/len(ids),
                "descriptive_cluster_bootstrap_95_interval": [draws[125],draws[4874]],
                "selection_corrected_inference": False,
                "note": "Exploratory outcome-selected development tasks; interval does not correct selection and is not confirmatory significance."})
    calls = [json.loads(x) for x in (OUT / "calls.jsonl").read_text().splitlines()]
    usage = defaultdict(lambda: {"calls":0,"prompt_tokens":0,"completion_tokens":0,"estimated_cny":0.0,"elapsed_s":[]})
    for call in calls:
        group = usage[(call["requested_model"],call["arm"])]
        group["calls"] += 1
        for field in ("prompt_tokens","completion_tokens"):
            group[field] += call.get("usage",{}).get(field,0)
        group["estimated_cny"] += call.get("estimated_cny",call.get("reserved_cny",0))
        group["elapsed_s"].append(call["elapsed_s"])
    cost = []
    for (model, arm), group in sorted(usage.items()):
        times = group.pop("elapsed_s")
        group["median_call_s"] = statistics.median(times)
        cost.append(dict(model=model,arm=arm,**group))
    result = {"scope": summary["scope"],"comparisons":comparisons,"cost_and_usage":cost,
              "all_image_clusters":len({find(k) for k in samples}),"actual_account_bill_verified":False}
    (OUT / "ANALYSIS.json").write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
