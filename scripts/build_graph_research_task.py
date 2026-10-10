"""Acquire and freeze a staged, source-attributed graph research task candidate.

Build does not run an autonomous framework. Fixed reference execution is a
separate command so the data and scientific protocol are frozen before results.
"""
# ruff: noqa: E501 -- Source URLs and authored research protocol literals.

import argparse
import json
import platform
import shutil
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import scipy
import sklearn

from scitaste.benchmark.graph_task_data import TASK_ID, digest, retain_json

PIN = "a431395582e929d88271309716bea4fe24ce6318"
ROOT = f"https://raw.githubusercontent.com/yandex-research/heterophilous-graphs/{PIN}"
GRAPHS = {
    "roman_empire": (22662, 300, 18),
    "amazon_ratings": (24492, 300, 5),
    "tolokers": (11758, 10, 2),
}

BRIEF = """# When does neighborhood information support a transferable prediction rule?

Develop a falsifiable account of when and why using graph neighborhoods improves
node prediction over using a node's own attributes. Use two development graphs to
form competing explanations, choose informative experiments, and develop a procedure
or a scientifically useful negative finding. Freeze the implementation and selection
rule, then examine its predictions and key controls in a third graph context.

This is open research, not a request to reproduce a named algorithm or maximize one
validation score. Explain what the work adds beyond existing heterophily studies:
ego/neighbor separation and feature propagation are already established ideas.
You choose the method, competing explanations and discriminating controls. Do not
invent a new method name as a substitute for a contribution. A supported failure
or appropriately narrowed conclusion is an admissible outcome.

## Research and submission

1. Read the protocol and source limitations. Investigate Roman-empire and
   Amazon-ratings with executed code. Record which observations change your
   hypotheses; numerical gains alone do not identify a mechanism.
2. Produce an initial report, obtain evidence-based critique, and revise or explain
   why a criticism is not supported. Development review must not use hidden labels.
3. Freeze SUBMISSION.json and all implementation files. Bind competing hypotheses,
   discriminating predictions, selection rule, target fit policy and method/control
   identifiers. The freeze must precede target-input release in the local workflow.
4. Run the unchanged procedure on Tolokers. Submit predictions for the primary
   procedure AND the predeclared key controls together before scoring. Training on
   target train labels is allowed; any inner holdout and early stopping must already
   be specified by the frozen program. No manual target-driven hyperparameter edits.
5. Complete a paper with methods, real experiments, related work and limitations,
   runnable source and conclusion-to-evidence links. Post-target revisions may
   correct interpretation; new experiments are exploratory, not replacements for
   the original confirmation. Report failures and inconclusive evidence honestly.

## Data and information boundary

Each graph NPZ has x, edges, y, train_mask, val_mask, test_mask and num_classes.
Only training labels enter fitting, graph-label propagation or supervised features.
Development val labels may select configurations and assess claims, not serve as
message-passing seeds or training targets. Full unlabeled x/edges are permitted:
this is transductive node prediction, NOT inductive unseen-node generalization.
The target graph is released only after source freeze, has no visible validation
labels, and permits no evaluator-label feedback during research. Labels not allowed
in the current view are -1. Other official random splits and original full-label
archives are evaluator-only because they would reveal hidden targets.

Upstream observations are public and potentially in model training. Staged access
does not make them secret or prove novelty/absence of prior exposure. Do not retrieve
original labels. The runtime must enforce filesystem/network separation in addition
to this export contract. No process isolation is implied by an asset-copy receipt.

## Scientific scope

The three graphs are three contexts within ONE research task family. Roman-empire
contains edges and targets constructed through related linguistic processing;
Tolokers models annotator banning with work-related attributes and relationships,
without a prospective temporal separation. Neither establishes a real-world causal
mechanism or prospective risk predictor. The study uses official split 0 only,
not the upstream ten-split aggregate. One target graph cannot establish universal
transfer. Target supervision fits the method, not the SciTaste controller.

Report accuracy for each multiclass development graph and ROC-AUC for Tolokers.
Do not average these into an overall score. The supplied linear and diffusion
controls are cheap executable references, not SOTA claims or AutoResearch baselines.
Their success cannot substitute for experiments by actual research frameworks.
"""


def acquire(url, destination, maximum=60_000_000):
    request = urllib.request.Request(url, headers={"User-Agent": "SciTaste-research-data/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError("Source exceeds predeclared acquisition ceiling")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as stream:
        stream.write(data)
    return {"url": url, "sha256": digest(destination), "bytes": len(data)}


def materialize_graph(source, public, private, graph):
    with np.load(source, allow_pickle=False) as archive:
        raw = {key: archive[key] for key in archive.files}
    x, y, edges = raw["node_features"], raw["node_labels"], raw["edges"]
    nodes, dimensions, classes = GRAPHS[graph]
    if x.shape != (nodes, dimensions) or y.shape != (nodes,) or not np.isfinite(x).all():
        raise ValueError("Unexpected graph features/labels")
    if not np.issubdtype(y.dtype, np.integer) or set(np.unique(y)) != set(range(classes)):
        raise ValueError("Unexpected target classes")
    if edges.ndim != 2 or edges.shape[1] != 2 or not np.issubdtype(edges.dtype, np.integer):
        raise ValueError("Invalid edge representation")
    if edges.min() < 0 or edges.max() >= nodes:
        raise ValueError("Edge endpoint outside graph")
    masks = {}
    for name, source_key in (
        ("train", "train_masks"),
        ("val", "val_masks"),
        ("test", "test_masks"),
    ):
        matrix = raw[source_key]
        if matrix.shape != (10, nodes) or matrix.dtype != np.bool_:
            raise ValueError("Require the ten original boolean masks")
        masks[name] = matrix[0]
    if not np.all(sum(mask.astype(int) for mask in masks.values()) == 1):
        raise ValueError("Split 0 must be disjoint and cover all nodes")
    if set(np.unique(y[masks["train"]])) != set(range(classes)):
        raise ValueError("Training set misses a class")
    is_target = graph == "tolokers"
    visible = masks["train"] if is_target else masks["train"] | masks["val"]
    masked = np.where(visible, y, -1)
    np.savez_compressed(
        public / f"{graph}.npz",
        x=x,
        y=masked,
        edges=edges,
        train_mask=masks["train"],
        val_mask=np.zeros(nodes, dtype=bool) if is_target else masks["val"],
        test_mask=masks["test"],
        num_classes=np.array(classes),
    )
    np.savez_compressed(
        private / f"{graph}-labels.npz",
        node_id=np.flatnonzero(masks["test"]),
        target=y[masks["test"]],
    )
    # Target validation labels are not silently added to endpoint or training.
    canonical_edges = np.sort(edges, axis=1)
    return {
        "graph_id": graph,
        "role": "confirmation" if is_target else "development",
        "nodes": nodes,
        "features": dimensions,
        "classes": classes,
        "stored_edges": len(edges),
        "unique_undirected_edges": len(np.unique(canonical_edges, axis=0)),
        "self_loops": int((edges[:, 0] == edges[:, 1]).sum()),
        "split": 0,
        "source_splits": 10,
        "counts": {name: int(mask.sum()) for name, mask in masks.items()},
        "class_counts": {
            name: np.bincount(y[mask], minlength=classes).tolist() for name, mask in masks.items()
        },
        "masked_labels": int((masked < 0).sum()),
        "endpoint": "roc_auc" if classes == 2 else "accuracy",
        "duplicate_feature_rows": nodes - len(np.unique(x, axis=0)),
        "duplicate_feature_interpretation": "not equivalent to duplicated entities or label leakage",
        "source_family": "yandex-heterophilous-graphs-2023",
    }


def build(output):
    output.mkdir(parents=True, exist_ok=False)
    public, private = output / "public" / TASK_ID, output / "private"
    public.mkdir(parents=True)
    private.mkdir()
    receipts = {}
    for name in ("README.md", "LICENCE.txt", "datasets.py"):
        receipts[name] = acquire(f"{ROOT}/{name}", private / "sources" / name, 100_000)
    shutil.copy2(private / "sources/LICENCE.txt", public / "UPSTREAM-LICENCE.txt")
    graphs = []
    for graph in GRAPHS:
        name = f"{graph}.npz"
        source = private / "sources" / name
        receipts[name] = acquire(f"{ROOT}/data/{name}", source)
        graphs.append(materialize_graph(source, public, private, graph))
    claims = [
        {
            "claim_id": "incremental_effect",
            "requirement": "Quantify the procedure versus a defensible feature-only reference, per context, tied to actual predictions.",
        },
        {
            "claim_id": "competing_explanation",
            "requirement": "Use at least one matched, rerun discriminating control for the paper's own central explanation; state remaining confounds.",
        },
        {
            "claim_id": "procedure_transfer",
            "requirement": "Compare the unchanged frozen procedure and its key control in the target context; no universal or zero-shot claim.",
        },
        {
            "claim_id": "scope_revision",
            "requirement": "Explain what observation changed, narrowed, retained or refuted the hypothesis and why; preserve negative findings.",
        },
    ]
    protocol = {
        "schema_version": "scitastebench.graph-research.v1",
        "task_id": TASK_ID,
        "research_units": 1,
        "contexts": list(GRAPHS),
        "split": "candidate-unassigned",
        "discovery_contexts": ["roman_empire", "amazon_ratings"],
        "confirmation_context": "tolokers",
        "source_pin": PIN,
        "official_split": 0,
        "claim_rubric": claims,
        "target_selection": "Optional inner train holdout/CV and early stopping must be predetermined in frozen code; no manual retuning after target release.",
        "confirmation_submission": "All predeclared primary/control predictions together, once, before any hidden score feedback; post-review reruns exploratory.",
        "metric_policy": "Accuracy and ROC-AUC separately; no mixed-domain arithmetic composite or independent-node inference.",
        "replication_policy": "Current reference has one fixed seed/split with no error bars. Formal execution must predeclare uncertainty design; no automatic ten-repeat requirement.",
        "reference_not_sota": True,
        "framework_budget": None,
        "framework_budget_status": "not assigned; must be common and resource-qualified before actual frameworks launch",
        "gpu_destination_if_needed": "remote 4090-2 only; no local GPU; no device reservation",
        "allowed_modes": [
            "training-based experimental subjects",
            "training-free inference procedures",
        ],
        "controller_training": False,
        "formal_evidence_eligible": False,
    }
    retain_json(public / "PROTOCOL.json", protocol)
    retain_json(
        public / "SUBMISSION.example.json",
        {
            "schema_version": "1.0",
            "task_id": TASK_ID,
            "entrypoint": "research.py",
            "files": ["research.py"],
            "selection_rule": "REPLACE with exact frozen procedure and hyperparameter selection policy",
            "fit_policy": "REPLACE with training, preprocessing, internal holdout, stopping and randomness policy",
            "scope": "REPLACE with the intended conclusion population and limitations",
            "methods": ["primary", "feature_only", "key_control"],
            "hypotheses": [
                {
                    "statement": "REPLACE with falsifiable explanation",
                    "discriminating_prediction": "REPLACE with outcome that distinguishes it",
                },
                {
                    "statement": "REPLACE with genuine alternative",
                    "discriminating_prediction": "REPLACE with contrary or inconclusive prediction",
                },
            ],
        },
    )
    retain_json(
        public / "REVIEW_PROTOCOL.json",
        {
            "required_claims": claims,
            "evidence_contract": "claim -> actual data/mask/config/code/prediction identity -> comparator -> metric -> scope",
            "numeric_checks": "Recompute exact metric and comparator differences, reject missing runs and altered masks; do not infer mechanism or novelty from these checks.",
            "fair_controls": "Use the same supervision, preprocessing/optimization/selection budget. A perturbation applied only at inference diagnoses sensitivity, not retrained comparative utility.",
            "interpretation": "Observed association, graph construction and intervention effects are not automatically real-world causal effects. Insufficient is valid but not a full scientific contribution by itself.",
            "judge_validation": "AI-only evaluation must be tested against supported/contradicted/insufficient anchors and style paraphrases; not human-expert validation.",
            "literature_limit": "Simple ego/neighbor separation is established; require a defensible incremental question/result, not renaming.",
        },
    )
    (public / "TASK.md").write_text(BRIEF)
    (public / "ATTRIBUTION.md").write_text(
        f"# Provenance and rights\n\nOriginal observations: Platonov et al., ICLR 2023; official repository revision `{PIN}`.\n"
        "https://github.com/yandex-research/heterophilous-graphs\n\n"
        "The repository carries the retained MIT licence for software/documentation. This does not establish blanket relicensing of upstream data. "
        "Roman-empire derives from Wikipedia and linguistic features; Amazon-ratings derives from SNAP Amazon metadata; Tolokers from TolokerGraph. "
        "Local research acquisition from the authors' public distribution is recorded. Redistribution approval for derivative datasets is unresolved; do not publish these archives as newly owned SciTaste data. "
        "Prefer fetch instructions with source attribution pending the source-specific rights review.\n\n"
        "SciTaste authors the staged task, research requirements and evidence protocol, not the source observations. "
        "The source paper is https://arxiv.org/abs/2302.11640 .\n"
    )
    reference = Path(__file__).with_name("graph_task_reference.py")
    shutil.copy2(reference, public / "reference.py")
    shutil.copy2(Path(__file__), private / "builder.py")
    from scitaste.benchmark import graph_task_data

    shutil.copy2(Path(graph_task_data.__file__), private / "scorer.py")
    retain_json(private / "SOURCE_RECEIPTS.json", receipts)
    retain_json(
        private / "DATA_QUALITY.json",
        {"graphs": graphs, "reference_execution": "not part of materialization"},
    )
    retain_json(
        private / "ENVIRONMENT.json",
        {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "sklearn": sklearn.__version__,
        },
    )
    retain_json(
        private / "REFERENCE_CONFIG.json",
        {
            "methods": ["features", "neighbors", "shuffled_messages", "label_diffusion"],
            "logistic": {"C": 1.0, "max_iter": 300, "tol": 1e-5},
            "scaler_fit": "train-only",
            "message_permutation_seed": 2718,
            "diffusion": {"steps": 20, "alpha": 0.8},
            "threads": 1,
            "device": "CPU",
            "parameter_search": False,
            "mode_note": "Three fitted logistic procedures and one label-conditioned inference procedure without learned parameters; none trains the SciTaste controller.",
            "convergence_note": "Solver warnings retained; completion is not convergence or optimality. No retry for better scores.",
        },
    )
    files = {p.relative_to(output).as_posix(): digest(p) for p in output.rglob("*") if p.is_file()}
    discovery = sorted(
        p.relative_to(output).as_posix() for p in public.iterdir() if p.name != "tolokers.npz"
    )
    retain_json(
        output / "PACK.json",
        {
            "schema_version": "scitastebench.graph-task-data.v1",
            "task_id": TASK_ID,
            "created_at": datetime.now(UTC).isoformat(),
            "graphs": graphs,
            "research_task_families": 1,
            "discovery_files": discovery,
            "transfer_files": [f"public/{TASK_ID}/tolokers.npz"],
            "files": files,
            "formal_release": False,
            "framework_comparison_executed": False,
            "exposure": "authoring/reference access; session pretraining unknown; prospective phase applies to fresh researcher context only",
            "rights": "local research candidate; third-party data redistribution unresolved",
        },
    )
    return {
        "pack": str(output),
        "graphs": len(graphs),
        "research_families": 1,
        "downloaded_bytes": sum(r["bytes"] for r in receipts.values()),
        "formal_release": False,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.output), indent=2))
