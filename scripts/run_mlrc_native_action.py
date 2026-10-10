#!/usr/bin/env python3
"""Dispatch a previously selected, explicitly bound remote action through Native."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scitaste.executor.native import SciTasteNativeExecutor
from scitaste.executor.remote_mlrc import RemoteMLRCActionHandler, RemoteMLRCBinding
from scitaste.schema.actions import ResearchAction
from scitaste.state.research_state import ResearchState


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("binding", "state", "action", "workspace", "artifact-root", "credentials-file"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--credential-name", default="SCITASTE_GPU_4090_2_SSH_PASSWORD")
    parser.add_argument("--allow-launch", action="store_true")
    args = parser.parse_args()
    binding = RemoteMLRCBinding(**json.loads(args.binding.read_text()))
    state = ResearchState.model_validate_json(args.state.read_text())
    action = ResearchAction.model_validate_json(args.action.read_text())
    handler = RemoteMLRCActionHandler(
        project_id=state.project_id,
        binding=binding,
        workspace=args.workspace / "remote",
        artifact_root=args.artifact_root,
        allow_launch=args.allow_launch,
        ssh_environment={
            "SCITASTE_ASKPASS_CREDENTIAL_FILE": str(args.credentials_file.resolve(strict=True)),
            "SCITASTE_ASKPASS_CREDENTIAL_NAME": args.credential_name,
            "SSH_ASKPASS": str(
                Path(__file__).with_name("ssh_askpass_resource_registry.py").resolve()
            ),
            "SSH_ASKPASS_REQUIRE": "force",
            "DISPLAY": ":0",
        },
    )
    executor = SciTasteNativeExecutor(
        handlers={action.type: handler},
        workspace=args.workspace / "native",
        artifact_root=args.artifact_root,
    )
    print(executor.execute(state, action).model_dump_json(indent=2))


if __name__ == "__main__":
    main()
