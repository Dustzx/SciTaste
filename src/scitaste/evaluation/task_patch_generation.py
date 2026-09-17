"""Model-node proposal surface for iterative benchmark research patches."""

from __future__ import annotations

import hashlib
import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scitaste.evaluation.task_patch import (
    BenchmarkPatchContext,
    BenchmarkPatchEdit,
    BenchmarkPatchPolicy,
    BenchmarkPatchProducer,
    BenchmarkPatchProposal,
)
from scitaste.model_nodes.models import NodeContext, NodePolicy
from scitaste.model_nodes.nodes import ModelNode
from scitaste.model_nodes.runtime import ModelNodeRegistration
from scitaste.project.models import content_sha256
from scitaste.schema.actions import MetaAction
from scitaste.taste.deliberation import TasteControlPacket

BENCHMARK_PATCH_NODE = "benchmark-research-patch"
_MAX_REPLACEMENT_CHARS = 1_048_576


class BenchmarkResearchActionDirective(BaseModel):
    """Sanitized high-level action passed from Taste control to patch generation."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    action_id: str = Field(min_length=1, max_length=300)
    action_type: Literal["PROBE", "PILOT", "EXPERIMENT", "ANALYZE", "REFINE", "PIVOT"]
    instruction: str = Field(min_length=1, max_length=2_000)
    directive_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def directive_is_self_hashed(self) -> BenchmarkResearchActionDirective:
        expected = content_sha256(self.model_dump(mode="json", exclude={"directive_sha256"}))
        if self.directive_sha256 != expected:
            raise ValueError("benchmark research-action directive hash differs")
        return self

    @classmethod
    def create(cls, **values: object) -> BenchmarkResearchActionDirective:
        payload = dict(values)
        payload.pop("directive_sha256", None)
        unsigned = cls.model_construct(directive_sha256="0" * 64, **payload)
        return cls(
            **payload,
            directive_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"directive_sha256"})
            ),
        )


class BenchmarkPatchGenerationInput(BaseModel):
    """Evidence and condition-specific guidance visible to one research turn."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: Literal["1.0", "1.1", "1.2"] = "1.0"
    task_id: str = Field(min_length=1, max_length=200)
    research_problem: str = Field(min_length=1, max_length=16_000)
    primary_metric: str = Field(min_length=1, max_length=128)
    metric_direction: Literal["higher", "lower"]
    baseline_development_score: float = Field(allow_inf_nan=False)
    current_development_score: float | None = Field(default=None, allow_inf_nan=False)
    best_development_score: float | None = Field(default=None, allow_inf_nan=False)
    iteration: int = Field(ge=1, le=1_000)
    remaining_experiment_runs: int = Field(ge=0, le=1_000)
    patch_context: BenchmarkPatchContext
    patch_policy: BenchmarkPatchPolicy
    experiment_feedback: tuple[str, ...] = Field(default=(), max_length=32)
    utility_guidance: tuple[str, ...] = Field(default=(), max_length=32)
    knowledge_guidance: tuple[str, ...] = Field(default=(), max_length=32)
    taste_guidance: tuple[str, ...] = Field(default=(), max_length=32)
    critic_guidance: tuple[str, ...] = Field(default=(), max_length=32)
    research_action: BenchmarkResearchActionDirective | None = None
    taste_control_packet_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
        exclude_if=lambda value: value is None,
    )
    taste_control_packet_abstained: bool | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    constraints: tuple[str, ...] = Field(min_length=1, max_length=64)

    @field_validator(
        "experiment_feedback",
        "utility_guidance",
        "knowledge_guidance",
        "taste_guidance",
        "critic_guidance",
        "constraints",
    )
    @classmethod
    def guidance_is_unique_and_bounded(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("benchmark patch guidance entries must be unique")
        if any(not item or len(item) > 2_000 for item in values):
            raise ValueError("benchmark patch guidance entries must be non-empty and bounded")
        return values

    @model_validator(mode="after")
    def scores_and_budget_are_coherent(self) -> BenchmarkPatchGenerationInput:
        if self.schema_version == "1.0" and (
            self.research_action is not None
            or self.taste_control_packet_sha256 is not None
            or self.taste_control_packet_abstained is not None
        ):
            raise ValueError("benchmark patch schema 1.0 cannot carry action control")
        if self.schema_version == "1.1" and (
            self.research_action is None
            or self.taste_control_packet_sha256 is not None
            or self.taste_control_packet_abstained is not None
        ):
            raise ValueError(
                "benchmark patch schema 1.1 requires a directive without a Taste packet"
            )
        if self.schema_version == "1.2":
            if (
                self.taste_control_packet_sha256 is None
                or self.taste_control_packet_abstained is None
            ):
                raise ValueError("benchmark patch schema 1.2 requires Taste packet provenance")
            if self.taste_control_packet_abstained == (self.research_action is not None):
                raise ValueError(
                    "an active Taste packet requires a directive and an abstaining packet "
                    "forbids it"
                )
        for score in (self.baseline_development_score, self.current_development_score):
            if score is not None and not math.isfinite(score):
                raise ValueError("benchmark development scores must be finite")
        if self.best_development_score is not None and not math.isfinite(
            self.best_development_score
        ):
            raise ValueError("best benchmark development score must be finite")
        return self


def benchmark_directive_from_taste_packet(
    packet: TasteControlPacket,
) -> BenchmarkResearchActionDirective | None:
    """Project one packet recommendation into the bounded patch-generator interface."""

    if packet.abstained:
        return None
    if packet.recommended_action_id is None:
        raise ValueError("active Taste packet lacks a recommended action")
    selected = next(
        (item for item in packet.action_menu if item.action_id == packet.recommended_action_id),
        None,
    )
    if selected is None:
        raise ValueError("Taste packet recommendation is absent from its frozen action menu")
    if selected.type is MetaAction.STOP:
        raise ValueError("STOP must terminate the research loop before patch generation")
    allowed = {
        MetaAction.PROBE,
        MetaAction.PILOT,
        MetaAction.EXPERIMENT,
        MetaAction.ANALYZE,
        MetaAction.REFINE,
        MetaAction.PIVOT,
    }
    if selected.type not in allowed:
        raise ValueError("Taste packet selected an action outside the patch directive ontology")
    return BenchmarkResearchActionDirective.create(
        action_id=selected.action_id,
        action_type=selected.type.value,
        instruction=selected.description,
    )


class BenchmarkPatchGenerationEdit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str = Field(min_length=1, max_length=1_000)
    replacement: str = Field(min_length=1, max_length=_MAX_REPLACEMENT_CHARS)


class BenchmarkPatchGenerationOutput(BaseModel):
    """Advisory model output; controller identities and execution remain absent."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: Literal["1.0"] = "1.0"
    decision: Literal["propose", "stop"]
    hypothesis: str = Field(min_length=1, max_length=4_000)
    expected_effect: str = Field(min_length=1, max_length=4_000)
    edits: tuple[BenchmarkPatchGenerationEdit, ...] = Field(default=(), max_length=50)
    stop_reason: str | None = Field(default=None, min_length=1, max_length=4_000)

    @model_validator(mode="after")
    def decision_matches_payload(self) -> BenchmarkPatchGenerationOutput:
        if self.decision == "propose":
            if not self.edits or self.stop_reason is not None:
                raise ValueError("propose requires edits and no stop reason")
        elif self.edits or self.stop_reason is None:
            raise ValueError("stop requires a reason and no edits")
        if len({item.path for item in self.edits}) != len(self.edits):
            raise ValueError("generated benchmark patch paths must be unique")
        return self


class BenchmarkPatchGenerationNode(
    ModelNode[BenchmarkPatchGenerationInput, BenchmarkPatchGenerationOutput]
):
    """Choose a bounded patch or stop; never invoke tools or execute experiments."""

    node_name = BENCHMARK_PATCH_NODE
    prompt_version = "benchmark-research-patch-v2"
    system_instruction = (
        "Act as one bounded autonomous-research iteration. Use the exact visible source, "
        "objective metric, prior development feedback, and only the guidance fields supplied. "
        "Return JSON matching the schema. Either propose replacement text for one or more files "
        "already present in patch_context, or stop when the evidence does not justify spending "
        "another experiment. Do not invent results, claim access to held-out data, propose shell "
        "commands, add dependencies, change evaluation code, widen policy, or claim execution. "
        "A missing guidance channel is disabled by the registered condition; do not reconstruct "
        "or simulate it from general knowledge. When research_action is present, treat it as the "
        "controller-owned objective for this turn; do not replace it with another high-level "
        "research action. "
        "A proposal remains untrusted until deterministic admission and isolated development "
        "execution. Preserve a substantive scientific hypothesis rather than making cosmetic edits."
    )
    input_model = BenchmarkPatchGenerationInput
    output_model = BenchmarkPatchGenerationOutput

    def _proposal_rejections(
        self,
        proposal: BenchmarkPatchGenerationOutput,
        *,
        input_data: BenchmarkPatchGenerationInput,
        context: NodeContext,
        policy: NodePolicy,
    ) -> list[str]:
        del context, policy
        if proposal.decision == "stop":
            return []
        visible = {item.path: item for item in input_data.patch_context.files}
        reasons: list[str] = []
        total_bytes = 0
        if len(proposal.edits) > input_data.patch_policy.maximum_files_per_patch:
            reasons.append("generated edit count exceeds the controller patch policy")
        for edit in proposal.edits:
            snapshot = visible.get(edit.path)
            if snapshot is None:
                reasons.append(f"generated path was not supplied in patch_context: {edit.path}")
                continue
            encoded = edit.replacement.encode("utf-8")
            total_bytes += len(encoded)
            if "```" in edit.replacement:
                reasons.append(f"generated replacement contains a Markdown fence: {edit.path}")
            if "\x00" in edit.replacement:
                reasons.append(f"generated replacement contains a NUL byte: {edit.path}")
            if len(encoded) > input_data.patch_policy.maximum_replacement_bytes_per_file:
                reasons.append(f"generated replacement exceeds the per-file limit: {edit.path}")
            if hashlib.sha256(encoded).hexdigest() == snapshot.sha256:
                reasons.append(f"generated replacement is unchanged: {edit.path}")
        if total_bytes > input_data.patch_policy.maximum_replacement_bytes_total:
            reasons.append("generated replacements exceed the total byte limit")
        return reasons


def materialize_benchmark_patch_proposal(
    output: BenchmarkPatchGenerationOutput,
    input_data: BenchmarkPatchGenerationInput,
    *,
    proposal_id: str,
    producer: BenchmarkPatchProducer,
) -> BenchmarkPatchProposal:
    """Bind an accepted model proposal to exact predecessor file identities."""

    if output.decision != "propose":
        raise ValueError("a benchmark stop decision cannot become a patch proposal")
    snapshots = {item.path: item for item in input_data.patch_context.files}
    edits: list[BenchmarkPatchEdit] = []
    for generated in output.edits:
        try:
            predecessor = snapshots[generated.path]
        except KeyError as exc:
            raise ValueError("generated benchmark patch path was not in its context") from exc
        replacement_sha256 = hashlib.sha256(generated.replacement.encode("utf-8")).hexdigest()
        edits.append(
            BenchmarkPatchEdit(
                path=generated.path,
                expected_sha256=predecessor.sha256,
                replacement=generated.replacement,
                replacement_sha256=replacement_sha256,
            )
        )
    return BenchmarkPatchProposal(
        proposal_id=proposal_id,
        spec_id=input_data.patch_context.spec_id,
        spec_fingerprint=input_data.patch_context.spec_fingerprint,
        policy_fingerprint=input_data.patch_policy.fingerprint,
        context_sha256=input_data.patch_context.context_sha256,
        iteration=input_data.iteration,
        base_editable_surface_sha256=input_data.patch_context.editable_surface_sha256,
        hypothesis=output.hypothesis,
        expected_effect=output.expected_effect,
        edits=tuple(edits),
        producer=producer,
    )


def benchmark_patch_node_types() -> dict[str, ModelNodeRegistration]:
    return {
        BENCHMARK_PATCH_NODE: ModelNodeRegistration(
            BenchmarkPatchGenerationNode,
            BenchmarkPatchGenerationInput,
            BenchmarkPatchGenerationOutput,
        )
    }


__all__ = [
    "BENCHMARK_PATCH_NODE",
    "BenchmarkPatchGenerationEdit",
    "BenchmarkPatchGenerationInput",
    "BenchmarkPatchGenerationNode",
    "BenchmarkPatchGenerationOutput",
    "BenchmarkResearchActionDirective",
    "benchmark_directive_from_taste_packet",
    "benchmark_patch_node_types",
    "materialize_benchmark_patch_proposal",
]
