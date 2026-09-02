"""Editable SVG and uncompressed draw.io exporters."""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

from scitaste.state.research_state import FigureContract, FigureObject


def export_svg(
    contract: FigureContract,
    objects: list[FigureObject],
    path: str | Path,
) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    width = max(360, 300 * len(contract.panel_plan))
    height = 360
    svg = ET.Element(
        "svg",
        {
            "xmlns": "http://www.w3.org/2000/svg",
            "width": str(width),
            "height": str(height),
            "viewBox": f"0 0 {width} {height}",
            "role": "img",
            "aria-labelledby": "figure-title figure-description",
        },
    )
    ET.SubElement(svg, "title", {"id": "figure-title"}).text = contract.purpose
    ET.SubElement(
        svg, "desc", {"id": "figure-description"}
    ).text = contract.intended_reader_takeaway
    defs = ET.SubElement(svg, "defs")
    marker = ET.SubElement(
        defs,
        "marker",
        {
            "id": "arrow",
            "viewBox": "0 0 10 10",
            "refX": "9",
            "refY": "5",
            "markerWidth": "7",
            "markerHeight": "7",
            "orient": "auto-start-reverse",
        },
    )
    ET.SubElement(marker, "path", {"d": "M 0 0 L 10 5 L 0 10 z", "fill": "#334155"})
    object_map = {item.object_id: item for item in objects}
    for panel_index, panel in enumerate(contract.panel_plan):
        group = ET.SubElement(svg, "g", {"id": panel.panel_id, "data-kind": "panel"})
        ET.SubElement(
            group,
            "rect",
            {
                "x": str(15 + panel_index * 300),
                "y": "20",
                "width": "270",
                "height": "310",
                "rx": "12",
                "fill": "#f8fafc",
                "stroke": "#cbd5e1",
            },
        )
        title = ET.SubElement(
            group,
            "text",
            {
                "x": str(30 + panel_index * 300),
                "y": "50",
                "font-family": "sans-serif",
                "font-size": "16",
                "font-weight": "600",
                "fill": "#0f172a",
            },
        )
        title.text = panel.title
    for relation in contract.required_relations:
        source = object_map[relation.source_entity_id]
        destination = object_map[relation.target_entity_id]
        group = ET.SubElement(
            svg,
            "g",
            {"id": relation.relation_id, "data-kind": "relation"},
        )
        x1, y1 = source.x + source.width, source.y + source.height / 2
        x2, y2 = destination.x, destination.y + destination.height / 2
        if source.panel_id == destination.panel_id:
            x1, y1 = source.x + source.width / 2, source.y + source.height
            x2, y2 = destination.x + destination.width / 2, destination.y
        backwards = x2 < x1
        stroke = {
            "fill": "none",
            "stroke": "#334155",
            "stroke-width": "2",
            "marker-end": "url(#arrow)",
        }
        if backwards:
            route_y = 300.0
            x2 = destination.x
            ET.SubElement(
                group,
                "path",
                {
                    "d": (
                        f"M {x1} {y1} L {x1 + 18} {y1} L {x1 + 18} {route_y} "
                        f"L {x2 - 15} {route_y} L {x2 - 15} {y2} L {x2} {y2}"
                    ),
                    **stroke,
                },
            )
            label_x, label_y = (x1 + x2) / 2, route_y - 7
        else:
            ET.SubElement(
                group,
                "line",
                {"x1": str(x1), "y1": str(y1), "x2": str(x2), "y2": str(y2), **stroke},
            )
            label_x, label_y = (x1 + x2) / 2, (y1 + y2) / 2 - 6
        label = ET.SubElement(
            group,
            "text",
            {
                "x": str(label_x),
                "y": str(label_y),
                "text-anchor": "middle",
                "font-family": "sans-serif",
                "font-size": "11",
                "fill": "#475569",
            },
        )
        label.text = relation.label
    for item in objects:
        prominent = item.emphasis == "prominent"
        group = ET.SubElement(
            svg,
            "g",
            {
                "id": item.object_id,
                "data-kind": "entity",
                "data-role": item.role,
                "data-emphasis": item.emphasis,
            },
        )
        ET.SubElement(
            group,
            "rect",
            {
                "x": str(item.x),
                "y": str(item.y),
                "width": str(item.width),
                "height": str(item.height),
                "rx": "8",
                "fill": "#dbeafe" if prominent else "#ffffff",
                "stroke": "#2563eb" if prominent else "#64748b",
                "stroke-width": "3" if prominent else "1.5",
            },
        )
        label = ET.SubElement(
            group,
            "text",
            {
                "x": str(item.x + item.width / 2),
                "y": str(item.y + item.height / 2 + 5),
                "text-anchor": "middle",
                "font-family": "sans-serif",
                "font-size": "14",
                "font-weight": "600" if prominent else "400",
                "fill": "#0f172a",
            },
        )
        label.text = item.label
    ET.indent(svg)
    target.write_text(ET.tostring(svg, encoding="unicode") + "\n", encoding="utf-8")
    return target


def export_drawio(
    contract: FigureContract,
    objects: list[FigureObject],
    path: str | Path,
) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    mxfile = ET.Element("mxfile", {"host": "app.diagrams.net", "compressed": "false"})
    diagram = ET.SubElement(mxfile, "diagram", {"id": contract.figure_id, "name": "Figure"})
    graph = ET.SubElement(
        diagram,
        "mxGraphModel",
        {"grid": "1", "page": "1", "pageScale": "1", "pageWidth": "1169"},
    )
    root = ET.SubElement(graph, "root")
    ET.SubElement(root, "mxCell", {"id": "0"})
    ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})
    for item in objects:
        prominent = item.emphasis == "prominent"
        shape_style = (
            "3;fillColor=#dbeafe;strokeColor=#2563eb;"
            if prominent
            else "1;fillColor=#ffffff;strokeColor=#64748b;"
        )
        style = "rounded=1;whiteSpace=wrap;html=1;strokeWidth=" + shape_style
        cell = ET.SubElement(
            root,
            "mxCell",
            {
                "id": item.object_id,
                "value": item.label,
                "style": style,
                "vertex": "1",
                "parent": "1",
            },
        )
        ET.SubElement(
            cell,
            "mxGeometry",
            {
                "x": str(item.x),
                "y": str(item.y),
                "width": str(item.width),
                "height": str(item.height),
                "as": "geometry",
            },
        )
    for relation in contract.required_relations:
        edge = ET.SubElement(
            root,
            "mxCell",
            {
                "id": relation.relation_id,
                "value": relation.label,
                "edge": "1",
                "parent": "1",
                "source": relation.source_entity_id,
                "target": relation.target_entity_id,
                "style": "edgeStyle=orthogonalEdgeStyle;rounded=1;endArrow=block;html=1;",
            },
        )
        ET.SubElement(edge, "mxGeometry", {"relative": "1", "as": "geometry"})
    ET.indent(mxfile)
    target.write_text(ET.tostring(mxfile, encoding="unicode") + "\n", encoding="utf-8")
    return target
