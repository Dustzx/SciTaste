"""Collect original per-domain meta-learning scores without another evaluation."""

import argparse
import hashlib
import json
import math
import os
import shlex
import subprocess
from pathlib import Path

from scitaste.executor.remote_mlrc import RemoteMLRCBinding
from scitaste.model_nodes.session_exchange import retain_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument(
        "--credentials", type=Path, default=Path("outputs/resources/access/credentials.env")
    )
    args = parser.parse_args()
    result = json.loads((args.run / "EXECUTION_RESULT.json").read_text())
    if result["status"] != "SUCCEEDED":
        raise ValueError("Only completed evaluations have scored domain details")
    binding = RemoteMLRCBinding(**json.loads((args.run / "BINDING.json").read_text()))
    path = binding.output_root + "/scoring_output/scores.txt"
    env = {
        **os.environ,
        "SCITASTE_ASKPASS_CREDENTIAL_FILE": str(args.credentials.resolve(strict=True)),
        "SCITASTE_ASKPASS_CREDENTIAL_NAME": "SCITASTE_GPU_4090_2_SSH_PASSWORD",
        "SSH_ASKPASS": str(Path("scripts/ssh_askpass_resource_registry.py").resolve()),
        "SSH_ASKPASS_REQUIRE": "force",
        "DISPLAY": ":0",
    }
    command = shlex.join(
        [
            binding.python,
            "-c",
            "import sys; from pathlib import Path; "
            "sys.stdout.buffer.write(Path(sys.argv[1]).read_bytes())",
            path,
        ]
    )
    raw = subprocess.check_output(
        [
            "ssh",
            "-T",
            "-o",
            "ClearAllForwardings=yes",
            "-o",
            "ConnectTimeout=10",
            binding.host,
            command,
        ],
        env=env,
        start_new_session=True,
        timeout=30,
    )
    digest = hashlib.sha256(raw).hexdigest()
    if digest != result["data"]["receipt"]["score_file_sha256"]:
        raise ValueError("Remote score file differs from measured receipt")
    scores = {}
    for line in raw.decode().splitlines():
        key, separator, value = line.partition(":")
        number = float(value)
        if not separator or key in scores or not math.isfinite(number):
            raise ValueError("Malformed or duplicate official score entry")
        scores[key] = number
    if scores["overall_score"] != result["data"]["primary_value"]:
        raise ValueError("Primary score mismatch")
    retain_json(
        args.run / "SCORE_DETAILS.json",
        {
            "source": path,
            "source_sha256": digest,
            "execution_result_sha256": hashlib.sha256(
                (args.run / "EXECUTION_RESULT.json").read_bytes()
            ).hexdigest(),
            "official_scores": scores,
            "raw_score_text": raw.decode(),
            "new_evaluations": 0,
            "formal_evidence_eligible": False,
            "interpretation": "Official within-evaluation domain/way/shot summaries, "
            "not independent research-agent replications.",
        },
    )
    print(json.dumps({"collected_metrics": len(scores), "new_evaluations": 0}))


if __name__ == "__main__":
    main()
