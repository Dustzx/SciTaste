"""Frozen strong-model seven-view exemplar counting baseline; development only."""
import argparse,base64,fcntl,io,json,os,threading,time
from pathlib import Path
from PIL import Image
from cvpr_fsc_contract import SYSTEM,EXAMPLE
from cvpr_count_run import BASE,TRANSFORMS
from cvpr_count_code import valid_count,vote
from cvpr_chart_run import ROOT,PROJECT,atomic_json,sha
from cvpr_chart_api import Budget,PRICES,credential,now
from cvpr_api_retry import PaidRequester
from cvpr_hrbench_views import letterbox

SOURCE='bailian_qwen38_max0902_fsc_headroom_v1'
MODEL='qwen3.8-max-0902'
NAMES=['identity','hflip','vflip','rot180','rot90','rot270','transpose']

def main():
    p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--stop-after',type=int,default=32);p.add_argument('--prepare-only',action='store_true');args=p.parse_args()
    assert args.run_id.replace('_','').replace('-','').isalnum() and 1<=args.stop_after<=32
    base=BASE/'fsc147';data=base/'data';source=base/'runs'/SOURCE;run=base/'runs'/args.run_id;run.mkdir(parents=True,exist_ok=True)
    lock=(run/'.run.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    manifest=json.loads((data/'MANIFEST.json').read_text());assert sha((data/'development_inputs.jsonl').read_bytes())==manifest['files']['development_inputs.jsonl']
    ids=json.loads((data/'screen_ids.json').read_text());rows={r['id']:r for r in map(json.loads,(data/'development_inputs.jsonl').read_text().splitlines())}
    oldproto=json.loads((source/'PROTOCOL.json').read_text());assert oldproto['sample_ids']==ids and oldproto['model']==MODEL and oldproto['max_generated_tokens_each_arm']==256
    examples={r['id']:r for r in json.loads((source/'EXEMPLAR_INPUTS.json').read_text())};oldcalls={c['sample_id']:c for c in map(json.loads,(source/'calls.jsonl').read_text().splitlines())};assert len(oldcalls)==32
    ledger=json.loads((PROJECT/'API_LEDGER.json').read_text());retained={k:v for k,v in ledger['attempts'].items() if v['status']!='settled'}
    assert not any(v['run_id']==args.run_id for v in retained.values())
    for e in retained.values():
        path=Path('/proc')/str(e['pid'])/'cmdline';assert not path.exists() or e['run_id'].encode() not in path.read_bytes()
    frozen=['cvpr_fsc_vote.py','cvpr_fsc_contract.py','cvpr_count_run.py','cvpr_count_code.py','cvpr_chart_api.py','cvpr_api_retry.py','cvpr_hrbench_views.py']
    proto={'model':MODEL,'weight_revision':None,'arms':['direct','transform_vote'],'sample_ids':ids,'temperature':0,'thinking':False,'training':False,'local_gpu':False,'scope':'Fixed32 exposed development groups; strong-model baseline only; no method or confirmation claim','transform_order':NAMES,'transform_targets':'Apply the same D4 transform to letterboxed scene and all three given example crops. Counts should be invariant; orientation may still alter perception.','prompt':EXAMPLE,'system':SYSTEM,'caps':{'per_call':256,'direct':256,'transform_vote':1792},'raster_pixels_per_call':768**2+3*128**2,'vote_rule':'Ignore invalid values; most frequent valid integer, first occurrence breaks ties; no valid returns invalid','shared_calls':'Reuse identity from SOURCE with exact prompt/image/cap hash and settled receipt, never resample identity. Logical vote pays all7; actual new calls exclude reused identities.','source_run':SOURCE,'source_calls_sha256':sha((source/'calls.jsonl').read_bytes()),'manifest_sha256':sha((data/'MANIFEST.json').read_bytes()),'provided_examples_sha256':sha((source/'EXEMPLAR_INPUTS.json').read_bytes()),'phase_cap_cny':20,'project_cap_cny':300,'workers':1,'prices':PRICES[MODEL],'retained_unknown':retained,'headroom_gate':'Stop saturated task if strong seven-view vote >=85% exact; otherwise retain headroom for distinct mechanism selection. Do not reopen failed regional decoder.','source_sha256':{n:sha((ROOT/'scripts'/n).read_bytes()) for n in frozen}}
    if (run/'PROTOCOL.json').exists():assert json.loads((run/'PROTOCOL.json').read_text())==json.loads(json.dumps(proto))
    else:
        atomic_json(run/'PROTOCOL.json',proto)
        for n in frozen:(run/n).write_bytes((ROOT/'scripts'/n).read_bytes())
    def images(uid):
        row=rows[uid];assert row['partition']=='development' and not {'answer','points','caption'}&set(row)
        path=ROOT/row['image']['path'];assert sha(path.read_bytes())==row['image']['sha256'];ims=[letterbox(Image.open(path).convert('RGB'),768)[0]]
        for ref in examples[uid]['provided_examples']:
            path=ROOT/ref['path'];assert sha(path.read_bytes())==ref['sha256'];ims.append(Image.open(path).convert('RGB'))
        return ims
    def encode(ims):
        blobs=[]
        for im in ims:b=io.BytesIO();im.save(b,format='PNG');blobs.append(b.getvalue())
        digest=sha(json.dumps({'prompt':EXAMPLE,'images':[sha(b) for b in blobs],'cap':256,'system':SYSTEM},sort_keys=True).encode());return blobs,digest
    # Validate all identities and source receipts before any new paid call.
    for uid in ids:
        _,digest=encode(images(uid));c=oldcalls[uid];assert c['prompt_sha256']==digest and c['requested_model']==MODEL
        e=ledger['attempts'][c['ledger_key']];assert e['status']=='settled' and e['response_id']==c['response_id']
    assert len({rows[k]['image_group'] for k in ids})==32
    if args.prepare_only:print(json.dumps({'identity_hashes_verified':32,'groups':32,'new_paid_calls':0,'new_requests_planned':192}));return
    calls=[json.loads(l) for l in (run/'calls.jsonl').read_text().splitlines()] if (run/'calls.jsonl').exists() else [];done={c['key']:c for c in calls}
    for c in calls:assert ledger['attempts'][c['ledger_key']]['status']=='settled'
    preds=json.loads((run/'PREDICTIONS.json').read_text()) if (run/'PREDICTIONS.json').exists() else [];completed={r['id'] for r in preds}
    start=time.monotonic();halt=threading.Event();requester=PaidRequester(budget=Budget(retained,retry_own_failures=True),run=run,run_id=args.run_id,secret=credential(),halt=halt,prices=PRICES[MODEL],phase_cap=20,wall_limit_seconds=1800)
    def status(state):atomic_json(run/'STATUS.json',{'state':state,'pid':os.getpid(),'updated_at':now(),'planned_samples':32,'completed_samples':len(preds)//2,'actual_calls':len(calls),'reused_identity_calls':32,'api_cost_cny':sum(c['api_cost_cny'] for c in calls),'elapsed_seconds':time.monotonic()-start,'local_gpu':False,'confirmation_evaluated':False})
    def save(c):
        with (run/'calls.jsonl').open('a') as f:f.write(json.dumps(c,ensure_ascii=False)+'\n');f.flush();os.fsync(f.fileno())
        calls.append(c);done[c['key']]=c
    def count(c):
        v=(c['parsed'] or {}).get('count');return v if valid_count(v) and not c['truncated'] else None
    status('running')
    try:
        for uid in ids[:args.stop_after]:
            if uid in completed:continue
            ims=images(uid);cs=[oldcalls[uid]]
            for name,t in zip(NAMES[1:],TRANSFORMS[1:]):
                blobs,digest=encode([im.transpose(t) for im in ims]);key=uid+'|'+name
                if key in done:c=done[key];assert c['prompt_sha256']==digest
                else:
                    same=next((x for x in [*cs,*calls] if x['sample_id']==uid and x['prompt_sha256']==digest),None)
                    if same:c=same
                    else:
                        body={'model':MODEL,'temperature':0,'enable_thinking':False,'max_tokens':256,'response_format':{'type':'json_object'},'messages':[{'role':'system','content':SYSTEM},{'role':'user','content':[{'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(b).decode()}} for b in blobs]+[{'type':'text','text':EXAMPLE}]}]}
                        c=requester.call(key=key,cap=256,body=body,digest=digest,save=save)
                cs.append(c)
            vals=[count(c) for c in cs]
            for arm,answer,used in [('direct',vals[0],cs[:1]),('transform_vote',vote(vals),cs)]:
                preds.append({'id':uid,'arm':arm,'image_group':rows[uid]['image_group'],'category':rows[uid]['category'],'answer':answer,'valid':answer is not None,'counts':vals if arm=='transform_vote' else vals[:1],'actual_call_keys':[c['ledger_key'] for c in used],'logical_calls':len(used),**{'logical_'+k:sum(c[k] for c in used) for k in ['input_tokens','output_tokens','elapsed_seconds','api_cost_cny']}})
            atomic_json(run/'PREDICTIONS.json',preds);status('running');print(json.dumps({'complete':uid,'samples':len(preds)//2,'new_calls':len(calls),'elapsed_seconds':time.monotonic()-start}),flush=True)
    except Exception:halt.set();status('held_execution_failure');raise
    status('completed_predictions' if args.stop_after==32 else 'checkpoint_predictions')

if __name__=='__main__':main()
