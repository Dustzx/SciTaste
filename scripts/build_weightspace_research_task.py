"""Materialize a source-bound development task from real, completed subject training."""

import argparse
import inspect
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from scitaste.benchmark.graph_task_data import digest, retain_json
from scitaste.benchmark.weightspace_task_data import TASK_ID

BRIEF = """# Can limited evidence support a transferable model-combination decision?

Given already-trained neural networks and limited labelled calibration images,
develop and empirically test an account of when a single-network combination is
preferable to selecting one input model. Which inexpensive observations distinguish
genuine compatibility from a favorable but fragile calibration result? Can the
resulting decision and scientific explanation survive unseen training lineages?

This is open research, not a request to implement an author-selected rule. Choose
competing explanations, experiments, procedures and discriminating controls. You
may reject merging, propose a diagnostic, optimize parameters on permitted labels,
or establish a useful failure boundary. A positive score is not mandatory. Simply
showing that identical functions can have permuted parameters, that naïve averaging
can fail, or that shared initialization helps is not a new scientific contribution:
these are already studied by Model soups (ICML 2022) and Git Re-Basin (ICLR 2023).

## Accessible real research material

The subject models are six ordinary convolution-ReLU layers with max-pooling,
global average pooling and a ten-class head; no batch normalization. They are
trained from scratch on the same 40,000 official CIFAR-10 training images. Three
models in each shared-prefix context branch from one trained prefix. Three in each
independent context start from separate initial weights. Total per-model training
exposure is matched; checkpoints and original training receipts are retained.
Development blocks and confirmation blocks use different seeds, with no checkpoint
selection by accuracy. Models, pairs and seed blocks are NOT new benchmark tasks.
The optimizer is AdamW: shared prefixes use learning rate 0.001 for eight epochs;
the three branches then use 0.0005/0.001/0.0015 for eight epochs. Independent models
use those respective rates for sixteen epochs. Lineage and optimization trajectories
therefore differ together; a lineage correlation alone cannot establish a causal
initialization effect. Do not claim such causal identification without a new control.

This is a small-model scientific study, not a replication of large pretrained
CLIP/ImageNet soups or evidence about foundation-model merging. Initialization
lineage is visible context, not a hidden answer. The shared prefix is NOT a large
pretraining corpus. Matching epochs is not matching all optimizer trajectories.

Read PROTOCOL.json, DEVELOPMENT.json and research_cnn.py. calibration.npz provides
512 labelled images; development_query.npz provides 5,000 images/labels for
development experiments, not parameter fitting or adaptive held-out selection.
Fit, align, distill, choose coefficients and choose models using calibration data
only. A model may also be selected using a frozen label-free rule. Do not train or
tune on development-query labels. All supplied images are real CIFAR observations.
Calibration image_id uses 100000 + official training-set row; query image_id is
the official test-set row. The two source splits therefore have distinct identities
even when their original row numbers match; this does not change images or labels.
The CIFAR archives and original test labels are unavailable to research processes;
do not retrieve them via network. Public-source prior exposure remains unknown.

## Scientific work and confirmation

Execute informative experiments, not a huge hyperparameter grid or repetitions
designed to achieve significance. Distinguish calibration fit from query performance,
weight compatibility from predictive diversity, and a diagnostic correlation from
a causal explanation. Useful controls include model selection, unaligned averaging,
and a prediction ensemble; these are METHOD controls, never AutoResearch systems.
Account for extra ensemble inference and additional fitting rather than attributing
those resources to taste. Justify any omitted established comparator.

Retain a scientific report, experimental code, actual measurements, figures and
an evidence-based critique/revision. Freeze all methods and controls together with
competing hypotheses, discriminating predictions, fit/selection policy and scope.
After source freeze the common service releases different labelled calibration
images (512) and unlabelled queries (5,000) with new subject checkpoints, executes
your unchanged program, and returns one joint packet for all declared procedures.
Confirmation must not select a favorable seed/context or repair the frozen code.
Different contexts reuse the same query images; do not count them as independent
image replications. Report accuracy and NLL separately per context, with training
block as the replication unit. Any exploratory follow-up stays separate.

The entrypoint accepts --data DIRECTORY --output DIRECTORY. Read QUERY.json from
the target directory: it names contexts, checkpoint files, query.npz and
calibration.npz. Query images are uint8[N,3,32,32], image_id is integer; normalize
by 255 as in the trained model. Checkpoints are plain torch state_dicts, safely
load with torch.load(..., weights_only=True, map_location='cpu'). Include a local
copy of the exact model definition in the frozen source if required; data helpers
are NOT automatically installed in the confirmation sandbox. Each context gets
its three models, not checkpoints from other contexts. Do not use target-query
labels, another context's calibration results, or development checkpoints to make
target decisions. Put fitted/auxiliary artifacts in an output subdirectory.

For each context and each declared method write CONTEXT--METHOD.npz at output's
top level, containing image_id[N] and finite normalized probabilities[N,10]. Only
these declared prediction NPZs may appear at top level. The same fit/selection rule
applies to every context; lineage-specific rules are legal only if frozen in advance.
No supplied reference score is a SOTA result or a required positive target.
"""

CLAIMS = [
    {
        "id": "transfer",
        "required": "Separate development from prospective frozen confirmation",
        "check": "Match claims to all predeclared context predictions; retain missing contexts",
    },
    {
        "id": "compatibility",
        "required": "Do not identify mechanism from a gain or correlation alone",
        "check": "Competing explanations and a discriminating executed control are required",
    },
    {
        "id": "calibration",
        "required": "No query labels used for fitting or adaptive selection",
        "check": "Inspect executable fitting/selection policy and data references",
    },
    {
        "id": "replication",
        "required": "Seed blocks/pairs/contexts are not independent research tasks",
        "check": "Training-block lineage and shared image denominators must be reported",
    },
    {
        "id": "cost",
        "required": "Ensembles/additional optimization have different inference/fit costs",
        "check": "Retain actual computation and avoid unsupported constant-cost claims",
    },
    {
        "id": "scope",
        "required": "Do not generalize from scratch-trained small CNNs to foundation models",
        "check": "Report prior-work scope and evidence limits, including negative outcomes",
    },
]


def build(project, assets, output, blocks_per_split, development_only=False):
    project, assets, output = (
        project.resolve(strict=True),
        assets.resolve(strict=True),
        output.resolve(),
    )
    assets.relative_to(project / "evaluations")
    output.relative_to(project / "evaluations")
    contract = json.loads((assets / "TRAINING_CONTRACT.json").read_text())
    rows = [json.loads(p.read_text()) for p in sorted((assets / "receipts").glob("*.json"))]
    roles = ("development",) if development_only else ("development", "confirmation")
    expected = [
        (role, i, kind, b)
        for role in roles
        for i in range(blocks_per_split)
        for kind in ("shared", "independent")
        for b in range(3)
    ]
    lookup = {(r["split"], r["block"], r["kind"], r["branch"]): r for r in rows}
    if len(lookup) != len(rows) or not all(k in lookup and lookup[k]["complete"] for k in expected):
        raise ValueError("Every preselected training block and branch must be complete")
    selected = [lookup[key] for key in expected]
    for row in selected:
        source = (assets / row["path"]).resolve(strict=True)
        source.relative_to(assets)
        if source.is_symlink() or digest(source) != row["sha256"]:
            raise ValueError("Trained checkpoint changed")
        if row["epochs_completed"] != contract["epochs"]:
            raise ValueError("Subject training exposure is unequal")
    output.mkdir(parents=True, exist_ok=False)
    public, target, private = output / "public" / TASK_ID, output / "target", output / "private"
    for folder in (public, target, private):
        folder.mkdir(parents=True)
    (public / "TASK.md").write_text(BRIEF)
    from scripts.build_weightspace_research_assets import ResearchCNN

    helper = "import torch\nfrom torch import nn\n\n" + inspect.getsource(ResearchCNN) + "\n"
    (public / "research_cnn.py").write_text(helper)
    discovery_files = [public / "TASK.md", public / "research_cnn.py"]
    transfer_files = []
    contexts = {}
    for role, folder in (("development", public), ("confirmation", target)):
        if role not in roles:
            continue
        role_rows = [r for r in selected if r["split"] == role]
        context_rows = []
        for block in range(blocks_per_split):
            for kind in ("shared", "independent"):
                names = []
                for row in role_rows:
                    if (row["block"], row["kind"]) == (block, kind):
                        source = assets / row["path"]
                        destination = folder / source.name
                        shutil.copy2(source, destination)
                        names.append(destination.name)
                        (discovery_files if role == "development" else transfer_files).append(
                            destination
                        )
                context_rows.append(
                    {
                        "context_id": f"block{block}_{kind}",
                        "training_block": block,
                        "lineage": kind,
                        "checkpoints": names,
                    }
                )
        contexts[role] = context_rows
        data_source = assets / (role + "-calibration.npz")
        with np.load(data_source, allow_pickle=False) as data:
            # The prefix is fixed before outcome inspection, identical for all contexts.
            data_arrays = {name: data[name][:512] for name in data.files}
            # Official train and test row numbers are separate namespaces, not
            # identities for the same images. Preserve a reversible split prefix.
            data_arrays["image_id"] = data_arrays["image_id"] + 100000
            np.savez_compressed(
                folder / ("calibration.npz" if role == "development" else "target-calibration.npz"),
                **data_arrays,
            )
        query_source = assets / (role + "-query.npz")
        with np.load(query_source, allow_pickle=False) as data:
            query_arrays = {
                name: data[name] for name in data.files if name != "labels" or role == "development"
            }
            np.savez_compressed(
                folder / ("development_query.npz" if role == "development" else "target-query.npz"),
                **query_arrays,
            )
            if role == "confirmation":
                np.savez_compressed(
                    private / "confirmation-labels.npz",
                    image_id=data["image_id"],
                    labels=data["labels"],
                )
        if role == "development":
            retain_json(folder / "DEVELOPMENT.json", {"contexts": context_rows})
            discovery_files += [
                folder / "calibration.npz",
                folder / "development_query.npz",
                folder / "DEVELOPMENT.json",
            ]
        else:
            retain_json(
                folder / "QUERY.json",
                {
                    "contexts": context_rows,
                    "query": "target-query.npz",
                    "calibration": "target-calibration.npz",
                },
            )
            transfer_files += [
                folder / "target-calibration.npz",
                folder / "target-query.npz",
                folder / "QUERY.json",
            ]
    # Canonical target asset names are read through QUERY.json, not hardcoded aliases.
    submission = {
        "schema_version": "1.0",
        "task_id": TASK_ID,
        "methods": ["primary", "key_control"],
        "hypotheses": [
            {
                "statement": "REPLACE with explanation",
                "discriminating_prediction": "REPLACE with observable prediction",
            },
            {
                "statement": "REPLACE with competing explanation",
                "discriminating_prediction": "REPLACE with discriminating observation",
            },
        ],
        "selection_rule": "REPLACE with a frozen selection rule",
        "fit_policy": "REPLACE with calibration-only fitting policy",
        "scope": "REPLACE with scientific scope and limits",
        "files": ["main.py", "research_cnn.py"],
        "entrypoint": "main.py",
    }
    retain_json(public / "SUBMISSION.example.json", submission)
    retain_json(
        public / "PROTOCOL.json",
        {
            "task_id": TASK_ID,
            "claim_rubric": CLAIMS,
            "primary_metrics": {"accuracy": "maximize; proportion", "nll": "minimize; nats"},
            "replication_unit": "training block; contexts share query images",
            "label_budget": 512,
            "image_identity": "calibration=100000+official_train_row; query=official_test_row",
            "development_blocks": blocks_per_split,
            "confirmation_blocks": 0 if development_only else blocks_per_split,
            "planned_confirmation_blocks": blocks_per_split,
            "authoring_development_only": development_only,
            "controller_training_required": False,
            "source_scope": "CIFAR-10 from scratch; not large pretrained model soups",
            "prior_work": [
                "https://proceedings.mlr.press/v162/wortsman22a.html",
                "https://arxiv.org/abs/2209.04836",
            ],
            "redistribution_authorized": False,
            "formal_evidence_eligible": False,
        },
    )
    retain_json(
        public / "REVIEW_PROTOCOL.json",
        {
            "task_id": TASK_ID,
            "visible_evidence": "development measurements and executed controls",
            "hidden_endpoints_excluded": True,
            "instruction": "Challenge unsupported compatibility explanations and selection bias; "
            "accept an evidence-supported negative result. Never demand a positive gain.",
            "claim_rubric": CLAIMS,
        },
    )
    discovery_files += [
        public / "SUBMISSION.example.json",
        public / "PROTOCOL.json",
        public / "REVIEW_PROTOCOL.json",
    ]
    files = {p.relative_to(output).as_posix(): digest(p) for p in output.rglob("*") if p.is_file()}
    manifest = {
        "schema_version": "1.0",
        "task_id": TASK_ID,
        "frozen_at": datetime.now(UTC).isoformat(),
        "source_commit": None,
        "task_families": 1,
        "benchmark_authored_annotations": True,
        "source": {
            "dataset": "official CIFAR-10",
            "dataset_sha256": contract["archive_sha256"],
            "training_contract": str((assets / "TRAINING_CONTRACT.json").relative_to(project)),
            "training_contract_sha256": digest(assets / "TRAINING_CONTRACT.json"),
        },
        "development_blocks": blocks_per_split,
        "confirmation_blocks": 0 if development_only else blocks_per_split,
        "confirmation_contexts": [r["context_id"] for r in contexts.get("confirmation", [])],
        "authoring_development_only": development_only,
        "selected_checkpoint_receipts": selected,
        "selection": "First preselected blocks per split, not accuracy-based filtering",
        "files": files,
        "discovery_files": [p.relative_to(output).as_posix() for p in discovery_files],
        "transfer_files": [p.relative_to(output).as_posix() for p in transfer_files],
        "permission": "local research only; no automatic dataset/weights redistribution",
        "private_labels_excluded_from_export": True,
        "formal_evidence_eligible": False,
        "source_family_independence": "Different data/research question from five prior candidate "
        "families; public-source prior exposure not ruled out",
    }
    retain_json(output / "PACK.json", manifest)
    return {
        "pack": str(output),
        "task_families": 1,
        "subject_models": len(selected),
        "formal_evidence_eligible": False,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for key in ("project", "assets", "output"):
        p.add_argument("--" + key, type=Path, required=True)
    p.add_argument("--blocks-per-split", type=int, choices=(2, 4), default=4)
    p.add_argument(
        "--development-only",
        action="store_true",
        help="Generate a separate authoring-only view for CPU references while targets train",
    )
    print(json.dumps(build(**vars(p.parse_args()))))


if __name__ == "__main__":
    main()
