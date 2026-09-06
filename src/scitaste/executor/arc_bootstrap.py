"""Process-local compatibility controls before delegating to upstream's CLI."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

_TRACE_EXCERPT_CHARS = 262_144


def _bounded_excerpt(value: str) -> tuple[str, bool]:
    if len(value) <= _TRACE_EXCERPT_CHARS * 2:
        return value, False
    omitted = len(value) - (_TRACE_EXCERPT_CHARS * 2)
    return (
        value[:_TRACE_EXCERPT_CHARS]
        + f"\n... [SciTaste trace omitted {omitted} characters] ...\n"
        + value[-_TRACE_EXCERPT_CHARS:],
        True,
    )


def _install_sandbox_trace() -> None:
    """Persist the exact successful runtime result that upstream may summarize away."""

    from researchclaw.experiment.sandbox import ExperimentSandbox

    upstream_run_project = ExperimentSandbox.run_project
    if getattr(upstream_run_project, "_scitaste_traced", False):
        return

    def traced_run_project(self, project_dir, *args, **kwargs):
        project = Path(project_dir).resolve()
        source_sha256 = {
            path.relative_to(project).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(project.rglob("*"))
            if path.is_file() and not path.is_symlink()
        }
        result = upstream_run_project(self, project_dir, *args, **kwargs)
        stdout = str(getattr(result, "stdout", "") or "")
        stderr = str(getattr(result, "stderr", "") or "")
        stdout_excerpt, stdout_truncated = _bounded_excerpt(stdout)
        stderr_excerpt, stderr_truncated = _bounded_excerpt(stderr)
        payload = {
            "schema_version": "1.0",
            "method": "process-local-sandbox-result-trace-v1",
            "returncode": int(getattr(result, "returncode", -1)),
            "timed_out": bool(getattr(result, "timed_out", False)),
            "elapsed_sec": float(getattr(result, "elapsed_sec", 0.0)),
            "metrics": getattr(result, "metrics", {}) or {},
            "project_source_sha256": source_sha256,
            "stdout_sha256": hashlib.sha256(stdout.encode()).hexdigest(),
            "stderr_sha256": hashlib.sha256(stderr.encode()).hexdigest(),
            "stdout_bytes": len(stdout.encode()),
            "stderr_bytes": len(stderr.encode()),
            "stdout_excerpt": stdout_excerpt,
            "stderr_excerpt": stderr_excerpt,
            "stdout_truncated": stdout_truncated,
            "stderr_truncated": stderr_truncated,
        }
        destination = Path(self.workdir) / "scitaste_execution_trace.json"
        temporary = destination.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, destination)
        return result

    traced_run_project._scitaste_traced = True
    ExperimentSandbox.run_project = traced_run_project


def _install_offline_literature() -> None:
    """Disable every upstream literature-network path for frozen-snapshot cells."""

    from researchclaw.literature import search as literature_search
    from researchclaw.literature import verify as literature_verify

    literature_search.search_papers = lambda *args, **kwargs: []
    literature_search.search_papers_multi_query = lambda *args, **kwargs: []

    def verify_frozen_citations(bib_text: str, **_kwargs: Any):
        entries = literature_verify.parse_bibtex_entries(bib_text)
        return literature_verify.VerificationReport(total=len(entries), skipped=len(entries))

    literature_verify.verify_citations = verify_frozen_citations


def _install_frozen_benchmark_asset() -> None:
    """Inject one content-addressed task kernel into each upstream sandbox project."""

    from researchclaw.experiment import validator
    from researchclaw.experiment.sandbox import ExperimentSandbox
    from researchclaw.pipeline.stage_impls import _code_generation

    source = Path(os.environ["SCITASTE_ARC_FROZEN_BENCHMARK_PATH"])
    expected_sha256 = os.environ["SCITASTE_ARC_FROZEN_BENCHMARK_SHA256"]
    module = os.environ["SCITASTE_ARC_FROZEN_BENCHMARK_MODULE"]
    entrypoint = Path(os.environ["SCITASTE_ARC_FROZEN_ENTRYPOINT_PATH"])
    expected_entrypoint_sha256 = os.environ["SCITASTE_ARC_FROZEN_ENTRYPOINT_SHA256"]
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError("invalid frozen benchmark SHA-256")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", module):
        raise ValueError("invalid frozen benchmark module name")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_entrypoint_sha256):
        raise ValueError("invalid frozen benchmark entrypoint SHA-256")
    if not source.is_file() or source.is_symlink():
        raise ValueError("frozen benchmark source is not a regular file")
    if not entrypoint.is_file() or entrypoint.is_symlink():
        raise ValueError("frozen benchmark entrypoint is not a regular file")
    payload = source.read_bytes()
    entrypoint_payload = entrypoint.read_bytes()
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise ValueError("frozen benchmark source hash does not match")
    if hashlib.sha256(entrypoint_payload).hexdigest() != expected_entrypoint_sha256:
        raise ValueError("frozen benchmark entrypoint hash does not match")
    source_text = payload.decode("utf-8")
    entrypoint_text = entrypoint_payload.decode("utf-8")

    upstream_extract = _code_generation._extract_multi_file_blocks
    if not getattr(upstream_extract, "_scitaste_frozen_benchmark", False):

        def frozen_extract(content):
            files = upstream_extract(content)
            if "main.py" in files:
                files["main.py"] = entrypoint_text
                files[f"{module}.py"] = source_text
            return files

        frozen_extract._scitaste_frozen_benchmark = True
        _code_generation._extract_multi_file_blocks = frozen_extract

    upstream_auto_fix = validator.auto_fix_unbound_locals
    if not getattr(upstream_auto_fix, "_scitaste_frozen_benchmark", False):

        def preserve_frozen_sources(code):
            digest = hashlib.sha256(code.encode("utf-8")).hexdigest()
            if digest in {expected_sha256, expected_entrypoint_sha256}:
                return code, 0
            return upstream_auto_fix(code)

        preserve_frozen_sources._scitaste_frozen_benchmark = True
        validator.auto_fix_unbound_locals = preserve_frozen_sources

    upstream_run_project = ExperimentSandbox.run_project
    if getattr(upstream_run_project, "_scitaste_frozen_benchmark", False):
        return

    def frozen_run_project(self, project_dir, *args, **kwargs):
        project = Path(project_dir).resolve()
        project.mkdir(parents=True, exist_ok=True)
        injections = (
            (project / "main.py", entrypoint_payload, expected_entrypoint_sha256),
            (project / f"{module}.py", payload, expected_sha256),
        )
        for destination, exact_payload, exact_sha256 in injections:
            if destination.is_symlink():
                raise ValueError("frozen benchmark destination cannot be a symlink")
            temporary = destination.with_suffix(destination.suffix + ".tmp")
            temporary.write_bytes(exact_payload)
            os.replace(temporary, destination)
            if hashlib.sha256(destination.read_bytes()).hexdigest() != exact_sha256:
                raise ValueError("injected frozen benchmark hash does not match")
        return upstream_run_project(self, project_dir, *args, **kwargs)

    frozen_run_project._scitaste_frozen_benchmark = True
    ExperimentSandbox.run_project = frozen_run_project


def main(argv: Sequence[str] | None = None) -> int:
    """Run unmodified ResearchClaw with an explicit per-call output-token ceiling."""

    raw_limit = os.environ.get("SCITASTE_ARC_MAX_OUTPUT_TOKENS", "")
    raw_total_limit = os.environ.get("SCITASTE_ARC_MAX_TOTAL_TOKENS", "")
    telemetry_path = os.environ.get("SCITASTE_ARC_TELEMETRY_PATH", "")
    if os.environ.get("SCITASTE_ARC_TRACE_SANDBOX", "").casefold() in {"1", "true", "yes"}:
        _install_sandbox_trace()
    if os.environ.get("SCITASTE_ARC_FROZEN_BENCHMARK_PATH"):
        _install_frozen_benchmark_asset()
    if os.environ.get("SCITASTE_ARC_OFFLINE", "").casefold() in {"1", "true", "yes"}:
        _install_offline_literature()
    if os.environ.get("SCITASTE_ARC_DISABLE_THINKING", "").casefold() in {"1", "true", "yes"}:
        import urllib.request

        upstream_request = urllib.request.Request

        def controlled_request(url: Any, data: Any = None, *args: Any, **kwargs: Any):
            if isinstance(data, bytes):
                try:
                    body = json.loads(data)
                except (TypeError, ValueError):
                    body = None
                if (
                    isinstance(body, dict)
                    and "model" in body
                    and ("messages" in body or "input" in body)
                ):
                    body["enable_thinking"] = False
                    data = json.dumps(body).encode("utf-8")
            return upstream_request(url, data, *args, **kwargs)

        urllib.request.Request = controlled_request
    if raw_limit or raw_total_limit or telemetry_path:
        limit = int(raw_limit) if raw_limit else 0
        total_limit = int(raw_total_limit) if raw_total_limit else 0
        if raw_limit and limit <= 0:
            raise ValueError("SCITASTE_ARC_MAX_OUTPUT_TOKENS must be positive")
        if raw_total_limit and total_limit <= 0:
            raise ValueError("SCITASTE_ARC_MAX_TOTAL_TOKENS must be positive")
        from researchclaw.llm.client import LLMClient

        upstream_chat = LLMClient.chat
        cumulative_tokens = 0
        if telemetry_path and Path(telemetry_path).is_file():
            for line in Path(telemetry_path).read_text(encoding="utf-8").splitlines():
                if line.strip():
                    cumulative_tokens += int(json.loads(line).get("total_tokens", 0) or 0)

        def request_size_upper_bound(args: tuple[Any, ...], kwargs: dict[str, Any]) -> int:
            """Return a conservative token bound without provider-specific tokenizers."""

            payload = {
                "args": args,
                "messages": kwargs.get("messages"),
                "system": kwargs.get("system"),
            }
            rendered = json.dumps(payload, ensure_ascii=False, default=str)
            # These English/code prompts empirically track about four UTF-8 bytes
            # per provider-counted token. Exact usage is still checked after every
            # response, so this estimate only sizes the remaining output allowance.
            return max(1, (len(rendered.encode("utf-8")) + 3) // 4)

        def bounded_chat(self, *args: Any, **kwargs: Any):
            nonlocal cumulative_tokens
            if raw_limit:
                requested = kwargs.get("max_tokens")
                kwargs["max_tokens"] = limit if requested is None else min(int(requested), limit)
            if raw_total_limit:
                remaining = total_limit - cumulative_tokens
                prompt_bound = request_size_upper_bound(args, kwargs)
                available_output = remaining - prompt_bound
                if available_output <= 0:
                    raise RuntimeError(
                        "SciTaste cumulative LLM token budget exhausted before request"
                    )
                requested = int(kwargs.get("max_tokens") or available_output)
                kwargs["max_tokens"] = min(requested, available_output)
            started = time.perf_counter()
            response = upstream_chat(self, *args, **kwargs)
            observed_tokens = int(getattr(response, "total_tokens", 0) or 0)
            cumulative_tokens += observed_tokens
            if telemetry_path:
                record = {
                    "schema_version": "1.0",
                    "model": getattr(response, "model", ""),
                    "prompt_tokens": int(getattr(response, "prompt_tokens", 0) or 0),
                    "completion_tokens": int(getattr(response, "completion_tokens", 0) or 0),
                    "total_tokens": int(getattr(response, "total_tokens", 0) or 0),
                    "latency_seconds": time.perf_counter() - started,
                }
                destination = Path(telemetry_path)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with destination.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, sort_keys=True) + "\n")
            if raw_total_limit and cumulative_tokens > total_limit:
                raise RuntimeError(
                    "SciTaste cumulative LLM token budget exceeded: "
                    f"{cumulative_tokens} > {total_limit}"
                )
            return response

        LLMClient.chat = bounded_chat

    from researchclaw.cli import main as upstream_main

    return upstream_main(list(argv) if argv is not None else None)


if __name__ == "__main__":  # pragma: no cover - exercised in the child process
    raise SystemExit(main())
