"""Optional local presentation paths; importing never reads project records."""
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def configured_path(name, fallback):
    value = os.environ.get(name)
    return Path(value).expanduser().resolve() if value else Path(fallback).resolve()

PROFILES = configured_path('SCITASTE_RESEARCH_PROFILES_ROOT', ROOT/'data/research_profiles')
INTRODUCTIONS = configured_path(
    'SCITASTE_RESEARCH_INTRODUCTIONS_ROOT', ROOT/'data/research_introductions'
)
SHARED_RACE = configured_path('SCITASTE_SHARED_RACE_PATH', ROOT/'report/SHARED_RACE.json')


def project_mapping():
    """Discover explicit local identities without publishing an owner's project list."""
    mapping = {}
    for path in sorted(PROFILES.glob('*.json')):
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,100}', path.stem):
            continue
        if path.is_symlink() or path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError('Local project profile exceeds presentation boundaries')
        profile = json.loads(path.read_text())
        if (not isinstance(profile, dict) or profile.get('project_id') != path.stem
                or not isinstance(profile.get('report_id'), str) or not profile['report_id'].strip()):
            raise ValueError('Local project profile identity mismatch')
        mapping[path.stem] = profile['report_id']
    return mapping
