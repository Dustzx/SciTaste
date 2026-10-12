"""Incremental synthetic tools/review safe projections and browser checks."""
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
    checks = []

    def check(name, condition):
        assert condition, name
        checks.append(name)

    with tempfile.TemporaryDirectory(prefix='tools-projection-check-') as temp:
        root = Path(temp)
        report = root / 'report'
        study = root / 'outputs/projects/fastresearch-cvpr2027/research'
        runs = study / 'diagram/runs'
        tools_run = runs / board.DIAGRAM_RUNS['cvpr_textflow_tools_control.py']
        unknown = runs / 'unknown_future_kind'
        for name, value in [('STATUS_BOARD.json', {'projects': [], 'axes': []}),
                            ('sources.json', {'projects': {}}), ('EXPERIENCE_POOL.json', {'entries': []})]:
            write(report / name, value)
        write(study / 'PORTFOLIO.json', {'branches': [], 'gates': [], 'cpu_candidates': [{
            'id': 'FR-DIAGRAM', 'name': 'Synthetic diagram candidate', 'current_action': 'Tools implementation only',
            'next_action': 'Stale uniform preparation'}]})
        protocol = {'kind': board.DIAGRAM_TOOLS_KIND, 'run_id': tools_run.name, 'N': 16,
                    'model': 'synthetic', 'arms': ['safe_tools', 'matched_review'], 'max_logical_calls': 48,
                    'family_prior_physical_attempts': 144, 'family_max_physical_attempts': 192,
                    'max_new_physical_attempts': 48, 'cpu_batch_deadline_seconds': 2,
                    'request_digests': {'SECRET_ID': 'SECRET'}, 'data_sha256': {'TARGETS': 'SECRET'},
                    'private_inputs': 'SECRET'}
        resources = {'physical_attempts': 8, 'successful_settled': 8, 'family_physical_attempts': 152,
                     'run_conservative_cny': .02, 'family_conservative_cny': .32,
                     'project_conservative_cny': 64.32, 'private_tool_results': 'SECRET'}
        status = {'kind': board.DIAGRAM_TOOLS_KIND, 'run_id': tools_run.name, 'status': 'running', 'pid': 123,
                  'completed_calls': 8, 'completed_solver_slots': 6, 'max_solver_slots': 32,
                  'max_logical_calls': 48, 'updated_at': '2026-10-12T14:00:00+08:00',
                  'resources': resources, 'tool_observations': 'SECRET'}
        write(tools_run / 'PROTOCOL.json', protocol)
        write(tools_run / 'STATUS.json', status)
        for name in ['PRIVATE_PREPARED.json', 'CPU_TOOLS.json', 'calls.jsonl', 'ALL_SOLVERS_FROZEN.json']:
            write(tools_run / name, {'SECRET': True})
        write(unknown / 'PROTOCOL.json', {'kind': 'future_not_allowlisted'})
        write(unknown / 'STATUS.json', {'status': 'running'})
        write(unknown / 'SUMMARY.json', {'SECRET': True})
        write(study / 'API_LEDGER.json', {'cap_cny': 300, 'attempts': {}})
        raw_read = board.read
        reads = []

        def guarded_read(path, default=None):
            path = Path(path)
            if path.is_relative_to(runs):
                reads.append(path)
                assert path.name in {'PROTOCOL.json', 'STATUS.json', 'SUMMARY.json', 'ROOT_READOUT_DECISION.json'}
                assert not (path.parent == unknown and path.name == 'SUMMARY.json')
            return raw_read(path, default)

        references = {arm: {'N': 16, 'correct': n, 'invalid': inv, 'answers': 'SECRET'}
                      for arm, n, inv in zip(board.DIAGRAM_ARMS, (7, 7, 10, 2, 14), (0, 0, 0, 3, 0))}
        full = {'kind': board.DIAGRAM_TOOLS_KIND, 'run_id': tools_run.name, 'status': 'complete', 'N': 16,
                'arms': {'safe_tools': {'N': 16, 'correct': 9, 'invalid': 1, 'tool_answer': 'SECRET'},
                         'matched_review': {'N': 16, 'correct': 8, 'invalid': 0}},
                'reference_arms': references, 'reused_uniform_first_calls': 16,
                'engineering_valid_each': {'safe_tools': True, 'matched_review': True},
                'oracle_minus_strongest_deployable': 4,
                'paired': {name: {'N': 16, 'wins': wins, 'losses': losses, 'net': wins-losses,
                                  'sample_ids': ['SECRET_ID']}
                           for name, wins, losses in [('safe_tools_vs_direct', 3, 1),
                              ('safe_tools_vs_highJSON', 2, 3), ('matched_review_vs_direct', 2, 1),
                              ('matched_review_vs_highJSON', 1, 3), ('safe_tools_vs_matched_review', 2, 1)]},
                'tool_terminal_kind_counts': {'text_first': 12, 'tool_final': 3, 'invalid_first': 1, 'invalid_CPU': 0},
                'resources': {**resources, 'physical_attempts': 35, 'successful_settled': 35,
                              'family_physical_attempts': 179, 'run_conservative_cny': .07,
                              'family_conservative_cny': .37, 'project_conservative_cny': 64.37},
                'new_method': False, 'confirmation_evaluated': False, 'publication_ready': False,
                'private_outputs': 'SECRET'}
        with patch.object(board, 'ROOT', root), patch.object(board, 'REPORT', report), \
             patch.object(board, 'read', guarded_read), patch.object(board, 'alive', lambda pid, run_id: run_id == tools_run.name):
            pending = board.snapshot()
            run = next(x for x in pending['experiments'] if x['name'] == tools_run.name)
            check('pending8newof48 and6of32 slots two unscored arms', run['completed'] == 8
                  and run['planned'] == 48 and run['completed_solver_slots'] == 6 and run['max_solver_slots'] == 32
                  and run['live'] and run['summary'] is None and len(run['arms']) == 2
                  and all(x['score'] is None for x in run['arms']))
            check('borrowed uniform16 distinct from new calls and old direct', run['reused_uniform_first_calls'] == 16
                  and run['reused_direct_records'] == 0 and '实际调用/token不同' in run['protocol'])
            check('unknown kind excluded and current candidate not formal branch', len(pending['experiments']) == 1
                  and pending['diagram_candidate']['next_action'] == 'Tools implementation only'
                  and not pending['portfolio']['branches'])
            safe_proto = board.source_document('run.' + tools_run.name + '.protocol')
            check('protocol endpoint allowlist without request or data hashes', safe_proto['projection'] == 'aggregate_allowlist'
                  and 'SECRET' not in safe_proto['content'] and 'data_sha256' not in safe_proto['content']
                  and json.loads(safe_proto['content'])['arms'] == ['safe_tools', 'matched_review'])
            check('status endpoint retains actual terminal progress and safe resources',
                  json.loads(board.source_document('run.' + tools_run.name + '.status')['content'])['completed_solver_slots'] == 6
                  and run['resources']['family_physical_attempts'] == 152 and 'SECRET' not in json.dumps(pending))
            for name in ['PRIVATE_PREPARED.json', 'CPU_TOOLS.json', 'calls.jsonl', 'ALL_SOLVERS_FROZEN.json']:
                with patch.object(board, 'sources', lambda name=name: {'bad': tools_run/name}):
                    check('explicit private endpoint denied ' + name, board.source_document('bad') is None)
            mutations = [
                ('N15', lambda v: v.update(N=15)),
                ('armN15', lambda v: v['arms']['safe_tools'].update(N=15)),
                ('missingarm', lambda v: v['arms'].pop('matched_review')),
                ('referenceN15', lambda v: v['reference_arms']['gold_diagnostic'].update(N=15)),
                ('missingreference', lambda v: v['reference_arms'].pop('textflow_mermaid')),
                ('badpairN', lambda v: v['paired']['safe_tools_vs_direct'].update(N=15)),
                ('badpairnet', lambda v: v['paired']['safe_tools_vs_direct'].update(net=4)),
                ('pairmetricdisagrees', lambda v: v['paired']['safe_tools_vs_direct'].update(wins=4, net=3)),
                ('missingpair', lambda v: v['paired'].pop('safe_tools_vs_matched_review')),
                ('terminalsum15', lambda v: v['tool_terminal_kind_counts'].update(text_first=11)),
                ('unknownterminal', lambda v: v['tool_terminal_kind_counts'].update(private_kind=0)),
                ('invalidterminalexceedsinvalid', lambda v: v['tool_terminal_kind_counts'].update(text_first=11, invalid_first=2)),
                ('borrowed15', lambda v: v.update(reused_uniform_first_calls=15)),
                ('engineeringwrong', lambda v: v['engineering_valid_each'].update(safe_tools=False)),
                ('missingfinalreceipt', lambda v: v['resources'].update(successful_settled=34)),
                ('familydrift', lambda v: v['resources'].update(family_physical_attempts=178)),
                ('overbudget', lambda v: v['resources'].update(physical_attempts=49, family_physical_attempts=193)),
                ('oraclewrong', lambda v: v.update(oracle_minus_strongest_deployable=5)),
                ('blocked', lambda v: v['resources'].update(blocking_unresolved=1)),
                ('kindmismatch', lambda v: v.update(kind=board.DIAGRAM_UNIFORM_KIND))]
            for name, mutate in mutations:
                bad = copy.deepcopy(full)
                mutate(bad)
                write(tools_run/'SUMMARY.json', bad)
                check('incomplete or inconsistent scores withheld ' + name, board.diagram_summary(tools_run) is None)
            write(tools_run/'SUMMARY.json', full)
            write(tools_run/'ROOT_READOUT_DECISION.json', {
                'decision': 'Synthetic complete pair preserve old gate', 'supported': ['Full pair only'],
                'unknown': ['Mechanism unproved'], 'next_action': {'safe_tools': 'No automatic expansion',
                    'new_method_proposal_or_expansion_authorized_by_this_readout': False, 'tool_raw': 'SECRET'},
                'source_data': 'SECRET'})
            safe = board.diagram_summary(tools_run)
            check('full32 terminal scores five reference arms five full pairs', safe['terminal_solver_slots'] == 32
                  and len(safe['arms']) == 2 and len(safe['reference_arms']) == 5 and len(safe['paired']) == 5)
            check('tool earlystop and invalid counts safe no outputs leak', safe['tool_terminal_kind_counts']['text_first'] == 12
                  and safe['tool_terminal_kind_counts']['invalid_first'] == 1
                  and 'SECRET' not in json.dumps(safe) and safe['reused_uniform_first_calls'] == 16)
            check('historical full score does not overwrite running source state',
                  board.diagram_experiment(tools_run, status, protocol)['status'] == 'running')
            status.update(status='completed_scored', completed_calls=35, completed_solver_slots=32, resources=full['resources'])
            write(tools_run/'STATUS.json', status)
            complete = board.snapshot()
            complete_run = next(x for x in complete['experiments'] if x['name'] == tools_run.name)
            check('completed source not live and actual35 not invented48', not complete_run['live']
                  and complete_run['completed'] == 35 and complete_run['planned'] == 48
                  and complete_run['resources']['run_conservative_cny'] == .07
                  and complete_run['resources']['family_conservative_cny'] == .37)
        original_bytes = Path.read_bytes

        def process_bytes(path):
            return b'python\0/scripts/cvpr_textflow_tools_control.py\0--operation\0run\0' if str(path) == '/proc/123/cmdline' else original_bytes(path)

        with patch.object(Path, 'read_bytes', process_bytes):
            check('exact tools worker basename and run identity', board.alive(123, tools_run.name))
            check('tools worker cannot mark uniform run live', not board.alive(123, board.DIAGRAM_RUNS['cvpr_textflow_solver_control.py']))
        errors, writes, outbound = [], [], []
        with sync_playwright() as engine:
            browser = engine.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 1100})
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: writes.append(request.url) if request.method != 'GET' else None)
            page.on('request', lambda request: outbound.append(request.url) if not request.url.startswith(BASE) else None)
            projected = [pending]
            page.route('**/api/progress', lambda route: route.fulfill(json=projected[0]))
            page.route('**/assets/training-free-evidence.js*', lambda route: route.fulfill(
                path=ROOT/'web/assets/training-free-evidence.js', content_type='application/javascript'))
            url = BASE+'/#/experiments/fastresearch-cvpr2027?origin=fastresearch&view=results&branch=FR-DIAGRAM&run='+tools_run.name
            page.goto(url)
            expect(page.locator('[data-tf-diagram-pending]')).to_be_visible()
            check('pending DOM actual8/48 and6/32 no partial score',
                  '8 / 48' in page.locator('.tf-run').inner_text()
                  and '6 / 32' in page.locator('[data-tf-diagram-pipeline]').inner_text()
                  and page.locator('[data-tf-arm]').count() == 0
                  and '匹配review首答16仅引用' in page.locator('.tf-run').inner_text())
            projected[0] = complete
            page.reload()
            expect(page.locator('[data-tf-diagram-results]')).to_be_visible()
            check('complete DOM two arms five references and five paired results',
                  page.locator('[data-tf-arm]').count() == 2 and page.locator('[data-tf-reference-arm]').count() == 5
                  and page.locator('[data-tf-diagram-paired] tbody tr').count() == 5)
            check('DOM four terminal kinds earlystop and actual compute caveat',
                  '首答文本直接结束 12' in page.locator('[data-tf-tool-terminal-kinds]').inner_text()
                  and 'CPU批次无效 0' in page.locator('[data-tf-tool-terminal-kinds]').inner_text()
                  and '实际调用、tokens或费用相等' in page.locator('[data-tf-tool-terminal-kinds]').inner_text())
            check('DOM separate actual costs and family budget no rebilling anchors',
                  '35 / 48' in page.locator('.tf-run').inner_text()
                  and '179 / 192' in page.locator('[data-tf-tools-resources]').inner_text()
                  and '¥0.07' in page.locator('[data-tf-tools-resources]').inner_text()
                  and '¥0.37' in page.locator('[data-tf-tools-resources]').inner_text()
                  and '引用统一solver首答16条' in page.locator('[data-tf-diagram-pipeline]').inner_text())
            check('DOM original failed gate retained root no scientific promotion',
                  '原五臂失败门保持' in page.locator('[data-tf-diagram-gate]').inner_text()
                  and '未授权' in page.locator('[data-tf-diagram-root-next]').inner_text()
                  and 'SECRET' not in page.locator('.tf-run').inner_text())
            page.set_viewport_size({'width': 390, 'height': 844})
            page.reload()
            expect(page.locator('[data-tf-tool-terminal-kinds]')).to_be_visible()
            check('mobile tools results stay within document', page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'))
            browser.close()
        check('browser zero writes outbound or page errors', not errors and not writes and not outbound)
        check('all diagram reads allowlisted only', all(x.name in {'PROTOCOL.json', 'STATUS.json', 'SUMMARY.json', 'ROOT_READOUT_DECISION.json'} for x in reads))
    receipt = {'status': 'passed', 'N_checks': len(checks), 'checks': checks,
               'real_model_api_calls': 0, 'real_data_GT_images_outputs_read': 0,
               'scope': 'Incremental safe-tools/matched-review synthetic projection and DOM checks only; no old suites rerun.',
               'source_sha256': {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in
                   ['scripts/progress_board.py', 'web/assets/training-free-evidence.js', 'scripts/check_textflow_tools_projection_ui.py']}}
    output = ROOT/'reports/textflow_tools_ui_validation.json'
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
