"""Compile a typed, source-bound artifact handoff before a costly READY boundary.

The model chooses dependencies; deterministic code verifies and stages exact
bytes. This is neither scientific source repair nor another experiment. No private
query can observe a partial bundle. Reusing a completed READY is forbidden.
"""

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator


class HandoffModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def relative_name(value):
    path = Path(value)
    if not value or path.is_absolute() or ".." in path.parts or str(path) != value:
        raise ValueError("Handoff paths must be canonical workspace-relative names")
    return path


class SourceArtifact(HandoffModel):
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def confined(self):
        relative_name(self.path)
        return self


class ArtifactHandoff(HandoffModel):
    manifest: SourceArtifact
    files: dict[str, SourceArtifact] = Field(min_length=1, max_length=32)
    directory: str = "submission"

    @model_validator(mode="after")
    def confined(self):
        relative_name(self.directory)
        for name in self.files:
            relative_name(name)
        return self


def read_bound(workspace, source):
    path = workspace / source.path
    token = relative_name(source.path)
    if {part.casefold() for part in token.parts} & {
        "credentials",
        ".ssh",
        ".git",
        "exchange",
    } or any(part.startswith(".env") for part in token.parts):
        raise ValueError("Private/credential paths are not submission dependencies")
    if any(
        (workspace / Path(*token.parts[:i])).is_symlink() for i in range(1, len(token.parts) + 1)
    ):
        raise ValueError("Handoff dependencies may not be symlinks")
    path.resolve(strict=True).relative_to(workspace)
    if not path.is_file() or path.stat().st_size > 32_000_000:
        raise ValueError("Handoff dependencies must be bounded regular files")
    if path.suffix.casefold() in {".env", ".pem", ".key"}:
        raise ValueError("Credentials are not submission dependencies")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != source.sha256:
        raise ValueError("Scientific source changed since the proposed handoff")
    return raw


def freeze_submission(environment, arguments):
    proposal = ArtifactHandoff.model_validate(arguments)
    workspace = environment.workspace
    destination = workspace / proposal.directory
    relative = destination.resolve().relative_to(workspace)
    if any(
        relative == Path(p) or Path(p) in relative.parents
        for p in environment.research_harness.profile.protected_paths
    ):
        raise ValueError("Handoff cannot mutate protected research inputs")
    if destination.exists():
        raise ValueError("Submission destination already exists; never replace a frozen handoff")
    if (workspace / "confirmation_feedback.json").exists():
        raise ValueError("Consumed confirmation requires a separately allocated continuation")
    manifest_raw = read_bound(workspace, proposal.manifest)
    manifest = json.loads(manifest_raw)
    declared = manifest.get("files")
    if not isinstance(declared, list) or not declared or len(declared) != len(set(declared)):
        raise ValueError("Submission manifest needs distinct declared source files")
    if set(declared) != set(proposal.files) or manifest.get("entrypoint") not in declared:
        raise ValueError("Handoff must bind exactly every declared file and entrypoint")
    if {"READY", "SUBMISSION.json", "HANDOFF.json"} & set(declared):
        raise ValueError("Sources may not replace handoff control files")
    contents = {name: read_bound(workspace, source) for name, source in proposal.files.items()}
    if sum(map(len, contents.values())) + len(manifest_raw) > 64_000_000:
        raise ValueError("Source-bound submission exceeds its allocation")
    receipt = {
        "manifest_sha256": proposal.manifest.sha256,
        "files": {name: source.model_dump(mode="json") for name, source in proposal.files.items()},
        "provided_source_bytes_changed": False,
        "provided_manifest_bytes_changed": False,
        "scientific_success_established": False,
        "additional_model_calls": 0,
        "handoff_policy": "all-dependencies-before-atomic-ready-v1",
    }
    # Validate EVERY dependency before any destination mutation. Stage READY last,
    # then rename the complete directory atomically on the same filesystem.
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".source-handoff-", dir=destination.parent))
    try:
        for name, raw in contents.items():
            target = staging / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(raw)
        with (staging / "SUBMISSION.json").open("xb") as stream:
            stream.write(manifest_raw)
        with (staging / "HANDOFF.json").open("x") as stream:
            json.dump(receipt, stream, indent=2)
        (staging / "READY").touch(exist_ok=False)
        os.rename(staging, destination)
    except Exception:
        # This temporary directory is this operation's own exact, validated target.
        shutil.rmtree(staging)
        raise
    return json.dumps(receipt)
