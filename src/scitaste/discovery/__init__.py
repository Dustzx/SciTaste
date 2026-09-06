"""Unified Hypothesis-Probe-Reformulate discovery loop."""

from scitaste.discovery.commands import (
    DiscoveryCommand,
    DiscoveryCommandPreview,
    DiscoveryCommandReport,
    DiscoveryCommandRunner,
)
from scitaste.discovery.evidence_to_idea import (
    ContradictoryPilotEvidence,
    EvidenceBackedIdeationResult,
    EvidenceToIdeaEngine,
)
from scitaste.discovery.loop import DiscoveryLoop, DiscoveryScenario, load_discovery_scenario
from scitaste.discovery.semantic_models import (
    DiscoveryHypothesisInput,
    DiscoveryHypothesisProposal,
    DiscoveryIdeationInput,
    DiscoveryIdeationProposal,
    DiscoveryIntuitionProposal,
    DiscoveryReformulationInput,
    DiscoveryReformulationProposal,
    DiscoverySemanticReference,
)

_PROJECT_WORKFLOW_EXPORTS = {
    "ProjectDiscoveryAdvanceReport",
    "ProjectDiscoveryManifest",
    "ProjectDiscoveryPreview",
    "ProjectDiscoveryStep",
    "ProjectDiscoveryVerification",
    "ProjectDiscoveryWorkflow",
}
_SEMANTIC_RUNTIME_EXPORTS = {
    "DiscoveryHypothesisNode",
    "DiscoveryIdeationNode",
    "DiscoveryReformulationNode",
    "DiscoverySemanticBinding",
}


def __getattr__(name: str):
    """Load the project/model integration only when that public API is requested."""

    if name in _PROJECT_WORKFLOW_EXPORTS:
        from scitaste.discovery import project_workflow

        return getattr(project_workflow, name)
    if name in _SEMANTIC_RUNTIME_EXPORTS:
        from scitaste.discovery import semantic

        return getattr(semantic, name)
    raise AttributeError(name)


__all__ = [
    "ContradictoryPilotEvidence",
    "DiscoveryCommand",
    "DiscoveryCommandPreview",
    "DiscoveryCommandReport",
    "DiscoveryCommandRunner",
    "DiscoveryHypothesisInput",
    "DiscoveryHypothesisNode",
    "DiscoveryHypothesisProposal",
    "DiscoveryIdeationInput",
    "DiscoveryIdeationNode",
    "DiscoveryIdeationProposal",
    "DiscoveryIntuitionProposal",
    "DiscoveryLoop",
    "DiscoveryReformulationInput",
    "DiscoveryReformulationNode",
    "DiscoveryReformulationProposal",
    "DiscoveryScenario",
    "DiscoverySemanticBinding",
    "DiscoverySemanticReference",
    "EvidenceBackedIdeationResult",
    "EvidenceToIdeaEngine",
    "ProjectDiscoveryAdvanceReport",
    "ProjectDiscoveryManifest",
    "ProjectDiscoveryPreview",
    "ProjectDiscoveryStep",
    "ProjectDiscoveryVerification",
    "ProjectDiscoveryWorkflow",
    "load_discovery_scenario",
]
