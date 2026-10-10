"""Source-preservation check; does not import Torch or launch an experiment."""

import ast
from pathlib import Path

import pytest

from scitaste.evaluation.mlrc_unlearning import (
    DEV_FUNCTIONS,
    development_scorer_source,
    offline_loader_source,
)


def test_pinned_development_extraction_preserves_scoring():
    root = Path(__file__).resolve().parents[2]
    env = root / (
        "outputs/projects/scitaste-self-development/evaluations/acquisitions/"
        "mlrc-bench-source-v1/checkout/MLAgentBench/benchmarks_base/machine_unlearning/env"
    )
    if not env.is_dir():
        pytest.skip("Pinned upstream acquisition is not installed")
    source = development_scorer_source(env)
    original = ast.parse((env / "evaluation.py").read_text())
    extracted = ast.parse(source)
    old_functions = {n.name: ast.dump(n) for n in original.body if isinstance(n, ast.FunctionDef)}
    new_functions = {n.name: ast.dump(n) for n in extracted.body if isinstance(n, ast.FunctionDef)}
    assert set(new_functions) == set(DEV_FUNCTIONS)
    assert all(value == old_functions[name] for name, value in new_functions.items())
    assert "kaggle" not in source.lower()
    assert "_evaluate_test" not in source
    compile(source, "evaluation_dev.py", "exec")
    loader = offline_loader_source(env)
    assert "requests" not in loader
    calls = [n for n in ast.walk(ast.parse(loader)) if isinstance(n, ast.Call)]
    for call in calls:
        name = ast.unparse(call.func)
        keywords = {
            k.arg: ast.literal_eval(k.value)
            for k in call.keywords
            if k.arg in {"weights_only", "download", "allow_pickle"}
        }
        if name == "torch.load":
            assert keywords["weights_only"] is True
        if name == "torchvision.datasets.CIFAR10":
            assert keywords["download"] is False
        if name == "np.load":
            assert keywords["allow_pickle"] is False
    compile(loader, "load_cifar_script.py", "exec")
