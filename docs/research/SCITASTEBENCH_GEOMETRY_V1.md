# Confidence-guided geometric inference

Canonical deliverable: `task-freeze`, then `taste-freeze` and the existing
`primary-experiments` comparison. This is one additional independent research
family, not 260 research tasks and not proof of benchmark release readiness.

## Scientific question and scope

When does descriptor-based confidence make robust inference more reliable, and
when does it hide spatial degeneracy or miscalibration? A useful research outcome
distinguishes these explanations and produces an input-observable decision rule
or a reproducible failure boundary. Rediscovering that PROSAC beats uniform
sampling is insufficient novelty.

The experimental subject is training-free planar geometric inference. Public
heuristic calibration and per-instance homography fitting are permitted;
descriptor, matcher and decision-policy weight training are not. This does not
constrain the training history of the SciTaste controller.

## Source-bound task pack

HPatches' original repository links the full-sequence Hugging Face mirror. The
1.28 GB archive is pinned to revision
`594f211e80b75081ad84a396c93960c8653235f8` and SHA-256
`99cf7e1ca167896eb4ca2fe3d903beff6566243a3c0c8e07a13a2596648ad670`.
Its Hub card declares MIT; retain original third-party scene attribution rather
than claiming the software license independently certifies all image rights.

Before descriptor extraction or research outcomes, label-blind scene hashing
assigns eight discovery, six validation and twelve confirmation scene groups
per change type. Day/night aliases and connected exact-image duplicates stay
together. One pre-feature representative supplies five pairs per group.
Unknown near duplicates and controller pretraining exposure remain limitations.

Ordinary SIFT preprocessing uses a 640-pixel longest side, permissive 0.99 ratio
filter and at most 1024 tentative correspondences. Public phases expose author
homographies; confirmation exposes only correspondences, confidence, shapes and
opaque joins. Resizing transforms include pixel-center offsets. No failed or
difficult pair is selected out using an experimental outcome.

This is an authored research protocol on HPatches, not the original descriptor
benchmark, the full matching leaderboard, or a test of nonplanar SLAM. Image
pairs are within-task observations; scene groups are uncertainty units.

## Evaluation and real-framework comparison

Primary endpoint is corner-reprojection AUC@5px, separately for illumination and
viewpoint. AUC@1px, failures, scene variation and runtime are diagnostic. Invalid
estimates remain in the denominator. All prospective procedures and selectors
are frozen and executed once against hidden confirmation labels. Selection
uses only public data; no best-private-method replacement is permitted.

USAC uniform and PROSAC controls share MSAC scoring/local optimization; MAGSAC
changes scoring/local optimization and is not a pure sampling ablation. Their
64/512 iteration caps do not guarantee equal actual work or monotone accuracy.
Measure actual runtime, and distinguish program-reported estimator time from
trusted total execution time. These geometric estimators are subject controls,
not autonomous-research system baselines.

System comparison remains pinned SciTaste Native+Taste, AutoResearchClaw and
MLR-Agent, with an additional prospectively matched Native OFF mechanism study.
The new campaign requires one named primary procedure before READY. Actual
progress and outcomes are maintained in the project status/results, not inferred
from this source-data design. An independent AI review permits a bounded
prospective episode but does not certify release quality or contribution novelty.

## Accepted-work alignment and remaining gap

The nearest accepted autonomous-research evaluation is
[MLR-Bench, NeurIPS 2025 Datasets and Benchmarks](https://proceedings.neurips.cc/paper_files/paper/2025/hash/ab8dd000d6f87f40061a73f8bca7fae4-Abstract-Datasets_and_Benchmarks_Track.html):
the comparison must assess real literature-to-paper execution and scientific
claims, not just geometry scores. This family adds a genuine visual inference
setting but does not resolve overall task breadth, judge calibration or novelty.

[LightGlue, ICCV 2023](https://openaccess.thecvf.com/content/ICCV2023/html/Lindenberger_LightGlue_Local_Feature_Matching_at_Light_Speed_ICCV_2023_paper.html)
and [HEB, CVPR 2023](https://openaccess.thecvf.com/content/CVPR2023/html/Barath_A_Large-Scale_Homography_Benchmark_CVPR_2023_paper.html)
inform subject-level metric/control requirements, not AutoResearch baselines.
The SIFT-derived scope must not inherit their reported scores or SOTA claims.

LightGlue empirically evaluates HPatches; hiding its result table would not make
it a source-independent Taste case for this held-out task. A candidate source is
[PROSAC, CVPR 2005, author PDF](https://cmp.felk.cvut.cz/~matas/papers/chum-prosac-cvpr05.pdf),
whose empirical examples predate HPatches. Its useful abstraction concerns
conditional ranking, progressive sampling and fallback, not a universal
accuracy theorem. Actual source quality, field-grounded abstraction and two fresh
independent reviews are retained in the source-maintenance successor manifest;
admission does not establish task benefit or automatic policy activation.
Broader image/source exposure
cannot be certified absent from publication dates alone.

## Evidence entry points

Project-relative, under `outputs/projects/scitaste-self-development/`:

- `evaluations/acquisitions/hpatches-official-20261007-v1/`
- `evaluations/scitastebench-hpatches-confidence-pack-20261007-v1/PACK.json`
- `evaluations/scitastebench-hpatches-confidence-reference-20261007-v1/RUN.json`

Current progress and next actions belong only in the existing project
`docs/project/experiments/CURRENT.md` and `PLAN.md`; measurements remain in the
source-bound run artifacts. Do not accumulate per-check status documents here.
