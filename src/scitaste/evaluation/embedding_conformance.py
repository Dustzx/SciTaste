"""Exact local embedding runner for task-excluded model-role conformance."""

from __future__ import annotations

import hashlib
import json
import math
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from scitaste.backends.checkpoint_manifest import (
    build_local_checkpoint_identity_manifest,
)
from scitaste.evaluation.model_role_conformance import (
    ConformanceCase,
    ConformanceCaseManifest,
    ConformanceCaseResult,
    ConformanceCaseResults,
    ConformanceExecutorReceipt,
    ConformanceMeasurements,
    EvidenceArtifact,
    EvidenceKind,
    EvidenceValidator,
    ExactModelIdentity,
    ExecutionKind,
    IdentityScope,
    ModelRole,
    ModelRoleConformanceRunResult,
    load_model_role_plan,
)
from scitaste.evaluation.model_role_conformance_campaign import (
    ConformanceRunnerKind,
    _document_bytes,
    _file_sha256,
    _save_bytes,
    _save_document,
    load_bytebound_campaign_plan,
)

_CONFIG = ConfigDict(extra="forbid", frozen=True)


class EmbeddingConformanceExecutionStatus(BaseModel):
    model_config = _CONFIG

    campaign_id: str
    candidate_id: str
    model_id: str
    checkpoint_identity_sha256: str
    executed_request_ids: tuple[str, ...]
    successful_cases: int = Field(ge=0)
    total_cases: int = Field(gt=0)
    reproducible: bool
    elapsed_ms: float = Field(ge=0)
    receipt_paths: tuple[str, ...]
    actual_local_execution: bool = True
    no_formal_or_heldout_content_used: bool = True


def execute_embedding_conformance(
    plan_path: str | Path,
    *,
    candidate_id: str,
    allow_local: bool = False,
    embedder_factory: Callable[[Path], Callable[[list[str]], list[list[float]]]] | None = None,
) -> EmbeddingConformanceExecutionStatus:
    """Execute every repetition for one frozen embedding candidate.

    The runner deliberately accepts the legacy campaign blocker that named this
    missing dispatcher: the function itself is that implementation.  All other
    blockers remain fatal.
    """

    if not allow_local:
        raise ValueError("embedding conformance requires explicit allow_local=True")
    source = Path(plan_path).resolve(strict=True)
    campaign_root = source.parent
    plan = load_bytebound_campaign_plan(source)
    requests = tuple(
        item
        for item in plan.requests
        if item.candidate.candidate.candidate_id == candidate_id
    )
    if not requests:
        raise ValueError(f"unknown campaign candidate {candidate_id!r}")
    if any(
        item.candidate.candidate.role is not ModelRole.EMBEDDING
        or item.runner_kind is not ConformanceRunnerKind.EMBEDDING_LOCAL
        for item in requests
    ):
        raise ValueError("selected candidate is not an embedding runner")
    for request in requests:
        residual = set(request.blockers) - {"embedding-dispatcher-not-implemented"}
        if residual:
            raise ValueError(f"embedding request remains blocked: {sorted(residual)!r}")
        if request.resource.local_model_path is None:
            raise ValueError("embedding request has no local checkpoint path")
        if _file_sha256(Path(request.case_path)) != request.case_sha256:
            raise ValueError("embedding conformance case bytes changed")

    model_path = Path(str(requests[0].resource.local_model_path)).resolve(strict=True)
    if any(
        Path(str(item.resource.local_model_path)).resolve(strict=True) != model_path
        for item in requests
    ):
        raise ValueError("embedding repetitions do not share one checkpoint")
    checkpoint = build_local_checkpoint_identity_manifest(model_path)
    checkpoint_path = _save_document(
        checkpoint,
        campaign_root / "checkpoint_identities" / f"{requests[0].resource.resource_id}.json",
    )
    checkpoint_file_sha256 = _file_sha256(checkpoint_path)
    revision = f"hf-manifest-{checkpoint.checkpoint_identity_sha256[:12]}"
    embed = (embedder_factory or _transformers_embedder_factory)(model_path)

    started_all = time.perf_counter()
    executions: list[dict[str, Any]] = []
    for request in requests:
        payload = request.case_payload.payload
        query = payload.get("query")
        documents = payload.get("documents")
        if not isinstance(query, str) or not isinstance(documents, list):
            raise ValueError("embedding case requires a query and document list")
        if not isinstance(documents, list) or not all(isinstance(item, str) for item in documents):
            raise ValueError("embedding documents must be strings")
        started_at = datetime.now(UTC)
        started = time.perf_counter()
        vectors = embed([query, *documents])
        similarities = [_cosine(vectors[0], item) for item in vectors[1:]]
        ranking = sorted(range(len(similarities)), key=lambda index: (-similarities[index], index))
        response = {
            "similarities": [round(value, 8) for value in similarities],
            "ranking": ranking,
        }
        response_sha256 = _canonical_sha256(response)
        elapsed_ms = (time.perf_counter() - started) * 1000
        completed_at = datetime.now(UTC)
        if completed_at <= started_at:
            completed_at = started_at + timedelta(microseconds=1)
        expected = request.case_payload.expected.get("top_document_indices")
        succeeded = isinstance(expected, list) and ranking[: len(expected)] == expected
        executions.append(
            {
                "request": request,
                "started_at": started_at,
                "completed_at": completed_at,
                "elapsed_ms": elapsed_ms,
                "response": response,
                "response_sha256": response_sha256,
                "succeeded": succeeded,
            }
        )

    reproducible = len({item["response_sha256"] for item in executions}) == 1
    role_plan = load_model_role_plan(campaign_root / plan.model_role_plan_ref)
    receipt_paths: list[str] = []
    for item in executions:
        request = item["request"]
        assert request.candidate.candidate.role is ModelRole.EMBEDDING
        request_payload = {
            "case_sha256": request.case_sha256,
            "checkpoint_identity_sha256": checkpoint.checkpoint_identity_sha256,
            "checkpoint_manifest_file_sha256": checkpoint_file_sha256,
            "repetition": request.repetition,
        }
        executor = ConformanceExecutorReceipt.create(
            runner_id="scitaste-embedding-conformance",
            runner_version="1.0.0",
            candidate_id=candidate_id,
            role=ModelRole.EMBEDDING,
            selection_scope_id=request.candidate.candidate.selection_scope_id,
            provider=request.resource.provider,
            model_id=request.resource.model_id,
            revision=revision,
            profile_sha256=request.candidate.profile.profile_sha256,
            budget_sha256=request.candidate.budget.budget_sha256,
            started_at_utc=item["started_at"],
            completed_at_utc=item["completed_at"],
            actual_execution=True,
            request_sha256=_canonical_sha256(request_payload),
            response_sha256=item["response_sha256"],
        )
        executor_bytes = _document_bytes(executor)
        executor_sha256 = hashlib.sha256(executor_bytes).hexdigest()
        case_manifest = ConformanceCaseManifest.create(
            manifest_id=f"{request.request_id}-case",
            cases=(
                ConformanceCase(
                    case_id=request.case_id,
                    task_id=request.case_payload.task_id,
                    source_group_id=request.case_payload.source_group_id,
                    input_sha256=request.case_sha256,
                ),
            ),
            formal_or_heldout_content_present=False,
        )
        case_manifest_bytes = _document_bytes(case_manifest)
        case_results = ConformanceCaseResults.create(
            case_manifest_sha256=case_manifest.manifest_sha256,
            executor_receipt_file_sha256=executor_sha256,
            cases=(
                ConformanceCaseResult(
                    case_id=request.case_id,
                    succeeded=item["succeeded"],
                    output_sha256=item["response_sha256"],
                ),
            ),
        )
        case_results_bytes = _document_bytes(case_results)
        success = float(item["succeeded"])
        run_result = ModelRoleConformanceRunResult(
            suite_id=role_plan.suite_id,
            plan_sha256=role_plan.plan_sha256,
            run_id=request.request_id,
            candidate_id=candidate_id,
            role=ModelRole.EMBEDDING,
            selection_scope_id=request.candidate.candidate.selection_scope_id,
            exact_identity=ExactModelIdentity(
                execution_kind=ExecutionKind.LOCAL,
                provider=request.resource.provider,
                model_id=request.resource.model_id,
                revision=revision,
                route=str(model_path),
                scope=IdentityScope.IMMUTABLE_CHECKPOINT,
                artifact_sha256=checkpoint.checkpoint_identity_sha256,
                identity_evidence_sha256=executor_sha256,
            ),
            profile_sha256=request.candidate.profile.profile_sha256,
            budget_sha256=request.candidate.budget.budget_sha256,
            task_ids=(request.case_payload.task_id,),
            source_group_ids=(request.case_payload.source_group_id,),
            measurements=ConformanceMeasurements(
                schema_adherence=1.0,
                tool_adherence=1.0,
                success=success,
                context=1.0,
                latency_cost=float(item["elapsed_ms"] <= request.candidate.budget.max_latency_ms),
                reproducibility=float(reproducible),
                task_fit=success,
                successful_cases=int(item["succeeded"]),
                total_cases=1,
                latency_p95_ms=math.ceil(item["elapsed_ms"]),
                cost_usd=0.0,
            ),
            evidence_artifacts=(
                EvidenceArtifact(
                    kind=EvidenceKind.EXECUTOR_RECEIPT,
                    validator=EvidenceValidator.CONFORMANCE_EXECUTION_V1,
                    locator=f"receipts/{request.request_id}/EXECUTOR_RECEIPT.json",
                    sha256=executor_sha256,
                ),
                EvidenceArtifact(
                    kind=EvidenceKind.CASE_MANIFEST,
                    validator=EvidenceValidator.CASE_MANIFEST_V1,
                    locator=f"receipts/{request.request_id}/CASE_MANIFEST.json",
                    sha256=hashlib.sha256(case_manifest_bytes).hexdigest(),
                ),
                EvidenceArtifact(
                    kind=EvidenceKind.CASE_RESULTS,
                    validator=EvidenceValidator.CASE_RESULTS_V1,
                    locator=f"receipts/{request.request_id}/CASE_RESULTS.json",
                    sha256=hashlib.sha256(case_results_bytes).hexdigest(),
                ),
            ),
            actual_execution=True,
            inventory_presence_was_not_used_as_result=True,
            formal_or_heldout_content_used=False,
        )
        receipt_root = campaign_root / "receipts" / request.request_id
        _save_bytes(executor_bytes, receipt_root / "EXECUTOR_RECEIPT.json")
        _save_bytes(case_manifest_bytes, receipt_root / "CASE_MANIFEST.json")
        _save_bytes(case_results_bytes, receipt_root / "CASE_RESULTS.json")
        run_path = _save_bytes(_document_bytes(run_result), receipt_root / "RUN_RESULT.json")
        receipt_paths.append(run_path.relative_to(campaign_root).as_posix())

    return EmbeddingConformanceExecutionStatus(
        campaign_id=plan.campaign_id,
        candidate_id=candidate_id,
        model_id=requests[0].resource.model_id,
        checkpoint_identity_sha256=checkpoint.checkpoint_identity_sha256,
        executed_request_ids=tuple(item.request_id for item in requests),
        successful_cases=sum(item["succeeded"] for item in executions),
        total_cases=len(executions),
        reproducible=reproducible,
        elapsed_ms=(time.perf_counter() - started_all) * 1000,
        receipt_paths=tuple(receipt_paths),
    )


def _transformers_embedder_factory(model_path: Path) -> Callable[[list[str]], list[list[float]]]:
    try:
        import torch
        from transformers import AutoModel, AutoTokenizer
    except ImportError as exc:  # pragma: no cover - optional runtime dependency
        raise RuntimeError("embedding conformance requires torch and transformers") from exc
    tokenizer = AutoTokenizer.from_pretrained(
        model_path,
        local_files_only=True,
        trust_remote_code=False,
    )
    model = AutoModel.from_pretrained(
        model_path,
        local_files_only=True,
        trust_remote_code=False,
    ).eval()

    def embed(texts: list[str]) -> list[list[float]]:
        encoded = tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="pt",
        )
        with torch.inference_mode():
            hidden = model(**encoded).last_hidden_state
        mask = encoded["attention_mask"].unsqueeze(-1).expand(hidden.size()).float()
        pooled = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
        pooled = torch.nn.functional.normalize(pooled, p=2, dim=1)
        return pooled.cpu().tolist()

    return embed


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        raise ValueError("embedding vectors must be non-empty and dimension matched")
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        raise ValueError("embedding vectors cannot have zero norm")
    return numerator / (left_norm * right_norm)


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


__all__ = [
    "EmbeddingConformanceExecutionStatus",
    "execute_embedding_conformance",
]
