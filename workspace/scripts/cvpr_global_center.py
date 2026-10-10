"""Fixed whole-scene reference frame for crop-center attribution; no labels."""
from PIL import ImageDraw

from cvpr_hrbench_views import letterbox
from cvpr_ownership import owns, view

SYSTEM = 'Use only supplied visual evidence. Follow the requested JSON schema.'
TARGET = ('Image 1 is the whole scene. Image 2 is a magnified crop of that same scene. '
          'Images 3, 4 and 5 are the task-provided visual examples of the target object type. '
          'The reference images are not extra objects. The green rectangles indicate the same '
          'ownership core in both scene views, not an object. Use both scene views to recognize '
          'distinct target objects. Do not invent hidden objects or count the same object twice. ')
POINT_RULE = ('Return ONLY JSON {"points":[[x,y],...]}, with no explanation or total count. '
              'All points use the coordinates of the entire displayed Image 1 square, '
              'normalized to 0..1000, top-left[0,0], bottom-right[1000,1000]. '
              'Enumerate all distinct target objects with any visible pixels in Image 2, '
              'including targets outside the green core. An empty list means none. ')
FRAGMENT = ('For each object, mark the center of only the portion of its visible extent '
            'that appears inside the crop Image 2, expressed at its position in Image 1. ')
INSTANCE = ('For each object, mark the center of its entire visible extent in the whole '
            'scene Image 1, even when only a fragment of that object appears in Image 2. '
            'Do not treat two crop fragments of one whole-scene object as distinct objects. ')
SCALAR = ('Count distinct targets whose centers of their entire visible extent in the whole '
          'scene Image 1 lie inside the specified half-open green ownership core. '
          'Use Image 2 for magnified evidence. Return ONLY JSON {"count":nonnegative_integer}, '
          'without explanation. Do not count the same whole-scene object twice. ')


def forward(point, meta):
    return [(point[k] * meta['size'][k] / meta['source_size'][k] + meta['offset'][k]) / meta['side'] * 1000 for k in range(2)]


def canvases(image, geometry):
    whole, meta = letterbox(image, 512)
    core = geometry['core']
    bounds = forward(core[:2], meta) + forward(core[2:], meta)
    ImageDraw.Draw(whole).rectangle([v / 1000 * 512 for v in bounds], outline=(0, 180, 0), width=2)
    crop, crop_geometry = view(image, geometry)
    viewport = forward(geometry['crop'][:2], meta) + forward(geometry['crop'][2:], meta)
    return whole, crop, {**crop_geometry, 'whole_letterbox': meta,
                         'core_in_whole_normalized': bounds, 'crop_in_whole_normalized': viewport}


def map_global(points, geometry):
    meta = geometry['whole_letterbox']
    mapped, seen = [], set()
    for p in points:
        if tuple(p) in seen:
            continue
        seen.add(tuple(p))
        xy = [(p[k] * meta['side'] / 1000 - meta['offset'][k]) / meta['size'][k] * meta['source_size'][k] for k in range(2)]
        for k in range(2):
            for boundary in [0, meta['source_size'][k], geometry['core'][k], geometry['core'][k + 2]]:
                if abs(xy[k] - boundary) < 1e-8:
                    xy[k] = boundary
        mapped.append({'point': xy, 'tile': geometry['tile'],
                       'in_scene': owns(xy, [0, 0, *meta['source_size']]),
                       'owned': owns(xy, geometry['core'])})
    return mapped


def prompt(arm, geometry):
    address = ('Image 2 covers whole-scene normalized bounds ' + str([round(x, 4) for x in geometry['crop_in_whole_normalized']]) +
               '. Green ownership core in Image 1 is x in[' + str(geometry['core_in_whole_normalized'][0]) + ',' + str(geometry['core_in_whole_normalized'][2]) +
               '), y in[' + str(geometry['core_in_whole_normalized'][1]) + ',' + str(geometry['core_in_whole_normalized'][3]) + '). ')
    if arm == 'instance_scalar':
        return TARGET + address + SCALAR
    return TARGET + address + POINT_RULE + (FRAGMENT if arm == 'fragment_center' else INSTANCE)
