"""Deterministic semantic reconstruction used before vector export."""

from __future__ import annotations

from scitaste.state.research_state import FigureContract, FigureObject


class SemanticDraftGenerator:
    """Lay out named objects while keeping every element independently editable."""

    def generate(
        self,
        contract: FigureContract,
        *,
        initial_emphasis: dict[str, str] | None = None,
    ) -> list[FigureObject]:
        emphasis = initial_emphasis or {}
        entities = {
            item.entity_id: item
            for item in [*contract.required_entities, *contract.optional_entities]
        }
        objects: list[FigureObject] = []
        panel_width = 300.0
        for panel_index, panel in enumerate(contract.panel_plan):
            count = len(panel.entity_ids)
            for entity_index, entity_id in enumerate(panel.entity_ids):
                entity = entities[entity_id]
                objects.append(
                    FigureObject(
                        object_id=entity.entity_id,
                        label=entity.label,
                        role=entity.role,
                        panel_id=panel.panel_id,
                        x=40.0 + panel_index * panel_width,
                        y=90.0 + entity_index * (180.0 / max(count, 1)),
                        width=210.0,
                        height=54.0,
                        emphasis=emphasis.get(entity_id, "normal"),
                    )
                )
        return objects
