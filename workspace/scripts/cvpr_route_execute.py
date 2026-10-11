"""Root-admitted NeSy-Route Task2 execution. Importing this module is unpaid."""
from __future__ import annotations

import argparse
import fcntl
import importlib.util
from io import BytesIO
import json
import os
from pathlib import Path
import re
import threading
import time

from PIL import Image

from cvpr_chart_api import Budget, credential, now
from cvpr_chart_run import ROOT, PROJECT, atomic_json
from cvpr_route_run import (BASE, SOURCE, SOURCE_CONTRACT_SHA256, REVISION, MODEL,
    CAP, N, DEPENDENCIES, sha, strict_json, load_inputs, assemble_protocol,
    execute_panel, make_requester)
from cvpr_route_score import validate_complete_panel

DATA = BASE/'data'
EXPANSION = DATA/'metadata_expansion_001_002'
SELECTION_SHA256 = '56e5e317c518d56465462f403675f526d18a143bdfad7585ac0f6acf0a6ed8b2'
SELECTION_EVIDENCE = {
    'projection.json': (EXPANSION/'SOURCE_METADATA_PROJECTION.json', '7056d8202f655da6b0f3bd079d50c706377a6cbf2057c57d58502ada5b7599a8'),
    'protocol.json': (EXPANSION/'METADATA_EXPANSION_PROTOCOL.json', 'a6c9f0da2704d647f0a6c8382437889e92c50d1b1b139f7108d80ed68ec88aaf'),
    'prior_receipt.json': (DATA/'METADATA_PROJECTION_RECEIPT.json', '21a02287264093693b07701594217337dfb0abd8e25f9e43b91ad16f71ebfb56'),
    'expansion_receipt.json': (EXPANSION/'METADATA_PROJECTION_RECEIPT.json', '8e6c72e80d75e02ea6caca6977ac94f3a568d660bceae1009ad16da188047da0'),
    'selection_tool.py': (BASE/'tools/safe_metadata_expansion.py', 'b3e4830e3f5886c809912367b72d4ef2fd40735d0b13429b487421b225ee6067')}
SCIENTIFIC_GATES = {'minimum_valid_predictions': 30,
    'minimum_distinct_present_mapping_error_ids': 8,
    'minimum_net_correct_over_strongest_control': 3,
    'baseline_before_method': True, 'ordinary_controls_are_not_novel': True}
ALLOCATION = {'temperature': 0.0, 'enable_thinking': False, 'max_tokens': CAP,
    'max_logical_calls': N, 'max_http_attempts': N*3, 'paid_workers': 1,
    'scientific_gates': SCIENTIFIC_GATES}


def bound_json(spec):
    if set(spec) != {'path','sha256'} or not re.fullmatch('[0-9a-f]{64}', spec['sha256']):
        raise ValueError('Missing bound file descriptor')
    path = Path(spec['path']).resolve()
    raw = path.read_bytes()
    if sha(raw) != spec['sha256']:
        raise ValueError('Bound metadata file changed')
    return strict_json(raw)


def verify_selection(rows, assets, selection_spec):
    if selection_spec['sha256'] != SELECTION_SHA256:
        raise ValueError('Original blind selection changed')
    selection = bound_json(selection_spec)
    evidence = {}
    for name,(path,digest) in SELECTION_EVIDENCE.items():
        raw = path.read_bytes()
        if sha(raw) != digest:
            raise ValueError('Fixed metadata-only selection evidence changed')
        evidence[name] = strict_json(raw) if name.endswith('.json') else raw
    projection = evidence['projection.json']
    allow = {'sample_id','difficulty','query_id','question','source_image_name','source_subfolder','annotated_image_file'}
    if (projection['revision'] != REVISION or set(projection['allowlist']) != allow
            or len(projection['rows']) != 640 or any(set(r) != allow for r in projection['rows'])):
        raise ValueError('Selection projection is not the frozen label-free640 pool')
    # Import our pinned metadata-only tool. Its network main() is not invoked.
    spec = importlib.util.spec_from_file_location('_route_frozen_blind_selection', SELECTION_EVIDENCE['selection_tool.py'][0])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    recomputed,_ = module.blind_select(projection['rows'])
    if (selection['revision'] != REVISION or selection['protocol_sha256'] != SELECTION_EVIDENCE['protocol.json'][1]
            or selection['seed'] != evidence['protocol.json']['sampling_seed']
            or selection['selected'] != recomputed or len(recomputed) != N):
        raise ValueError('Blind components/rank/selected metadata fail recomputation')
    # Recover exact shard-local row coordinates from the pinned projection order.
    locations, offset = {}, 0
    shards = evidence['prior_receipt.json']['shards'] + evidence['expansion_receipt.json']['shards']
    for shard in shards:
        count = shard['projected_rows']
        for index,row in enumerate(projection['rows'][offset:offset+count]):
            locations[row['sample_id']] = (shard['shard'], index)
        offset += count
    if offset != len(projection['rows']) or len(locations) != offset:
        raise ValueError('Projection shard/ID layout inconsistent')
    for row,asset,selected in zip(rows,assets,recomputed,strict=True):
        meta = selected['input_metadata']
        if (row['sample_id'] != meta['sample_id'] or row['question'] != meta['question']
                or row['source_group'] != selected['component_sha256'] or row['query_group'] != meta['query_id']
                or (asset['source_shard'],asset['row_index']) != locations[meta['sample_id']]):
            raise ValueError('Input differs from exact blind-selected metadata or source location')
    if len({row['query_group'] for row in rows}) != N:
        raise ValueError('Distinct32 observed query proxies required')
    return selection


def read_admission(path, expected_sha256):
    raw = Path(path).read_bytes()
    if sha(raw) != expected_sha256:
        raise ValueError('Root admission SHA mismatch')
    admission = strict_json(raw)
    required = {'schema_version','kind','run_id','paid_admission','model','phase_cap_cny',
                'project_cap_cny','inputs','manifest','selection','targets_contract',
                'image_root','source_contract_sha256','allocation'}
    if (set(admission) != required or admission['schema_version'] != 1
            or admission['kind'] != 'route_task2' or admission['paid_admission'] is not True
            or admission['model'] != MODEL or admission['phase_cap_cny'] != 20
            or admission['project_cap_cny'] != 300 or admission['allocation'] != ALLOCATION
            or admission['source_contract_sha256'] != SOURCE_CONTRACT_SHA256
            or not re.fullmatch('[A-Za-z0-9_-]+', admission['run_id'])):
        raise ValueError('Root paid admission absent or allocation differs')
    for name in ('inputs','manifest','selection','targets_contract'):
        bound_json(admission[name])
    rows,manifest,input_sha,manifest_sha = load_inputs(
        admission['inputs']['path'], admission['manifest']['path'], image_root=admission['image_root'])
    if input_sha != admission['inputs']['sha256'] or manifest_sha != admission['manifest']['sha256']:
        raise ValueError('Independent input manifest binding changed')
    if manifest['selection_sha256'] != admission['selection']['sha256']:
        raise ValueError('Manifest blind-selection hash mismatch')
    verify_selection(rows,manifest['image_assets'],admission['selection'])
    # This file contains only paths/hashes/IDs. NEVER hash/open targets_path here.
    targets = bound_json(admission['targets_contract'])
    target_fields = {'schema_version','role','input_sha256','selection_sha256','sample_ids','targets_path','targets_sha256'}
    if (set(targets) != target_fields or targets['schema_version'] != 1
            or targets['role'] != 'selected_development_only'
            or targets['input_sha256'] != input_sha or targets['selection_sha256'] != admission['selection']['sha256']
            or targets['sample_ids'] != manifest['sample_ids']
            or not re.fullmatch('[0-9a-f]{64}', targets['targets_sha256'])
            or Path(targets['targets_path']).resolve() in {Path(admission[k]['path']).resolve() for k in ('inputs','manifest','selection','targets_contract')}):
        raise ValueError('Selected-only target contract missing or changed')
    return admission,rows,manifest,targets


def checked_image(asset):
    """Verify true format and original/payload pixels; never transform at runtime."""
    source_raw = Path(asset['source_image_path']).read_bytes()
    payload = Path(asset['image_path']).read_bytes()
    if sha(source_raw) != asset['source_image_bytes_sha256'] or sha(payload) != asset['image_sha256']:
        raise ValueError('Original or payload image bytes changed')
    mime = {'PNG':'image/png','JPEG':'image/jpeg','WEBP':'image/webp','TIFF':'image/tiff'}

    def decode(raw,expected_mime):
        with Image.open(BytesIO(raw)) as probe:
            if mime.get(probe.format) != expected_mime or getattr(probe,'n_frames',1) != 1:
                raise ValueError('Actual image format/multipage contract mismatch')
            probe.verify()
        with Image.open(BytesIO(raw)) as image:
            image.load()
            if image.size != (asset['width'],asset['height']):
                raise ValueError('Image dimensions changed')
            # A TIFF conversion is container-only for an already RGB source.
            if asset['pixel_transform'] != 'none' and image.mode != 'RGB':
                raise ValueError('Container adaptation requires RGB TIFF and RGB PNG')
            rgb = image.convert('RGB')
            if sha(rgb.tobytes()) != asset['decoded_rgb_sha256']:
                raise ValueError('Decoded RGB pixels changed')
            return rgb.tobytes()

    before = decode(source_raw,asset['source_mime_type'])
    after = decode(payload,asset['mime_type'])
    if before != after:
        raise ValueError('Container adaptation changed RGB pixels')
    if asset['pixel_transform'] == 'none' and source_raw != payload:
        raise ValueError('None-transform original container changed')
    return payload


def protocol_and_bundle(admission_path, admission_sha, admission, rows, manifest):
    protocol = assemble_protocol(manifest, inputs_sha256=admission['inputs']['sha256'],
                                 manifest_sha256=admission['manifest']['sha256'])
    protocol.update(stage='root_admitted_author4shot_baseline', paid_admission=True,
                    run_id=admission['run_id'], admission_sha256=admission_sha,
                    allocation=ALLOCATION, targets_contract_sha256=admission['targets_contract']['sha256'])
    bundle = {'ADMISSION.json': Path(admission_path),
              'INPUTS.json': Path(admission['inputs']['path']),
              'MANIFEST.json': Path(admission['manifest']['path']),
              'TARGETS_CONTRACT.json': Path(admission['targets_contract']['path']),
              'SELECTION.json': Path(admission['selection']['path']),
              'AUTHOR/SOURCE_CONTRACT.json': SOURCE/'SOURCE_CONTRACT.json'}
    bundle.update({'scripts/'+name:ROOT/'scripts'/name for name in DEPENDENCIES})
    bundle.update({'metadata/'+name:path for name,(path,_) in SELECTION_EVIDENCE.items()})
    bundle.update({'AUTHOR/'+item['path']: SOURCE/item['path'] for item in protocol['source_files']})
    protocol['snapshot_sha256'] = {name:sha(path.read_bytes()) for name,path in bundle.items()}
    expected = {'ADMISSION.json':admission_sha,
        'INPUTS.json':admission['inputs']['sha256'], 'MANIFEST.json':admission['manifest']['sha256'],
        'TARGETS_CONTRACT.json':admission['targets_contract']['sha256'],
        'SELECTION.json':admission['selection']['sha256'],
        'AUTHOR/SOURCE_CONTRACT.json':SOURCE_CONTRACT_SHA256}
    expected.update({'scripts/'+name:digest for name,digest in protocol['implementation_sha256'].items()})
    expected.update({'metadata/'+name:digest for name,(_,digest) in SELECTION_EVIDENCE.items()})
    expected.update({'AUTHOR/'+item['path']:item['sha256'] for item in protocol['source_files']})
    if any(protocol['snapshot_sha256'][name] != digest for name,digest in expected.items()):
        raise ValueError('Bound metadata/source changed while assembling protocol')
    return protocol,bundle


def freeze(run, protocol, bundle):
    run = Path(run)
    path = run/'PROTOCOL.json'
    if path.exists():
        if strict_json(path.read_bytes()) != protocol:
            raise ValueError('Immutable protocol changed; no API call allowed')
    else:
        # Materialize every source before declaring a protocol fully frozen.
        if (run/'SOURCE_SNAPSHOTS').exists():
            raise ValueError('Interrupted freeze needs root review; do not overwrite evidence')
        for name,source in bundle.items():
            data = source.read_bytes()
            if sha(data) != protocol['snapshot_sha256'][name]:
                raise ValueError('Source changed during snapshot')
            target = run/'SOURCE_SNAPSHOTS'/name
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(data)
        atomic_json(path,protocol)
    verify_snapshots(run,protocol)


def verify_snapshots(run, protocol):
    for name,digest in protocol['snapshot_sha256'].items():
        if sha((Path(run)/'SOURCE_SNAPSHOTS'/name).read_bytes()) != digest:
            raise ValueError('Frozen snapshot changed')
    for name,digest in protocol['implementation_sha256'].items():
        if sha((ROOT/'scripts'/name).read_bytes()) != digest:
            raise ValueError('Runtime dependency differs from frozen source')


class NoRequests:
    def call(self,**kwargs):
        raise RuntimeError('Completed cache may never issue another request')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id',required=True)
    parser.add_argument('--admission',required=True,type=Path)
    parser.add_argument('--admission-sha256',required=True)
    args = parser.parse_args()
    admission,rows,manifest,_ = read_admission(args.admission,args.admission_sha256)
    if args.run_id != admission['run_id']:
        raise ValueError('CLI run ID differs from root admission')
    run = BASE/'runs'/admission['run_id']
    run.mkdir(parents=True,exist_ok=True)
    with (run/'.run.lock').open('a') as run_lock, (PROJECT/'.api-single-worker.lock').open('a') as worker_lock:
        fcntl.flock(run_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        fcntl.flock(worker_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        protocol,bundle = protocol_and_bundle(args.admission,args.admission_sha256,admission,rows,manifest)
        freeze(run,protocol,bundle)
        calls_path = run/'calls.jsonl'
        calls = [strict_json(line) for line in calls_path.read_text().splitlines()] if calls_path.exists() else []
        predictions_path = run/'PREDICTIONS.json'
        predictions = strict_json(predictions_path.read_bytes()) if predictions_path.exists() else []
        prior_status = strict_json((run/'STATUS.json').read_bytes()) if (run/'STATUS.json').exists() else {}
        started, tick = prior_status.get('started_at',now()),time.monotonic()

        def state(status,preds,receipts,sample=None,error=None):
            value = {'status':status,'kind':'route_task2','mode':protocol['mode'],
                'run_id':admission['run_id'],'pid':os.getpid(),'started_at':started,'updated_at':now(),
                'selected_samples':N,'completed_samples':len(preds),'successful_calls':len(receipts),
                'active_sample':sample,'input_tokens':sum(c.get('input_tokens',0) for c in receipts),
                'output_tokens':sum(c.get('output_tokens',0) for c in receipts),
                'elapsed_seconds_this_session':time.monotonic()-tick,'local_gpu':False}
            if error:value['error']=error
            atomic_json(run/'STATUS.json',value)
            return value

        halt = threading.Event()
        try:
            state('preflight',predictions,calls)
            for asset in manifest['image_assets']:
                checked_image(asset)
            if len(calls) == N and len(predictions) == N:
                validate_complete_panel(predictions,calls,protocol['sample_ids'])
                requester = NoRequests()
            else:
                ledger = strict_json((PROJECT/'API_LEDGER.json').read_bytes())
                unknown = {k:v for k,v in ledger['attempts'].items() if v['status'] != 'settled'}
                if any(Path('/proc/'+str(v['pid'])).exists() for v in unknown.values()):
                    raise RuntimeError('Unresolved attempt belongs to live process')
                prior = {}
                for entry in ledger['attempts'].values():
                    if entry['run_id'] == admission['run_id']:
                        prior[entry['key']] = max(prior.get(entry['key'],0),entry.get('attempt_index',1))
                requester = make_requester(budget=Budget(unknown,retry_own_failures=True),
                    run=run,run_id=admission['run_id'],secret=credential(),halt=halt,prior_attempts=prior)
            assets = {a['sample_id']:a for a in manifest['image_assets']}
            state('running',predictions,calls)
            predictions,calls = execute_panel(rows,manifest,requester=requester,
                image_loader=lambda row:checked_image(assets[row['sample_id']]),run=run,calls=calls,
                on_state=lambda p,c,s:state('running',p,c,s))
            validate_complete_panel(predictions,calls,protocol['sample_ids'])
            print(json.dumps(state('model_completed',predictions,calls)),flush=True)
        except BaseException as exc:
            halt.set()
            predictions = strict_json(predictions_path.read_bytes()) if predictions_path.exists() else []
            calls = [strict_json(line) for line in calls_path.read_text().splitlines()] if calls_path.exists() else []
            state('held',predictions,calls,error=type(exc).__name__)
            raise


if __name__ == '__main__':
    main()
