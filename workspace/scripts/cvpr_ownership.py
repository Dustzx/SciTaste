"""Crop geometry and deterministic point ownership; no labels or model calls."""
import math

from PIL import ImageDraw

from cvpr_hrbench_views import letterbox


def tiles(width, height, halo):
    """Four disjoint cores with clipped, overlapping context windows."""
    assert width >= 2 and height >= 2 and 0 <= halo < .5
    xs, ys = [0, width // 2, width], [0, height // 2, height]
    hx, hy = round(width * halo), round(height * halo)
    result = []
    for j in range(2):
        for i in range(2):
            core = [xs[i], ys[j], xs[i + 1], ys[j + 1]]
            crop = [max(0, core[0] - hx), max(0, core[1] - hy),
                    min(width, core[2] + hx), min(height, core[3] + hy)]
            result.append({'tile': len(result), 'core': core, 'crop': crop})
    return result


def owns(point, core):
    x, y = point
    return core[0] <= x < core[2] and core[1] <= y < core[3]


def view(image, geometry):
    crop = geometry['crop']
    canvas, meta = letterbox(image.crop(crop), 768)
    sx, sy = meta['size'][0] / (crop[2] - crop[0]), meta['size'][1] / (crop[3] - crop[1])
    ox, oy = meta['offset']
    core = geometry['core']
    bounds = [(core[0] - crop[0]) * sx + ox, (core[1] - crop[1]) * sy + oy,
              (core[2] - crop[0]) * sx + ox, (core[3] - crop[1]) * sy + oy]
    # Same marked pixels for scalar and point queries on each geometry.
    ImageDraw.Draw(canvas).rectangle(bounds, outline=(0, 180, 0), width=2)
    return canvas, {**geometry, 'letterbox': meta,
                    'core_normalized': [round(v / 768 * 1000, 3) for v in bounds]}


def parsed_points(call):
    obj = call.get('parsed')
    if call.get('truncated') or not isinstance(obj, dict) or not isinstance(obj.get('points'), list):
        return None
    points = obj['points']
    if len(points) > 512:
        return None
    for p in points:
        if not isinstance(p, list) or len(p) != 2:
            return None
        if any(isinstance(x, bool) or not isinstance(x, (float, int)) or
               not math.isfinite(x) or not 0 <= x <= 1000 for x in p):
            return None
    return points


def map_points(points, geometry):
    """Inverse letterboxing uses actual rounded raster dimensions per axis."""
    crop, meta, core = geometry['crop'], geometry['letterbox'], geometry['core']
    mapped, seen = [], set()
    for p in points:
        local = tuple(p)
        if local in seen:
            continue
        seen.add(local)
        point = [(p[k] * 768 / 1000 - meta['offset'][k]) / meta['size'][k]
                 * (crop[k + 2] - crop[k]) + crop[k] for k in range(2)]
        for k in range(2):
            for boundary in [crop[k], crop[k + 2], core[k], core[k + 2]]:
                if abs(point[k] - boundary) < 1e-8:
                    point[k] = boundary
        mapped.append({'point': point, 'in_crop': owns(point, crop),
                       'owned': owns(point, core), 'tile': geometry['tile']})
    return mapped


def merge_cross_view(points, radius):
    """Fixed-radius connected-component stitching, a necessary conventional control."""
    parent = list(range(len(points)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, a in enumerate(points):
        for j, b in enumerate(points[:i]):
            if a['tile'] != b['tile'] and math.dist(a['point'], b['point']) <= radius:
                parent[find(i)] = find(j)
    return len({find(i) for i in range(len(points))})
