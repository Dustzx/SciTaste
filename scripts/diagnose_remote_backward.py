"""Bounded random-input diagnostics after an actual remote backward failure."""

import argparse
import os
import shlex
import subprocess
from pathlib import Path

from scitaste.model_nodes.session_exchange import retain_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--legacy-only", action="store_true")
    args = parser.parse_args()
    root = Path.cwd()
    env = {
        **os.environ,
        "SCITASTE_ASKPASS_CREDENTIAL_FILE": str(root / "outputs/resources/access/credentials.env"),
        "SCITASTE_ASKPASS_CREDENTIAL_NAME": "SCITASTE_GPU_4090_2_SSH_PASSWORD",
        "SSH_ASKPASS": str(root / "scripts/ssh_askpass_resource_registry.py"),
        "SSH_ASKPASS_REQUIRE": "force",
        "DISPLAY": ":0",
    }
    cases = [
        ("eval-cudnn", False, True),
        ("eval-no-cudnn", False, False),
        ("train-cudnn", True, True),
    ]
    if args.legacy_only:
        cases = [("eval-legacy-cudnn", False, True)]
    for name, train, cudnn in cases:
        code = (
            "import torch; from torchvision.models import resnet18; torch.set_num_threads(4); "
            f"torch.backends.cudnn.enabled={cudnn!r}; "
            f"n=resnet18(weights=None,num_classes=10).cuda().train({train!r}); "
            + (
                "import os; os.environ['TORCH_CUDNN_V8_API_DISABLED']='1'; "
                if args.legacy_only
                else ""
            )
            + "x=torch.randn(128,3,32,32,device='cuda'); "
            "y=torch.randint(0,10,(128,),device='cuda'); "
            "torch.nn.functional.cross_entropy(n(x),y).backward(); torch.cuda.synchronize(); "
            "print('BACKWARD_OK',torch.__version__,torch.backends.cudnn.version())"
        )
        command = shlex.join(
            [
                "env",
                "CUDA_VISIBLE_DEVICES=6",
                "/data/zfx/scitaste/mlrc-meta-dev-20260925/venv/bin/python",
                "-c",
                code,
            ]
        )
        result = subprocess.run(
            ["ssh", "-T", "-o", "ClearAllForwardings=yes", "4090-2", command],
            env=env,
            start_new_session=True,
            capture_output=True,
            text=True,
            timeout=45,
        )
        args.output.mkdir(parents=True, exist_ok=True)
        retain_json(
            args.output / f"{name}.json",
            {
                "code": code,
                "host": "4090-2",
                "gpu_index": 6,
                "data": "Random inputs and untrained model; no benchmark measurements",
                "returncode": result.returncode,
                "stdout": result.stdout[-8000:],
                "stderr": result.stderr[-8000:],
                "api_calls": 0,
            },
        )
        print(name, result.returncode, result.stdout.strip(), flush=True)


if __name__ == "__main__":
    main()
