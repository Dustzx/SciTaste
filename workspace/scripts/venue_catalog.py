"""Read the local submission catalogue without network access or research calls."""
import hashlib
import json
from pathlib import Path

CATALOGUE = Path(__file__).resolve().parents[1] / "data/submission_venues.json"


def snapshot():
    raw = CATALOGUE.read_bytes()
    data = json.loads(raw)
    if data.get("schema_version") != 1 or not isinstance(data.get("venues"), list):
        raise ValueError("Unsupported submission catalogue")
    venues = data["venues"]
    if (len({v["id"] for v in venues}) != len(venues)
            or any(v["rank"] not in {"A", "B"} or v["kind"] not in {"conference", "journal"} for v in venues)):
        raise ValueError("Invalid submission catalogue entries")
    return data, '"' + hashlib.sha256(raw).hexdigest() + '"'
