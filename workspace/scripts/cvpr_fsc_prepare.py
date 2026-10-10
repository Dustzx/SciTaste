"""Official FSC-147 val development/test reserve; no count-based selection."""
import json
from collections import Counter,defaultdict
from pathlib import Path
import numpy as np
from PIL import Image
from cvpr_hrbench_prepare import phash
from cvpr_chart_run import ROOT,PROJECT,atomic_json,sha

BASE=PROJECT/'counting/fsc147'

def signature(path):
    im=Image.open(path).convert('RGB')
    return {'rgb':sha(str(im.size).encode()+im.tobytes()),'hash':sum(int(b)<<i for i,b in enumerate(phash(im))),
            'aspect':im.width/im.height,'size':list(im.size)}

def similar(a,b):
    return a['rgb']==b['rgb'] or ((a['hash']^b['hash']).bit_count()<=4 and abs(a['aspect']/b['aspect']-1)<=.02)

def main():
    data=BASE/'data';src=BASE/'sources';assert not (data/'MANIFEST.json').exists()
    source=json.loads((src/'DATASET_SOURCE.json').read_text());splits=json.loads((src/'Train_Test_Val_FSC_147.json').read_text());annotations=json.loads((src/'annotation_FSC147_384.json').read_text())
    classes=dict(line.split('\t',1) for line in (src/'ImageClasses_FSC147.txt').read_text().splitlines())
    receipts={r['name']:r for r in source['images']};names=sorted(set(splits['val']+splits['test']));sigs={}
    for name in names:
        path=data/'images'/name;assert sha(path.read_bytes())==receipts[name]['sha256'];sigs[name]=signature(path)
    parent={k:k for k in names}
    def root(k):
        while parent[k]!=k:parent[k]=parent[parent[k]];k=parent[k]
        return k
    for i,a in enumerate(names):
        for b in names[i+1:]:
            if similar(sigs[a],sigs[b]):parent[root(b)]=root(a)
    prior=[]
    for dataset in [PROJECT/'hrbench',PROJECT/'counting']:
        done_ids=set()
        for path in (dataset/'runs').glob('*/calls.jsonl'):
            done_ids.update(json.loads(l)['sample_id'] for l in path.read_text().splitlines())
        for r in map(json.loads,(dataset/'data/development_inputs.jsonl').read_text().splitlines()):
            if r['id'] in done_ids:prior.append(signature(ROOT/r['image']['path']))
    exposed_groups={root(name) for name in names if any(similar(sigs[name],p) for p in prior)}
    dev_groups={root(n) for n in splits['val']};excluded={root(n) for n in splits['test']} & (dev_groups|exposed_groups)
    records=[];labels=[]
    for split in ['val','test']:
        for name in splits[split]:
            sig=sigs[name];group=root(name);uid='fsc-'+Path(name).stem
            partition='development' if split=='val' else ('excluded_exposed' if group in excluded else 'confirmation')
            row={'id':uid,'source_name':name,'source_split':split,'question':'How many '+classes[name]+' are in the image? If none, report zero.',
                 'category':classes[name],'image_type':'real','image_group':group,'partition':partition,
                 'image':{'path':str((data/'images'/name).relative_to(ROOT)),'sha256':receipts[name]['sha256'],'rgb_sha256':sig['rgb'],'size':sig['size']}}
            records.append(row);labels.append({'id':uid,'answer':len(annotations[name]['points']),'image_group':group,'partition':partition})
    strata=defaultdict(list)
    for r in records:
        if r['partition']=='development':strata[r['category']].append(r)
    for rows in strata.values():rows.sort(key=lambda r:sha(('cvpr27-count-fsc-v1|'+r['id']).encode()))
    screen=[];used=set();cats=sorted(strata,key=lambda k:sha(('category|'+k).encode()))
    for i in range(max(map(len,strata.values()))):
        for cat in cats:
            if i<len(strata[cat]):
                r=strata[cat][i]
                if r['image_group'] not in used:screen.append(r['id']);used.add(r['image_group'])
            if len(screen)==32:break
        if len(screen)==32:break
    for part in ['development','confirmation','excluded_exposed']:
        (data/(part+'_inputs.jsonl')).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in records if r['partition']==part))
        atomic_json(data/(part+'_labels.json'),[r for r in labels if r['partition']==part])
    atomic_json(data/'screen_ids.json',screen);lookup={r['id']:r for r in records}
    atomic_json(data/'MANIFEST.json',{'dataset':'FSC-147','official_commit':source['official_commit'],'image_mirror_revision':source['mirror_revision'],
        'official_split_sizes':source['official_split_sizes'],'downloaded_images':len(names),'counts':Counter(r['partition'] for r in records),
        'unique_rgb_images':len({s['rgb'] for s in sigs.values()}),'image_groups':len({root(n) for n in names}),
        'development_groups':len(dev_groups),'confirmation_groups':len({r['image_group'] for r in records if r['partition']=='confirmation'}),
        'screen_samples':len(screen),'screen_categories':Counter(lookup[k]['category'] for k in screen),'prior_exposed_overlap_groups':len(exposed_groups),
        'excluded_test_overlap_groups':len(excluded),'confirmation_evaluated':False,
        'assignment':'Official val only development; official test reserve excluding groups overlapping val or any previously inferred HR/Tally image. Hash percategory roundrobin 32 distinct image groups, no count/error filtering.',
        'grouping':'Decoded RGB + pHash<=4/aspect<=2%, heuristic; no semantic/source independence guarantee.',
        'task':'Category-prompt zero-shot counting without exemplars; target=number of official point annotations. Not original few-shot task, not a certified corrected annotation set.',
        'license':'Images via credited community mirror; upstream image-specific rights unverified, mirror MIT label not assumed to relicense originals. Local research only, no redistribution.',
        'script_sha256':sha(Path(__file__).read_bytes()),'files':{p.name:sha(p.read_bytes()) for p in data.glob('*.json*') if p.name!='MANIFEST.json'}})
    (src/'cvpr_fsc_prepare.py').write_bytes(Path(__file__).read_bytes())
    print(json.dumps({k:v for k,v in json.loads((data/'MANIFEST.json').read_text()).items() if k!='files'},indent=2))

if __name__=='__main__':main()
