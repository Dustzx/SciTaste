"""Freeze image-scene groups before extracting ordinary tentative matches."""
# ruff: noqa: E501 -- Immutable scientific brief and claim obligations.

import argparse
import hashlib
import io
import json
import re
import shutil
import sys
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from scitaste.benchmark.graph_task_data import digest, retain_json

TASK_ID = "confidence-guided-geometry"
SEED = "scitastebench/hpatches-confidence/v1/20261007"
ZIP_SHA = "99cf7e1ca167896eb4ca2fe3d903beff6566243a3c0c8e07a13a2596648ad670"
MAX_MATCHES = 1024

BRIEF = """# When should match confidence guide geometric inference?

Investigate when descriptor confidence helps or misleads robust geometric
estimation, and whether an input-observable diagnostic can improve the choice
of sampling or filtering under a fixed compute objective. Choose your own
competing explanations, procedures and informative controls. A standard sampler
swap, rediscovering that PROSAC works, or showing one good image pair is not a
new scientific contribution. A supported failure boundary is valid research.

## Real observations and permitted research

The source is HPatches full image sequences: real changes in illumination and
viewpoint with author-supplied planar homographies. Common preprocessing uses
OpenCV SIFT, a permissive descriptor ratio <=0.99, at most 1024 tentative matches
per pair, and a reference-image longest dimension of 640 pixels. Coordinates,
image shapes and confidence=1-ratio are released; images and source identities
are not. Do not fetch the source archive or original homographies. This task
studies robust inference from a common matcher, not end-to-end feature learning,
all local feature methods, or the official full HPatches leaderboard.

Each NPZ contains pair_id[N], scene_id[N], points1/points2[N,1024,2], confidence
[N,1024], n_matches[N], shape1/shape2[N,2] (height,width). Padding must be ignored.
Opaque IDs are joins, not predictive features. Discovery contains eight scene
groups per change type; validation has six different groups per type, each with
five pairs. Both public phases include homography[N,3,3]. Confirmation has twelve
new groups per type, with no homographies released. Scene aliases and exact
image duplicates cannot cross these phases; prior source/model exposure and
unknown near-duplicate camera identities are not certified absent.

Use discovery to form hypotheses and calibrate procedures; validation selects
the final procedure before confirmation. Do not train descriptor, matcher or
policy model weights. Selecting fixed heuristic/calibration constants on public
data is allowed. Per-image fitting of a homography is geometric inference, not
task-specific model training; this is the training-free subject route, not a
training-free constraint on the autonomous controller.

reference.py supplies modern ordinary USAC uniform, PROSAC and MAGSAC++ controls
at 64 and 512 nominal maximum sampling iterations. These are not AutoResearch
frameworks. The uniform/PROSAC pair keeps MSAC scoring and local-optimization
settings fixed; MAGSAC changes score and local optimization and cannot isolate
the sampling effect. Actual runtime and accuracy must be measured: iteration caps
are not equal executed work, and these controls are not proof of SOTA.

Primary endpoint is corner-reprojection AUC@5px at the frozen procedure's stated
compute objective, reported separately by illumination and viewpoint. AUC@1px,
explicit failures and measured CPU seconds are diagnostic. Corner error is the
mean distance between projected reference-image corners under prediction and
source homography. Missing/invalid estimates remain failures, not dropped pairs.
Report scene-group variation; five pairs are not five independent research tasks.

## Confirmation and delivery

Freeze all procedures, controls, fit/calibration policy, selection rule and at
least two hypotheses with discriminating predictions in submission/SUBMISSION.json.
Include every required source/helper. After completion write submission/READY.
The evaluator snapshots source, mounts redacted query point sets, executes it
unchanged offline and scores all declared procedures once. Never repair/refreeze
after READY or substitute public results for failed confirmation.

Entrypoint --data DIRECTORY --output DIRECTORY reads QUERY.json's contexts.
Write exactly illumination--METHOD.npz and viewpoint--METHOD.npz for every method,
with pair_id[N], homography[N,3,3], valid[N] boolean and seconds[N] finite/nonnegative.
Failed estimates have valid=false and finite placeholder matrices. Runtime from
the program is measured-but-self-reported; the trusted evaluator separately
records total execution duration. Inspect actual confirmation_feedback.json
before the paper. Deliver executed code, measurements, informative figures,
evidence-based paper, critique and justified revision. Negative results and
correctly narrowed claims are valid. Do not claim 3D scene geometry, nonplanar
motion, visual SLAM, universal confidence calibration or research novelty from
planar corner accuracy alone.
"""


def identity(name):
    return int(hashlib.sha256((SEED + ":id:" + name).encode()).hexdigest()[:15], 16)


def build(source, output, opencv_runtime):
    source, output = source.resolve(strict=True), output.resolve()
    archive = source / "hpatches-sequences-release.zip"
    if digest(archive) != ZIP_SHA:
        raise ValueError("Wrong author-linked archive bytes")
    sys.path.insert(0, str(opencv_runtime.resolve(strict=True)))
    import cv2

    cv2.setNumThreads(2)
    output.mkdir(parents=True, exist_ok=False)
    public, target, private = output / "public" / TASK_ID, output / "target", output / "private"
    for directory in (public, target, private):
        directory.mkdir(parents=True)
    started = time.monotonic()
    z = zipfile.ZipFile(archive)
    members = {i.filename: i for i in z.infolist()}
    if (
        len(members) != len(z.infolist())
        or sum(i.file_size for i in members.values()) > 10_000_000_000
    ):
        raise ValueError("Duplicate members or oversized source")
    roots = sorted(str(Path(n).parent) for n in members if n.endswith("/1.ppm"))
    if len(roots) != 116:
        raise ValueError("Unexpected original sequence count")
    groups, image_owners = {}, {}
    for root in roots:
        name = Path(root).name
        group = re.sub(r"(?:day|night)$", "", name)
        groups.setdefault(group, []).append(root)
        for i in range(1, 7):
            key = hashlib.sha256(z.read(f"{root}/{i}.ppm")).hexdigest()
            image_owners.setdefault(key, set()).add(group)
    # Connected exact-image aliases merge; names known to share day/night scenes
    # already share one group. Do not pretend this certifies all near duplicates.
    parents = {group: group for group in groups}

    def canonical(group):
        while parents[group] != group:
            parents[group] = parents[parents[group]]
            group = parents[group]
        return group

    for owners in image_owners.values():
        representatives = sorted({canonical(owner) for owner in owners})
        for owner in representatives[1:]:
            parents[owner] = representatives[0]
    merged = {}
    for group, sequences in groups.items():
        merged.setdefault(canonical(group), []).extend(sequences)
    groups = merged
    assignments, used = {}, set()
    for change, prefix in (("illumination", "i_"), ("viewpoint", "v_")):
        names = sorted(
            (g for g in groups if g.startswith(prefix)),
            key=lambda g: hashlib.sha256((SEED + ":split:" + g).encode()).digest(),
        )
        if len(names) < 26:
            raise ValueError("Insufficient independent scene groups")
        for phase, names_for_phase in (
            ("discovery", names[:8]),
            ("validation", names[8:14]),
            ("query", names[14:26]),
        ):
            assignments[f"{change}-{phase}"] = names_for_phase
            if used.intersection(names_for_phase):
                raise ValueError("Scene group crosses phases")
            used.update(names_for_phase)
    retain_json(
        private / "SCENE_ASSIGNMENT.json",
        {
            "seed": SEED,
            "groups": groups,
            "assignments": assignments,
            "frozen_before_feature_outcomes": True,
        },
    )
    detector = cv2.SIFT_create(nfeatures=2048)

    def image(file):
        original = cv2.imdecode(np.frombuffer(z.read(file), np.uint8), cv2.IMREAD_GRAYSCALE)
        if original is None:
            raise ValueError("Corrupt original image")
        height, width = original.shape
        scale = min(1.0, 640.0 / max(height, width))
        dimensions = (round(width * scale), round(height * scale))
        resized = cv2.resize(original, dimensions, interpolation=cv2.INTER_AREA)
        sx, sy = dimensions[0] / width, dimensions[1] / height
        transform = np.array([[sx, 0, (sx - 1) / 2], [0, sy, (sy - 1) / 2], [0, 0, 1]])
        points, descriptors = detector.detectAndCompute(resized, None)
        return resized.shape, transform, points, descriptors

    bf = cv2.BFMatcher(cv2.NORM_L2)
    inventories = {}
    for split, scene_groups in assignments.items():
        rows, truths = [], []
        for group in scene_groups:
            # Multiple known aliases stay in one split; select one sequence by
            # pre-feature hash, not the easy one. Never drop difficult pairs.
            root = min(groups[group], key=lambda r: hashlib.sha256((SEED + r).encode()).digest())
            shape1, transform1, points1, descriptors1 = image(f"{root}/1.ppm")
            for view in range(2, 7):
                shape2, transform2, points2, descriptors2 = image(f"{root}/{view}.ppm")
                pairs = []
                if descriptors1 is not None and descriptors2 is not None and len(descriptors2) >= 2:
                    for match in bf.knnMatch(descriptors1, descriptors2, k=2):
                        if len(match) == 2 and match[1].distance > 1e-12:
                            ratio = match[0].distance / match[1].distance
                            if ratio <= 0.99:
                                pairs.append((ratio, match[0].queryIdx, match[0].trainIdx))
                pairs.sort()
                pairs = pairs[:MAX_MATCHES]
                p1, p2, confidence = (
                    np.zeros((MAX_MATCHES, 2)),
                    np.zeros((MAX_MATCHES, 2)),
                    np.zeros(MAX_MATCHES),
                )
                for index, (ratio, first, second) in enumerate(pairs):
                    p1[index], p2[index], confidence[index] = (
                        points1[first].pt,
                        points2[second].pt,
                        1 - ratio,
                    )
                homography = np.loadtxt(io.StringIO(z.read(f"{root}/H_1_{view}").decode()))
                homography = transform2 @ homography @ np.linalg.inv(transform1)
                if (
                    homography.shape != (3, 3)
                    or not np.isfinite(homography).all()
                    or abs(np.linalg.det(homography)) < 1e-14
                ):
                    raise ValueError("Invalid author homography; no silent replacement")
                rows.append(
                    {
                        "pair_id": identity(root + f":{view}"),
                        "scene_id": identity(group),
                        "points1": p1,
                        "points2": p2,
                        "confidence": confidence,
                        "n_matches": len(pairs),
                        "shape1": shape1,
                        "shape2": shape2,
                    }
                )
                truths.append(homography)
        arrays = {key: np.asarray([row[key] for row in rows]) for key in rows[0]}
        inventories[split] = {"pairs": len(rows), "scene_groups": len(scene_groups)}
        if split.endswith("query"):
            np.savez_compressed(target / f"{split}.npz", **arrays)
            np.savez_compressed(
                private / f"{split.replace('query', 'labels')}.npz",
                pair_id=arrays["pair_id"],
                shape1=arrays["shape1"],
                homography=np.stack(truths),
            )
        else:
            np.savez_compressed(public / f"{split}.npz", **arrays, homography=np.stack(truths))
    contexts = {name: f"{name}-query.npz" for name in ("illumination", "viewpoint")}
    retain_json(target / "QUERY.json", {"task_id": TASK_ID, "contexts": contexts})
    (public / "TASK.md").write_text(BRIEF)
    (public / "ATTRIBUTION.md").write_text(
        "HPatches, CVPR 2017: https://github.com/hpatches/hpatches-dataset\n"
        "Author-linked mirror: https://huggingface.co/datasets/vbalnt/hpatches\n"
        "Hub card declares MIT; retain original references for third-party scenes.\n"
        "Derived point sets do not certify all source-image redistribution rights.\n"
    )
    rubric = [
        {"claim_id": key, "obligation": text}
        for key, text in (
            (
                "ranking",
                "Validate match-rank reliability rather than assume it from descriptor similarity",
            ),
            (
                "geometry",
                "Discriminate spatial degeneracy and match filtering from ranking benefit",
            ),
            (
                "budget",
                "Compare genuine same-configuration sampling controls and actual measured cost",
            ),
            ("selection", "Frozen public-data selector; no private-label choice or oracle policy"),
            (
                "scope",
                "Separate planar geometry, full matching, novelty and autonomous-research claims",
            ),
        )
    ]
    retain_json(
        public / "PROTOCOL.json",
        {
            "task_id": TASK_ID,
            "claim_rubric": rubric,
            "subject_route": "training-free",
            "inventories": inventories,
            "primary_endpoint": "corner_auc_5px",
            "confirmation_contexts": list(contexts),
            "scenes_not_pairs_are_uncertainty_units": True,
            "source_preprocessing": {
                "opencv": cv2.__version__,
                "max_matches": MAX_MATCHES,
                "max_image_side": 640,
                "ratio_limit": 0.99,
                "descriptor": "SIFT",
            },
        },
    )
    retain_json(
        public / "REVIEW_PROTOCOL.json",
        {
            "claim_obligations": rubric,
            "novelty_not_certified_by_score": True,
            "negative_findings_valid": True,
        },
    )
    retain_json(
        public / "SUBMISSION.example.json",
        {
            "schema_version": "1.0",
            "task_id": TASK_ID,
            "entrypoint": "predict.py",
            "files": ["predict.py"],
            "methods": ["primary", "control"],
            "selection_rule": "REPLACE prospective selector",
            "fit_policy": "REPLACE calibration policy",
            "scope": "REPLACE scope",
            "hypotheses": [
                {
                    "statement": "REPLACE hypothesis",
                    "discriminating_prediction": "REPLACE prediction",
                },
                {
                    "statement": "REPLACE alternative",
                    "discriminating_prediction": "REPLACE alternative prediction",
                },
            ],
        },
    )
    shutil.copy2(Path(__file__).with_name("hpatches_task_reference.py"), public / "reference.py")
    files = {p.relative_to(output).as_posix(): digest(p) for p in output.rglob("*") if p.is_file()}
    manifest = {
        "schema_version": "1.0",
        "task_id": TASK_ID,
        "source_family": "hpatches-planar-scenes",
        "frozen_at": datetime.now(UTC).isoformat(),
        "source_archive_sha256": ZIP_SHA,
        "source_revision": "594f211e80b75081ad84a396c93960c8653235f8",
        "files": files,
        "discovery_files": [n for n in files if n.startswith("public/")],
        "transfer_files": [n for n in files if n.startswith("target/")],
        "confirmation_contexts": list(contexts),
        "inventories": inventories,
        "build_seconds": time.monotonic() - started,
        "quality_admitted": False,
        "formal_evidence_eligible": False,
        "source_independence_certified": False,
        "authoring_development_only": False,
        "research_outputs_observed_before_freeze": False,
        "scope": "One authored research family; disjoint declared scene groups, unknown near-duplicates/prior exposure",
    }
    retain_json(output / "PACK.json", manifest)
    print(
        json.dumps(
            {
                "pack": str(output),
                "inventories": inventories,
                "build_seconds": manifest["build_seconds"],
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "output", "opencv-runtime"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    build(args.source, args.output, args.opencv_runtime)
