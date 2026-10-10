"""Bounded scene-disjoint development diagnostic, with official visible inputs.

User-authorized bounded HTTP retries; no confirmation access, no expert or local GPU.
The scene-table control is deliberately explicit about observe-transform-infer.
"""
import argparse
import base64
import concurrent.futures
import fcntl
import json
import os
import sys
import threading
import time
from pathlib import Path

import requests

from cvpr_chart_api import Budget,ENDPOINT,PRICES,credential,now
from cvpr_chart_run import PROJECT,ROOT,sha,atomic_json,parse_json
from cvpr_spacecast_state import invalidate
from cvpr_api_retry import PaidRequester

RUN_ID='bailian_qwen38_flash_spacecast_state_screen_v3_recovery_v1'
ARMS=['direct','review','state_table','state_invalidation']
EXTRACT='''Observe only the initial scene, BEFORE the hypothetical edit in the question. Return ONLY JSON:
{"intervention":{"kind":"none|object_move|object_rotate|object_remove|frame_rotate|unknown","frame":"camera|world|object|unknown","targets":["exact entity names in question"]},"facts":[{"subject":"entity","relation":"direction|distance|occludes|attachment|facing|other","object":"entity","value":"brief observed relation with uncertainty","frame":"camera|world|object|invariant|unknown","frame_owner":"camera/world or named object","post_validity":"unchecked"}]}.
Up to24 concise facts. Classify the requested intervention, but do NOT apply it in observed facts. Do NOT output the answer, reasoning toward options, made-up coordinates or unseen outcomes. Use unknown when evidence is insufficient. Spatial frame must be explicit; use invariant only for distance/topology that is independent of coordinate basis.'''
SOLVE='''The table below is fallible evidence about the scene BEFORE the edit. Observe-transform-infer: identify the requested intervention and reference frame, preserve unaffected relations, recompute affected relations, and then answer. A must_recompute marker means the prior relation cannot be used unchanged; it provides no new relation or answer. Verify the facts using the SAME observed images. Use the question's exact directional/frame conventions. Keep reasoning brief and return final Answer line.'''
REVIEW='''Recheck the provisional reasoning below against the images, requested intervention and reference frame. Keep reasoning brief; give the final Answer line. The previous answer may be wrong.'''


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--stop-after',type=int,default=32)
    parser.add_argument('--run-id', default=RUN_ID)
    parser.add_argument('--source-run', default='bailian_qwen38_flash_spacecast_state_screen_v3')
    args=parser.parse_args()
    assert all(v.replace('-','').replace('_','').isalnum() for v in [args.run_id,args.source_run])
    assert args.run_id!=args.source_run
    run_id=args.run_id
    assert args.stop_after in {2,32}
    base=PROJECT/'spacecast';data=base/'data';manifest=json.loads((data/'MANIFEST.json').read_text())
    sys.path.insert(0,str(PROJECT/'sources/spacecast'))
    from spacecast_eval.protocol import parse_prediction,SYSTEM_PROMPT
    ordered=json.loads((data/'screen_ids.json').read_text());rows={r['question_uid']:r for r in map(json.loads,(data/'development_inputs.jsonl').read_text().splitlines())}
    assert len(ordered)==32 and len({rows[k]['scene_group'] for k in ordered})==32
    for row in rows.values():
        assert row['partition']=='development' and not {'answer','Answer','depth','coordinates'}&set(row)
        for im in row['images']:assert sha((ROOT/im['path']).read_bytes())==im['sha256']
    source=base/'runs'/args.source_run
    authorization=json.loads((PROJECT/'RETRY_AUTHORIZATION.json').read_text())
    assert authorization['instruction']=='遇 HTTP 异常熔断后应该自主重试' and authorization['max_attempts_per_logical_request']==3
    source_protocol=json.loads((source/'PROTOCOL.json').read_text())
    source_status=json.loads((source/'STATUS.json').read_text())
    assert not Path(f'/proc/{source_status["pid"]}').exists(), 'Source still alive'
    assert source_protocol['prompts']=={'extract':EXTRACT,'solve':SOLVE,'review':REVIEW}
    assert source_protocol['manifest_sha256']==sha((data/'MANIFEST.json').read_bytes())
    assert source_protocol['sample_ids']==ordered and source_protocol['arms']==ARMS
    assert source_protocol['source_sha256']['cvpr_spacecast_state.py']==sha((ROOT/'scripts/cvpr_spacecast_state.py').read_bytes())
    ledger=json.loads((PROJECT/'API_LEDGER.json').read_text())
    retained={k:v for k,v in ledger['attempts'].items() if v['status']!='settled'}
    source_unknown={k:v for k,v in retained.items() if v['run_id']==source.name}
    allowed_unknown={**source_protocol['retained_unknown'],**source_unknown}
    assert retained==allowed_unknown, 'Unrelated unresolved attempt; inspect before recovery'
    prior_attempts={v['key']:max(e.get('attempt_index',1) for e in ledger['attempts'].values() if e['key']==v['key'] and 'spacecast' in e['run_id']) for v in source_unknown.values()}
    assert all(n<3 for n in prior_attempts.values()), 'Bounded attempt limit already reached'
    run=base/'runs'/run_id
    # Recovery writes a new cohort; no overwrite of old scientific artifacts.
    run.mkdir(exist_ok=False)
    lock=(run/'.run.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    protocol={**source_protocol,'source_run':source.name,'retained_unknown':retained,
        'retry_authorization_sha256':sha((PROJECT/'RETRY_AUTHORIZATION.json').read_bytes()),
        'source_sha256':{p.name:sha(p.read_bytes()) for p in [Path(__file__),ROOT/'scripts/cvpr_spacecast_state.py',ROOT/'scripts/cvpr_api_retry.py',ROOT/'scripts/cvpr_chart_api.py']},
        'retry':{'authorized_by':'2026-10-10 user: 遇 HTTP 异常熔断后应该自主重试','max_attempts_per_logical_request':3,
                 'retryable':'408/429/5xx/timeout/connection; honor Retry-After and30/90s backoff',
                 'unknown_billing':'retain full old reservation, reserve every new attempt separately','wall_limit_seconds':1800},
        'scientific_comparability':'Identical data, images, prompts, caps and v3 operator. Successful/truncated responses reused; no outcome-selected reruns. Rolling model alias/date still limit reproducibility.'}
    atomic_json(run/'PROTOCOL.json',protocol)
    for name in protocol['source_sha256']:(run/name).write_bytes((ROOT/'scripts'/name).read_bytes())
    cached=[json.loads(x) for x in (source/'calls.jsonl').read_text().splitlines()]
    assert len({c['key'] for c in cached})==len(cached)
    for c in cached:
        receipt_key=c.get('ledger_key',c.get('inherited_from_run',source.name)+'|'+c['key'])
        entry=ledger['attempts'][receipt_key]
        assert c['status']=='ok' and entry['status']=='settled' and entry['response_id']==c['response_id'] and entry['cost_cny']==c['api_cost_cny']
    records=[{**c,'inherited_from_run':source.name,'ledger_key':c.get('ledger_key',c.get('inherited_from_run',source.name)+'|'+c['key'])} for c in cached]
    (run/'calls.jsonl').write_text(''.join(json.dumps(c,ensure_ascii=False)+'\n' for c in records))
    preds=json.loads((source/'PREDICTIONS.json').read_text())
    assert len(preds)%4==0 and len({p['question_uid'] for p in preds})==len(preds)//4
    assert {p['question_uid'] for p in preds}<=set(ordered)
    assert len({(p['question_uid'],p['arm']) for p in preds})==len(preds)
    assert all({p['arm'] for p in preds if p['question_uid']==uid}==set(ARMS) for uid in {p['question_uid'] for p in preds})
    atomic_json(run/'PREDICTIONS.json',preds)
    atomic_json(run/'RECOVERY.json',{'source_run':source.name,'source_hashes':{name:sha((source/name).read_bytes()) for name in ['PROTOCOL.json','calls.jsonl','PREDICTIONS.json','STATUS.json']},
        'cached_successes':len(records),'inherited_complete_samples':len(preds)//4,'retained_unknown':retained,'prior_attempts':prior_attempts,
        'source_method_unchanged':True,'recovery_authorized_by':protocol['retry']['authorized_by'],'old_failures_and_reservations_preserved':True})
    calls_path=run/'calls.jsonl';done={r['key']:r for r in records};complete={p['question_uid'] for p in preds}
    phase_runs={e['run_id'] for e in ledger['attempts'].values() if 'spacecast' in e['run_id']}|{run_id}
    budget=Budget(retained,retry_own_failures=True,phase_run_ids=phase_runs);secret=credential()
    mutex=threading.Lock();halt=threading.Event();started=time.monotonic()
    requester=PaidRequester(budget=budget,run=run,run_id=run_id,secret=secret,halt=halt,prior_attempts=prior_attempts)
    def save(item):
        with mutex:
            with calls_path.open('a') as handle:
                handle.write(json.dumps(item,ensure_ascii=False)+'\n');handle.flush();os.fsync(handle.fileno())
            records.append(item);done[item['key']]=item
    def call(row,stage,prompt,cap,as_json=False):
        key=row['question_uid']+'|'+stage;digest=sha((prompt+json.dumps(row['images'])+str(cap)+str(as_json)).encode())
        if key in done:
            assert done[key]['prompt_sha256']==digest;return done[key]
        images=[{'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+base64.b64encode((ROOT/i['path']).read_bytes()).decode()}} for i in row['images']]
        body={'model':protocol['model'],'messages':[{'role':'system','content':SYSTEM_PROMPT},{'role':'user','content':images+[{'type':'text','text':prompt}]}],
              'max_tokens':cap,'temperature':0,'enable_thinking':False}
        if as_json:body['response_format']={'type':'json_object'}
        result=requester.call(key=key,cap=cap,body=body,digest=digest,save=save)
        print(json.dumps({'key':key,'seconds':result['elapsed_seconds'],'cost_cny':result['api_cost_cny'],'truncated':result['truncated'],'attempt_index':result['attempt_index']}),flush=True)
        return result
    def process(uid):
        row=rows[uid];question=row['question'].strip()+'\n\n'+'\n'.join(f'{chr(65+i)}) {v}' for i,v in enumerate(row['options']))
        form=('Select all correct choices.' if row['multi_select'] else 'Select exactly one choice.')+' Return ONLY a JSON object with fields in this order: {"answer":"letter(s), comma-separated for multiple choices","reasoning":"brief rationale, at most80 words"}. Commit the answer first; do not write step-by-step explorations.'
        shared=call(row,'extract',question+'\n\n'+EXTRACT,1280,True)
        parsed=shared['parsed'] or {}
        graph={k:parsed[k] for k in ['intervention','facts'] if k in parsed}
        revised,audit=invalidate(graph);local=[];table_final=None
        for arm in ARMS:
            if arm=='direct':final=call(row,'direct',question+'\n\n'+form,1792,True);charge=[final]
            elif arm=='review':
                first=call(row,'reason',question+'\n\n'+form,1280,True);final=call(row,'review',question+'\n\n'+REVIEW+'\n'+first['text']+'\n\n'+form,512,True);charge=[first,final]
            else:
                use=graph if arm=='state_table' else revised
                if arm=='state_invalidation' and use==graph:final=table_final
                else:final=call(row,arm,question+'\n\n'+SOLVE+'\n'+json.dumps(use,ensure_ascii=False)+'\n\n'+form,512,True)
                if arm=='state_table':table_final=final
                charge=[shared,final]
            allowed=[chr(65+i) for i in range(len(row['options']))]
            ans=parse_prediction((final['parsed'] or {}).get('answer'),allowed,row['multi_select']) if not final['truncated'] else None
            answer=sorted(ans) if ans is not None else None
            local.append({'question_uid':uid,'scene_group':row['scene_group'],'type':row['type'],'level':row['level'],'source_type':row['source_type'],
                'arm':arm,'prediction':answer,'raw_response':'Answer: '+', '.join(answer) if answer else '',
                'status':'ok','valid':answer is not None,'logical_calls':len(charge),'logical_input_tokens':sum(c['input_tokens'] for c in charge),
                'logical_output_tokens':sum(c['output_tokens'] for c in charge),'logical_seconds':sum(c['elapsed_seconds'] for c in charge),
                'logical_api_cost_cny':sum(c['api_cost_cny'] for c in charge),'actual_call_keys':[c['key'] for c in charge],
                'state_audit':audit if arm=='state_invalidation' else None})
        with mutex:
            preds.extend(local);atomic_json(run/'PREDICTIONS.json',preds)
            atomic_json(run/'STATUS.json',{'state':'running','pid':os.getpid(),'updated_at':now(),'planned_samples':32,
                'completed_samples':len(preds)//4,'predictions':len(preds),'actual_calls':len(records),'local_gpu':False,
                'elapsed_seconds_this_session':time.monotonic()-started,'api_cost_cny':sum(c['api_cost_cny'] for c in records)})
    atomic_json(run/'STATUS.json',{'state':'running','pid':os.getpid(),'started_at':now(),'planned_samples':32,'checkpoint_samples':args.stop_after,
        'completed_samples':len(complete),'local_gpu':False})
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(process,k) for k in ordered[:args.stop_after] if k not in complete]
            try:
                for f in concurrent.futures.as_completed(futures):f.result()
            except Exception:
                halt.set()
                for f in futures:f.cancel()
                raise
    except Exception:
        atomic_json(run/'STATUS.json',{'state':'held_execution_failure','pid':os.getpid(),'updated_at':now(),'planned_samples':32,
            'completed_samples':len(preds)//4,'retry_authorized':True,'attempt_limit':3});raise
    atomic_json(run/'STATUS.json',{'state':'completed_predictions' if args.stop_after==32 else 'checkpoint_predictions','pid':os.getpid(),
        'completed_at':now(),'planned_samples':32,'completed_samples':len(preds)//4,'predictions':len(preds),'actual_calls':len(records),
        'elapsed_seconds_this_session':time.monotonic()-started,'api_cost_cny':sum(c['api_cost_cny'] for c in records),
        'local_gpu':False,'scientific_score_computed':False})


if __name__=='__main__':main()
