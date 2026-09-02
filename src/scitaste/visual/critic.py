"""Visual-taste criticism separated into communication and aesthetics."""

from __future__ import annotations

from scitaste.state.research_state import FigureContract, FigureCritique, FigureObject


class VisualTasteCritic:
    dimensions = (
        ("purpose clarity", "communication"),
        ("argument support", "communication"),
        ("hierarchy", "communication"),
        ("density", "aesthetics"),
        ("panel logic", "communication"),
        ("text/figure consistency", "communication"),
        ("redundancy", "communication"),
        ("misleading emphasis", "communication"),
        ("editability", "aesthetics"),
        ("publication readiness", "aesthetics"),
    )

    def review(
        self,
        contract: FigureContract,
        objects: list[FigureObject],
        *,
        known_claim_ids: set[str],
    ) -> list[FigureCritique]:
        checks = {
            "purpose clarity": self._purpose(contract),
            "argument support": self._argument(contract, objects),
            "hierarchy": self._emphasis(contract, objects, "Hierarchy"),
            "density": self._density(contract, objects),
            "panel logic": self._panels(contract, objects),
            "text/figure consistency": self._claims(contract, known_claim_ids),
            "redundancy": self._redundancy(objects),
            "misleading emphasis": self._emphasis(contract, objects, "Forbidden emphasis"),
            "editability": self._editability(objects),
            "publication readiness": self._bounds(objects),
        }
        reports: list[FigureCritique] = []
        for dimension, category in self.dimensions:
            message, object_ids, operation = checks[dimension]
            reports.append(
                FigureCritique(
                    dimension=dimension,
                    category=category,
                    score=3 if object_ids else 5,
                    severity="warning" if object_ids else "pass",
                    message=message,
                    object_ids=object_ids,
                    suggested_operation=operation,
                )
            )
        return reports

    @staticmethod
    def _purpose(contract: FigureContract):
        failed = not contract.purpose.strip() or not contract.intended_reader_takeaway.strip()
        return (
            "Purpose and reader takeaway are explicit." if not failed else "Purpose is unclear.",
            [contract.figure_id] if failed else [],
            None,
        )

    @staticmethod
    def _argument(contract: FigureContract, objects: list[FigureObject]):
        available = {item.object_id for item in objects}
        missing = [
            item.entity_id for item in contract.required_entities if item.entity_id not in available
        ]
        missing.extend(
            relation.relation_id
            for relation in contract.required_relations
            if {relation.source_entity_id, relation.target_entity_id} - available
        )
        return (
            "All required argument entities are present."
            if not missing
            else "Required argument entities are missing.",
            missing,
            None,
        )

    @staticmethod
    def _emphasis(contract: FigureContract, objects: list[FigureObject], label: str):
        forbidden = set(contract.forbidden_emphasis)
        offenders = [
            item.object_id
            for item in objects
            if item.object_id in forbidden and item.emphasis == "prominent"
        ]
        return (
            f"{label} is aligned with the contract."
            if not offenders
            else f"{label} elevates contract-forbidden objects.",
            offenders,
            "set_emphasis_normal" if offenders else None,
        )

    @staticmethod
    def _density(contract: FigureContract, objects: list[FigureObject]):
        dense = [
            panel.panel_id
            for panel in contract.panel_plan
            if sum(item.panel_id == panel.panel_id for item in objects) > 6
        ]
        return (
            "Panel density remains scannable." if not dense else "Panels exceed six entities.",
            dense,
            None,
        )

    @staticmethod
    def _panels(contract: FigureContract, objects: list[FigureObject]):
        valid = {panel.panel_id for panel in contract.panel_plan}
        invalid = [item.object_id for item in objects if item.panel_id not in valid]
        return (
            "Every object follows the declared panel plan."
            if not invalid
            else "Objects appear outside the panel plan.",
            invalid,
            None,
        )

    @staticmethod
    def _claims(contract: FigureContract, known_claim_ids: set[str]):
        unknown = sorted(set(contract.target_claim_ids) - known_claim_ids)
        return (
            "Figure targets resolve to canonical claims."
            if not unknown
            else "Figure targets unknown claims.",
            unknown,
            None,
        )

    @staticmethod
    def _redundancy(objects: list[FigureObject]):
        labels: dict[str, list[str]] = {}
        for item in objects:
            labels.setdefault(item.label.casefold(), []).append(item.object_id)
        duplicates = [item for ids in labels.values() if len(ids) > 1 for item in ids]
        return (
            "Entity labels are non-redundant." if not duplicates else "Duplicate labels compete.",
            duplicates,
            None,
        )

    @staticmethod
    def _editability(objects: list[FigureObject]):
        identifiers = [item.object_id for item in objects]
        invalid = identifiers if len(identifiers) != len(set(identifiers)) else []
        return (
            "Every semantic object has a stable editable identifier."
            if not invalid
            else "Object identifiers are not unique.",
            invalid,
            None,
        )

    @staticmethod
    def _bounds(objects: list[FigureObject]):
        invalid = [
            item.object_id
            for item in objects
            if item.x < 0 or item.y < 0 or item.width < 24 or item.height < 18
        ]
        return (
            "Objects satisfy the vector publication preflight."
            if not invalid
            else "Objects fail publication bounds.",
            invalid,
            None,
        )


def blocking_findings(report: list[FigureCritique]) -> list[FigureCritique]:
    return [item for item in report if item.severity != "pass"]
