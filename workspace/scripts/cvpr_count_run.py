"""Frozen development-only TallyBench screen, budgeted via the shared ledger."""
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

from PIL import Image, ImageDraw

from cvpr_api_retry import PaidRequester
from cvpr_chart_api import Budget, PRICES, credential, now
from cvpr_chart_run import ROOT, PROJECT, atomic_json, sha
from cvpr_hrbench_views import letterbox
from cvpr_count_code import MATRIX, decode, valid_count, vote

BASE=PROJECT/'counting'
FORM='Count the objects requested in the question from the actual image. Return ONLY JSON {"count":nonnegative_integer,"reasoning":"brief visual justification"}. Do not use external captions or estimate from a stereotypical scene.'
SYSTEM='You count visible objects in supplied images. Follow the question and report a numerical count.'
REGION='''The full image is retained for context. Thin red lines divide its displayed square into three disjoint vertical strips: A is x in [0,256), B is [256,512), C is [512,768]. Assign each eligible object once, by the horizontal center of its visible bounding box, including partially visible objects if the original question includes them. An object on a boundary belongs to the strip on its right. Ignore the added red lines as objects. Count only objects with centers in the selected strips {selected}. Preserve any eligibility conditions from the original question; the requested output is this selected-region count, not the whole-image total. Return ONLY JSON {{"count":nonnegative_integer,"reasoning":"brief visual justification"}}.'''
TRANSFORMS=[None,Image.Transpose.FLIP_LEFT_RIGHT,Image.Transpose.FLIP_TOP_BOTTOM,Image.Transpose.ROTATE_180,Image.Transpose.ROTATE_90,Image.Transpose.ROTATE_270,Image.Transpose.TRANSPOSE]


def main():
    p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--mode',choices=['baseline','full'],required=True);p.add_argument('--stop-after',type=int,default=32)
    p.add_argument('--dataset',choices=['tallybench','fsc147'],default='tallybench')
    args=p.parse_args();assert args.run_id.replace('_','').replace('-','').isalnum();assert 1<=args.stop_after<=32
    base=BASE if args.dataset=='tallybench' else BASE/'fsc147'
    data=base/'data';manifest=json.loads((data/'MANIFEST.json').read_text());ids=json.loads((data/'screen_ids.json').read_text())
    assert len(ids)==32 and sha((data/'development_inputs.jsonl').read_bytes())==manifest['files']['development_inputs.jsonl']
    rows={r['id']:r for r in map(json.loads,(data/'development_inputs.jsonl').read_text().splitlines())}
    for k in ids:
        r=rows[k];assert r['partition']=='development' and not {'answer','caption','gt_answer'}&set(r)
        assert sha((ROOT/r['image']['path']).read_bytes())==r['image']['sha256']
    assert len({rows[k]['image_group'] for k in ids})==32
    run=base/'runs'/args.run_id;run.mkdir(parents=True,exist_ok=True)
    lock=(run/'.run.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    ledger=json.loads((PROJECT/'API_LEDGER.json').read_text());retained={k:v for k,v in ledger['attempts'].items() if v['status']!='settled'}
    assert not any(v['run_id']==args.run_id for v in retained.values()),'Unresolved own attempt requires reconciliation'
    for v in retained.values():
        path=Path('/proc')/str(v['pid'])/'cmdline'
        assert not path.exists() or v['run_id'].encode() not in path.read_bytes(),'Unresolved sibling is alive'
    proto={'model':'qwen3.8-flash','temperature':0,'enable_thinking':False,'weight_revision':None,'local_gpu':False,
           'sample_ids':ids,'dataset':manifest['dataset'],'manifest_sha256':sha((data/'MANIFEST.json').read_bytes()),'scope':'32 fixed image-group development screen; not official test; confirmation unopened',
           'prompts':{'system':SYSTEM,'form':FORM,'region':REGION},'matrix':MATRIX.tolist(),
           'arms':['direct','transform_vote','partition_sum','conservation_decode'],
           'transform_order':['identity','hflip','vflip','rot180','rot90','rot270','transpose'],
           'caps':{'per_call':256,'transform_vote':7*256,'conservation_decode':7*256,'partition_sum':3*256,'direct':256},
           'raster_pixels':{'per_call':768**2,'transform_vote':7*768**2,'conservation_decode':7*768**2},
           'shared_calls':'Identity whole-image response shared by direct/vote/code; partition_sum reuses A/B/C. Each arm charged full logical calls. 13 actual distinct requests/sample.',
           'headroom_gate':'Only proceed from all 32 baseline to full paired screen if direct exact accuracy <85%; otherwise stop this benchmark/version.',
           'expansion_gate':'At least 3 net improved image groups over BOTH transform_vote and partition_sum; at least 8 accepted conservation decodes including >=2 corrections of an incorrect global count; all32 paired; visual case audit and novelty audit required before confirmation.',
           'decoder':'Solve all invertible 3-row subsets for nonnegative integers; unique min-Hamming candidate accepted only <=1 mismatch/erasure, otherwise global fallback. Tie in vote: first response among tied modes.',
           'limits':'Count conservation depends on correct semantic eligibility and center ownership. Internally consistent perception can be wrong; no truth certificate. Region markings and transformed image content differ intentionally. D4 may disrupt orientation-dependent questions, reported not excluded. Shared identities are not resampled. Provider visual compute opaque; retries add unknown cost.',
           'phase_cap_cny':20,'project_cap_cny':300,'retained_unknown':retained,'prices':PRICES['qwen3.8-flash'],
           'source_sha256':{n:sha((ROOT/'scripts'/n).read_bytes()) for n in ['cvpr_count_run.py','cvpr_count_code.py','cvpr_api_retry.py','cvpr_chart_api.py']}}
    if (run/'PROTOCOL.json').exists():assert json.loads((run/'PROTOCOL.json').read_text())==json.loads(json.dumps(proto)),'Frozen protocol changed'
    else:
        atomic_json(run/'PROTOCOL.json',proto)
        for n in proto['source_sha256']:(run/n).write_bytes((ROOT/'scripts'/n).read_bytes())
    if args.mode=='full':assert json.loads((run/'HEADROOM.json').read_text())['proceed_full'], 'Failed baseline headroom gate'
    records=[json.loads(s) for s in (run/'calls.jsonl').read_text().splitlines()] if (run/'calls.jsonl').exists() else []
    done={r['key']:r for r in records};assert len(done)==len(records)
    for r in records:
        e=ledger['attempts'][r['ledger_key']];assert e['status']=='settled' and e['response_id']==r['response_id']
    predfile=run/('BASELINE_PREDICTIONS.json' if args.mode=='baseline' else 'PREDICTIONS.json')
    preds=json.loads(predfile.read_text()) if predfile.exists() else [];completed={r['id'] for r in preds}
    halt=threading.Event();mutex=threading.Lock();start=time.monotonic()
    requester=PaidRequester(budget=Budget(retained,retry_own_failures=True),run=run,run_id=args.run_id,secret=credential(),halt=halt,prices=PRICES['qwen3.8-flash'],phase_cap=20,wall_limit_seconds=7200)
    def status(state):
        atomic_json(run/'STATUS.json',{'state':state,'mode':args.mode,'pid':os.getpid(),'updated_at':now(),'planned_samples':32,'completed_samples':len(preds),
            'actual_calls':len(records),'api_cost_cny':sum(r['api_cost_cny'] for r in records),'elapsed_seconds_this_session':time.monotonic()-start,'local_gpu':False,'confirmation_evaluated':False})
    def save(item):
        with mutex:
            with (run/'calls.jsonl').open('a') as f:f.write(json.dumps(item,ensure_ascii=False)+'\n');f.flush();os.fsync(f.fileno())
            records.append(item);done[item['key']]=item
    def call(row,stage,prompt,image):
        stream=io.BytesIO();image.save(stream,format='PNG');blob=stream.getvalue();key=row['id']+'|'+stage
        digest=sha(json.dumps({'prompt':prompt,'image_sha':sha(blob),'cap':256,'system':SYSTEM},sort_keys=True).encode())
        if key in done:
            assert done[key]['prompt_sha256']==digest;return done[key]
        same=next((r for r in done.values() if r['sample_id']==row['id'] and r['prompt_sha256']==digest),None)
        if same:return same
        body={'model':'qwen3.8-flash','temperature':0,'enable_thinking':False,'max_tokens':256,'response_format':{'type':'json_object'},
              'messages':[{'role':'system','content':SYSTEM},{'role':'user','content':[{'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(blob).decode()}},{'type':'text','text':prompt}]}]}
        response=requester.call(key=key,cap=256,body=body,digest=digest,save=save)
        print(json.dumps({'key':key,'seconds':response['elapsed_seconds'],'truncated':response['truncated']}),flush=True);return response
    def count(r):
        value=(r['parsed'] or {}).get('count');return value if valid_count(value) and not r['truncated'] else None
    def metrics(calls):
        return {'call_keys':[r['key'] for r in calls],'logical_calls':len(calls),**{out:sum(r[k] for r in calls) for out,k in [('input_tokens','input_tokens'),('output_tokens','output_tokens'),('api_cost_cny','api_cost_cny'),('seconds','elapsed_seconds')]}}
    def process(uid):
        row=rows[uid];original=Image.open(ROOT/row['image']['path']).convert('RGB');overview=letterbox(original,768)[0]
        whole=call(row,'identity',row['question']+'\n'+FORM,overview)
        entry={'id':uid,'image_group':row['image_group'],'category':row['category'],'image_type':row['image_type'],'direct':{'answer':count(whole),**metrics([whole])}}
        if args.mode=='full':
            marked=overview.copy();d=ImageDraw.Draw(marked);d.line([(256,0),(256,767)],fill='red',width=2);d.line([(512,0),(512,767)],fill='red',width=2)
            calls={'vote':[whole],'code':[]}
            def transformed():
                for i,t in enumerate(TRANSFORMS[1:],1):calls['vote'].append(call(row,'view'+str(i),row['question']+'\n'+FORM,letterbox(original.transpose(t),768)[0]))
            def regional():
                for i,bits in enumerate(MATRIX[:-1]):
                    selected=', '.join(c for c,b in zip('ABC',bits) if b)
                    calls['code'].append(call(row,'region'+str(i),row['question']+'\n'+REGION.format(selected=selected),marked))
            # Alternate order, retaining the exact same frozen queries.
            for fn in ([regional,transformed] if ids.index(uid)%2 else [transformed,regional]):fn()
            calls['code'].append(whole);values=[count(r) for r in calls['code']];decoded=decode(values)
            entry['transform_vote']={'answer':vote([count(r) for r in calls['vote']]),'counts':[count(r) for r in calls['vote']],**metrics(calls['vote'])}
            entry['partition_sum']={'answer':sum(values[:3]) if all(valid_count(v) for v in values[:3]) else None,**metrics(calls['code'][:3])}
            entry['conservation_decode']={**decoded,'counts':values,**metrics(calls['code'])}
            folder=run/'views';folder.mkdir(exist_ok=True);marked.save(folder/(uid+'.png'))
        with mutex:preds.append(entry);atomic_json(predfile,preds);status('running')
        print(json.dumps({'complete':uid,'samples':len(preds),'elapsed_seconds':time.monotonic()-start}),flush=True)
    status('running')
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(process,k) for k in ids[:args.stop_after] if k not in completed]
            for future in concurrent.futures.as_completed(futures):
                try:future.result()
                except Exception:
                    halt.set()
                    for f in futures:f.cancel()
                    raise
    except Exception:
        halt.set();status('held_execution_failure');raise
    status(('completed_baseline' if args.mode=='baseline' else 'completed_predictions') if args.stop_after==32 else 'checkpoint_predictions')


if __name__=='__main__':main()
