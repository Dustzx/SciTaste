"""Freeze scene-separated SpaceCast development/confirmation; no inference."""
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq

from cvpr_chart_run import PROJECT, ROOT, atomic_json, sha

PIN = 'b169e90f6de0bfb7dd23b239e14a0def46c10f2b'
PARQUET_SHA = '27541adff7aec596d0846ccb86b5d49df01366087e2dc050834946b48c426ea2'


def main():
    base=PROJECT/'spacecast/data';source=base/'raw/data/test-00000-of-00001.parquet'
    if (base/'MANIFEST.json').exists():
        raise RuntimeError('Frozen partition exists; verify it rather than reselect')
    h=hashlib.sha256()
    with source.open('rb') as f:
        for block in iter(lambda:f.read(8*1024*1024),b''):h.update(block)
    assert h.hexdigest()==PARQUET_SHA
    sys.path.insert(0,str(PROJECT/'sources/spacecast'))
    from spacecast_eval.data import release_check,source_type,validate_view_metadata
    from spacecast_eval.protocol import prepare_image
    rows=pq.read_table(source).to_pylist();assert len(rows)==3862
    assert release_check(rows)['matches_release']
    assert len({r['question_uid'] for r in rows})==len(rows)
    # Join scene aliases if they contain the exact same original image bytes.
    scenes={(r['dataset'],r['scene_id']) for r in rows};parent={s:s for s in scenes}
    def find(s):
        while parent[s]!=s:parent[s]=parent[parent[s]];s=parent[s]
        return s
    image_owner={}
    for r in rows:
        s=(r['dataset'],r['scene_id']);validate_view_metadata(r,len(r['images']))
        for image in r['images']:
            assert image['bytes'];key=sha(image['bytes'])
            if key in image_owner:
                a,b=find(s),find(image_owner[key]);parent[max(a,b)]=min(a,b)
            else:image_owner[key]=s
    groups={s:find(s) for s in scenes}
    unique=sorted(set(groups.values()),key=lambda s:sha(('spacecast-group-v1|'+repr(s)).encode()))
    dev=set(unique[:max(32,round(len(unique)*.25))]);confirmation=set(unique)-dev
    buckets={}
    for r in rows:
        buckets.setdefault(source_type(r),[]).append(r)
    atomic_json(base/'PREPARATION_DIAGNOSTICS.json', {
        'labels_inspected':False,'raw_scenes':len(scenes),'joined_groups':len(unique),'development_groups':len(dev),
        'component_scene_counts':dict(Counter(map(str,Counter(groups.values()).values()))),
        'development_type_scene_counts':{k:len({groups[(r['dataset'],r['scene_id'])] for r in v}) for k,v in buckets.items()},
        'global_type_scene_counts':{k:len({groups[(r['dataset'],r['scene_id'])] for r in rows if source_type(r)==k}) for k in sorted({source_type(r) for r in rows})}})
    slots=[(rank,code) for rank in range(2) for code in sorted(buckets)]
    eligible={slot:sorted(buckets[slot[1]],key=lambda r:sha(('spacecast-screen-v1|'+r['question_uid']).encode())) for slot in slots}
    assigned={};choices={}
    def assign(slot,visited):
        for row in eligible[slot]:
            group=groups[(row['dataset'],row['scene_id'])]
            if group in visited:continue
            visited.add(group)
            if group not in assigned or assign(assigned[group],visited):
                assigned[group]=slot;choices[slot]=row;return True
        return False
    for slot in slots:
        if not assign(slot,set()):raise RuntimeError('No matching satisfies unique-scene/type quotas; frozen split not widened')
    selected=[choices[slot] for slot in slots];used=set(assigned)
    # Before any inference/partition freeze, stratify by task metadata within
    # the same 46-scene allocation. Answers never affect scene assignment.
    target_dev=max(32,round(len(unique)*.25))
    dev=set(used)
    dev.update([g for g in unique if g not in used][:target_dev-len(used)])
    confirmation=set(unique)-dev
    assert len(dev)==target_dev and not dev & confirmation
    assert len(selected)==32 and len(buckets)==16
    prepared={};images=base/'images';images.mkdir(parents=True,exist_ok=True)
    for r in selected:
        image_paths=[]
        for image in r['images']:
            blob=prepare_image(image['bytes']);digest=sha(blob);p=images/(digest+'.jpg')
            if not p.exists():p.write_bytes(blob)
            image_paths.append({'path':str(p.relative_to(ROOT)),'sha256':digest})
        prepared[r['question_uid']]=image_paths
    inputs=[];labels=[];confirm_ids=[]
    for r in rows:
        group=repr(groups[(r['dataset'],r['scene_id'])]);partition='development' if groups[(r['dataset'],r['scene_id'])] in dev else 'confirmation'
        labels.append({k:r[k] for k in ['question_uid','dataset','scene_id','question','options','answer','type','level','multi_select']})
        labels[-1].update(partition=partition,scene_group=group,source_type=source_type(r))
        if partition=='confirmation':confirm_ids.append(r['question_uid'])
        if r['question_uid'] not in prepared:continue
        # Match official model-visible permissions: question/options and ordered observed images only.
        item={k:r[k] for k in ['question_uid','question','options','type','level','multi_select']}
        item.update(partition='development',scene_group=group,source_type=source_type(r),images=prepared[r['question_uid']])
        inputs.append(item)
    labels_by_id={r['question_uid']:r for r in labels}
    inputs.sort(key=lambda r:next(i for i,x in enumerate(selected) if x['question_uid']==r['question_uid']))
    (base/'development_inputs.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in inputs))
    atomic_json(base/'development_labels.json',[r for r in labels if r['partition']=='development'])
    atomic_json(base/'confirmation_labels_private.json',[r for r in labels if r['partition']=='confirmation'])
    atomic_json(base/'confirmation_ids.json',confirm_ids)
    atomic_json(base/'screen_ids.json',[r['question_uid'] for r in inputs])
    manifest={'schema_version':1,'dataset':'hongxingli/SpaceCast-Bench','revision':PIN,'parquet_sha256':PARQUET_SHA,
              'source_commit':json.loads((PROJECT/'sources/spacecast/SOURCES.json').read_text())['commit'],
              'release_check':release_check(rows),'scene_grouping':'dataset+scene_id plus exact original-image aliases; no semantic-near-duplicate guarantee',
              'groups':len(unique),'development_groups':len(dev),'confirmation_groups':len(confirmation),
              'development_questions':sum(r['partition']=='development' for r in labels),'confirmation_questions':len(confirm_ids),
              'screen_questions':32,'screen_unique_groups':len(used),'screen_type_counts':dict(Counter(r['source_type'] for r in inputs)),
              'selection':'Before any inference, match two slots per16 types to distinct scenes using deterministic augmenting matching in SHA question order; put those32 scenes in DEV then SHA-fill to25%/46scenes. Remaining scenes confirmation. No answers used. Failed pure-hash/greedy preparations preserved; no inference used them.',
              'input_contract':'Only official visible questions/options/initial ordered images. No answer/3D coordinates/depth/post-transform views.',
              'image_protocol':'official prepare_image: JPEG quality90, max1280px, preserved view order',
              'confirmation_evaluated':False,'scope':'exploratory development subset, not official full benchmark or macro_type_accuracy',
              'source_license':'code Apache-2.0; dataset card does not specify license; private research use, no redistribution'}
    manifest['files']={p.name:sha(p.read_bytes()) for p in base.glob('*.json*')}
    atomic_json(base/'MANIFEST.json',manifest)
    print(json.dumps({k:v for k,v in manifest.items() if k not in ['files','screen_type_counts']},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
