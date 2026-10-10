"""Package-owned I/O and provider support for Native workspace execution."""

import hashlib
import json
import os

import httpx

from scitaste.backends.mlagentbench import provider_ledger_accounting
from scitaste.backends.openai_compatible import HttpxTransport
from scitaste.backends.openai_compatible import OpenAICompatibleBackend as OpenAICompatibleBackend
from scitaste.backends.openai_compatible import OpenAICompatibleConfig as OpenAICompatibleConfig
from scitaste.backends.replay import ResumableRecordingBackend as ResumableRecordingBackend
from scitaste.model_nodes.openai_compatible import (
    load_structured_openai_compatible_config as load_structured_openai_compatible_config,
)
from scitaste.project.models import ProjectRun
from scitaste.project.runtime import ProjectRuntime as ProjectRuntime
from scitaste.state.research_state import ResearchStage as ResearchStage
from scitaste.state.research_state import ResearchState as ResearchState
from scitaste.state.research_state import ResourceBudget as ResourceBudget
from scitaste.taste.controller import TasteController as TasteController


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bind_credential(path, name):
    if not path.exists() and not path.is_symlink() and os.environ.get(name):
        return
    if not path.is_file() or path.is_symlink() or path.stat().st_mode & 0o077:
        raise ValueError("credential file must be a regular mode-0600 file")
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not key.isidentifier() or key in values:
            raise ValueError("credential file has an invalid binding")
        values[key] = value
    if not values.get(name):
        raise ValueError("Credential file lacks the configured provider key")
    os.environ[name] = values[name]


def write_new(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        stream.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def api_ceiling(output):
    return provider_ledger_accounting(output / "logs/provider_calls")["liability_usd"]


def register_progress(project, output, status, *, provider, model):
    runtime = ProjectRuntime(project.parent.parent)
    snapshot = runtime.open(project.name)
    artifact = output / ("RESULT.json" if (output / "RESULT.json").exists() else "CONTRACT.json")
    changes = {"status": status, "artifact": artifact.relative_to(project).as_posix()}
    existing = next((r for r in snapshot.manifest.runs if r.run_id == output.name), None)
    if existing is None:
        runtime.begin_run(
            project.name,
            ProjectRun(
                run_id=output.name,
                provider=provider,
                model=model,
                condition="native-workspace-development",
                seed=0,
                seed_semantics="registration placeholder; no deterministic provider seed implied",
                evidence_scope="development task; not formal method evidence",
                formal_evidence_eligible=False,
                **changes,
            ),
            expected_revision=snapshot.manifest.revision,
        )
    elif (existing.provider, existing.model) != (provider, model):
        raise ValueError("Registered run cannot switch provider/model")
    elif existing.status != status or existing.artifact != changes["artifact"]:
        runtime.update_run(
            project.name, output.name, expected_revision=snapshot.manifest.revision, **changes
        )


class RecordedTransport(HttpxTransport):
    def __init__(self, path):
        self.path = path

    def post(self, url, *, headers, payload, timeout):
        with httpx.Client(timeout=timeout, trust_env=False) as client:
            raw = client.post(url, headers=headers, json=payload)
            raw.raise_for_status()
            response = raw.json()
        # Authorization headers are never serialized.
        with self.path.open("a") as stream:
            stream.write(json.dumps({"request": payload, "response": response}) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        return response


class PreferenceTransport:
    """Rank alternatives through the same durable request/cost ledger."""

    def __init__(self, bridge):
        self.bridge = bridge

    def post(self, url, *, headers, payload, timeout):
        del url, headers, timeout
        index = len(list(self.bridge.records.glob("*.json")))
        self.bridge.complete_text(
            json.dumps(payload["messages"], ensure_ascii=False),
            self.bridge.root / f"rank-{index}.log",
            payload["model"],
            max_tokens_to_sample=payload.get("max_tokens", 4096),
            stop_sequences=None,
        )
        return json.loads((self.bridge.records / f"{index:05d}.response").read_text())
