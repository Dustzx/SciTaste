"""Controlled ARCADE paper-history supplement; never strict paper reproduction.

Only main() can construct a paid requester. CPU engine sees label-free inputs.
No successful/refused/invalid/truncated stage is regenerated on replay.
"""
import argparse
import base64
import fcntl
import importlib.metadata
import json
import os
from pathlib import Path
import tempfile
import threading
import time

from cvpr_api_retry import PaidRequester
from cvpr_chart_api import Budget, credential, now
from cvpr_chart_run import ROOT, PROJECT, atomic_json, sha
from cvpr_intent_control_run import (BASE, CAP, MODEL, REFERENCE, SOURCE,
    load_inputs, load_upstream, price, safe_run_id, validate_rows)

CONTRACT = BASE/'sources/ARCADE/PAPER_HISTORY_CONTRACT.json'
CONTRACT_SHA256 = 'a11800d119203db0070a20de9a84967e5b331fb7f46d59786fdab683c9106c1b'
MODE = 'controlled_history_variant'
SPEC = {'mode': MODE, 'rounds': 3, 'gate_temperature': 0.0,
        'prosecutor_temperature': 0.8, 'defender_temperature': 0.8,
        'judge_temperature': 0.1,
        'implicit_edges': {'P': 'S,P_prev,D_prev', 'D': 'S,P_current,D_prev'},
        'judge_history': 'all_three_round_pairs',
        'serialization': 'role_named_json_fields',
        'prompt_policy': 'unchanged_upstream_prompts'}
DEPENDENCIES = ('cvpr_intent_history_run.py', 'cvpr_intent_history_score.py',
                'cvpr_intent_control_run.py', 'cvpr_intent_control_score.py',
                'cvpr_api_retry.py', 'cvpr_chart_api.py', 'cvpr_chart_run.py',
                'cvpr_chart_binding.py')
DIRECT_STAGES = ('gate', 'direct-p', 'direct-d', 'direct-judge')
INDIRECT_STAGES = ('gate', 'implicit-p1', 'implicit-d1', 'implicit-p2',
                   'implicit-d2', 'implicit-p3', 'implicit-d3', 'implicit-judge')
ALL_STAGES = set(DIRECT_STAGES) | set(INDIRECT_STAGES)


def load_contract(path=CONTRACT):
    contract = json.loads(Path(path).read_text())
    if sha(Path(path).read_bytes()) != CONTRACT_SHA256 or contract.get('machine_execution_spec') != SPEC:
        raise ValueError('Independent paper-history contract is absent or differs from frozen implementation')
    return contract


def implementation_hashes():
    return {name: sha((ROOT/'scripts'/name).read_bytes()) for name in DEPENDENCIES}


class InvalidStage(Exception):
    def __init__(self, stage, refused=False):
        self.stage, self.refused = stage, refused
        super().__init__(stage)


def parse_stage(court, text):
    value = court.clean_json_like(text)
    if isinstance(value, (dict, list)):
        return value
    return ({'content': value, 'error': 'Output format is not JSON', 'refusal': False}
            if isinstance(value, str) else {'error': 'Empty Response', 'refusal': True})


def stage_invalid(stage, parsed, truncated=False):
    """Author advocate outputs are arrays; cue/rebuttal fields stay unaltered.

    Empty arrays remain legal (P1 dismissal, empty defense, later empty P).
    Item-level field enforcement would add a stricter schema than this control.
    """
    return bool(truncated or
        isinstance(parsed, dict) and (parsed.get('refusal') is True or 'error' in parsed) or
        'judge' not in stage and (not isinstance(parsed, list) or
                                 any(not isinstance(item, dict) for item in parsed)))


def request_body(system, row, prompt, temperature, fields=None, instruction=None):
    content, has_image = system._prepare_multimodal_content(row['tweet_text'], row['local_image_path'])
    images = [part['image_url']['url'] for part in content if part.get('type') == 'image_url']
    if (not has_image or len(images) != 1 or
            sha(base64.b64decode(images[0].split(',', 1)[1], validate=True)) != row['image_sha256']):
        raise ValueError('Every stage must receive original image bytes')
    if fields is not None:
        content.append({'type': 'text', 'text': '\nHistory: '+json.dumps(
            fields, ensure_ascii=False, sort_keys=True, separators=(',', ':'))})
    if instruction is not None:
        content.append({'type': 'text', 'text': instruction})
    return {'model': MODEL, 'messages': [{'role': 'system', 'content': prompt},
            {'role': 'user', 'content': content}], 'temperature': temperature,
            'max_tokens': CAP, 'enable_thinking': False, 'stream': False}


def execute_panel(rows, *, court, system, requester, run, calls=None,
                  on_state=None, image_root=BASE/'data/images'):
    """Adaptive fixed graph; paper history and .8 roles are joint changes."""
    rows = validate_rows(rows, image_root=image_root)
    run = Path(run)
    calls = list(calls or [])
    by_key = {call['key']: call for call in calls}
    possible = {row['id']+'|'+stage for row in rows for stage in ALL_STAGES}
    if len(by_key) != len(calls) or not set(by_key) <= possible or any(c.get('status') != 'ok' for c in calls):
        raise ValueError('Invalid or unrelated successful stage cache')
    path = run/'PREDICTIONS.json'
    predictions = json.loads(path.read_text()) if path.exists() else []
    old = {p['id']: p for p in predictions}
    if len(old) != len(predictions) or not set(old) <= {row['id'] for row in rows}:
        raise ValueError('Invalid cached prediction identities')
    used = set()

    def emit(sample=None, stage=None):
        if on_state:
            on_state(predictions, list(by_key.values()), sample, stage)

    def save(call):
        if call['key'] in by_key:
            raise ValueError('Never regenerate a successful response')
        with (run/'calls.jsonl').open('a') as handle:
            handle.write(json.dumps(call, ensure_ascii=False)+'\n')
            handle.flush()
            os.fsync(handle.fileno())
        by_key[call['key']] = call

    def call_stage(row, stage, prompt, temperature, fields=None, instruction=None):
        body = request_body(system, row, prompt, temperature, fields, instruction)
        digest = sha(json.dumps(body, ensure_ascii=False, sort_keys=True).encode())
        key = row['id']+'|'+stage
        if key in by_key:
            call = by_key[key]
            if (call.get('prompt_sha256') != digest or call.get('token_cap') != CAP
                    or call.get('requested_model') != MODEL):
                raise ValueError('Cached request changed; refusing regeneration')
        else:
            call = requester.call(key=key, cap=CAP, body=body, digest=digest, save=save)
            if by_key.get(key) != call:
                raise ValueError('Successful stage lacks durable replay record')
        used.add(key)
        emit(row['id'], stage)
        parsed = parse_stage(court, call['text'])
        refused = isinstance(parsed, dict) and parsed.get('refusal') is True
        if stage_invalid(stage, parsed, call.get('truncated')):
            raise InvalidStage(stage, refused)
        return parsed

    prompts = system.prompts
    for row in rows:
        try:
            gate = call_stage(row, 'gate', prompts.PROSECUTOR_DIRECT_PROMPT, 0.0,
                              instruction='\nTask: Identify DIRECT hate speech cues. Output JSON.')
            # Preserve upstream route semantics and terminal gate failure.
            if isinstance(gate, dict) and (gate.get('refusal') or 'error' in gate):
                result = {'final_stage': 'error', 'verdict': {'refusal': True, 'label': -1,
                          'reason': 'Stage A Failed'}, 'gate': gate}
                stages = ('gate',)
            elif isinstance(gate, list) and gate:
                p = call_stage(row, 'direct-p', prompts.PROSECUTOR_PROMPT, .8,
                               instruction='\nTask: Analyze accusations.')
                d = call_stage(row, 'direct-d', prompts.DEFENDER_PROMPT, .8,
                               instruction='\nAccusations: '+json.dumps(p)+'\nTask: Refute.')
                verdict = call_stage(row, 'direct-judge', prompts.JUDGE_PROMPT, .1,
                          instruction='\nProsecutor: '+json.dumps(p)+'\nDefense: '+json.dumps(d)+'\nVerdict.')
                result = {'final_stage': 'direct_standard', 'prosecutor': p, 'defense': d,
                          'verdict': verdict, 'gate': gate}
                stages = DIRECT_STAGES
            else:
                history, p_prev, d_prev = [], [], []
                for k in range(1, 4):
                    p = call_stage(row, f'implicit-p{k}',
                        prompts.PROSECUTOR_INDIRECT_PROMPT if k == 1 else prompts.PROSECUTOR_ROUND_2_PROMPT, .8,
                        None if k == 1 else {'prosecutor_previous': p_prev, 'defender_previous': d_prev})
                    if k == 1 and isinstance(p, list) and not p:
                        break
                    d = call_stage(row, f'implicit-d{k}',
                        prompts.DEFENDER_INDIRECT_PROMPT if k == 1 else prompts.DEFENSE_ROUND_2_PROMPT, .8,
                        {'prosecutor_current': p, 'defender_previous': d_prev})
                    history.append({'round': k, 'prosecutor': p, 'defense': d})
                    p_prev, d_prev = p, d
                if not history:
                    result = {'final_stage': 'safe', 'verdict': {'label': 0, 'reason': 'No cues found.'}, 'gate': gate}
                    stages = ('gate', 'implicit-p1')
                else:
                    verdict = call_stage(row, 'implicit-judge', prompts.JUDGE_PROMPT_INDIRECT, .1,
                                         instruction='\nTranscript: '+json.dumps(history)+'\nVerdict.')
                    result = {'final_stage': 'indirect_multiround', 'prosecutor': p_prev,
                              'defense': d_prev, 'verdict': verdict, 'history': history, 'gate': gate}
                    stages = INDIRECT_STAGES
        except InvalidStage as exc:
            stages = tuple(stage for stage in INDIRECT_STAGES if row['id']+'|'+stage in used)
            if any(row['id']+'|'+stage in used for stage in DIRECT_STAGES[1:]):
                stages = tuple(stage for stage in DIRECT_STAGES if row['id']+'|'+stage in used)
            result = {'final_stage': 'error', 'verdict': {'label': None,
                      'refusal': exc.refused, 'error': 'invalid_completed_stage'},
                      'failure_stage': exc.stage,
                      'failure_policy': 'Malformed/refused/truncated stage counts as full-panel error; no content retry.'}
        prediction = {'id': row['id'], 'result': result, 'stage_keys': list(stages), 'logical_calls': len(stages)}
        if row['id'] in old:
            if old[row['id']] != prediction:
                raise ValueError('Cached prediction differs from deterministic stage replay')
        else:
            predictions.append(prediction)
            atomic_json(path, predictions)
        emit(row['id'], 'sample_completed')
    if set(by_key) != used:
        raise ValueError('Cached stages do not belong to the deterministic completed route')
    return predictions, list(by_key.values())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--inputs', type=Path, default=BASE/'data/DEVELOPMENT_INPUTS.json')
    parser.add_argument('--manifest', type=Path, default=BASE/'data/MANIFEST.json')
    parser.add_argument('--contract', type=Path, default=CONTRACT)
    args = parser.parse_args()
    safe_run_id(args.run_id)
    rows, reference = load_inputs(args.inputs, args.manifest)
    court, receipt = load_upstream()
    run = BASE/'runs'/args.run_id
    run.mkdir(parents=True, exist_ok=True)
    with (run/'.run.lock').open('a') as run_lock, (PROJECT/'.api-single-worker.lock').open('a') as worker_lock:
        fcntl.flock(run_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(worker_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        contract = load_contract(args.contract)
        protocol = {
            'kind': 'intent_history', 'diagnostic_kind': 'intent_history', 'mode': MODE,
            'title': 'ARCADE论文历史信息流受控变体（非严格复现）',
            'model': MODEL, 'weight_revision': None, 'training': False, 'local_gpu': False,
            'maximum_concurrency': 1, 'rounds': 3, 'machine_execution_spec': SPEC,
            'max_tokens_per_call': CAP, 'max_logical_calls': 256, 'max_http_attempts': 768,
            'total_output_ceiling_per_sample': 16384, 'phase_cap_cny': 20, 'project_cap_cny': 300,
            'routing': 'Normal routes2 safe,4 direct,8 implicit; invalid content terminates at its1–8stage prefix as error. No later empty-P dismissal.',
            'comparison_boundary': 'Controlled supplement changes implicit argument wiring AND implicit .7 to paper role .8; no history-only attribution.',
            'deviations_from_upstream': [
                'Implicit P receives previous P,D; D receives current P and previous D as role-named JSON data.',
                'Implicit P/D .8 follows paper role-level temperature, unlike public code .7.',
                'JSON serialization and round2/3 prompt selection are controlled choices, not uniquely specified by paper.',
                'Explicit nonthinking and2048 output cap; bounded durable retry max3, one paid worker.',
                'All non-Judge gate/advocate outputs must be arrays of JSON objects; no additional cue-field validation. Malformed/refused/truncated success is retained and terminates the case as error; no content retry.',
                'Same exposed32 official train H-VLI-source panel; no independent confirmation.'],
            'failure_policy': 'Malformed gate/history, refusal or truncation terminates this case as full32 error; retain raw successful cache, never resample. API exceptions propagate to held, never safe.',
            'retry': 'Existing durable max3 attempts; unknown reservations retained; failed HTTP usage outside successful-path cap.',
            'scope': 'Supplement to accepted ACL2026 Findings paper/code discrepancy; not a new method or strict reproduction.',
            'sample_ids': [row['id'] for row in rows],
            'inputs_sha256': reference['inputs_sha256'], 'manifest_sha256': reference['manifest_sha256'],
            'reference_protocol_sha256': sha(REFERENCE.read_bytes()),
            'paper_history_contract_sha256': sha(args.contract.read_bytes()),
            'paper_history_contract_path': str(args.contract.resolve()),
            'upstream_revision': receipt['revision'], 'source_files': receipt['files'],
            'implementation_sha256': implementation_hashes(),
            'runtime_packages': {name: importlib.metadata.version(name) for name in ['requests', 'json_repair', 'scikit-learn']},
            'price_source': 'https://help.aliyun.com/zh/model-studio/model-pricing',
            'prices_cny_per_million': {'input_le32k': 1, 'output_le32k': 10, 'reservation_max_tier': [3,30]},
        }
        frozen = run/'PROTOCOL.json'
        if frozen.exists():
            if json.loads(frozen.read_text()) != protocol:
                raise ValueError('Frozen protocol changed; no API call permitted')
        else:
            atomic_json(frozen, protocol)
            snapshots = run/'SOURCE_SNAPSHOTS'
            snapshots.mkdir()
            (snapshots/'PAPER_HISTORY_CONTRACT.json').write_bytes(args.contract.read_bytes())
            for name, digest in protocol['implementation_sha256'].items():
                data = (ROOT/'scripts'/name).read_bytes()
                if sha(data) != digest:
                    raise ValueError('Source changed during freeze')
                (snapshots/name).write_bytes(data)
        for name, digest in protocol['implementation_sha256'].items():
            if sha((run/'SOURCE_SNAPSHOTS'/name).read_bytes()) != digest:
                raise ValueError('Frozen source snapshot changed')
        if sha((run/'SOURCE_SNAPSHOTS/PAPER_HISTORY_CONTRACT.json').read_bytes()) != protocol['paper_history_contract_sha256']:
            raise ValueError('Frozen paper-history contract snapshot changed')
        calls_path = run/'calls.jsonl'
        calls = [json.loads(line) for line in calls_path.read_text().splitlines()] if calls_path.exists() else []
        ledger = json.loads((PROJECT/'API_LEDGER.json').read_text())
        unknown = {key: value for key, value in ledger['attempts'].items() if value['status'] != 'settled'}
        if any(Path(f"/proc/{value['pid']}").exists() for value in unknown.values()):
            raise RuntimeError('Unresolved attempt belongs to a live process')
        prior = {}
        for item in ledger['attempts'].values():
            if item['run_id'] == args.run_id:
                prior[item['key']] = max(prior.get(item['key'], 0), item.get('attempt_index', 1))
        halt = threading.Event()
        requester = PaidRequester(budget=Budget(unknown, retry_own_failures=True), run=run,
                                  run_id=args.run_id, secret=credential(), halt=halt,
                                  prior_attempts=prior, prices=(3, 30), cost_function=price,
                                  phase_cap=20, wall_limit_seconds=10800, request_timeout=(15, 180))
        existing_status = json.loads((run/'STATUS.json').read_text()) if (run/'STATUS.json').exists() else {}
        started = existing_status.get('started_at', now())
        tick = time.monotonic()

        def state(status, predictions, responses, sample=None, stage=None, error=None):
            value = {'status': status, 'kind': 'intent_history', 'mode': MODE,
                     'pid': os.getpid(), 'model': MODEL, 'started_at': started, 'updated_at': now(),
                     'selected_samples': 32, 'completed_samples': len(predictions),
                     'successful_calls': len(responses), 'max_logical_calls': 256,
                     'active_sample': sample, 'active_stage': stage,
                     'input_tokens': sum(c.get('input_tokens', 0) for c in responses),
                     'output_tokens': sum(c.get('output_tokens', 0) for c in responses),
                     'elapsed_seconds_this_session': time.monotonic() - tick}
            if error:
                value['error'] = error
            atomic_json(run/'STATUS.json', value)
            return value

        with tempfile.TemporaryDirectory(prefix='intent_history_') as cache:
            system = court.CourtroomSystem(None, str(ROOT), cache_base_dir=cache, class_mode='multiclass')
            state('running', [], calls)
            try:
                predictions, responses = execute_panel(rows, court=court, system=system, requester=requester,
                    run=run, calls=calls, on_state=lambda preds, records, sid, stage: state('running', preds, records, sid, stage))
                print(json.dumps(state('model_completed', predictions, responses)), flush=True)
            except BaseException as exc:
                halt.set()
                predictions = json.loads((run/'PREDICTIONS.json').read_text()) if (run/'PREDICTIONS.json').exists() else []
                responses = [json.loads(line) for line in calls_path.read_text().splitlines()] if calls_path.exists() else []
                state('held', predictions, responses, error=type(exc).__name__)
                raise


if __name__ == '__main__':
    main()
