"""Freeze image-grouped ChartQAPro inputs without exposing final answers to inference."""
import hashlib
import io
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
from PIL import Image
from scipy.fft import dctn

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "outputs/projects/fastresearch-cvpr2027/research"
REVISION = "e27c2874825874d6767d2bbc538ed4f0dc2c64c2"
SALT = "fastresearch-cvpr2027-chart-group-v1"
EXPOSED_PREVIEW_INDICES = {0, 1}


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def main():
    manifest_path = PROJECT / "data/MANIFEST.json"
    if manifest_path.exists():
        if json.loads(manifest_path.read_text()).get("protocol_version") != "image-groups-v2-preview-excluded":
            raise RuntimeError("Archive/correct the prior partition before reusing it")
        print("Frozen dataset retained; no partition re-selection")
        return
    parquet = PROJECT / "data" / f"chartqapro-{REVISION}.parquet"
    rows = pq.read_table(parquet).to_pylist()
    images = PROJECT / "data/images"
    images.mkdir(parents=True, exist_ok=True)
    unique, canonical = {}, []
    for row in rows:
        original = row["image"]
        with Image.open(io.BytesIO(original)) as im:
            if im.mode == "RGBA":
                bg = Image.new("RGBA", im.size, "white")
                im = Image.alpha_composite(bg, im).convert("RGB")
            else:
                im = im.convert("RGB")
            key = sha(str(im.size).encode() + im.tobytes())
            if key not in unique:
                path = images / (key + ".png")
                im.save(path)
                small = np.asarray(im.convert("L").resize((32, 32)), dtype=np.float64)
                spectrum = dctn(small, type=2, norm="ortho")[:8, :8].ravel()[1:]
                bits = spectrum > np.median(spectrum)
                fingerprint = sum(int(b) << i for i, b in enumerate(bits))
                unique[key] = {"path": str(path.relative_to(ROOT)), "width": im.width,
                               "height": im.height, "phash": fingerprint,
                               "png_sha256": sha(path.read_bytes())}
        canonical.append(key)
    # Conservatively keep near-identical rendered images in the same partition.
    # This is image grouping, not verified article/source grouping.
    keys = sorted(unique)
    parent = {key: key for key in keys}

    def find(key):
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    pairs = []
    for i, left in enumerate(keys):
        a = unique[left]
        for right in keys[:i]:
            b = unique[right]
            ratio_a, ratio_b = a["width"] / a["height"], b["width"] / b["height"]
            if abs(ratio_a / ratio_b - 1) > 0.02:
                continue
            distance = (a["phash"] ^ b["phash"]).bit_count()
            if distance <= 4:
                x, y = find(left), find(right)
                parent[max(x, y)] = min(x, y)
                pairs.append({"left": left, "right": right, "phash_distance": distance})
    group_map = {key: find(key) for key in keys}
    exposed_groups = {group_map[canonical[i]] for i in EXPOSED_PREVIEW_INDICES}
    inputs, labels = [], []
    for index, row in enumerate(rows):
        key = canonical[index]
        group = group_map[key]
        bucket = int(sha((SALT + "|" + group).encode())[:8], 16) % 10
        partition = "development" if bucket < 2 or group in exposed_groups else "confirmation"
        questions = list(row["Question"])
        answers = list(row["Answer"])
        assert len(questions) == len(answers) and questions
        # Prior conversational answers are part of the official supplied context.
        # The final target is never present in the inference record.
        history = [{"question": q, "answer": a} for q, a in zip(questions[:-1], answers[:-1])]
        inputs.append({"id": f"chartqapro-{index:04}", "dataset_index": index,
                       "partition": partition, "image_group": group, "image_rgb_sha256": key,
                       "image_path": unique[key]["path"], "image_png_sha256": unique[key]["png_sha256"],
                       "question": questions[-1], "question_type": row["Question Type"],
                       "paragraph": row["Paragraph"] or "", "history": history})
        labels.append({"id": f"chartqapro-{index:04}", "partition": partition,
                       "Answer": answers, "Question Type": row["Question Type"], "Year": list(row["Year"])})
    eligible = defaultdict(list)
    for row in inputs:
        if row["partition"] == "development" and row['image_group'] not in exposed_groups:
            eligible[row["question_type"]].append(row)
    screen, used_groups = [], set()
    for kind in sorted(eligible):
        candidates = sorted(eligible[kind], key=lambda r: sha((SALT + "|screen|" + r["id"]).encode()))
        selected = []
        for row in candidates:
            if row["image_group"] in used_groups:
                continue
            selected.append(row["id"])
            used_groups.add(row["image_group"])
            if len(selected) == 8:
                break
        if len(selected) != 8:
            raise RuntimeError(f"Insufficient independent dev groups for {kind}")
        screen.extend(selected)
    for partition in ["development", "confirmation"]:
        subset = [r for r in inputs if r["partition"] == partition]
        (PROJECT / "data" / f"{partition}_inputs.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in subset))
        dump(PROJECT / "data" / f"{partition}_labels.json", [r for r in labels if r["partition"] == partition])
    dump(PROJECT / "data/screen_ids.json", screen)
    dump(PROJECT / "data/near_duplicate_groups.json", pairs)
    counts = {p: {"questions": sum(r["partition"] == p for r in inputs),
                  "groups": len({r["image_group"] for r in inputs if r["partition"] == p}),
                  "types": dict(Counter(r["question_type"] for r in inputs if r["partition"] == p))}
              for p in ["development", "confirmation"]}
    dev = {r["image_group"] for r in inputs if r["partition"] == "development"}
    confirm = {r["image_group"] for r in inputs if r["partition"] == "confirmation"}
    assert not dev & confirm
    files = {str(p.relative_to(PROJECT)): sha(p.read_bytes()) for p in (PROJECT / "data").glob("*.json*")}
    dump(manifest_path, {"dataset": "ahmed-masry/ChartQAPro", "revision": REVISION,
         "protocol_version": "image-groups-v2-preview-excluded",
         "exposed_preview_indices": sorted(EXPOSED_PREVIEW_INDICES),
         "exposure_policy": "Two inspected Dataset Viewer preview targets and their entire image groups are development-only and excluded from screen selection",
         "license": "MIT dataset metadata; chart copyright remains with sources",
         "original_split": "test", "parquet_sha256": sha(parquet.read_bytes()),
         "rows": len(rows), "unique_rgb_images": len(unique), "image_groups": len(set(group_map.values())),
         "near_duplicate_pairs": len(pairs), "grouping": "exact decoded RGB + pHash<=4 with aspect ratio within 2%; transitive closure",
         "split_salt": SALT, "counts": counts, "screen_questions": len(screen), "files": files,
         "source_disjoint_claim": False, "source_metadata_available": False,
         "confirmation_used_for_method_selection": False,
         "prior_answer_context": "Official conversational history only; never the final target",
         "report_scope": "Internal group-disjoint development/confirmation partitions of official test; no full-test score yet"})
    print(json.dumps({"rows": len(rows), "unique_images": len(unique), "counts": counts,
                      "screen_questions": len(screen), "near_duplicate_pairs": len(pairs)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
