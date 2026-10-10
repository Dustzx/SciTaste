"""Freeze a label-blind, stratified ScreenSpot-Pro development panel."""
import concurrent.futures
import io
import json
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import quote

import requests
from PIL import Image

from cvpr_chart_api import now
from cvpr_chart_run import ROOT, PROJECT, atomic_json, sha

BASE = PROJECT / 'gui'
SEED = 'fastresearch-gui-headroom-20261010-v1'


def main():
    source, data = BASE / 'sources', BASE / 'data'
    if (data / 'MANIFEST.json').exists():
        raise RuntimeError('Panel already frozen; verify/reuse it instead of selecting again')
    receipts = json.loads((source / 'ANNOTATION_RECEIPTS.json').read_text())
    hub = json.loads((source / 'HUB_METADATA.json').read_text())
    rows = []
    for entry in receipts['files']:
        path = source / entry['file']
        assert sha(path.read_bytes()) == entry['sha256']
        rows += json.loads(path.read_text())
    assert len(rows) == len({r['id'] for r in rows}) == len({r['img_filename'] for r in rows}) == 1581
    strata = defaultdict(list)
    for row in rows:
        strata[(row['group'], row['ui_type'])].append(row)
    for values in strata.values():
        values.sort(key=lambda r: sha((SEED + '|' + r['id']).encode()))
    keys = sorted(strata)
    selected = []
    while len(selected) < 32:
        for key in keys:
            if strata[key] and len(selected) < 32:
                selected.append(strata[key].pop(0))
    data.mkdir(parents=True, exist_ok=True)
    selected_ids = {r['id'] for r in selected}
    atomic_json(data / 'screen_ids.json', [r['id'] for r in selected])
    atomic_json(data / 'DEVELOPMENT_LABELS.json', {r['id']: r for r in selected})
    # Reserve by immutable filename; near-duplicate/session independence is still unaudited.
    atomic_json(data / 'RESERVED_IDS.json', [r['id'] for r in rows if r['id'] not in selected_ids])

    def fetch(row):
        rel = Path(row['img_filename'])
        assert not rel.is_absolute() and '..' not in rel.parts
        path = data / 'images' / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        url = f'https://huggingface.co/datasets/{hub["id"]}/resolve/{hub["sha"]}/images/' + quote(str(rel))
        if not path.exists():
            response = requests.get(url, timeout=(15, 120))
            response.raise_for_status()
            path.write_bytes(response.content)
        blob = path.read_bytes()
        image = Image.open(io.BytesIO(blob))
        assert image.format == 'PNG' and list(image.size) == row['img_size']
        assert len(blob) * 4 / 3 + 20000 < 16 * 1024**2, 'DashScope domain body limit; no silent resize'
        return {'id': row['id'], 'partition': 'development', 'image_group': row['img_filename'],
                'category': row['group'], 'ui_type': row['ui_type'], 'application': row['application'],
                'platform': row['platform'], 'instruction': row['instruction'],
                'image': {'path': str(path.relative_to(ROOT)), 'sha256': sha(blob),
                          'size': list(image.size), 'bytes': len(blob), 'url': url}}

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        inputs = list(pool.map(fetch, selected))
    assert len({r['image']['sha256'] for r in inputs}) == 32
    (data / 'development_inputs.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in inputs))
    manifest = {'created_at': now(), 'dataset': hub['id'], 'revision': hub['sha'],
                'official_rows': len(rows), 'development_groups': 32, 'reserved_groups': len(rows) - 32,
                'seed': SEED, 'selection': 'Hash within category x ui_type, sorted-stratum round robin; no label/box-size/error filtering',
                'strata_counts': dict(Counter(r['category'] + '/' + r['ui_type'] for r in inputs)),
                'grouping_limit': 'Unique filenames and exact image hashes checked; same-session/near-duplicate independence not yet certified. Public official test panel becomes development before inference.',
                'source_receipts_sha256': sha((source / 'SOURCE_RECEIPTS.json').read_bytes()),
                'annotation_receipts_sha256': sha((source / 'ANNOTATION_RECEIPTS.json').read_bytes()),
                'prepare_source_sha256': sha(Path(__file__).read_bytes()),
                'files': {name: sha((data / name).read_bytes()) for name in ['screen_ids.json', 'DEVELOPMENT_LABELS.json', 'RESERVED_IDS.json', 'development_inputs.jsonl']},
                'legal': 'Dataset card MIT tag; screenshot third-party rights not independently cleared, local evaluation only, no republication.',
                'viewer': 'Official Viewer disabled/unsupported; pinned original annotations/images used, failed Viewer receipts retained.'}
    atomic_json(data / 'MANIFEST.json', manifest)
    print(json.dumps({k: manifest[k] for k in ['development_groups', 'reserved_groups', 'strata_counts']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
