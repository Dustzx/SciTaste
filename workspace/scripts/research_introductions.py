"""Bounded, source-indexed project explanations; presentation, never execution."""
import json
from pathlib import Path

import progress_board

ROOT = Path(__file__).resolve().parents[1]
from local_research import INTRODUCTIONS as DIRECTORY
ASSETS = ROOT / 'web/assets/research-introductions'
MAPPING = {'revise-opd': 'reviseOPD', 'attn-opd': 'attnOPD',
           'jev-verifier': 'jevVerifier', 'scitaste-self-development': 'SciTaste',
           'fastresearch-cvpr2027': 'FastResearch', 'voa': 'VOA',
           'image-centric-active-vision': 'Image_centric', 'oc-sod': 'OC-SOD',
           'rrmot-cvpr2027': 'RRMOT'}


def validate(payload, project_id, indexed):
    if (not isinstance(payload, dict) or payload.get('schema_version') != 1
            or payload.get('project_id') != project_id
            or payload.get('report_id') != MAPPING.get(project_id)):
        raise ValueError('Project introduction identity mismatch')
    for key in ('motivation', 'idea', 'method', 'contribution', 'evidence', 'diagram'):
        if not isinstance(payload.get(key), dict):
            raise ValueError('Project introduction section is missing')
    def meaningful(value):
        return (isinstance(value, str) and bool(value.strip())) or (
            isinstance(value, list) and bool(value) and all(
                isinstance(item, str) and item.strip() for item in value))
    for key in ('title', 'one_liner', 'reviewed_at'):
        if not isinstance(payload.get(key), str) or not meaningful(payload[key]):
            raise ValueError('Project introduction metadata is missing')
    for section, fields in {
        'motivation': ('problem', 'consequence', 'observation'),
        'idea': ('hypothesis', 'mechanism', 'status', 'why_it_matters', 'not_yet_proven'),
        'method': ('version', 'inputs', 'outputs', 'controls'),
        'contribution': ('claim', 'status', 'conditions', 'falsifier'),
        'evidence': ('supported', 'limitations', 'next_decision'),
    }.items():
        if any(not meaningful(payload[section].get(field)) for field in fields):
            raise ValueError('Project introduction requires complete explanations')
    if not isinstance(payload['contribution']['conditions'], list):
        raise ValueError('Contribution conditions must be explicit items')
    if (payload['diagram'].get('kind') != project_id
            or payload['diagram'].get('scope') != '机制示意，不是新增实测或真实样例'
            or not meaningful(payload['diagram'].get('caption'))):
        raise ValueError('Diagram identity and illustrative scope are required')
    steps, related = payload['method'].get('steps'), payload.get('related_work')
    if (not isinstance(steps, list) or not 3 <= len(steps) <= 6
            or any(not isinstance(s, dict) or not s.get('title') or not s.get('detail') for s in steps)
            or not isinstance(related, list) or not 3 <= len(related) <= 12):
        raise ValueError('Project introduction explanation bounds exceeded')
    for item in related:
        if not isinstance(item, dict) or any(not item.get(k) for k in
                ('name', 'mechanism', 'shared', 'difference', 'comparison_status', 'source_keys')):
            raise ValueError('Related work requires explicit differences and comparison status')
    references = [payload.get('reading_sources'), payload['motivation'].get('source_keys'),
                  *[item['source_keys'] for item in related]]
    if any(not isinstance(keys, list) or not keys or any(
            not isinstance(key, str) for key in keys) for keys in references):
        raise ValueError('Introduction source keys must be explicit lists')
    keys = {key for references_list in references for key in references_list}
    if not keys or any(key not in indexed for key in keys):
        raise ValueError('Introduction source is not explicitly indexed')
    if len(json.dumps(payload, ensure_ascii=False).encode()) > 100_000:
        raise ValueError('Introduction exceeds small presentation payload')
    return payload


def get(project_id):
    if project_id not in MAPPING:
        raise ValueError('Unknown reviewed introduction')
    path = DIRECTORY / (project_id + '.json')
    if not path.is_file():
        return None
    payload = validate(json.loads(path.read_text()), project_id, progress_board.sources())
    payload['diagram'] = {**payload['diagram'],
        'svg_url': ('/assets/research-introductions/' + project_id + '/mechanism.svg')
            if (ASSETS/project_id/'mechanism.svg').is_file() else None,
        'png_url': ('/assets/research-introductions/' + project_id + '/mechanism.png')
            if (ASSETS/project_id/'mechanism.png').is_file() else None}
    # The public exporter does not bundle benchmark or private illustration assets.
    payload['media'] = []
    return payload


def snapshot():
    return dict(schema_version=1, projects=[value for project in MAPPING if (value := get(project)) is not None],
                scope='reviewed_explanations_not_new_experiments')


def signature_paths():
    return [DIRECTORY / (project + '.json') for project in MAPPING]
