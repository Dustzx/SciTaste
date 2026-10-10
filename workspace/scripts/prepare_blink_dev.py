"""Fetch only a fixed small public-val development panel, never test answers."""
import concurrent.futures
import hashlib
import json
import random
import time
from pathlib import Path

import requests
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports/bailian_blink_dev_v1"
CACHE = ROOT / "cache/blink_dev_v1"
BASE = "https://datasets-server.huggingface.co"


def get(path, params=None):
    # Only public read-only dataset fetches retry; paid model calls never do.
    for attempt in range(3):
        try:
            response = requests.get(path, params=params, timeout=60)
            response.raise_for_status()
            return response
        except requests.RequestException:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def prepare_one(job):
    task, index, order, row = job
    cached = OUT / "rows" / f"{task}_{index}.json"
    if cached.exists():
        pair = json.loads(cached.read_text())
        assert pair[0]["sample_order"] == order
        return pair
    images = []
    for position in range(1, 5):
        asset = row.get(f"image_{position}")
        if not asset:
            continue
        payload = get(asset["src"]).content
        digest = hashlib.sha256(payload).hexdigest()
        destination = CACHE / (digest + ".img")
        destination.write_bytes(payload)
        with Image.open(destination) as im:
            width, height = im.size
            mime = Image.MIME[im.format]
        images.append({"path": str(destination.relative_to(ROOT)), "sha256": digest,
                       "width": width, "height": height, "mime": mime,
                       "source_image_position": position})
    if not images:
        raise ValueError("No images in development sample")
    # Answer/explanation are deliberately absent from the inference manifest.
    sample = {"id": f"{task}:{row['idx']}", "task": task, "row_index": index,
              "sample_order": order, "prompt": row["prompt"], "choices": row["choices"],
              "images": images, "split": "val", "scope": "exposed_development"}
    pair = sample, {"id": sample["id"], "answer": row["answer"]}
    cached.write_text(json.dumps(pair, ensure_ascii=False))
    return pair


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    (OUT / "rows").mkdir(exist_ok=True)
    if (OUT / "samples.json").exists():
        raise SystemExit("Existing manifest retained. Do not silently redraw the panel.")
    cfg = json.loads((ROOT / "configs/bailian_blink_dev_v1.json").read_text())
    size = get(BASE + "/size", {"dataset": cfg["dataset"]}).json()
    splits = [s for s in size["size"]["splits"] if s["split"] == "val"]
    revision = get("https://huggingface.co/api/datasets/BLINK-Benchmark/BLINK").json()["sha"]
    rng = random.Random(cfg["seed"])
    jobs = []
    for split in sorted(splits, key=lambda s: s["config"]):
        indices = rng.sample(range(split["num_rows"]), cfg["samples_per_task"])
        jobs.extend((split["config"], index, order) for order, index in enumerate(indices))
    selection_path = OUT / "selection.json"
    if selection_path.exists():
        previous = json.loads(selection_path.read_text())
        assert previous["revision"] == revision and previous["jobs"] == [list(j) for j in jobs]
    else:
        selection_path.write_text(json.dumps({"revision": revision, "jobs": jobs,
            "source_size": size, "seed": cfg["seed"], "selection_uses_answers": False}, indent=2))
    prepared_jobs = []
    for split in sorted(splits, key=lambda s: s["config"]):
        task = split["config"]
        # Batch metadata, keep only selected rows. Never fetch full image parquet.
        wanted = {i for t,i,o in jobs if t == task}
        rows = {}
        for offset in range(0, split["num_rows"], 100):
            if not any(offset <= i < offset + 100 for i in wanted):
                continue
            batch = get(BASE + "/rows", {"dataset": cfg["dataset"], "config": task,
                        "split": "val", "offset": offset, "length": min(100, split["num_rows"]-offset)}).json()["rows"]
            rows.update({x["row_idx"]:x["row"] for x in batch if x["row_idx"] in wanted})
            time.sleep(1)
        prepared_jobs.extend((t,i,o,rows[i]) for t,i,o in jobs if t == task)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        pairs = list(pool.map(prepare_one, prepared_jobs))
    samples, answers = zip(*pairs)
    assert len({s["id"] for s in samples}) == len(samples)
    (OUT / "samples.json").write_text(json.dumps(samples, ensure_ascii=False, indent=2))
    (OUT / "answers.json").write_text(json.dumps(answers, ensure_ascii=False, indent=2))
    print(json.dumps({"samples": len(samples), "tasks": len(splits), "revision": revision,
                      "cache_bytes": sum(p.stat().st_size for p in CACHE.iterdir())}), flush=True)


if __name__ == "__main__":
    main()
