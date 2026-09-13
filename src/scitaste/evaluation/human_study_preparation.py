"""Compile exact benchmark recordings into a condition-hidden H1/H2 review package."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from scitaste.backends.replay import ReplayRecord
from scitaste.benchmark.models import (
    BenchmarkCondition,
    BenchmarkEvidenceTier,
    BenchmarkSuite,
    CandidateOrder,
)
from scitaste.benchmark.runner import load_benchmark_suite
from scitaste.benchmark.treatment_manifest import load_reference_treatment_manifest
from scitaste.evaluation.human_outcomes import (
    BlindedHumanComparison,
    BlindedOutputBinding,
    HumanBlindKey,
    HumanBlindKeyEntry,
    HumanOutcomeStudyManifest,
    HumanStudyFileBinding,
    HumanStudyTreatmentCommitment,
    TasteMechanismHypothesis,
    TasteStudyCondition,
    TreatmentGenerationLedger,
    TreatmentGenerationRecord,
)

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_RECORDING_BYTES = 256 * 1_048_576
_MAX_INPUT_BYTES = 64 * 1_048_576


class BlindedDecisionArtifact(BaseModel):
    """Condition-free decision shown to a human reviewer."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    output_id: str
    case_id: str
    selected_action_id: str
    selected_action_description: str
    rationale: str
    confidence: float = Field(ge=0, le=1)


class HumanStudyPreparationReport(BaseModel):
    """Content-addressed summary of one no-call review-package compilation."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    study_id: str
    project_id: str
    study_scope: Literal["pilot", "formal"]
    benchmark_suite_file_sha256: str = Field(pattern=_SHA256)
    benchmark_suite_semantic_sha256: str = Field(pattern=_SHA256)
    reference_treatment_manifest_file_sha256: str = Field(pattern=_SHA256)
    reference_treatment_manifest_semantic_sha256: str = Field(pattern=_SHA256)
    recording_file_sha256: str = Field(pattern=_SHA256)
    generation_ledger_sha256: str = Field(pattern=_SHA256)
    blind_key_sha256: str = Field(pattern=_SHA256)
    study_sha256: str = Field(pattern=_SHA256)
    case_count: int = Field(gt=0)
    generation_record_count: int = Field(gt=0)
    comparison_count: int = Field(gt=0)
    reviewer_count: Literal[2] = 2
    candidate_order: CandidateOrder
    seed: int = Field(ge=0, le=2**63 - 1)
    randomization_seed: int = Field(ge=0, le=2**63 - 1)
    prepared_at: datetime
    public_study: HumanStudyFileBinding
    private_blind_key: HumanStudyFileBinding
    private_generation_ledger: HumanStudyFileBinding
    private_blinding_secret: HumanStudyFileBinding
    condition_labels_absent_from_reviewer_metadata: Literal[True] = True
    no_external_action_performed: Literal[True] = True
    authorizes_model_calls: Literal[False] = False
    authorizes_api_spend: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False
    authorizes_human_recruitment: Literal[False] = False
    authorizes_experiment: Literal[False] = False


class HumanStudyPreparation(BaseModel):
    """In-memory models and final paths returned by the compiler."""

    model_config = _CONFIG

    output_dir: Path
    study_path: Path
    blind_key_path: Path
    generation_ledger_path: Path
    blinding_secret_path: Path
    report_path: Path
    study: HumanOutcomeStudyManifest
    blind_key: HumanBlindKey
    generation_ledger: TreatmentGenerationLedger
    report: HumanStudyPreparationReport


def prepare_human_outcome_study(
    *,
    evidence_root: str | Path,
    output_dir: str | Path,
    benchmark_suite_path: str | Path,
    reference_treatment_manifest_path: str | Path,
    recording_path: str | Path,
    study_id: str,
    project_id: str,
    study_scope: Literal["pilot", "formal"],
    protocol_path: str | Path,
    rubric_path: str | Path,
    interface_path: str | Path,
    analysis_contract_path: str | Path,
    power_analysis_path: str | Path | None,
    reviewer_identity_sha256s: tuple[str, str],
    seed: int,
    candidate_order: CandidateOrder,
    randomization_seed: int,
    context_budget_tokens: int,
    maximum_output_tokens: int,
    prepared_at: datetime | None = None,
) -> HumanStudyPreparation:
    """Materialize a review package from an already-recorded exact benchmark run."""

    root = Path(evidence_root).resolve(strict=True)
    target = _new_output_target(root, output_dir)
    suite_binding = _input_binding(root, benchmark_suite_path)
    treatment_binding = _input_binding(root, reference_treatment_manifest_path)
    recording_binding = _input_binding(root, recording_path, maximum_bytes=_MAX_RECORDING_BYTES)
    protocol = _input_binding(root, protocol_path)
    rubric = _input_binding(root, rubric_path)
    interface = _input_binding(root, interface_path)
    analysis_contract = _input_binding(root, analysis_contract_path)
    power_analysis = (
        _input_binding(root, power_analysis_path) if power_analysis_path is not None else None
    )
    if len(set(reviewer_identity_sha256s)) != 2:
        raise ValueError("human study preparation requires two distinct reviewer identities")
    timestamp = prepared_at or datetime.now(UTC)
    if timestamp.utcoffset() is None:
        raise ValueError("human study preparation timestamp must include a timezone")

    suite = load_benchmark_suite(root / suite_binding.path)
    treatment = load_reference_treatment_manifest(root / treatment_binding.path)
    if _sha256(root / suite_binding.path) != suite_binding.sha256:
        raise ValueError("benchmark suite changed while preparing the human study")
    if treatment.file_sha256 != treatment_binding.sha256:
        raise ValueError("treatment manifest changed while preparing the human study")
    _verify_upstream_population(
        suite=suite,
        treatment_file_sha256=treatment_binding.sha256,
        treatment_semantic_sha256=treatment.manifest.manifest_sha256,
        treatment_project_id=treatment.manifest.project_id,
        treatment_cases={item.case_id: item.mechanism_context for item in treatment.manifest.cases},
        project_id=project_id,
        study_scope=study_scope,
    )
    selected = _load_exact_recordings(
        root / recording_binding.path,
        suite=suite,
        seed=seed,
        candidate_order=candidate_order,
        expected_file_sha256=recording_binding.sha256,
        require_raw_response=study_scope == "formal",
    )

    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{target.name}.", dir=target.parent) as temporary:
        workspace = Path(temporary)
        blinding_secret = secrets.token_hex(32)
        output_bindings: dict[tuple[str, TasteStudyCondition], BlindedOutputBinding] = {}
        generation_records: dict[tuple[str, TasteStudyCondition], TreatmentGenerationRecord] = {}
        condition_map = _condition_map()
        cases = {item.case_id: item for item in suite.cases}
        presentation_profile_sha256 = _canonical_sha256(
            {
                "protocol": protocol.sha256,
                "rubric": rubric.sha256,
                "interface": interface.sha256,
                "context_budget_tokens": context_budget_tokens,
                "maximum_output_tokens": maximum_output_tokens,
            }
        )
        for (case_id, condition), recording in selected.items():
            case = cases[case_id]
            benchmark_condition = condition_map[condition]
            context = case.mechanism_context.for_condition(benchmark_condition)
            output_id = _opaque_id(
                "blind",
                study_id,
                case_id,
                condition.value,
                str(randomization_seed),
                blinding_secret,
            )
            output_relative = Path("reviewer") / "outputs" / f"{output_id}.json"
            trace_relative = (
                Path("private") / "traces" / f"{_opaque_id('trace', case_id, condition.value)}.json"
            )
            output_path = workspace / output_relative
            trace_path = workspace / trace_relative
            action = next(
                item
                for item in case.candidate_actions
                if item.action_id == recording.response.selected_action_id
            )
            artifact = BlindedDecisionArtifact(
                output_id=output_id,
                case_id=case_id,
                selected_action_id=action.action_id,
                selected_action_description=action.description,
                rationale=recording.response.rationale,
                confidence=recording.response.confidence,
            )
            _write_json(output_path, artifact.model_dump(mode="json"))
            _write_json(
                trace_path,
                recording.model_dump(mode="json", exclude={"request": {"fingerprint"}}),
            )
            output_file = _workspace_binding(root, target, workspace, output_relative)
            trace_file = _workspace_binding(root, target, workspace, trace_relative)
            generation = TreatmentGenerationRecord.create(
                record_id=_opaque_id("generation", study_id, case_id, condition.value),
                case_id=case_id,
                source_group=case.source_group_id,
                condition=condition,
                seed=seed,
                candidate_order=candidate_order.value,
                benchmark_request_fingerprint=recording.request.fingerprint,
                treatment_construction_receipt_sha256=context.construction_receipt_sha256,
                provider=recording.response.backend,
                model=recording.response.model,
                execution_trace=trace_file,
                output=output_file,
                generated_at=recording.recorded_at,
            )
            generation_records[(case_id, condition)] = generation
            output_bindings[(case_id, condition)] = BlindedOutputBinding(
                **output_file.model_dump(mode="python"),
                output_id=output_id,
                presentation_profile_sha256=presentation_profile_sha256,
                context_budget_tokens=context_budget_tokens,
                maximum_output_tokens=maximum_output_tokens,
            )

        ledger = TreatmentGenerationLedger.create(
            ledger_id=_opaque_id("ledger", study_id, str(randomization_seed)),
            study_id=study_id,
            project_id=project_id,
            benchmark_suite=suite_binding,
            benchmark_suite_semantic_sha256=suite.sha256,
            reference_treatment_manifest=treatment_binding,
            reference_treatment_manifest_semantic_sha256=(treatment.manifest.manifest_sha256),
            entries=tuple(generation_records.values()),
            created_at=timestamp,
        )
        comparisons, key_entries = _build_comparisons(
            suite=suite,
            study_id=study_id,
            reviewers=reviewer_identity_sha256s,
            randomization_seed=randomization_seed,
            blinding_secret=blinding_secret,
            outputs=output_bindings,
            records=generation_records,
        )
        draft = HumanOutcomeStudyManifest(
            schema_version="1.2",
            study_id=study_id,
            project_id=project_id,
            protocol=protocol,
            rubric=rubric,
            interface=interface,
            study_scope=study_scope,
            preference_analysis_contract=analysis_contract,
            power_analysis=power_analysis,
            treatment_commitment=HumanStudyTreatmentCommitment(
                benchmark_suite_file_sha256=suite_binding.sha256,
                benchmark_suite_semantic_sha256=suite.sha256,
                reference_treatment_manifest_file_sha256=treatment_binding.sha256,
                reference_treatment_manifest_semantic_sha256=(treatment.manifest.manifest_sha256),
                generation_ledger_sha256=ledger.ledger_sha256,
            ),
            blind_key_sha256="0" * 64,
            comparisons=comparisons,
        )
        key = HumanBlindKey(
            study_id=study_id,
            assignment_sha256=draft.assignment_sha256,
            created_at=timestamp,
            entries=key_entries,
        )
        payload = draft.model_dump(
            mode="python",
            exclude={"assignment_sha256", "study_sha256", "blind_key_sha256"},
        )
        study = HumanOutcomeStudyManifest(**payload, blind_key_sha256=key.blind_key_sha256)

        study_relative = Path("public") / "study.json"
        key_relative = Path("private") / "blind-key.json"
        ledger_relative = Path("private") / "generation-ledger.json"
        secret_relative = Path("private") / "blinding-secret.json"
        _write_json(
            workspace / study_relative,
            study.model_dump(mode="json", exclude={"assignment_sha256", "study_sha256"}),
        )
        _write_json(
            workspace / key_relative,
            key.model_dump(mode="json", exclude={"blind_key_sha256"}),
        )
        _write_json(workspace / ledger_relative, ledger.model_dump(mode="json"))
        _write_json(
            workspace / secret_relative,
            {
                "schema_version": "1.0",
                "study_id": study_id,
                "randomization_seed": randomization_seed,
                "blinding_secret": blinding_secret,
            },
        )
        study_file = _workspace_binding(root, target, workspace, study_relative)
        key_file = _workspace_binding(root, target, workspace, key_relative)
        ledger_file = _workspace_binding(root, target, workspace, ledger_relative)
        secret_file = _workspace_binding(root, target, workspace, secret_relative)
        report = HumanStudyPreparationReport(
            study_id=study_id,
            project_id=project_id,
            study_scope=study_scope,
            benchmark_suite_file_sha256=suite_binding.sha256,
            benchmark_suite_semantic_sha256=suite.sha256,
            reference_treatment_manifest_file_sha256=treatment_binding.sha256,
            reference_treatment_manifest_semantic_sha256=(treatment.manifest.manifest_sha256),
            recording_file_sha256=recording_binding.sha256,
            generation_ledger_sha256=ledger.ledger_sha256,
            blind_key_sha256=key.blind_key_sha256,
            study_sha256=study.study_sha256,
            case_count=len(suite.cases),
            generation_record_count=len(generation_records),
            comparison_count=len(comparisons),
            candidate_order=candidate_order,
            seed=seed,
            randomization_seed=randomization_seed,
            prepared_at=timestamp,
            public_study=study_file,
            private_blind_key=key_file,
            private_generation_ledger=ledger_file,
            private_blinding_secret=secret_file,
        )
        report_relative = Path("PREPARATION.json")
        _write_json(workspace / report_relative, report.model_dump(mode="json"))
        if target.exists() or target.is_symlink():
            raise FileExistsError(target)
        os.replace(workspace, target)

    return HumanStudyPreparation(
        output_dir=target,
        study_path=target / study_relative,
        blind_key_path=target / key_relative,
        generation_ledger_path=target / ledger_relative,
        blinding_secret_path=target / secret_relative,
        report_path=target / report_relative,
        study=study,
        blind_key=key,
        generation_ledger=ledger,
        report=report,
    )


def _load_exact_recordings(
    path: Path,
    *,
    suite: BenchmarkSuite,
    seed: int,
    candidate_order: CandidateOrder,
    expected_file_sha256: str,
    require_raw_response: bool,
) -> dict[tuple[str, TasteStudyCondition], ReplayRecord]:
    condition_map = _condition_map()
    expected: dict[str, tuple[str, TasteStudyCondition]] = {}
    permitted: dict[str, str] = {}
    for case in suite.cases:
        for condition, benchmark_condition in condition_map.items():
            request = case.to_request(
                benchmark_condition,
                seed=seed,
                candidate_order=candidate_order,
            )
            expected[request.fingerprint] = (case.case_id, condition)
            permitted[request.fingerprint] = case.case_id
        base = case.to_request(
            BenchmarkCondition.BASE,
            seed=seed,
            candidate_order=candidate_order,
        )
        permitted[base.fingerprint] = case.case_id
    observed: dict[str, ReplayRecord] = {}
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_file_sha256:
        raise ValueError("benchmark recording changed while preparing the human study")
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise ValueError("benchmark recording must be UTF-8 JSONL") from exc
    cases = {item.case_id: item for item in suite.cases}
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            record = ReplayRecord.model_validate_json(line)
        except ValueError as exc:
            raise ValueError(f"invalid formal benchmark recording line {line_number}") from exc
        fingerprint = record.request.fingerprint
        if fingerprint not in permitted:
            raise ValueError("recording contains a request outside the exact selected run")
        if fingerprint in observed:
            raise ValueError("recording contains duplicate request fingerprints")
        if (
            record.response.request_id != record.request.request_id
            or record.response.request_fingerprint != fingerprint
        ):
            raise ValueError("recording response does not bind its request")
        if record.recorded_at is None:
            raise ValueError("formal human study requires timestamped benchmark recordings")
        case = cases[permitted[fingerprint]]
        if record.response.selected_action_id not in case.action_roles:
            raise ValueError("recording selected an action outside its benchmark case")
        if record.response.raw_response is None and record.response.raw_response_sha256 is not None:
            raise ValueError("recording has a raw-response hash without raw-response bytes")
        if require_raw_response and record.response.raw_response is None:
            raise ValueError("formal human study requires retained raw model responses")
        if record.response.raw_response is not None and (
            record.response.raw_response_sha256
            != hashlib.sha256(record.response.raw_response.encode()).hexdigest()
        ):
            raise ValueError("recording raw-response hash does not match its bytes")
        observed[fingerprint] = record
    missing = set(expected) - set(observed)
    if missing:
        raise ValueError("recording lacks one or more exact H1/H2 condition requests")
    return {identity: observed[fingerprint] for fingerprint, identity in expected.items()}


def _verify_upstream_population(
    *,
    suite: BenchmarkSuite,
    treatment_file_sha256: str,
    treatment_semantic_sha256: str,
    treatment_project_id: str,
    treatment_cases: dict[str, object],
    project_id: str,
    study_scope: Literal["pilot", "formal"],
) -> None:
    if suite.version != "3.0":
        raise ValueError("human study preparation requires SciTasteBench v3")
    if study_scope == "formal" and suite.evidence_tier is not BenchmarkEvidenceTier.FORMAL:
        raise ValueError("formal human study preparation requires a formal benchmark suite")
    if treatment_project_id != project_id:
        raise ValueError("treatment manifest belongs to another project")
    if suite.reference_treatment_manifest_sha256 != treatment_file_sha256:
        raise ValueError("suite does not bind the supplied treatment-manifest bytes")
    suite_cases = {item.case_id: item for item in suite.cases}
    if set(suite_cases) != set(treatment_cases):
        raise ValueError("suite and treatment manifest case populations differ")
    if any(
        case.mechanism_context is None or treatment_cases[case_id] != case.mechanism_context
        for case_id, case in suite_cases.items()
    ):
        raise ValueError("suite and treatment manifest mechanism contexts differ")
    if not treatment_semantic_sha256:
        raise ValueError("treatment manifest lacks a semantic identity")


def _build_comparisons(
    *,
    suite: BenchmarkSuite,
    study_id: str,
    reviewers: tuple[str, str],
    randomization_seed: int,
    blinding_secret: str,
    outputs: dict[tuple[str, TasteStudyCondition], BlindedOutputBinding],
    records: dict[tuple[str, TasteStudyCondition], TreatmentGenerationRecord],
) -> tuple[tuple[BlindedHumanComparison, ...], tuple[HumanBlindKeyEntry, ...]]:
    comparisons: list[BlindedHumanComparison] = []
    keys: list[HumanBlindKeyEntry] = []
    contrasts = (
        (
            TasteMechanismHypothesis.H1_TASTE_ABSTRACTION,
            TasteStudyCondition.SAME_SOURCE_RAW_RAG,
        ),
        (
            TasteMechanismHypothesis.H2_TASTE_SPECIFICITY,
            TasteStudyCondition.SOURCE_DISJOINT_MISMATCHED_TASTE,
        ),
    )
    for case in suite.cases:
        for hypothesis, comparator in contrasts:
            matched = TasteStudyCondition.MATCHED_ABSTRACTED_TASTE
            flip = (
                int(
                    _canonical_sha256(
                        [
                            study_id,
                            case.case_id,
                            hypothesis.value,
                            randomization_seed,
                            blinding_secret,
                        ]
                    ),
                    16,
                )
                % 2
            )
            first = (matched, comparator) if flip == 0 else (comparator, matched)
            orders = (first, tuple(reversed(first)))
            for reviewer_index, (x_condition, y_condition) in enumerate(orders):
                comparison_id = _opaque_id(
                    "comparison",
                    study_id,
                    case.case_id,
                    hypothesis.value,
                    str(reviewer_index),
                )
                comparisons.append(
                    BlindedHumanComparison(
                        comparison_id=comparison_id,
                        hypothesis=hypothesis,
                        case_id=case.case_id,
                        source_group=case.source_group_id,
                        reviewer_identity_sha256=reviewers[reviewer_index],
                        x_output=outputs[(case.case_id, x_condition)],
                        y_output=outputs[(case.case_id, y_condition)],
                    )
                )
                keys.append(
                    HumanBlindKeyEntry(
                        comparison_id=comparison_id,
                        x_condition=x_condition,
                        y_condition=y_condition,
                        x_generation_trace_sha256=records[
                            (case.case_id, x_condition)
                        ].record_sha256,
                        y_generation_trace_sha256=records[
                            (case.case_id, y_condition)
                        ].record_sha256,
                    )
                )
    return tuple(comparisons), tuple(keys)


def _condition_map() -> dict[TasteStudyCondition, BenchmarkCondition]:
    return {
        TasteStudyCondition.MATCHED_ABSTRACTED_TASTE: (BenchmarkCondition.MATCHED_ABSTRACTED_TASTE),
        TasteStudyCondition.SAME_SOURCE_RAW_RAG: BenchmarkCondition.RAW_SOURCE_RAG,
        TasteStudyCondition.SOURCE_DISJOINT_MISMATCHED_TASTE: (BenchmarkCondition.MISMATCHED_TASTE),
    }


def _new_output_target(root: Path, output_dir: str | Path) -> Path:
    target = Path(output_dir)
    if not target.is_absolute():
        target = root / target
    target = target.resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("human study output must stay inside the evidence root") from exc
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    return target


def _input_binding(
    root: Path,
    path: str | Path | None,
    *,
    maximum_bytes: int = _MAX_INPUT_BYTES,
) -> HumanStudyFileBinding:
    if path is None:
        raise ValueError("required human study input path is absent")
    source = Path(path)
    if not source.is_absolute():
        source = root / source
    if source.is_symlink():
        raise ValueError("human study inputs cannot be symlinks")
    resolved = source.resolve(strict=True)
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("human study inputs must stay inside the evidence root") from exc
    if not resolved.is_file() or resolved.stat().st_size > maximum_bytes:
        raise ValueError("human study input is not a bounded regular file")
    return HumanStudyFileBinding(
        path=relative.as_posix(),
        sha256=hashlib.sha256(resolved.read_bytes()).hexdigest(),
    )


def _workspace_binding(
    root: Path,
    target: Path,
    workspace: Path,
    relative: Path,
) -> HumanStudyFileBinding:
    path = workspace / relative
    return HumanStudyFileBinding(
        path=(target / relative).relative_to(root).as_posix(),
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _opaque_id(prefix: str, *parts: str) -> str:
    return f"{prefix}-{_canonical_sha256(parts)[:24]}"


def _canonical_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


__all__ = [
    "BlindedDecisionArtifact",
    "HumanStudyPreparation",
    "HumanStudyPreparationReport",
    "prepare_human_outcome_study",
]
