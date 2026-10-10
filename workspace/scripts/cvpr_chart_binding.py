"""Training-free pixel matching for VLM-proposed chart evidence addresses.

No labels, learned experts, gradients or target answers enter this module.
Ambiguous or unsupported evidence retains the model's mapping unchanged.
"""
import copy
import itertools
import math

import numpy as np


def color(image, box):
    if not isinstance(box, list) or len(box) != 4:
        return None
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in box):
        return None
    if not (0 <= box[0] < box[2] <= 1000 and 0 <= box[1] < box[3] <= 1000):
        return None
    width, height = image.size
    x0, y0 = int(box[0] * width / 1000), int(box[1] * height / 1000)
    x1, y1 = math.ceil(box[2] * width / 1000), math.ceil(box[3] * height / 1000)
    pixels = np.asarray(image.crop((x0, y0, x1, y1)).convert("RGB"), dtype=np.float64).reshape(-1, 3)
    if not len(pixels):
        return None
    # Exclude white background and low-saturation text/axes. Grayscale or style-only
    # legends are explicitly unsupported by this first prototype.
    selected = pixels[(pixels.max(1) - pixels.min(1) >= 30) & (pixels.mean(1) < 245)]
    if len(selected) < 5:
        return None
    quantized = (selected // 24).astype(int)
    bins, inverse, counts = np.unique(quantized, axis=0, return_inverse=True, return_counts=True)
    dominant = int(counts.argmax())
    fraction = float(counts[dominant] / len(selected))
    if counts[dominant] < 5 or fraction < 0.40:
        return None
    rgb = np.median(selected[inverse == dominant], axis=0)
    scaled = rgb / 255
    linear = np.where(scaled <= 0.04045, scaled / 12.92, ((scaled + 0.055) / 1.055) ** 2.4)
    xyz = linear @ np.array([[0.4124564, 0.2126729, 0.0193339],
                             [0.3575761, 0.7151522, 0.1191920],
                             [0.1804375, 0.0721750, 0.9503041]])
    xyz /= np.array([0.95047, 1.0, 1.08883])
    transformed = np.where(xyz > (6 / 29) ** 3, np.cbrt(xyz), xyz / (3 * (6 / 29) ** 2) + 4 / 29)
    lab = np.array([116 * transformed[1] - 16, 500 * (transformed[0] - transformed[1]),
                    200 * (transformed[1] - transformed[2])])
    return {"rgb": rgb.tolist(), "lab": lab, "dominance": fraction, "colored_pixels": len(selected)}


def repair(image, graph):
    result = copy.deepcopy(graph)
    audit = []
    panels = result.get("panels", []) if isinstance(result, dict) else []
    if not isinstance(panels, list) or len(panels) > 3:
        return graph, [{"status": "unsupported_schema"}]
    for panel in panels:
        if not isinstance(panel, dict):
            audit.append({"status": "unsupported_schema"})
            continue
        legends, marks = panel.get("legend", []), panel.get("marks", [])
        record = {"panel": panel.get("id"), "status": "unsupported"}
        audit.append(record)
        if not (isinstance(legends, list) and isinstance(marks, list) and 2 <= len(legends) == len(marks) <= 6):
            continue
        if not all(isinstance(item, dict) and isinstance(item.get("id"), str) for item in legends + marks):
            continue
        ids = [item["id"] for item in legends]
        if len(set(ids)) != len(ids) or len({m['id'] for m in marks}) != len(marks):
            continue
        legend_colors = [color(image, item.get("swatch")) for item in legends]
        mark_colors = [color(image, item.get("sample")) for item in marks]
        if any(c is None for c in legend_colors + mark_colors):
            record["status"] = "insufficient_pixel_support"
            continue
        l = np.stack([c["lab"] for c in legend_colors])
        m = np.stack([c["lab"] for c in mark_colors])
        separations = [float(np.linalg.norm(l[i] - l[j])) for i in range(len(l)) for j in range(i)]
        if min(separations) < 12:
            record["status"] = "indistinguishable_colors"
            continue
        costs = np.linalg.norm(m[:, None, :] - l[None, :, :], axis=-1)
        possibilities = sorted((float(sum(costs[i, j] for i, j in enumerate(p))), p)
                               for p in itertools.permutations(range(len(l))))
        best, assignment = possibilities[0]
        margin = possibilities[1][0] - best
        worst_distance = max(float(costs[i, j]) for i, j in enumerate(assignment))
        record.update({"minimum_total_delta_e": best, "assignment_margin": margin,
                       "maximum_pair_delta_e": worst_distance,
                       "legend_rgb": [c['rgb'] for c in legend_colors],
                       "mark_rgb": [c['rgb'] for c in mark_colors]})
        if margin < 12 or worst_distance > 20:
            record["status"] = "ambiguous_assignment"
            continue
        changes = []
        for i, j in enumerate(assignment):
            old = marks[i].get("claimed_legend")
            new = legends[j]["id"]
            if old != new:
                changes.append({"mark": marks[i]["id"], "before": old, "after": new})
            marks[i]["claimed_legend"] = new
        record.update({"status": "accepted", "changes": changes})
    if isinstance(result, dict):
        result["pixel_binding_audit"] = audit
    return result, audit
