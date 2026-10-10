"""Freeze label-separated HR-Bench image groups, never treat rotations as images."""
import base64
import hashlib
import io
import json
from collections import Counter, defaultdict

import numpy as np
import pyarrow.parquet as pq
from PIL import Image
from scipy.fft import dctn

from cvpr_chart_run import PROJECT, ROOT, atomic_json, sha

BASE = PROJECT / 'hrbench'


def phash(im):
    values = np.asarray(im.convert('L').resize((32, 32)), dtype=float)
    low = dctn(values, norm='ortho')[:8, :8].ravel()[1:]
    return low > np.median(low)


def main():
    data = BASE / 'data'
    if (data / 'MANIFEST.json').exists():
        raise RuntimeError('Frozen data already exists; do not overwrite assignments')
    raw = data / 'raw/hr_bench_4k.parquet'
    source = json.loads((BASE / 'sources/DATASET_SOURCE.json').read_text())
    assert hashlib.file_digest(raw.open('rb'), 'sha256').hexdigest() == source['sha256']
    rows = pq.read_table(raw).to_pylist()
    raw_images = {str(r['index']): r['image'] for r in rows}
    image_dir = data / 'images'
    image_dir.mkdir(exist_ok=True)
    images, questions = {}, defaultdict(list)
    for row in rows:
        value = row['image']
        while len(value) < 64:
            value = raw_images[value]
        blob = base64.b64decode(value)
        im = Image.open(io.BytesIO(blob)).convert('RGB')
        key = sha(str(im.size).encode() + im.tobytes())
        if key not in images:
            path = image_dir / (key + '.img')
            path.write_bytes(blob)
            images[key] = {'path': str(path.relative_to(ROOT)), 'sha256': sha(blob),
                           'rgb_sha256': key, 'size': list(im.size), 'phash': phash(im)}
        question_key = sha((key + '|' + row['question'].strip()).encode())
        questions[question_key].append((row, key))
    parents = {key: key for key in images}

    def root(key):
        while parents[key] != key:
            key = parents[key]
        return key

    keys = list(images)
    for i, a in enumerate(keys):
        for b in keys[i+1:]:
            x, y = images[a], images[b]
            if abs((x['size'][0]/x['size'][1])/(y['size'][0]/y['size'][1])-1) <= .02 and np.count_nonzero(x['phash'] != y['phash']) <= 4:
                parents[root(b)] = root(a)
    records, labels, rotations = [], [], {}
    for qkey, variants in questions.items():
        variants.sort(key=lambda v: int(v[0]['index']))
        row, image = variants[0]
        group = root(image)
        uid = 'hr4k-' + str(row['index'])
        options = {k: row[k] for k in 'ABCD'}
        assert row['answer'] in options
        assert len({tuple(sorted(v[0][k] for k in 'ABCD')) for v in variants}) == 1
        assert len({v[0][v[0]['answer']] for v in variants}) == 1
        records.append({'id': uid, 'question': row['question'], 'options': options,
                        'category': row['category'], 'image_group': group, 'image': {k:v for k,v in images[image].items() if k!='phash'},
                        'source_index': int(row['index'])})
        labels.append({'id': uid, 'answer': row['answer'], 'image_group': group})
        rotations[uid] = [{'source_index': int(v['index']), 'options': {k:v[k] for k in 'ABCD'}, 'answer': v['answer'],
                           'cycle_category': v.get('cycle_category')} for v, _ in variants]
    groups_by_category = defaultdict(set)
    for row in records:
        groups_by_category[row['category']].add(row['image_group'])
    dev = set()
    for cat, groups in sorted(groups_by_category.items()):
        ordered = sorted(groups, key=lambda g: sha(('cvpr27-hr-evidence-v1|' + g).encode()))
        dev.update(ordered[:max(1, round(len(groups)*.2))])
    for row in records:
        row['partition'] = 'development' if row['image_group'] in dev else 'confirmation'
    lookup = {r['id']: r for r in records}
    bycat = {cat: sorted([r for r in records if r['partition']=='development' and r['category']==cat],
                         key=lambda r:sha(('screen|' + r['id']).encode())) for cat in groups_by_category}
    screen = []
    for i in range(max(map(len, bycat.values()))):
        for cat in sorted(bycat):
            if i < len(bycat[cat]):
                r = bycat[cat][i]
                if r['image_group'] not in {lookup[k]['image_group'] for k in screen}:
                    screen.append(r['id'])
    screen = screen[:40]
    for part in ['development', 'confirmation']:
        subset = [r for r in records if r['partition']==part]
        path = data / (part + '_inputs.jsonl')
        path.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in subset))
        atomic_json(data/(part+'_labels.json'), [{**r,'partition':part} for r in labels if lookup[r['id']]['partition']==part])
        atomic_json(data/(part+'_rotations.json'), {k:v for k,v in rotations.items() if lookup[k]['partition']==part})
    atomic_json(data/'screen_ids.json', screen)
    manifest = {'dataset':source, 'original_rows':len(rows), 'unique_questions':len(records), 'unique_rgb_images':len(images),
                'image_groups':len({root(k) for k in images}), 'counts':Counter(r['partition'] for r in records),
                'categories':Counter(r['category'] for r in records), 'screen_samples':len(screen),
                'screen_categories':Counter(lookup[k]['category'] for k in screen),
                'grouping':'Exact decoded RGB plus pHash<=4 and aspect ratio difference<=2%; all rotations grouped. 8K counterpart is NOT an independent confirmation set.',
                'assignment':'Before any model outputs; per-category 20% hash image groups; no label-based filtering',
                'primary_readout':'Canonical lowest source-index variant; exact A/B/C/D JSON readout. Cyclic all-four metric reserved as separate confirmation analysis; no LLM judge.',
                'confirmation_evaluated':False, 'script_sha256':sha(open(__file__,'rb').read()),
                'files':{p.name:sha(p.read_bytes()) for p in data.glob('*.json*') if p.name!='MANIFEST.json'}}
    atomic_json(data/'MANIFEST.json', manifest)
    print(json.dumps({k:v for k,v in manifest.items() if k not in ['files','dataset']},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
