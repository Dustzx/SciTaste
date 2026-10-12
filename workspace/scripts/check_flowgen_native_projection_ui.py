"""Synthetic native-parsing aggregate projection and desktop/mobile DOM checks."""
import copy
import hashlib
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import progress_board as board
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE = 'http://127.0.0.1:8765'


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def main():
    checks, errors, writes, outbound, reads = [], [], [], [], []

    def check(name, condition):
        assert condition, name
        checks.append(name)

    with tempfile.TemporaryDirectory(prefix='native-projection-check-') as temp:
        root = Path(temp)
        report = root/'report'
        study = root/'outputs/projects/fastresearch-cvpr2027/research'
        runs = study/'diagram/runs'
        run = runs/board.DIAGRAM_RUNS['cvpr_flowgen_native_screen.py']
        unknown = runs/'unknown_future_native'
        for name, value in [('STATUS_BOARD.json', {'projects': [], 'axes': []}),
                            ('sources.json', {'projects': {}}), ('EXPERIENCE_POOL.json', {'entries': []})]:
            write(report/name, value)
        write(study/'PORTFOLIO.json', {'branches': [], 'gates': [], 'cpu_candidates': [{
            'id': 'FR-DIAGRAM', 'current_action': 'Native source preparation only'}]})
        write(study/'API_LEDGER.json', {'cap_cny': 300, 'attempts': {}})
        closed = {'run_ids': list(board.DIAGRAM_RUNS.values())[:-1], 'physical_attempts': 192,
                  'conservative_cny': .4, 'closed': True, 'attempts_sha256': 'SECRET'}
        resources = {'physical_attempts': 8, 'successful_settled': 8, 'run_conservative_cny': .01,
                     'project_conservative_cny': 64.4, 'phase_cny': 20, 'project_cap_cny': 300,
                     'physical_cap': 31, 'retry_unknown_count': 0, 'closed_family': closed,
                     'private_attempts': 'SECRET'}
        protocol = {'kind': board.DIAGRAM_NATIVE_KIND, 'run_id': run.name, 'N': 16, 'model': 'synthetic',
                    'max_logical_calls': 16, 'max_physical_attempts': 31, 'phase_cny': 20,
                    'project_cny': 300, 'request_digests': {'SECRET': True}, 'private': 'SECRET'}
        status = {'kind': board.DIAGRAM_NATIVE_KIND, 'run_id': run.name, 'status': 'running',
                  'completed_calls': 8, 'max_logical_calls': 16, 'pid': 123,
                  'resources': resources, 'updated_at': '2026-10-12T11:00:00+08:00', 'private': 'SECRET'}
        write(run/'PROTOCOL.json', protocol)
        write(run/'STATUS.json', status)
        forbidden = ['NATIVE_PREDICTIONS_FROZEN.json', 'PRIVATE_PREPARED.json', 'calls.jsonl',
                     'ALL_SOLVERS_FROZEN.json', 'TARGETS.json']
        for name in forbidden:
            write(run/name, {'SECRET': True})
        write(unknown/'PROTOCOL.json', {'kind': 'unknown_native_kind'})
        write(unknown/'STATUS.json', {'status': 'running'})
        write(unknown/'SUMMARY.json', {'SECRET': True})
        original_read, original_bytes = board.read, Path.read_bytes

        def guard_path(path):
            path = Path(path)
            if path.is_relative_to(runs):
                reads.append(path.name)
                assert path.name in {'PROTOCOL.json', 'STATUS.json', 'SUMMARY.json', 'ROOT_READOUT_DECISION.json'}
                assert not (path.parent == unknown and path.name == 'SUMMARY.json')

        def guarded_read(path, default=None):
            guard_path(path)
            return original_read(path, default)

        def guarded_bytes(path):
            guard_path(path)
            return original_bytes(path)

        full = {'kind': board.DIAGRAM_NATIVE_KIND, 'run_id': run.name, 'N': 16,
                'status': 'completed_unscored', 'score': None, 'GT_read': False,
                'terminal_status_counts': {'ok': 15, 'truncated': 1, 'refusal': 0, 'error': 0},
                'resources': {**resources, 'physical_attempts': 17, 'successful_settled': 16,
                              'retry_unknown_count': 1, 'run_conservative_cny': .08},
                'new_method': False, 'confirmation_evaluated': False, 'publication_ready': False,
                'predictions_sha256': 'SECRET', 'evidence_sha256': {'PRIVATE': 'SECRET'}}
        review = {'owner': 'root', 'kind': board.DIAGRAM_NATIVE_KIND, 'run_id': run.name,
                  'status': 'complete_root_audited', 'N': 16,
                  'official_macro': {'precision': .7, 'recall': .6, 'f1_score': .65, 'answers': 'SECRET'},
                  'invalid': 1, 'engineering_valid': True,
                  'headroom_gate': {'valid_predictions': 15, 'minimum_valid': 15, 'saturated': False,
                      'semantic_loss_fullN': .3, 'valid_images_f1_le_0_90': 8,
                      'passes_development_headroom': True, 'action': 'source_method_preparation_only',
                      'automatic_paid_expansion': False, 'PRIVATE': 'SECRET'},
                  'evidence_sha256': {'SUMMARY.json': ''}, 'private_mappings': 'SECRET'}
        with patch.object(board, 'ROOT', root), patch.object(board, 'REPORT', report), \
             patch.object(board, 'read', guarded_read), patch.object(Path, 'read_bytes', guarded_bytes), \
             patch.object(board, 'alive', lambda pid, identity: identity == run.name):
            pending = board.snapshot()
            observed = pending['experiments'][0]
            check('native pending8/16 live no scores or QA arms', len(pending['experiments']) == 1
                  and observed['live'] and observed['completed'] == 8 and observed['planned'] == 16
                  and observed['summary'] is None and observed['arms'] == [])
            check('native attempts are STATUS-only not absent ledger0', observed['requests']['attempts'] == 8
                  and observed['actual_calls'] == 8 and observed['resources']['closed_family']['closed'])
            check('candidate remains CPU-only no formal branch', not pending['portfolio']['branches']
                  and pending['diagram_candidate']['current_run'] == run.name)
            check('safe protocol excludes prepared and request bindings',
                  'SECRET' not in board.source_document('run.'+run.name+'.protocol')['content'])
            for name in forbidden:
                with patch.object(board, 'sources', lambda name=name: {'bad': run/name}):
                    check('private native endpoint denied '+name, board.source_document('bad') is None)
            for label, mutate in [
                ('partial15', lambda v: v['terminal_status_counts'].update(ok=14)),
                ('fewerreceipts', lambda v: v['resources'].update(successful_settled=15)),
                ('overphysicalcap', lambda v: v['resources'].update(physical_attempts=32)),
                ('scoredstatus', lambda v: v.update(status='complete')),
                ('inventedscore', lambda v: v.update(score=.8)),
                ('GTflag', lambda v: v.update(GT_read=True)),
                ('readyflag', lambda v: v.update(publication_ready=True)),
                ('familyreopened', lambda v: v['resources']['closed_family'].update(closed=False)),
                ('wrongphasecap', lambda v: v['resources'].update(phase_cny=40)),
                ('nonfinitecost', lambda v: v['resources'].update(run_conservative_cny=float('inf'))),
                ('overphasecost', lambda v: v['resources'].update(run_conservative_cny=21)),
                ('overprojectcost', lambda v: v['resources'].update(project_conservative_cny=301)),
                ('unknowncountdrift', lambda v: v['resources'].update(retry_unknown_count=2)),
                ('wrongidentity', lambda v: v.update(run_id='other'))]:
                bad = copy.deepcopy(full)
                mutate(bad)
                write(run/'SUMMARY.json', bad)
                check('malformed native summary withheld '+label, board.diagram_summary(run) is None)
            write(run/'SUMMARY.json', full)
            unscored = board.diagram_summary(run)
            check('full16 remains unscored with no fabricated official metric', unscored['status'] == 'completed_unscored'
                  and unscored['score'] is None and 'root_readout_decision' not in unscored
                  and 'accuracy' not in json.dumps(unscored))
            review['evidence_sha256']['SUMMARY.json'] = hashlib.sha256((run/'SUMMARY.json').read_bytes()).hexdigest()
            write(run/'ROOT_READOUT_DECISION.json', review)
            safe = board.diagram_summary(run)
            check('bound root continuous macro metrics separate from SUMMARY score', safe['score'] is None
                  and safe['status'] == 'completed_unscored'
                  and safe['root_readout_decision']['official_macro']['f1_score'] == .65
                  and 'SECRET' not in json.dumps(safe))
            for label, mutate in [
                ('wrongowner', lambda v: v.update(owner='other')),
                ('wrongrun', lambda v: v.update(run_id='other')),
                ('wrongkind', lambda v: v.update(kind=board.DIAGRAM_SCREEN_KIND)),
                ('partialN', lambda v: v.update(N=15)),
                ('wrongstatus', lambda v: v.update(status='complete')),
                ('summarydrift', lambda v: v['evidence_sha256'].update({'SUMMARY.json': '0'*64})),
                ('nanmacro', lambda v: v['official_macro'].update(f1_score=float('nan'))),
                ('outofrange', lambda v: v['official_macro'].update(precision=1.1)),
                ('boolmacro', lambda v: v['official_macro'].update(recall=True)),
                ('invalidbounds', lambda v: v.update(invalid=17)),
                ('engineeringcontradiction', lambda v: v.update(engineering_valid=False)),
                ('validcountcontradiction', lambda v: v['headroom_gate'].update(valid_predictions=16)),
                ('gatecontradiction', lambda v: v['headroom_gate'].update(passes_development_headroom=False)),
                ('autoexpand', lambda v: v['headroom_gate'].update(automatic_paid_expansion=True)),
                ('saturationcontradiction', lambda v: v['headroom_gate'].update(saturated=True)),
                ('lowf1countbounds', lambda v: v['headroom_gate'].update(valid_images_f1_le_0_90=16))]:
                bad = copy.deepcopy(review)
                mutate(bad)
                write(run/'ROOT_READOUT_DECISION.json', bad)
                check('stale or inconsistent root withheld '+label,
                      'root_readout_decision' not in board.diagram_summary(run))
            write(run/'ROOT_READOUT_DECISION.json', review)
            status.update(status='completed_unscored', completed_calls=16, resources=full['resources'])
            write(run/'STATUS.json', status)
            complete = board.snapshot()
            final = complete['experiments'][0]
            check('completed source permanently unscored not live root separately audited',
                  final['status'] == 'completed_unscored' and not final['live']
                  and final['summary']['root_readout_decision']['status'] == 'complete_root_audited'
                  and final['requests']['attempts'] == 17 and final['requests']['successful'] == 16
                  and final['requests']['unsettled'] == 1)
            check('safe source endpoint binds root without private evidence exposure',
                  'SECRET' not in board.source_document('run.'+run.name+'.root_readout')['content'])
            write(run/'ROOT_READOUT_DECISION.json', {})
            awaiting = board.snapshot()
        with patch.object(Path, 'read_bytes', lambda path: b'python\0/scripts/cvpr_flowgen_native_screen.py\0--operation\0run\0'
                          if str(path) == '/proc/123/cmdline' else original_bytes(path)):
            check('native fixed worker matches exact identity', board.alive(123, run.name))
            check('native worker cannot mark tools live', not board.alive(123, board.DIAGRAM_RUNS['cvpr_textflow_tools_control.py']))
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 1100})
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: writes.append(request.url) if request.method != 'GET' else None)
            page.on('request', lambda request: outbound.append(request.url) if not request.url.startswith(BASE) else None)
            document = [pending]
            page.route('**/api/progress', lambda route: route.fulfill(json=document[0]))
            page.route('**/assets/training-free-evidence.js*', lambda route: route.fulfill(
                path=ROOT/'web/assets/training-free-evidence.js', content_type='application/javascript'))
            url = BASE+'/#/experiments/fastresearch-cvpr2027?origin=fastresearch&view=results&branch=FR-DIAGRAM&run='+run.name
            page.goto(url)
            expect(page.locator('[data-tf-native-pending]')).to_be_visible()
            check('pending DOM8/16 no partial native metric or QA accuracy',
                  '8 / 16' in page.locator('.tf-run').inner_text() and page.locator('[data-tf-native-metrics]').count() == 0
                  and page.locator('[data-tf-arm]').count() == 0)
            document[0] = awaiting
            page.reload()
            expect(page.locator('[data-tf-native-unscored]')).to_be_visible()
            check('completed-unscored DOM explicit no fabricated scores',
                  'completed_unscored' in page.locator('[data-tf-native-completed]').inner_text()
                  and page.locator('[data-tf-native-metrics]').count() == 0)
            document[0] = complete
            page.reload()
            expect(page.locator('[data-tf-native-metrics]')).to_be_visible()
            check('native bottom readout has reviewed state not source pending text',
                  '根审阅的官方逐图macro P/R/F1已绑定' in page.locator('.tf-finding').inner_text()
                  and '预测完成·源记录未评分' in page.locator('.tf-run').inner_text()
                  and '尚未根审评分' not in page.locator('.tf-run').inner_text())
            check('reviewed DOM full16 macro0.65 without QA accuracy',
                  '0.65' in page.locator('[data-tf-native-metrics]').inner_text()
                  and '连续指标，不是QA正确率' in page.locator('[data-tf-native-metrics]').inner_text()
                  and '准确率' not in page.locator('[data-tf-native-metrics]').inner_text())
            check('reviewed DOM old family20/31 caps distinct original gate preserved',
                  '192 次' in page.locator('[data-tf-native-pipeline]').inner_text()
                  and '/ 31' in page.locator('[data-tf-native-pipeline]').inner_text()
                  and '原custom QA失败门保持' in page.locator('[data-tf-native-gate]').inner_text()
                  and '仅允许来源/方法准备' in page.locator('[data-tf-native-gate]').inner_text())
            page.set_viewport_size({'width': 390, 'height': 844})
            page.reload()
            expect(page.locator('[data-tf-native-metrics]')).to_be_visible()
            check('mobile native results no horizontal document overflow',
                  page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'))
            browser.close()
        check('browser zero writes outbound errors', not errors and not writes and not outbound)
        check('all run source reads limited to four safe basenames',
              set(reads) <= {'PROTOCOL.json', 'STATUS.json', 'SUMMARY.json', 'ROOT_READOUT_DECISION.json'})
    receipt = {'status': 'passed', 'N_checks': len(checks), 'checks': checks,
               'real_model_API_calls': 0, 'real_native_data_GT_predictions_raw_read': 0,
               'scope': 'Synthetic pending/full16-unscored/hash-bound-root projections and desktop/mobile DOM only.',
               'source_sha256': {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in
                   ('scripts/progress_board.py', 'web/assets/training-free-evidence.js',
                    'scripts/check_flowgen_native_projection_ui.py')}}
    out = ROOT/'reports/flowgen_native_projection_ui_validation.json'
    out.write_text(json.dumps(receipt, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
