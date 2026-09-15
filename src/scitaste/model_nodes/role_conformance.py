"""Generic structured node for task-excluded model-role conformance cases."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from scitaste.model_nodes.models import NodeContext, NodePolicy
from scitaste.model_nodes.nodes import ModelNode

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class RoleConformanceInput(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    case_id: str = Field(pattern=r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$")
    role: Literal["research_agent", "code_agent", "judge", "task_training"]
    selection_scope_id: str = Field(pattern=r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$")
    task_id: str = Field(pattern=r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$")
    source_group_id: str = Field(pattern=r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$")
    objective: str = Field(min_length=1, max_length=4_000)
    payload: dict[str, JsonValue]
    required_response_fields: tuple[str, ...] = Field(min_length=1, max_length=20)
    allowed_tool_names: tuple[str, ...] = Field(default=(), max_length=20)
    formal_or_heldout: Literal[False] = False

    @model_validator(mode="after")
    def declarations_are_unique(self) -> RoleConformanceInput:
        if len(self.required_response_fields) != len(set(self.required_response_fields)):
            raise ValueError("required conformance response fields must be unique")
        if len(self.allowed_tool_names) != len(set(self.allowed_tool_names)):
            raise ValueError("allowed conformance tools must be unique")
        return self


class RoleConformanceProposal(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    case_id: str
    response: dict[str, JsonValue]
    evidence_refs: tuple[str, ...] = ()
    proposed_tools: tuple[str, ...] = ()
    abstained: bool = False


class RoleConformanceNode(ModelNode[RoleConformanceInput, RoleConformanceProposal]):
    node_name = "role-conformance"
    prompt_version = "1.0.0"
    system_instruction = (
        "Solve one task-excluded conformance case. Return only the requested JSON schema. "
        "Do not infer, request, or expose any formal or heldout benchmark material."
    )
    input_model = RoleConformanceInput
    output_model = RoleConformanceProposal

    def _proposal_rejections(
        self,
        proposal: RoleConformanceProposal,
        *,
        input_data: RoleConformanceInput,
        context: NodeContext,
        policy: NodePolicy,
    ) -> list[str]:
        del context, policy
        reasons: list[str] = []
        if proposal.case_id != input_data.case_id:
            reasons.append("proposal case_id differs from the frozen conformance case")
        missing = set(input_data.required_response_fields) - set(proposal.response)
        if missing:
            reasons.append("proposal omits required response fields: " + ", ".join(sorted(missing)))
        disallowed = set(proposal.proposed_tools) - set(input_data.allowed_tool_names)
        if disallowed:
            reasons.append("proposal names disallowed tools: " + ", ".join(sorted(disallowed)))
        return reasons


def role_conformance_node_types():
    from scitaste.model_nodes.runtime import ModelNodeRegistration

    return {
        RoleConformanceNode.node_name: ModelNodeRegistration(
            RoleConformanceNode,
            RoleConformanceInput,
            RoleConformanceProposal,
        )
    }


__all__ = [
    "RoleConformanceInput",
    "RoleConformanceNode",
    "RoleConformanceProposal",
    "role_conformance_node_types",
]
