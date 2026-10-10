"""Collect an existing remote attempt without launching or resuming any experiment."""

import argparse
import json
from pathlib import Path

from scitaste.executor.remote_unlearning import RemoteUnlearningExperiment


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempt", type=Path, required=True)
    parser.add_argument(
        "--credentials", type=Path, default=Path("outputs/resources/access/credentials.env")
    )
    args = parser.parse_args()
    attempt = args.attempt.resolve(strict=True)
    attempt.relative_to(Path("outputs/projects").resolve(strict=True))
    binding = json.loads((attempt / "BINDING.json").read_text())
    experiment = RemoteUnlearningExperiment(
        run_id=Path(binding["root"]).name,
        output=attempt,
        code_root=Path.cwd(),
        gpu_index=binding["gpu_index"],
        wall_seconds=binding["wall_seconds"],
        ssh_environment={
            "SCITASTE_ASKPASS_CREDENTIAL_FILE": str(args.credentials.resolve(strict=True)),
            "SCITASTE_ASKPASS_CREDENTIAL_NAME": "SCITASTE_GPU_4090_2_SSH_PASSWORD",
            "SSH_ASKPASS": str(Path("scripts/ssh_askpass_resource_registry.py").resolve()),
            "SSH_ASKPASS_REQUIRE": "force",
            "DISPLAY": ":0",
        },
    )
    result = experiment.observe()
    print(
        json.dumps(
            {
                "status": result["status"],
                "data": result.get("data"),
                "observations": result.get("observations"),
                "error": result.get("error"),
                "launch_performed": False,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
