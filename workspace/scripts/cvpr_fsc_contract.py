"""Original-example versus class-text task contract diagnostic, development only."""
import argparse,base64,concurrent.futures,fcntl,io,json,os,threading,time
from pathlib import Path
from PIL import Image
import numpy as np
from cvpr_count_code import valid_count
from cvpr_count_run import BASE
from cvpr_chart_run import ROOT,PROJECT,atomic_json,sha
from cvpr_chart_api import Budget,PRICES,credential,now
from cvpr_api_retry import PaidRequester
from cvpr_hrbench_views import letterbox

SYSTEM='Count visible objects using the supplied task evidence. Return only the requested JSON integer.'
FORM='Return ONLY JSON {"count":nonnegative_integer}. Do not output an explanation.'
EXAMPLE='The first image is the full scene. Images 2, 3 and 4 are the three visual object examples supplied by this counting task, cropped from the scene. Count all distinct objects of the same visual type as these examples in the full scene. Count each object once; the example crops are references, not additional objects. '+FORM
ARMS=['class_count_only','exemplar_count_only']

def main():
    p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--stop-after',type=int,default=32);p.add_argument('--prepare-only',action='store_true');p.add_argument('--model',choices=PRICES,default='qwen3.8-flash');p.add_argument('--exemplar-only',action='store_true');args=p.parse_args()
    arms=['exemplar_count_only'] if args.exemplar_only else ARMS
    workers=1 if PRICES[args.model][0]>=10 else 2
    phase_cap=20 if workers==1 else 10
    assert args.run_id.replace('_','').replace('-','').isalnum() and 1<=args.stop_after<=32
    base=BASE/'fsc147';data=base/'data';ids=json.loads((data/'screen_ids.json').read_text());rows={r['id']:r for r in map(json.loads,(data/'development_inputs.jsonl').read_text().splitlines())}
    ann=json.loads((base/'sources/annotation_FSC147_384.json').read_text());run=base/'runs'/args.run_id;run.mkdir(parents=True,exist_ok=True)
    lock=(run/'.run.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    inputs=[]
    for uid in ids:
        row=rows[uid];assert row['partition']=='development';im=Image.open(ROOT/row['image']['path']).convert('RGB');assert sha((ROOT/row['image']['path']).read_bytes())==row['image']['sha256']
        boxes=ann[row['source_name']]['box_examples_coordinates'];assert len(boxes)==3;refs=[]
        folder=run/'examples'/uid;folder.mkdir(parents=True,exist_ok=True)
        for i,box in enumerate(boxes):
            points=np.array(box,dtype=float);assert points.shape==(4,2) and np.isfinite(points).all()
            x0,y0=np.floor(points.min(axis=0)).astype(int);x1,y1=np.ceil(points.max(axis=0)).astype(int)
            assert 0<=x0<x1<=im.width and 0<=y0<y1<=im.height, (uid,box,im.size)
            image=letterbox(im.crop((x0,y0,x1,y1)),128)[0];path=folder/(str(i)+'.png');stream=io.BytesIO();image.save(stream,format='PNG');blob=stream.getvalue()
            if path.exists():assert path.read_bytes()==blob
            else:path.write_bytes(blob)
            refs.append({'path':str(path.relative_to(ROOT)),'sha256':sha(blob),'box_pixels':[int(v) for v in [x0,y0,x1,y1]]})
        inputs.append({'id':uid,'provided_examples':refs,'source_field':'Official task-provided box_examples_coordinates; no point/count target supplied'})
    if (run/'EXEMPLAR_INPUTS.json').exists():assert json.loads((run/'EXEMPLAR_INPUTS.json').read_text())==inputs
    else:atomic_json(run/'EXEMPLAR_INPUTS.json',inputs)
    if args.prepare_only:print(json.dumps({'prepared':len(inputs),'provided_examples':len(inputs)*3,'paid_calls':0}));return
    lookup={r['id']:r for r in inputs};ledger=json.loads((PROJECT/'API_LEDGER.json').read_text());retained={k:v for k,v in ledger['attempts'].items() if v['status']!='settled'}
    assert not any(v['run_id']==args.run_id for v in retained.values())
    for e in retained.values():
        path=Path('/proc')/str(e['pid'])/'cmdline';assert not path.exists() or e['run_id'].encode() not in path.read_bytes()
    proto={'model':args.model,'weight_revision':None,'arms':arms,'sample_ids':ids,'temperature':0,'thinking':False,'training':False,'local_gpu':False,
        'prompts':{'system':SYSTEM,'form':FORM,'example':EXAMPLE},'max_generated_tokens_each_arm':256,'raster_pixels':{'class_count_only':768**2,'exemplar_count_only':768**2+3*128**2},
        'scope':'Fixed-model exemplar-conditioned headroom check on32 exposed development groups; not independent confirmation' if args.exemplar_only else 'Input-contract diagnostic on all32 already-exposed development groups; not novel-method gain or independent confirmation',
        'interpretation':'Visual examples and intended object-set definition differ. Both arms use count-only output. No inference about cloud-compute equality or pure effect of adding images.',
        'headroom_gate':'Exemplar arm >=85% exact stops saturated task; below85% informs new mechanism selection, never reopens failed conservation version',
        'phase_cap_cny':phase_cap,'project_cap_cny':300,'workers':workers,'retained_unknown':retained,'prices':PRICES[args.model],
        'manifest_sha256':sha((data/'MANIFEST.json').read_bytes()),'provided_examples_sha256':sha((run/'EXEMPLAR_INPUTS.json').read_bytes()),'source_sha256':sha(Path(__file__).read_bytes())}
    if (run/'PROTOCOL.json').exists():assert json.loads((run/'PROTOCOL.json').read_text())==json.loads(json.dumps(proto))
    else:atomic_json(run/'PROTOCOL.json',proto);(run/'cvpr_fsc_contract.py').write_bytes(Path(__file__).read_bytes())
    calls=[json.loads(l) for l in (run/'calls.jsonl').read_text().splitlines()] if (run/'calls.jsonl').exists() else [];done={r['key']:r for r in calls}
    for c in calls:assert ledger['attempts'][c['ledger_key']]['status']=='settled' and ledger['attempts'][c['ledger_key']]['response_id']==c['response_id']
    preds=json.loads((run/'PREDICTIONS.json').read_text()) if (run/'PREDICTIONS.json').exists() else [];completed={r['id'] for r in preds}
    halt=threading.Event();mutex=threading.Lock();start=time.monotonic();requester=PaidRequester(budget=Budget(retained,retry_own_failures=True),run=run,run_id=args.run_id,secret=credential(),halt=halt,prices=PRICES[args.model],phase_cap=phase_cap,wall_limit_seconds=1800)
    def status(state):atomic_json(run/'STATUS.json',{'state':state,'pid':os.getpid(),'updated_at':now(),'planned_samples':32,'completed_samples':len(preds)//len(arms),'actual_calls':len(calls),'api_cost_cny':sum(c['api_cost_cny'] for c in calls),'elapsed_seconds':time.monotonic()-start,'local_gpu':False,'confirmation_evaluated':False})
    def save(c):
        with mutex:
            with (run/'calls.jsonl').open('a') as f:f.write(json.dumps(c,ensure_ascii=False)+'\n');f.flush();os.fsync(f.fileno())
            calls.append(c);done[c['key']]=c
    def process(uid):
        row=rows[uid];overview=letterbox(Image.open(ROOT/row['image']['path']).convert('RGB'),768)[0];local=[]
        for arm in (arms if ids.index(uid)%2==0 else arms[::-1]):
            images=[overview];prompt=row['question']+'\n'+FORM
            if arm=='exemplar_count_only':images += [Image.open(ROOT/r['path']).convert('RGB') for r in lookup[uid]['provided_examples']];prompt=EXAMPLE
            blobs=[]
            for im in images:buf=io.BytesIO();im.save(buf,format='PNG');blobs.append(buf.getvalue())
            key=uid+'|'+arm;digest=sha(json.dumps({'prompt':prompt,'images':[sha(b) for b in blobs],'cap':256,'system':SYSTEM},sort_keys=True).encode())
            if key in done:c=done[key];assert c['prompt_sha256']==digest
            else:
                body={'model':args.model,'temperature':0,'enable_thinking':False,'max_tokens':256,'response_format':{'type':'json_object'},'messages':[{'role':'system','content':SYSTEM},{'role':'user','content':[{'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(b).decode()}} for b in blobs]+[{'type':'text','text':prompt}]}]}
                c=requester.call(key=key,cap=256,body=body,digest=digest,save=save)
            answer=(c['parsed'] or {}).get('count');answer=answer if valid_count(answer) and not c['truncated'] else None
            local.append({'id':uid,'arm':arm,'image_group':row['image_group'],'answer':answer,'valid':answer is not None,'category':row['category'],'actual_call_keys':[c['key']],'logical_calls':1,'logical_input_tokens':c['input_tokens'],'logical_output_tokens':c['output_tokens'],'logical_seconds':c['elapsed_seconds'],'logical_api_cost_cny':c['api_cost_cny']})
        with mutex:preds.extend(local);atomic_json(run/'PREDICTIONS.json',preds);status('running')
        print(json.dumps({'complete':uid,'complete_samples':len(preds)//len(arms),'elapsed_seconds':time.monotonic()-start}),flush=True)
    status('running')
    try:
        with concurrent.futures.ThreadPoolExecutor(workers) as pool:
            futures=[pool.submit(process,k) for k in ids[:args.stop_after] if k not in completed]
            for f in concurrent.futures.as_completed(futures):
                try:f.result()
                except Exception:
                    halt.set()
                    for pending in futures:pending.cancel()
                    raise
    except Exception:status('held_execution_failure');raise
    status('completed_predictions' if args.stop_after==32 else 'checkpoint_predictions')

if __name__=='__main__':main()
