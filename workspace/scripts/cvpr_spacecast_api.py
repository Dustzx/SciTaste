"""Bounded scene-disjoint development diagnostic, with official visible inputs.

No retries, no confirmation access, no learned/geometric expert, no local GPU.
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

RUN_ID='bailian_qwen38_flash_spacecast_state_screen_v3'
ARMS=['direct','review','state_table','state_invalidation']
EXTRACT='''Observe only the initial scene, BEFORE the hypothetical edit in the question. Return ONLY JSON:
{"intervention":{"kind":"none|object_move|object_rotate|object_remove|frame_rotate|unknown","frame":"camera|world|object|unknown","targets":["exact entity names in question"]},"facts":[{"subject":"entity","relation":"direction|distance|occludes|attachment|facing|other","object":"entity","value":"brief observed relation with uncertainty","frame":"camera|world|object|invariant|unknown","frame_owner":"camera/world or named object","post_validity":"unchecked"}]}.
Up to24 concise facts. Classify the requested intervention, but do NOT apply it in observed facts. Do NOT output the answer, reasoning toward options, made-up coordinates or unseen outcomes. Use unknown when evidence is insufficient. Spatial frame must be explicit; use invariant only for distance/topology that is independent of coordinate basis.'''
SOLVE='''The table below is fallible evidence about the scene BEFORE the edit. Observe-transform-infer: identify the requested intervention and reference frame, preserve unaffected relations, recompute affected relations, and then answer. A must_recompute marker means the prior relation cannot be used unchanged; it provides no new relation or answer. Verify the facts using the SAME observed images. Use the question's exact directional/frame conventions. Keep reasoning brief and return final Answer line.'''
REVIEW='''Recheck the provisional reasoning below against the images, requested intervention and reference frame. Keep reasoning brief; give the final Answer line. The previous answer may be wrong.'''


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--stop-after',type=int,default=32);args=parser.parse_args()
    assert args.stop_after in {2,32}
    base=PROJECT/'spacecast';data=base/'data';manifest=json.loads((data/'MANIFEST.json').read_text())
    sys.path.insert(0,str(PROJECT/'sources/spacecast'))
    from spacecast_eval.protocol import parse_prediction,SYSTEM_PROMPT
    ordered=json.loads((data/'screen_ids.json').read_text());rows={r['question_uid']:r for r in map(json.loads,(data/'development_inputs.jsonl').read_text().splitlines())}
    assert len(ordered)==32 and len({rows[k]['scene_group'] for k in ordered})==32
    for row in rows.values():
        assert row['partition']=='development' and not {'answer','Answer','depth','coordinates'}&set(row)
        for im in row['images']:assert sha((ROOT/im['path']).read_bytes())==im['sha256']
    old=PROJECT/'runs/bailian_qwen38_flash_screen_recovery_v1/RECOVERY.json';retained=json.loads(old.read_text())['retained_unknown']
    run=base/'runs'/RUN_ID;run.mkdir(parents=True,exist_ok=True)
    lock=(run/'.run.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    protocol={'model':'qwen3.8-flash','scope':'exploratory SpaceCast development32; not official full score','sample_ids':ordered,
              'arms':ARMS,'manifest_sha256':sha((data/'MANIFEST.json').read_bytes()),'retained_unknown':retained,
              'source_commit':manifest['source_commit'],'official_visible_inputs':True,'image_protocol':manifest['image_protocol'],
              'thinking':False,'temperature':0,'max_new_tokens_total_per_arm':1792,'two_pass_allocation':[1280,512],
              'prompts':{'extract':EXTRACT,'solve':SOLVE,'review':REVIEW},
              'source_sha256':{p.name:sha(p.read_bytes()) for p in [Path(__file__),ROOT/'scripts/cvpr_spacecast_state.py']},
              'control':'Explicit observe-transform-infer scene table; intervention annotations unchecked in control',
              'output_contract':'All arms use JSON object, answer field first, rationale<=80 words; changed from truncated original-last-line v1, cap unchanged',
              'intervention':'Only dependency-invalidated facts change post_validity to must_recompute; no new facts',
              'shared_extraction':'Full logical extraction cost counted in both table arms; identical graph shares same final response',
              'phase_cap_cny':20,'project_cap_cny':300,'local_gpu':False,'cloud_gpu':None,'retry':'none; new unknown holds all submissions'}
    if (run/'PROTOCOL.json').exists():assert json.loads((run/'PROTOCOL.json').read_text())==protocol
    else:
        atomic_json(run/'PROTOCOL.json',protocol)
        for name in protocol['source_sha256']:(run/name).write_bytes((ROOT/'scripts'/name).read_bytes())
        previous=base/'runs/bailian_qwen38_flash_spacecast_state_screen_v2'
        receipt=json.loads((previous/'PROTOCOL.json').read_text())
        assert receipt['manifest_sha256']==protocol['manifest_sha256'] and receipt['model']==protocol['model']
        cached=[json.loads(x) for x in (previous/'calls.jsonl').read_text().splitlines()]
        assert all(x['status']=='ok' and not x['truncated'] for x in cached)
        ledger=json.loads((PROJECT/'API_LEDGER.json').read_text())['attempts']
        for x in cached:
            prior=ledger[previous.name+'|'+x['key']];assert prior['status']=='settled' and prior['response_id']==x['response_id']
        (run/'calls.jsonl').write_text(''.join(json.dumps({**x,'inherited_from_run':previous.name},ensure_ascii=False)+'\n' for x in cached))
        atomic_json(run/'CACHE_RECEIPT.json',{'source_run':previous.name,'source_calls_sha256':sha((previous/'calls.jsonl').read_bytes()),
            'cached_successes':len(cached),'policy':'Reuse exact prompt/image/cap matches; v2 never issued invalidation calls; no failed request retry'})
    calls_path=run/'calls.jsonl';records=list(map(json.loads,calls_path.read_text().splitlines())) if calls_path.exists() else []
    if any(r['status']!='ok' for r in records):raise RuntimeError('Failure retained; no retries')
    done={r['key']:r for r in records};preds=json.loads((run/'PREDICTIONS.json').read_text()) if (run/'PREDICTIONS.json').exists() else []
    complete={p['question_uid'] for p in preds};budget=Budget(retained);secret=credential()
    mutex=threading.Lock();rate=threading.Lock();last=[0.0];halt=threading.Event();started=time.monotonic()
    def call(row,stage,prompt,cap,as_json=False):
        key=row['question_uid']+'|'+stage;digest=sha((prompt+json.dumps(row['images'])+str(cap)+str(as_json)).encode())
        if key in done:
            assert done[key]['prompt_sha256']==digest;return done[key]
        if halt.is_set():raise RuntimeError('Sibling failure')
        ledger_key=RUN_ID+'|'+key;reserve=.8+cap*2.7/1e6
        with rate:
            time.sleep(max(0,2.5-(time.monotonic()-last[0])))
            if halt.is_set():raise RuntimeError('Sibling failure')
            budget.change(ledger_key,record={'run_id':RUN_ID,'key':key,'pid':os.getpid(),'model':protocol['model'],
                'reserved_cny':reserve,'status':'pending','started_at':now()},phase_cap=20,run_id=RUN_ID);last[0]=time.monotonic()
        images=[{'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+base64.b64encode((ROOT/i['path']).read_bytes()).decode()}} for i in row['images']]
        body={'model':protocol['model'],'messages':[{'role':'system','content':SYSTEM_PROMPT},{'role':'user','content':images+[{'type':'text','text':prompt}]}],
              'max_tokens':cap,'temperature':0,'enable_thinking':False}
        if as_json:body['response_format']={'type':'json_object'}
        tick=time.monotonic()
        try:
            response=requests.post(ENDPOINT,headers={'Authorization':'Bearer '+secret},json=body,timeout=(15,180));response.raise_for_status()
            obj=response.json();usage=obj['usage'];choice=obj['choices'][0];inp,out=int(usage['prompt_tokens']),int(usage['completion_tokens'])
            assert inp<=1000000 and out<=cap;cost=(inp*.8+out*2.7)/1e6
            text=choice['message']['content'];assert isinstance(text,str) and not choice['message'].get('reasoning_content')
            item={'key':key,'sample_id':row['question_uid'],'stage':stage,'status':'ok','created_at':now(),'prompt_sha256':digest,
                  'requested_model':protocol['model'],'returned_model':obj.get('model'),'response_id':obj['id'],'usage':usage,
                  'input_tokens':inp,'output_tokens':out,'token_cap':cap,'api_cost_cny':cost,'elapsed_seconds':time.monotonic()-tick,
                  'finish_reason':choice.get('finish_reason'),'truncated':choice.get('finish_reason')=='length','text':text,'parsed':parse_json(text)}
            with mutex:
                with calls_path.open('a') as f:f.write(json.dumps(item,ensure_ascii=False)+'\n');f.flush();os.fsync(f.fileno())
                records.append(item);done[key]=item
            budget.change(ledger_key,settle={'status':'settled','cost_cny':cost,'settled_at':now(),'response_id':obj['id'],'usage':usage})
            print(json.dumps({'key':key,'seconds':item['elapsed_seconds'],'cost_cny':cost,'truncated':item['truncated']}),flush=True);return item
        except Exception as exc:
            halt.set();budget.change(ledger_key,settle={'status':'unknown','exception_type':type(exc).__name__,'failed_at':now()})
            raise RuntimeError('Paid request failed; no retry') from None
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
            'completed_samples':len(preds)//4,'retry_authorized':False});raise
    atomic_json(run/'STATUS.json',{'state':'completed_predictions' if args.stop_after==32 else 'checkpoint_predictions','pid':os.getpid(),
        'completed_at':now(),'planned_samples':32,'completed_samples':len(preds)//4,'predictions':len(preds),'actual_calls':len(records),
        'elapsed_seconds_this_session':time.monotonic()-started,'api_cost_cny':sum(c['api_cost_cny'] for c in records),
        'local_gpu':False,'scientific_score_computed':False})


if __name__=='__main__':main()
