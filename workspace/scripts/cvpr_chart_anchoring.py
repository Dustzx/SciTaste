"""Bounded paired diagnostic: does provisional-answer context cause regressions?

Reuses frozen, development-only extraction responses. Two contemporaneous solve
arms differ only in retaining versus dropping top-level notes/answer. This is a
failure diagnosis, not the pixel method or an independent confirmation.
"""
import base64
import concurrent.futures
import fcntl
import json
import os
import threading
import time
from pathlib import Path

import requests

from cvpr_chart_api import Budget, ENDPOINT, PRICES, credential, now
from cvpr_chart_run import ROOT, PROJECT, SOLVE, context, parse_json, sha, atomic_json

SOURCE = 'bailian_qwen38_flash_screen_recovery_v1'
RUN_ID = 'bailian_qwen38_flash_anchoring_diagnostic_v1'
ARMS = ['full_structure_replay', 'answer_blind_structure']


def main():
    source = PROJECT/'runs'/SOURCE
    old_protocol = json.loads((source/'PROTOCOL.json').read_text())
    assert json.loads((source/'STATUS.json').read_text())['state'] == 'completed_recovery_predictions'
    ids = old_protocol['sample_ids']
    rows = {r['id']:r for r in map(json.loads, (PROJECT/'data/development_inputs.jsonl').read_text().splitlines())}
    extraction = {r['sample_id']:r for r in map(json.loads, (source/'calls.jsonl').read_text().splitlines()) if r['stage']=='extract'}
    assert len(ids)==38 and set(extraction)==set(ids)
    retained = old_protocol['recovery']['retained_unknown']
    for row in rows.values():
        assert row['partition']=='development' and not {'answer','Answer'} & set(row)
    run=PROJECT/'runs'/RUN_ID;run.mkdir(exist_ok=True)
    lock=(run/'.run.lock').open('a');fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
    protocol={'model':old_protocol['model'],'scope':'paired development-only anchoring failure diagnostic',
              'source_run':SOURCE, 'sample_ids':ids,'arms':ARMS,'retained_unknown':retained,
              'source_calls_sha256':sha((source/'calls.jsonl').read_bytes()),
              'data_manifest_sha256':old_protocol['data_manifest_sha256'],
              'source_sha256':sha(Path(__file__).read_bytes()), 'thinking':False,'temperature':0,
              'max_new_tokens_total_per_arm':1792,'two_pass_allocation':[1280,512],
              'shared_extraction':'Historical actual response; full logical extraction cost charged to both arms',
              'intervention':'Only remove top-level notes and answer from parsed extraction (or raw-text notes fallback)',
              'selection':'All 38 complete image groups, without correctness filtering; not a balanced full40 or unseen test',
              'phase_cap_cny':20,'retry':'none; any new unknown trips circuit; old two reservations retained'}
    if (run/'PROTOCOL.json').exists():
        assert json.loads((run/'PROTOCOL.json').read_text())==protocol
    else:
        atomic_json(run/'PROTOCOL.json',protocol)
        (run/Path(__file__).name).write_bytes(Path(__file__).read_bytes())
    path=run/'calls.jsonl';records=list(map(json.loads,path.read_text().splitlines())) if path.exists() else []
    if any(x['status']!='ok' for x in records):raise RuntimeError('Previous failure; no retries')
    done={x['key']:x for x in records};preds=json.loads((run/'PREDICTIONS.json').read_text()) if (run/'PREDICTIONS.json').exists() else []
    complete={p['id'] for p in preds};budget=Budget(retained);secret=credential()
    mutex=threading.Lock();rate=threading.Lock();last=[0.0];halt=threading.Event();started=time.monotonic()
    def process(uid):
        row=rows[uid];blob=(ROOT/row['image_path']).read_bytes();assert sha(blob)==row['image_png_sha256']
        uri='data:image/png;base64,'+base64.b64encode(blob).decode()
        shared=extraction[uid];full=shared['parsed'] or {'notes':shared['text'],'panels':[]}
        clean={k:v for k,v in full.items() if k not in {'notes','answer'}}
        pair=[]
        # Alternate arm order by frozen question order to reduce temporal/order effects.
        for arm in ARMS[::1 if ids.index(uid)%2==0 else -1]:
            graph=full if arm==ARMS[0] else clean
            prompt=context(row)+'\n\n'+SOLVE+'\n'+json.dumps(graph,ensure_ascii=False)
            key=uid+'|'+arm;digest=sha((prompt+row['image_png_sha256']+'512').encode())
            if key in done:
                final=done[key];assert final['prompt_sha256']==digest
            else:
                if halt.is_set():raise RuntimeError('Sibling failure')
                reserve=PRICES[protocol['model']][0]+512*PRICES[protocol['model']][1]/1e6
                ledger_key=RUN_ID+'|'+key
                with rate:
                    time.sleep(max(0,2.5-(time.monotonic()-last[0])))
                    if halt.is_set():raise RuntimeError('Sibling failure')
                    budget.change(ledger_key,record={'run_id':RUN_ID,'key':key,'pid':os.getpid(),'model':protocol['model'],
                                  'reserved_cny':reserve,'status':'pending','started_at':now()},phase_cap=20,run_id=RUN_ID)
                    last[0]=time.monotonic()
                tick=time.monotonic()
                try:
                    response=requests.post(ENDPOINT,headers={'Authorization':'Bearer '+secret},json={
                        'model':protocol['model'],'messages':[{'role':'user','content':[{'type':'image_url','image_url':{'url':uri}},
                        {'type':'text','text':prompt}]}],'max_tokens':512,'temperature':0,'enable_thinking':False,
                        'response_format':{'type':'json_object'}},timeout=(15,180))
                    response.raise_for_status();obj=response.json();usage=obj['usage'];choice=obj['choices'][0]
                    inp,out=int(usage['prompt_tokens']),int(usage['completion_tokens']);assert inp<=1000000 and out<=512
                    cost=(inp*PRICES[protocol['model']][0]+out*PRICES[protocol['model']][1])/1e6
                    text=choice['message']['content'];assert isinstance(text,str) and not choice['message'].get('reasoning_content')
                    final={'key':key,'sample_id':uid,'stage':arm,'status':'ok','created_at':now(),'prompt_sha256':digest,
                           'response_id':obj['id'],'requested_model':protocol['model'],'returned_model':obj.get('model'),
                           'text':text,'parsed':parse_json(text),'finish_reason':choice.get('finish_reason'),
                           'truncated':choice.get('finish_reason')=='length','usage':usage,'input_tokens':inp,'output_tokens':out,
                           'api_cost_cny':cost,'elapsed_seconds':time.monotonic()-tick}
                    with mutex:
                        with path.open('a') as f:f.write(json.dumps(final,ensure_ascii=False)+'\n');f.flush();os.fsync(f.fileno())
                        records.append(final);done[key]=final
                    budget.change(ledger_key,settle={'status':'settled','cost_cny':cost,'response_id':obj['id'],'usage':usage,'settled_at':now()})
                    print(json.dumps({'key':key,'seconds':final['elapsed_seconds'],'cost_cny':cost}),flush=True)
                except Exception as exc:
                    halt.set();budget.change(ledger_key,settle={'status':'unknown','exception_type':type(exc).__name__,'failed_at':now()})
                    raise RuntimeError('Paid request failed; no retry') from None
            answer=final['parsed'].get('answer') if final['parsed'] else None
            answer=repr(answer) if isinstance(answer,list) else str(answer) if answer is not None else None
            pair.append({'id':uid,'image_group':row['image_group'],'question_type':row['question_type'],'arm':arm,
                         'answer':answer,'valid':answer is not None and bool(answer.strip()) and not final['truncated'],
                         'logical_input_tokens':shared['input_tokens']+final['input_tokens'],
                         'logical_output_tokens':shared['output_tokens']+final['output_tokens'],'logical_calls':2,
                         'logical_seconds':shared['elapsed_seconds']+final['elapsed_seconds'],
                         'logical_api_cost_cny':shared['api_cost_cny']+final['api_cost_cny'],'pixel_audit':[],
                         'actual_call_keys':[shared['key'],key]})
        with mutex:
            preds.extend(pair);atomic_json(run/'PREDICTIONS.json',preds)
            atomic_json(run/'STATUS.json',{'state':'running','pid':os.getpid(),'updated_at':now(),'planned_samples':38,
                'completed_samples':len(preds)//2,'predictions':len(preds),'actual_calls':len(records),'local_gpu':False,
                'elapsed_seconds_this_session':time.monotonic()-started,'api_cost_cny':sum(x['api_cost_cny'] for x in records)})
    atomic_json(run/'STATUS.json',{'state':'running','pid':os.getpid(),'started_at':now(),'planned_samples':38,'completed_samples':len(complete),'local_gpu':False})
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(process,k) for k in ids if k not in complete]
            for f in concurrent.futures.as_completed(futures):f.result()
    except Exception:
        halt.set();atomic_json(run/'STATUS.json',{'state':'held_execution_failure','pid':os.getpid(),'updated_at':now(),
            'planned_samples':38,'completed_samples':len(preds)//2,'retry_authorized':False});raise
    atomic_json(run/'STATUS.json',{'state':'completed_diagnostic_predictions','pid':os.getpid(),'completed_at':now(),
        'planned_samples':38,'completed_samples':len(preds)//2,'predictions':len(preds),'actual_calls':len(records),'local_gpu':False,
        'elapsed_seconds_this_session':time.monotonic()-started,'api_cost_cny':sum(x['api_cost_cny'] for x in records),
        'scientific_score_computed':False})


if __name__=='__main__':
    main()
