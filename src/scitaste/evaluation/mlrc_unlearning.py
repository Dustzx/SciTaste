"""Build a source-bound, offline MLRC unlearning development scorer.

This prepares trusted evaluation code, not a candidate execution sandbox. Never
run agent-authored methods in the trusted scorer process: reference weights and
held-out development examples belong only to the evaluator.
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

EVALUATION_SHA256 = "8bc1bbc03dde8eab3d9a104bddc2e0654bae2d513b2c5040564ede0e1e152d14"
LOADER_SHA256 = "8288a0292d3df4d3d44ee85538dd9b6c2eb4fb27a95ac5f9d2cd7b651052fbb6"
DEV_FUNCTIONS = (
    "accuracy",
    "compute_outputs",
    "false_positive_rate",
    "false_negative_rate",
    "cross_entropy_f",
    "logistic_regression_attack",
    "best_threshold_attack",
    "compute_epsilon_s",
    "bin_index_fn",
    "F",
    "forgetting_quality",
    "_evaluate_dev",
)


def _verified_source(path: Path, expected: str) -> str:
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError(f"Unreviewed MLRC source: {path.name}")
    return raw.decode("utf-8")


def development_scorer_source(env_dir: Path) -> str:
    """Keep original dev function text; exclude Kaggle and test submission code.

    The ten-model protocol, Gaussian reference approximation and score formula
    are deliberately unchanged. This is the upstream *development proxy*, not
    the competition's private evaluation or a certified privacy guarantee.
    """
    source = _verified_source(env_dir / "evaluation.py", EVALUATION_SHA256)
    tree = ast.parse(source)
    selected: list[str] = []
    found: list[str] = []
    for node in tree.body:
        keep = False
        if isinstance(node, ast.FunctionDef) and node.name in DEV_FUNCTIONS:
            keep = True
            found.append(node.name)
        elif isinstance(node, ast.Assign):
            keep = any(isinstance(t, ast.Name) and t.id == "SCORING" for t in node.targets)
        if keep:
            segment = ast.get_source_segment(source, node)
            assert segment is not None
            selected.append(segment)
    if tuple(found) != DEV_FUNCTIONS:
        raise ValueError("Unexpected development scorer function inventory")
    header = """# Extracted from pinned MLRC source; development only.
import os
from copy import deepcopy
from typing import Callable
import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader
from sklearn import linear_model, model_selection
from sklearn.metrics import make_scorer
from tqdm import tqdm
from load_cifar_script import get_cifar10_data, get_cifar10_pretrained_models
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
NUM_MODELS = 10
"""
    return header + "\n\n" + "\n\n".join(selected) + "\n"


class _OfflineLoader(ast.NodeTransformer):
    """Only remove downloads and restrict deserialization; preserve data splits."""

    def visit_Import(self, node: ast.Import) -> ast.Import | None:
        node.names = [name for name in node.names if name.name != "requests"]
        return node if node.names else None

    def visit_If(self, node: ast.If) -> ast.AST | None:
        # Exact upstream source is digest-bound above, not arbitrary candidate code.
        if ast.unparse(node.test) == "not os.path.exists(local_path)":
            return None
        return self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> ast.AST:
        self.generic_visit(node)
        name = ast.unparse(node.func)
        for keyword in node.keywords:
            if (name == "torchvision.datasets.CIFAR10" and keyword.arg == "download") or (
                name == "np.load" and keyword.arg == "allow_pickle"
            ):
                keyword.value = ast.Constant(False)
        if name == "torch.load":
            node.keywords.append(ast.keyword(arg="weights_only", value=ast.Constant(True)))
        return node


def offline_loader_source(env_dir: Path) -> str:
    """Build evaluator-only loader; missing assets fail instead of downloading."""
    source = _verified_source(env_dir / "load_cifar_script.py", LOADER_SHA256)
    tree = _OfflineLoader().visit(ast.parse(source))
    ast.fix_missing_locations(tree)
    return (
        "# Offline trusted evaluator loader; do not expose to candidates.\n"
        + ast.unparse(tree)
        + "\n"
    )
