"""Frozen HR-Bench development screen: ordinary crop versus explicit correspondence."""
import argparse
import base64
import concurrent.futures
import fcntl
import io
import json
import os
import threading
import time
from pathlib import Path

from PIL import Image

from cvpr_api_retry import PaidRequester
from cvpr_chart_api import Budget, PRICES, credential, now
from cvpr_chart_run import ROOT, PROJECT, atomic_json, sha
from cvpr_hrbench_views import letterbox, regions, views, correspondence

BASE = PROJECT/'hrbench'
ARMS = ['direct','review','crop_plain','crop_linked','crop_shuffled']
FORM = 'Return ONLY JSON with fields in this order: {"answer":"A or B or C or D","reasoning":"brief justification, at most 100 words"}. Exactly one option letter.'
LOCATE = '''The displayed image is a 1024x1024 letterboxed overview. Identify exactly two source regions whose fine detail is most useful for answering the question. A region may be a chart panel, text block, object or pair of interacting objects. Use the displayed square's coordinates, including its white padding: 0..1000, x increasing right, y increasing down. Return ONLY JSON {"regions":[{"description":"what to inspect, without guessing an answer","box":[x0,y0,x1,y1]},{"description":"what to inspect","box":[x0,y0,x1,y1]}]}. Boxes must enclose visible evidence and necessary nearby context. Do NOT output an answer or infer unreadable details. Empty regions are allowed if no useful addresses can be identified.'''
SOLVE = '''The first image is an overview and the next two images are enlarged source crops. Re-read their actual pixels to answer the question. Proposed region descriptions may be wrong. Crop-image arrangement does not imply a spatial relation in the original scene. Use the overview for relations and the enlarged crops for fine details.'''
LINK = '''Source correspondence is provided below. Integer rectangle IDs mark the actual crop locations in the overview; crop image indices count the overview as image 1. The program supplies addresses only, not verified object identities or answers. Match each detail to its source before combining observations. A full-image fallback has no rectangle.'''
REVIEW = 'Recheck the provisional solution against the image. Correct visual and reasoning errors; do not copy a previous answer uncritically.'


def cached_response(done, key, digest):
    if key in done:
        assert done[key]['prompt_sha256']==digest, 'Persisted request inputs changed'
        return done[key]
    sample=key.split('|')[0]
    return next((r for r in done.values() if r['sample_id']==sample and r['prompt_sha256']==digest), None)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--run-id',required=True)
    parser.add_argument('--stop-after',type=int,default=40)
    parser.add_argument('--model',choices=PRICES,default='qwen3.8-flash')
    parser.add_argument('--phase-cap-cny',type=float,default=20)
    args=parser.parse_args()
    assert args.run_id.replace('-','').replace('_','').isalnum()
    assert 1<=args.stop_after<=40 and 0<args.phase_cap_cny<=300
    data=BASE/'data';manifest=json.loads((data/'MANIFEST.json').read_text())
    ids=json.loads((data/'screen_ids.json').read_text())
    rows={r['id']:r for r in map(json.loads,(data/'development_inputs.jsonl').read_text().splitlines())}
    assert len({rows[k]['image_group'] for k in ids})==len(ids)
    assert sha((data/'development_inputs.jsonl').read_bytes())==manifest['files']['development_inputs.jsonl']
    for k in ids:
        r=rows[k];assert r['partition']=='development' and not {'answer','Answer'}&set(r)
        assert sha((ROOT/r['image']['path']).read_bytes())==r['image']['sha256']
    run=BASE/'runs'/args.run_id;run.mkdir(parents=True,exist_ok=True)
    lock=(run/'.run.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    ledger=json.loads((PROJECT/'API_LEDGER.json').read_text())
    retained={k:v for k,v in ledger['attempts'].items() if v['status']!='settled'}
    for e in retained.values():
        assert e['run_id']!=args.run_id, 'Reconcile unknown attempts before resuming this run'
        pid=e.get('pid');p=Path(f'/proc/{pid}/cmdline')
        assert not p.exists() or e['run_id'].encode() not in p.read_bytes(), 'Unresolved live sibling process'
    protocol={'model':args.model,'weight_revision':None,'training':False,'local_gpu':False,'thinking':False,'temperature':0,
              'arms':ARMS,'sample_ids':ids,'scope':'exploratory HR-Bench 4K development-only; canonical option ordering',
              'prompts':{'form':FORM,'locate':LOCATE,'solve':SOLVE,'link':LINK,'review':REVIEW},
              'max_generated_tokens_per_arm':1792,'two_call_allocation':[768,1024],
              'submitted_pixel_budget':{'direct':1810**2,'review':2*1280**2,'each_crop_arm':2*1024**2+2*768**2},
              'pixel_budget_caveat':'Submitted square raster pixels incl padding; provider internal visual tokens opaque. Plain/linked/shuffled use identical source crop pixels and sizes, with annotation/order differences intentional.',
              'primary_comparison':'crop_linked vs crop_plain; same localization response, crop multiset, call/token ceilings; shared localization logically charged to every crop arm',
              'negative_control':'crop_shuffled swaps the two crop images while retaining correct overview labels and metadata; measures sensitivity to correspondence corruption, not a deployment baseline',
              'expansion_gate':'At least 3 net improved image groups over BOTH crop_plain and review, non-saturated baseline, >=20 supported-address samples; full paired outputs; case audit must show correspondence repair. Otherwise stop this version. No confirmation without freeze.',
              'scientific_limits':'Coarse fallible proposed boxes, no ground-truth ROI. Candidate extends known crop/SoM ideas, novelty unestablished. Direct is 700 fewer submitted pixels (<.03%). Equal caps do not mean identical billed tokens/FLOPs; retry attempts cost extra.',
              'manifest_sha256':sha((data/'MANIFEST.json').read_bytes()),'phase_cap_cny':args.phase_cap_cny,'project_cap_cny':300,
              'prices':PRICES[args.model],'retained_unknown':retained,'retry_authorization_sha256':sha((PROJECT/'RETRY_AUTHORIZATION.json').read_bytes()),
              'source_sha256':{p.name:sha(p.read_bytes()) for p in [Path(__file__),ROOT/'scripts/cvpr_hrbench_views.py',ROOT/'scripts/cvpr_api_retry.py',ROOT/'scripts/cvpr_chart_api.py']}}
    if (run/'PROTOCOL.json').exists():
        old=json.loads((run/'PROTOCOL.json').read_text())
        assert old==json.loads(json.dumps(protocol)), 'Changed protocol; do not overwrite'
    else:
        atomic_json(run/'PROTOCOL.json',protocol)
        for name in protocol['source_sha256']:(run/name).write_bytes((ROOT/'scripts'/name).read_bytes())
    records=[json.loads(s) for s in (run/'calls.jsonl').read_text().splitlines()] if (run/'calls.jsonl').exists() else []
    done={r['key']:r for r in records};preds=json.loads((run/'PREDICTIONS.json').read_text()) if (run/'PREDICTIONS.json').exists() else []
    assert len(done)==len(records)
    for r in records:
        e=ledger['attempts'][r['ledger_key']]
        assert e['status']=='settled' and e['response_id']==r['response_id'], 'Reconcile persisted success before any further calls'
    complete={p['id'] for p in preds}
    assert all(sum(p['id']==k for p in preds)==len(ARMS) for k in complete)
    halt=threading.Event();mutex=threading.Lock();start=time.monotonic()
    budget=Budget(retained,retry_own_failures=True)
    requester=PaidRequester(budget=budget,run=run,run_id=args.run_id,secret=credential(),halt=halt,
                            prices=PRICES[args.model],phase_cap=args.phase_cap_cny,wall_limit_seconds=7200)
    def save(item):
        with mutex:
            with (run/'calls.jsonl').open('a') as f:
                f.write(json.dumps(item,ensure_ascii=False)+'\n');f.flush();os.fsync(f.fileno())
            done[item['key']]=item;records.append(item)
    def call(row,stage,prompt,images,cap):
        key=row['id']+'|'+stage
        blobs=[]
        for image in images:
            stream=io.BytesIO();image.save(stream,format='PNG');blobs.append(stream.getvalue())
        digest=sha(json.dumps({'prompt':prompt,'images':[sha(b) for b in blobs],'cap':cap},sort_keys=True).encode())
        reused=cached_response(done,key,digest)
        if reused is not None:
            return reused
        visual=[{'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(b).decode()}} for b in blobs]
        body={'model':args.model,'messages':[{'role':'system','content':'You answer visual multiple-choice questions using the supplied images.'},
              {'role':'user','content':visual+[{'type':'text','text':prompt}]}],
              'max_tokens':cap,'temperature':0,'enable_thinking':False,'response_format':{'type':'json_object'}}
        item=requester.call(key=key,cap=cap,body=body,digest=digest,save=save)
        print(json.dumps({'key':key,'seconds':round(item['elapsed_seconds'],2),'cost_cny':item['api_cost_cny'],'truncated':item['truncated']},ensure_ascii=False),flush=True)
        return item
    def status(state):
        atomic_json(run/'STATUS.json',{'state':state,'pid':os.getpid(),'updated_at':now(),'model':args.model,'planned_samples':len(ids),
                    'checkpoint_samples':args.stop_after,'completed_samples':len(preds)//len(ARMS),'predictions':len(preds),'actual_calls':len(records),
                    'elapsed_seconds_this_session':time.monotonic()-start,'api_cost_cny':sum(r['api_cost_cny'] for r in records),'local_gpu':False,
                    'confirmation_evaluated':False})
    def process(uid):
        row=rows[uid];image=Image.open(ROOT/row['image']['path']).convert('RGB')
        question=row['question']+'\n'+'\n'.join(k+') '+v for k,v in row['options'].items())
        locate=call(row,'locate',question+'\n'+LOCATE,[letterbox(image,1024)[0]],768)
        chosen,audit=regions(locate['parsed'] if not locate['truncated'] else {},image)
        folder=run/'views'/uid;folder.mkdir(parents=True,exist_ok=True)
        atomic_json(folder/'REGIONS.json',{'regions':chosen,'address_audit':audit,'locator_key':locate['key']})
        for j,view in enumerate(views(image,chosen,linked=True)):view.save(folder/f'linked_{j}.png')
        local=[]
        # Alternate plain/linked order; direct/review remain fixed strong controls.
        ordered=ARMS[:2]+(['crop_linked','crop_plain'] if ids.index(uid)%2 else ['crop_plain','crop_linked'])+['crop_shuffled']
        for arm in ordered:
            if arm=='direct':
                final=call(row,arm,question+'\n'+FORM,[letterbox(image,1810)[0]],1792);charge=[final]
            elif arm=='review':
                first=call(row,'reason',question+'\n'+FORM,[letterbox(image,1280)[0]],768)
                final=call(row,arm,question+'\n'+REVIEW+'\n'+first['text']+'\n'+FORM,[letterbox(image,1280)[0]],1024);charge=[first,final]
            else:
                prompt=question+'\n'+SOLVE+'\nProposed region descriptions: '+json.dumps([r['description'] for r in chosen],ensure_ascii=False)
                linked=arm!='crop_plain'
                if linked:prompt+='\n'+LINK+'\n'+json.dumps(correspondence(chosen))
                final=call(row,arm,prompt+'\n'+FORM,views(image,chosen,linked=linked,shuffled=arm=='crop_shuffled'),1024)
                charge=[locate,final]
            answer=(final['parsed'] or {}).get('answer')
            valid=isinstance(answer,str) and answer.strip() in 'ABCD' and len(answer.strip())==1 and not final['truncated']
            local.append({'id':uid,'image_group':row['image_group'],'category':row['category'],'arm':arm,
                          'answer':answer.strip() if valid else None,'valid':valid,'actual_call_keys':[r['key'] for r in charge],
                          'logical_calls':len(charge),'logical_input_tokens':sum(r['input_tokens'] for r in charge),
                          'logical_output_tokens':sum(r['output_tokens'] for r in charge),'logical_seconds':sum(r['elapsed_seconds'] for r in charge),
                          'logical_api_cost_cny':sum(r['api_cost_cny'] for r in charge),'supported_regions':sum(r['supported'] for r in chosen)})
        with mutex:
            preds.extend(local);atomic_json(run/'PREDICTIONS.json',preds);status('running')
        print(json.dumps({'complete':uid,'paired_samples':len(preds)//len(ARMS),'elapsed_seconds':time.monotonic()-start}),flush=True)
    status('running')
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            pending=[pool.submit(process,k) for k in ids[:args.stop_after] if k not in complete]
            for future in concurrent.futures.as_completed(pending):
                try:future.result()
                except Exception:
                    halt.set()
                    for f in pending:f.cancel()
                    raise
    except Exception:
        status('held_execution_failure');raise
    status('completed_predictions' if args.stop_after>=len(ids) else 'checkpoint_predictions')


if __name__=='__main__':
    main()
