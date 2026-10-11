"""Optional local presentation paths; importing never reads project records."""
import os
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
