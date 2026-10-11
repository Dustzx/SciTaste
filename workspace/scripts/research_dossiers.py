"""Read-only, source-bound research workspaces; no synthetic native runs."""
import json
from pathlib import Path

import progress_board
import research_introductions

ROOT = Path(__file__).resolve().parents[1]
from local_research import PROFILES, SHARED_RACE as RACE
MAPPING = {'revise-opd': 'reviseOPD', 'attn-opd': 'attnOPD',
           'jev-verifier': 'jevVerifier', 'scitaste-self-development': 'SciTaste',
           'fastresearch-cvpr2027': 'FastResearch',
           'image-centric-active-vision': 'Image_centric', 'oc-sod': 'OC-SOD',
           'rrmot-cvpr2027': 'RRMOT', 'voa': 'VOA'}



def shared_race():
    return progress_board.read(RACE, {})


def reviewed_cases(profile, indexed):
    """Load only an explicitly indexed, small presentation payload, never raw datasets."""
    config = profile.get('cases', {})
    key = config.get('source_key')
    if not key:
        return config
    document = progress_board.source_document(key) if key in indexed else None
    if not document:
        raise ValueError('Case source must be an explicitly indexed readable document')
    payload = json.loads(document['content'])
    if (not isinstance(payload, dict) or payload.get('schema_version') != 1 or payload.get('project_id') != profile['project_id']
            or payload.get('report_id') != profile['report_id']):
        raise ValueError('Case source identity mismatch')
    datasets, samples = payload.get('datasets', []), payload.get('samples', [])
    if not isinstance(datasets, list) or not isinstance(samples, list) or len(datasets) > 12 or len(samples) > 24:
        raise ValueError('Case source exceeds presentation bounds')
    for collection in (datasets, samples):
        if any(not isinstance(row, dict) or not isinstance(row.get('id'), str) for row in collection):
            raise ValueError('Case records require explicit identities')
        if len({row['id'] for row in collection}) != len(collection):
            raise ValueError('Duplicate case source identity')
    ids = {row['id'] for row in datasets}
    for sample in samples:
        if sample.get('dataset_id') not in ids:
            raise ValueError('Case dataset is not declared')
        for field in ('inputs', 'annotations'):
            if not isinstance(sample.get(field), list) or any(not isinstance(row, list) or len(row) != 2 for row in sample[field]):
                raise ValueError('Case input/annotation fields must be pairs')
        columns, rows = sample.get('output_columns', []), sample.get('outputs', [])
        if not isinstance(columns, list) or not isinstance(rows, list) or any(not isinstance(row, list) or len(row) != len(columns) for row in rows):
            raise ValueError('Case prediction table shape mismatch')
    return {**config, **payload, 'available': bool(samples), 'source_keys': list(dict.fromkeys([key, *config.get('source_keys', [])]))}


def snapshot():
    progress = progress_board.snapshot()
    reports = {p['id']: p for p in progress['projects']}
    projects = []
    indexed = progress_board.sources()
    for project_id, report_id in MAPPING.items():
        path = PROFILES/(project_id+'.json')
        if not path.is_file() or report_id not in reports:
            continue
        profile = json.loads(path.read_text())
        if profile.get('project_id') != project_id or profile.get('report_id') != report_id:
            raise ValueError('Research dossier identity mismatch')
        profile['cases'] = reviewed_cases(profile, indexed)
        profile['presentation'] = research_introductions.get(project_id)
        for kind in ('methods', 'results'):
            rows = profile.get(kind, [])
            if len({r['id'] for r in rows}) != len(rows):
                raise ValueError('Duplicate research dossier section')
            for row in rows:
                if any(key not in indexed for key in row.get('source_keys', [])):
                    raise ValueError('Research dossier source is not explicitly indexed')
        report = reports[report_id]
        profile.update(
            current=report['brief'].get('current') or profile.get('summary'),
            claim=report['brief'].get('claim'), brief=report['brief'],
            reviewed_at=report.get('reviewed_at'), sources=report['sources'],
            report_changed=report['report_changed'], axis_states=report['axis_states'],
            gap=report.get('gap'), next=report.get('next'),
            native_available=(ROOT/'outputs/projects'/project_id/'PROJECT.json').is_file(),
            projection=progress_board.stamp(path),
            evidence_policy='来源研究的只读审阅投影；历史实验不登记为新原生运行，页面不启动实验。')
        if report_id in {'attnOPD', 'reviseOPD'}:
            profile['shared_race'] = shared_race()
        projects.append(profile)
    return {'schema_version': 1, 'generated_at': progress['generated_at'],
            'projects': projects, 'voa_dedicated_workspace': '#/experiments/voa',
            'verification_policy': progress['verification_policy']}


def signature_paths():
    return [PROFILES/(project+'.json') for project in MAPPING]+[RACE]+research_introductions.signature_paths()
