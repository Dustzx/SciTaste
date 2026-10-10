"""Freeze TallyBench image-group partitions and label-free screen before inference."""
import io
import json
from collections import Counter, defaultdict
import hashlib

import numpy as np
import pyarrow.parquet as pq
from PIL import Image

from cvpr_chart_run import ROOT, PROJECT, atomic_json, sha
from cvpr_hrbench_prepare import phash

BASE = PROJECT/'counting'


def main():
    data=BASE/'data'
    assert not (data/'MANIFEST.json').exists(), 'Frozen dataset must not be overwritten'
    source=json.loads((BASE/'sources/DATASET_SOURCE.json').read_text())
    paths=[BASE/f['file'] for f in source['files'] if f['file'].endswith('.parquet')]
    for path in paths:
        entry=next(f for f in source['files'] if BASE/f['file']==path)
        assert hashlib.file_digest(path.open('rb'),'sha256').hexdigest()==entry['sha256']
    images={};records=[];labels=[];out=data/'images';out.mkdir(exist_ok=True)
    for path in paths:
        for batch in pq.ParquetFile(path).iter_batches(batch_size=32):
            for row in batch.to_pylist():
                blob=row['image']['bytes'];im=Image.open(io.BytesIO(blob)).convert('RGB')
                rgb=sha(str(im.size).encode()+im.tobytes())
                if rgb not in images:
                    dest=out/(rgb+'.img');dest.write_bytes(blob)
                    h=phash(im);bits=sum(int(b)<<i for i,b in enumerate(h))
                    images[rgb]={'path':str(dest.relative_to(ROOT)),'sha256':sha(blob),'rgb_sha256':rgb,'size':list(im.size),'phash':bits}
                uid='tally-'+row['image_name'].rsplit('.',1)[0]
                records.append({'id':uid,'question':row['vlm_question'],'category':row['categories'],
                                'image_type':row['image_type'],'image':{k:v for k,v in images[rgb].items() if k!='phash'}})
                assert type(row['gt_answer']) is int and row['gt_answer']>=0
                labels.append({'id':uid,'answer':row['gt_answer']})
    assert len({r['id'] for r in records})==len(records)
    parents={k:k for k in images}
    def root(k):
        while parents[k]!=k:
            parents[k]=parents[parents[k]];k=parents[k]
        return k
    keys=list(images)
    for i,a in enumerate(keys):
        x=images[a]
        for b in keys[i+1:]:
            y=images[b]
            if (x['phash']^y['phash']).bit_count()<=4 and abs((x['size'][0]/x['size'][1])/(y['size'][0]/y['size'][1])-1)<=.02:
                parents[root(b)]=root(a)
    exposed=set()
    preview_ids={'tally-'+str(i).zfill(4) for i in range(1,9)}
    exposed.update(root(r['image']['rgb_sha256']) for r in records if r['id'] in preview_ids)
    # HR development images have been viewed; detected cross-benchmark overlap stays development.
    hr=PROJECT/'hrbench/data/development_inputs.jsonl'
    prior=[]
    for row in map(json.loads,hr.read_text().splitlines()):
        im=Image.open(ROOT/row['image']['path']).convert('RGB');prior.append((row['image']['rgb_sha256'],sum(int(b)<<i for i,b in enumerate(phash(im))),im.width/im.height))
    for k,im in images.items():
        if any(k==rgb or ((im['phash']^h).bit_count()<=4 and abs((im['size'][0]/im['size'][1])/aspect-1)<=.02) for rgb,h,aspect in prior):exposed.add(root(k))
    groups=sorted({root(k) for k in images},key=lambda k:sha(('cvpr27-count-code-v1|'+k).encode()))
    dev=set(groups[:round(.2*len(groups))])|exposed
    lookup={r['id']:r for r in records}
    for r in records:
        r['image_group']=root(r['image']['rgb_sha256']);r['partition']='development' if r['image_group'] in dev else 'confirmation'
    strata=defaultdict(list)
    for r in records:
        if r['partition']=='development':strata[r['image_type']].append(r)
    for rows in strata.values():rows.sort(key=lambda r:sha(('screen|'+r['id']).encode()))
    screen=[];used=set()
    for i in range(max(map(len,strata.values()))):
        for typ in sorted(strata):
            if i<len(strata[typ]):
                r=strata[typ][i]
                if r['image_group'] not in used:screen.append(r['id']);used.add(r['image_group'])
        if len(screen)>=32:break
    screen=screen[:32]
    for part in ['development','confirmation']:
        (data/(part+'_inputs.jsonl')).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in records if r['partition']==part))
        atomic_json(data/(part+'_labels.json'),[{**r,'partition':part,'image_group':lookup[r['id']]['image_group']} for r in labels if lookup[r['id']]['partition']==part])
    atomic_json(data/'screen_ids.json',screen)
    atomic_json(data/'MANIFEST.json',{'dataset':source['dataset'],'revision':source['revision'],'original_rows':len(records),
        'unique_rgb_images':len(images),'image_groups':len(groups),'counts':Counter(r['partition'] for r in records),
        'screen_samples':len(screen),'screen_types':Counter(lookup[k]['image_type'] for k in screen),'screen_categories':Counter(lookup[k]['category'] for k in screen),
        'previous_hr_development_overlap_groups':len(exposed),'confirmation_evaluated':False,
        'grouping':'Decoded RGB plus pHash<=4/aspect<=2%; heuristic duplicate detection, not guaranteed semantic independence',
        'assignment':'Global hash first 20% image groups; first 8 source-preview labels and detected prior-HR-development overlaps assigned development; screen alternates image_type, one question per group. No gold-based filtering.',
        'license':'Dataset card declares CC-BY-4.0; original image rights not individually verified; local research only, no data republication.',
        'script_sha256':sha(open(__file__,'rb').read()),'files':{p.name:sha(p.read_bytes()) for p in data.glob('*.json*') if p.name!='MANIFEST.json'}})
    print(json.dumps(json.loads((data/'MANIFEST.json').read_text()),indent=2))


if __name__=='__main__':main()
