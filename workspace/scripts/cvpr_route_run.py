"""Label-blind NeSy-Route Task2 CPU adapter scaffold. No paid CLI entrypoint.

Root must admit an independent input manifest and supply image_loader/requester.
Import, source inspection and protocol assembly cannot read images or targets.
"""
from __future__ import annotations

import ast
import base64
import hashlib
import json
import os
from pathlib import Path
import re

from cvpr_api_retry import PaidRequester
from cvpr_chart_run import ROOT, PROJECT, atomic_json

BASE = PROJECT / 'route'
SOURCE = BASE / 'sources/NeSy-Route-contract'
SOURCE_CONTRACT_SHA256 = 'd6c03e9430a49e769ff5b72f4a223d62ccf57600ef32610d50863ebbe14ab9af'
REVISION = '9757b0d1f6d6ab54fd675768d1212fb80509c351'
MODEL, CAP, N = 'qwen3-vl-plus', 2048, 32
VECTOR_FIELDS = ('region_vector', 'traverse_vector', 'cost_vector')
ROW_FIELDS = {'sample_id', 'question', 'image_path', 'image_sha256', 'source_group', 'query_group'}
ASSET_FIELDS = {'sample_id', 'image_path', 'image_sha256', 'mime_type', 'origin',
                'pixel_transform', 'source_shard', 'row_index', 'width', 'height', 'decoded_rgb_sha256',
                'source_image_path', 'source_image_bytes_sha256', 'source_mime_type'}
DEPENDENCIES = ('cvpr_route_execute.py', 'cvpr_route_evaluate.py', 'cvpr_route_run.py', 'cvpr_route_score.py', 'cvpr_api_retry.py',
                'cvpr_chart_api.py', 'cvpr_chart_run.py', 'cvpr_chart_binding.py')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def strict_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate_json_key')
            result[key] = value
        return result

    def constant(_):
        raise ValueError('nonfinite_json_constant')

    return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)


def verify_source(source=SOURCE):
    source = Path(source).resolve()
    receipt_bytes = (source/'SOURCE_CONTRACT.json').read_bytes()
    if sha(receipt_bytes) != SOURCE_CONTRACT_SHA256:
        raise ValueError('Source contract differs from audited contract')
    receipt = strict_json(receipt_bytes)
    for item in receipt['files']:
        path = (source/item['path']).resolve()
        if source not in path.parents or sha(path.read_bytes()) != item['sha256']:
            raise ValueError('Original source changed')
    return receipt


def load_prompts(source=SOURCE):
    """Extract literal strings by AST, without executing author code."""
    verify_source(source)
    tree = ast.parse((Path(source)/'evaluation/task2/prompts.py').read_text())
    values = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for name in node.targets:
                if isinstance(name, ast.Name) and name.id in {'SOLVER_SYSTEM_PROMPT', 'USER_TEMPLATE'}:
                    if name.id in values:
                        raise ValueError('Duplicate author prompt assignment')
                    values[name.id] = ast.literal_eval(node.value)
    expected = {'SOLVER_SYSTEM_PROMPT': '8f92e3653853c5f2103bb121502ece2d705efaa7050a67d818580ae449517206',
                'USER_TEMPLATE': '5c42646011a78c099b503b7be740a7ebb7a2d84be0b41da5c08b037add5ab525'}
    if set(values) != set(expected) or any(not isinstance(v, str) or sha(v.encode()) != expected[k] for k,v in values.items()):
        raise ValueError('Original four-shot prompt strings differ')
    return values


def valid_vectors(value):
    return (isinstance(value, dict) and all(
        isinstance(value.get(field), list) and len(value[field]) == 8
        and all(type(v) is int and v >= 0 for v in value[field])
        for field in VECTOR_FIELDS)
        and all(v in (0, 1) for v in value['traverse_vector']))


def parse_response(text):
    """Local declared parser; author publishes no VLM-response parser."""
    if not isinstance(text, str):
        return {'success': False, 'status': 'parse_failure'}
    raw = text.strip()
    if raw.startswith('```'):
        match = re.fullmatch(r'```json[ \t]*\r?\n(.*?)\r?\n```', raw, re.DOTALL)
        if not match:
            return {'success': False, 'status': 'parse_failure'}
        raw = match.group(1)
    try:
        value = strict_json(raw)
    except (ValueError, TypeError):
        return {'success': False, 'status': 'parse_failure'}
    if isinstance(value, dict) and value.get('refusal') is True:
        return {'success': False, 'status': 'refusal'}
    if not valid_vectors(value) or 'error' in value:
        return {'success': False, 'status': 'schema_failure'}
    # Auxiliary reasoning spelling differs between schema and author examples.
    result = {'success': True, 'status': 'valid', **{key: value[key] for key in VECTOR_FIELDS}}
    for key in ('logic_reasoning', 'reasoning'):
        if isinstance(value.get(key), str):
            result[key] = value[key]
    return result


def prediction_from_call(call):
    sid, stage = call['key'].split('|')
    if stage != 'direct':
        raise ValueError('Unknown Route stage')
    if call.get('truncated') or call.get('finish_reason') == 'length':
        result = {'success': False, 'status': 'truncated'}
    elif call.get('refusal') is True or call.get('finish_reason') == 'content_filter':
        result = {'success': False, 'status': 'refusal'}
    else:
        result = parse_response(call.get('text'))
    return {'sample_id': sid, **result}


def validate_inputs(projection, manifest, *, inputs_sha256, image_root):
    """Independent, label-free manifest. Does not open image paths."""
    header = {'schema_version', 'role', 'task', 'revision', 'items'}
    manifest_fields = {'schema_version', 'dataset_repository', 'revision', 'task', 'role',
                       'inputs_sha256', 'selection_sha256', 'sample_ids', 'image_assets',
                       'source_contract_sha256', 'grouping_scope'}
    if (set(projection) != header or projection['schema_version'] != 1
            or projection['role'] != 'development_only' or projection['task'] != 'task2'
            or projection['revision'] != REVISION):
        raise ValueError('Only label-free Task2 development projection permitted')
    if (set(manifest) != manifest_fields or manifest['schema_version'] != 1
            or manifest['dataset_repository'] != 'Ming1010/NeSy-Route'
            or manifest['task'] != 'task2' or manifest['revision'] != REVISION
            or manifest['role'] != 'evaluation_derived_development'
            or manifest['source_contract_sha256'] != SOURCE_CONTRACT_SHA256
            or manifest['inputs_sha256'] != inputs_sha256
            or not re.fullmatch('[0-9a-f]{64}', manifest['selection_sha256'])):
        raise ValueError('Independent input manifest missing or changed')
    rows, assets = projection['items'], manifest['image_assets']
    if not isinstance(rows, list) or len(rows) != N or not isinstance(assets, list) or len(assets) != N:
        raise ValueError('Exactly32 frozen input rows and image assets required')
    root = Path(image_root).resolve()
    for row, asset in zip(rows, assets, strict=True):
        if set(row) != ROW_FIELDS or any(not isinstance(v, str) or not v for v in row.values()):
            raise ValueError('Target-bearing or incomplete input fields')
        if not re.fullmatch('[A-Za-z0-9_-]+', row['sample_id']):
            raise ValueError('Unsafe sample ID')
        if not re.fullmatch('[0-9a-f]{64}', row['image_sha256']):
            raise ValueError('Missing original image byte hash')
        if root not in Path(row['image_path']).resolve().parents:
            raise ValueError('Image path outside admitted image root')
        if set(asset) != ASSET_FIELDS or any(asset[key] != row[key] for key in ('sample_id','image_path','image_sha256')):
            raise ValueError('Image asset mismatch or unexpected fields')
        if (asset['origin'] != 'official_task2_numbered_region_raster'
                or asset['pixel_transform'] not in ('none', 'lossless_container_to_png_no_resize')
                or asset['mime_type'] not in ('image/png', 'image/jpeg', 'image/webp')
                or asset['source_mime_type'] not in ('image/png', 'image/jpeg', 'image/webp', 'image/tiff')
                or root not in Path(asset['source_image_path']).resolve().parents
                or not re.fullmatch('[0-9a-f]{64}', asset['source_image_bytes_sha256'])
                or not isinstance(asset['source_shard'], str) or not asset['source_shard']
                or type(asset['row_index']) is not int or asset['row_index'] < 0
                or any(type(asset[k]) is not int or asset[k] <= 0 for k in ('width','height'))
                or not re.fullmatch('[0-9a-f]{64}', asset['decoded_rgb_sha256'])):
            raise ValueError('Official numbered raster provenance not admitted')
        if asset['pixel_transform'] == 'none':
            if any(asset[left] != asset[right] for left,right in (
                    ('source_image_bytes_sha256','image_sha256'),
                    ('source_mime_type','mime_type'))):
                raise ValueError('None transform requires original byte container')
        elif asset['source_mime_type'] != 'image/tiff' or asset['mime_type'] != 'image/png':
            raise ValueError('Only lossless TIFF-to-PNG container adaptation is admitted')
    ids = [r['sample_id'] for r in rows]
    if (len(set(ids)) != N or ids != manifest['sample_ids']
            or len({r['source_group'] for r in rows}) != N
            or len({r['query_group'] for r in rows}) != N
            or len({r['image_sha256'] for r in rows}) != N):
        raise ValueError('Duplicate identity/image/source proxy or changed ordering')
    return rows


def load_inputs(inputs_path, manifest_path, *, image_root):
    raw, manifest_raw = Path(inputs_path).read_bytes(), Path(manifest_path).read_bytes()
    projection, manifest = strict_json(raw), strict_json(manifest_raw)
    rows = validate_inputs(projection, manifest, inputs_sha256=sha(raw), image_root=image_root)
    return rows, manifest, sha(raw), sha(manifest_raw)


def request_body(row, asset, image_bytes, prompts):
    if not isinstance(image_bytes, bytes) or sha(image_bytes) != row['image_sha256']:
        raise ValueError('Original numbered image bytes not supplied')
    # Only raw question and original image enter the user payload.
    return {'model': MODEL,
            'messages': [{'role': 'system', 'content': prompts['SOLVER_SYSTEM_PROMPT']},
                         {'role': 'user', 'content': [
                             {'type': 'text', 'text': prompts['USER_TEMPLATE'].format(question=row['question'])},
                             {'type': 'image_url', 'image_url': {'url': 'data:'+asset['mime_type']+';base64,'+base64.b64encode(image_bytes).decode()}}]}],
            'temperature': 0.0, 'max_tokens': CAP, 'enable_thinking': False, 'stream': False}


def price(inp, out):
    rates = (1, 10) if inp <= 32768 else (1.5, 15) if inp <= 131072 else (3, 30)
    return (inp*rates[0]+out*rates[1])/1e6


def make_requester(*, budget, run, run_id, secret, halt, prior_attempts=None):
    """Root-only integration hook; no credential discovery or paid CLI here."""
    return PaidRequester(budget=budget, run=Path(run), run_id=run_id, secret=secret,
                         halt=halt, prior_attempts=prior_attempts, prices=(3, 30),
                         cost_function=price, phase_cap=20, wall_limit_seconds=10800,
                         request_timeout=(15,180))


def assemble_protocol(manifest, *, inputs_sha256, manifest_sha256):
    receipt, prompts = verify_source(), load_prompts()
    return {
        'kind': 'route_task2', 'mode': 'author_fourshot_api_adapter', 'model': MODEL,
        'stage': 'CPU_scaffold_only_data_admission_pending', 'paid_admission': False,
        'sample_ids': manifest['sample_ids'], 'selected_samples': N,
        'inputs_sha256': inputs_sha256, 'manifest_sha256': manifest_sha256,
        'selection_sha256': manifest['selection_sha256'], 'dataset_revision': REVISION,
        'source_contract_sha256': SOURCE_CONTRACT_SHA256, 'source_files': receipt['files'],
        'source_revision': receipt['commit'],
        'implementation_sha256': {name: sha((ROOT/'scripts'/name).read_bytes()) for name in DEPENDENCIES},
        'prompts_sha256': {k: sha(v.encode()) for k,v in prompts.items()},
        'max_tokens_per_call': CAP, 'temperature': 0.0, 'enable_thinking': False,
        'max_logical_calls': N, 'max_http_attempts': N*3, 'paid_workers': 1,
        'phase_cap_cny': 20, 'project_cap_cny': 300,
        'reservation_cny_per_physical_attempt': 3+CAP*30/1e6,
        'reservation_semantics': 'Existing PaidRequester reserves one million input tokens at3CNY/M plus capped output at30CNY/M before each physical attempt, not the32768-token proposal. Settled success releases excess; old unknown reservations remain.',
        'six_unsettled_attempts_cny': 6*(3+CAP*30/1e6),
        'seven_unsettled_attempts_cny': 7*(3+CAP*30/1e6),
        'completion_under_phase_cap_guaranteed': False,
        'input_token_preflight_limit': None,
        'input_limit_note': 'No exact provider image-tokenizer is available in this scaffold. Conservative existing reservation covers up to1M input tokens; root must verify context/pixel contract before launch, without claiming a32768 preflight bound.',
        'parser': 'One JSON object or one outer json fence; reject duplicate keys/nonfinite values; all3 vectors exactly8 nonnegative true integers, traverse binary; no repair/resampling.',
        'failure_policy': 'Successful invalid/refused/truncated responses retained as failed full-denominator IDs. API exceptions propagate as held/incomplete and never generate a guessed vector.',
        'deviations': ['Author API caller/parser/settings absent; transparent API adapter, not exact paper-score reproduction.',
                       'Original code4shot preserved despite paper zero-shot wording.',
                       'T0/nonthinking/2048 explicit local settings; historical rolling alias/resize policy unknown.'],
        'grouping_scope': manifest['grouping_scope'], 'confirmation_evaluated': False,
        'publication_ready': False, 'original_score_reproduced': False,
        'required_before_paid_launch': ['Root admission of official image bytes and independent manifest/selection linkage.',
                                        'External root wrapper must take project single-worker and run locks, freeze source snapshots, construct existing shared Budget and preserve unknown attempts.',
                                        'Separate selected-only targets manifest; no target loading until32 successful API response receipts/prediction records are frozen.',
                                        'Tier/pixel/context and cumulative ledger preflight; no automatic provider/model/GPU substitution.']}


def execute_panel(rows, manifest, *, requester, image_loader, run, calls=None, on_state=None):
    """CPU-testable orchestration. Caller must already validate/admit manifest.

    No API client factory, image file loader or target reader is constructed here.
    Both successful malformed outputs and truncations are replayed, never retried.
    """
    if len(rows) != N or [row['sample_id'] for row in rows] != manifest['sample_ids']:
        raise ValueError('Complete frozen32 input sequence required')
    run, prompts = Path(run), load_prompts()
    calls = list(calls or [])
    by_key = {call['key']: call for call in calls}
    expected = {row['sample_id']+'|direct' for row in rows}
    if len(by_key) != len(calls) or not set(by_key) <= expected or any(c.get('status') != 'ok' for c in calls):
        raise ValueError('Unrelated or unsuccessful cached API receipts')
    path = run/'PREDICTIONS.json'
    predictions = strict_json(path.read_bytes()) if path.exists() else []
    old = {p['sample_id']: p for p in predictions}
    if len(old) != len(predictions) or not set(old) <= {r['sample_id'] for r in rows}:
        raise ValueError('Invalid cached prediction identities')

    def emit(sample=None):
        if on_state:
            on_state(predictions, list(by_key.values()), sample)

    def save(call):
        if call['key'] in by_key:
            raise ValueError('Successful response cannot be regenerated')
        with (run/'calls.jsonl').open('a') as handle:
            handle.write(json.dumps(call, ensure_ascii=False)+'\n')
            handle.flush()
            os.fsync(handle.fileno())
        by_key[call['key']] = call
        emit(call['key'].split('|', 1)[0])

    for row, asset in zip(rows, manifest['image_assets'], strict=True):
        emit(row['sample_id'])
        key = row['sample_id']+'|direct'
        body = request_body(row, asset, image_loader(row), prompts)
        digest = sha(json.dumps(body, ensure_ascii=False, sort_keys=True).encode())
        call = by_key.get(key)
        if call is None:
            call = requester.call(key=key, cap=CAP, body=body, digest=digest, save=save)
            if by_key.get(key) != call:
                raise ValueError('Response was not durably cached')
        if call.get('prompt_sha256') != digest or call.get('token_cap') != CAP or call.get('requested_model') != MODEL:
            raise ValueError('Cached request changed')
        prediction = prediction_from_call(call)
        if row['sample_id'] in old:
            if old[row['sample_id']] != prediction:
                raise ValueError('Cached prediction differs from deterministic response replay')
        else:
            predictions.append(prediction)
            atomic_json(path, predictions)
        emit(row['sample_id'])
    if set(by_key) != expected:
        raise ValueError('Incomplete response panel')
    return predictions, list(by_key.values())


if __name__ == '__main__':
    raise SystemExit('CPU scaffold only: root must admit data and integrate locked durable execution; no paid CLI enabled.')
