"""Complete additive registry for every first-party semantic model node."""

from __future__ import annotations

from scitaste.model_nodes.runtime import ModelNodeRegistration


def first_party_node_types() -> dict[str, ModelNodeRegistration]:
    """Load all extension registries lazily so runtime verification cannot drift."""

    from scitaste.discovery.semantic import discovery_node_types
    from scitaste.taste.semantic import taste_node_types
    from scitaste.writing.semantic import writing_node_types

    registries = (discovery_node_types(), taste_node_types(), writing_node_types())
    combined: dict[str, ModelNodeRegistration] = {}
    for registry in registries:
        overlap = set(combined) & set(registry)
        if overlap:
            raise ValueError(f"duplicate first-party model-node names: {sorted(overlap)!r}")
        combined.update(registry)
    return combined


__all__ = ["first_party_node_types"]
