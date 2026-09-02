"""Object-level patches derived from visual critic findings."""

from __future__ import annotations

from scitaste.state.research_state import FigureCritique, FigureObject, FigurePatch


class ObjectPatcher:
    def plan(self, report: list[FigureCritique], objects: list[FigureObject]) -> list[FigurePatch]:
        object_map = {item.object_id: item for item in objects}
        patches: list[FigurePatch] = []
        seen: set[tuple[str, str]] = set()
        for finding in report:
            if finding.suggested_operation != "set_emphasis_normal":
                continue
            for object_id in finding.object_ids:
                key = (object_id, "emphasis")
                if key in seen:
                    continue
                seen.add(key)
                item = object_map[object_id]
                patches.append(
                    FigurePatch(
                        operation="set",
                        object_id=object_id,
                        field="emphasis",
                        old_value=item.emphasis,
                        new_value="normal",
                        rationale=finding.message,
                    )
                )
        return patches

    @staticmethod
    def apply(objects: list[FigureObject], patches: list[FigurePatch]) -> list[FigureObject]:
        by_object = {patch.object_id: patch for patch in patches}
        return [
            item.model_copy(update={patch.field: patch.new_value})
            if (patch := by_object.get(item.object_id))
            else item.model_copy(deep=True)
            for item in objects
        ]
