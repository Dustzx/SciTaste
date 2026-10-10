#!/usr/bin/env python3
"""Refresh a source-bound CCF A/B submission catalogue; never starts research."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import tarfile
import urllib.request
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).resolve().parents[1]
REPO = "ccfddl/ccf-deadlines"
CATEGORIES = dict(zip(
    ["DS", "NW", "SC", "SE", "DB", "CT", "CG", "AI", "HI", "MX"],
    ["体系结构、并行与存储", "计算机网络", "网络与信息安全", "软件工程与程序设计", "数据库、挖掘与检索",
     "计算机科学理论", "图形学与多媒体", "人工智能", "人机交互与普适计算", "交叉、综合与新兴"]))


def get(url):
    request = urllib.request.Request(url, headers={"User-Agent": "SciTaste-VenueSync/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read(25 * 1024 * 1024 + 1)


def deadline(value, zone):
    """Keep unpublished/unsupported dates null, and preserve original strings."""
    raw = str(value) if value is not None else "TBD"
    result = {"raw": raw, "timezone": zone, "utc": None}
    if raw.upper() in {"TBD", "TBA", "NONE", "NULL", ""}:
        return result
    try:
        moment = datetime.fromisoformat(raw)
        if moment.tzinfo is None:
            if zone in {"AoE", "AOE"}:
                tz = timezone(timedelta(hours=-12))
            elif zone == "PT":
                tz = ZoneInfo("America/Los_Angeles")
            elif zone == "UTC":
                tz = timezone.utc
            elif re.fullmatch(r"UTC[+-]\d{1,2}(?::\d{2})?", str(zone)):
                match = re.fullmatch(r"UTC([+-])(\d{1,2})(?::(\d{2}))?", zone)
                offset = timedelta(hours=int(match[2]), minutes=int(match[3] or 0))
                tz = timezone(offset if match[1] == "+" else -offset)
            else:
                result["parse_issue"] = "Unknown source timezone"
                return result
            moment = moment.replace(tzinfo=tz)
        result["utc"] = moment.astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError, OverflowError):
        result["parse_issue"] = "Unparsed source deadline"
    return result


def catalogue(source, commit):
    venues = []
    receipts = []
    for file in sorted((source / "conference").rglob("*.yml")):
        relative = file.relative_to(source).as_posix()
        raw = file.read_bytes()
        receipts.append({"path": relative, "sha256": hashlib.sha256(raw).hexdigest()})
        for entry in yaml.safe_load(raw) or []:
            rank = (entry.get("rank") or {}).get("ccf")
            if rank not in {"A", "B"}:
                continue
            category = entry["sub"]
            assert category in CATEGORIES
            identity = re.sub(r"[^a-z0-9]+", "-", entry["title"].lower()).strip("-")
            venue = {"id": f"conference-{category}-{identity}", "kind": "conference", "rank": rank,
                     "abbreviation": entry["title"], "name": entry.get("description", entry["title"]),
                     "categories": [category], "source_kind": "ccfddl", "source_path": relative,
                     "source_url": f"https://github.com/{REPO}/blob/{commit}/{relative}", "editions": []}
            for conf in entry.get("confs", []):
                zone = conf.get("timezone")
                rounds = []
                for item in conf.get("timeline", []):
                    rounds.append({"comment": item.get("comment", ""),
                                   **{key: deadline(item[key], zone) for key in
                                      ["deadline", "abstract_deadline", "rebuttal_deadline", "decision_deadline", "opening"]
                                      if key in item}})
                venue["editions"].append({"year": conf["year"], "id": conf["id"], "url": conf.get("link"),
                                          "timezone": zone, "meeting_date": conf.get("date"),
                                          "place": conf.get("place"), "rounds": rounds})
            venues.append(venue)
    journal_data = json.loads((ROOT / "data/journal_catalog_2026.json").read_text())
    journals = {}
    for row in journal_data["journals"]:
        key = (row["name"].casefold(), row["rank"])
        reference = {"category": row["category"], "page": row["source_page"],
                     "row": row["source_row"], "url": row["source_url"], "directory_url": row["directory_url"]}
        if key not in journals:
            digest = hashlib.sha256((key[0] + key[1]).encode()).hexdigest()[:12]
            journals[key] = {"id": "journal-" + digest, "kind": "journal", "rank": row["rank"],
                             "abbreviation": row["abbreviation"], "name": row["name"], "publisher": row["publisher"],
                             "categories": [], "source_kind": row["source_kind"], "source_url": row["source_url"],
                             "directory_url": row["directory_url"], "submission_url": None, "editions": [],
                             "references": []}
        journals[key]["categories"].append(row["category"])
        journals[key]["references"].append(reference)
    venues.extend(journals.values())
    assert len({v["id"] for v in venues}) == len(venues), "Duplicate venue IDs"
    assert all(v["rank"] in {"A", "B"} for v in venues)
    counts = Counter(v["kind"] + "_" + v["rank"] for v in venues)
    return {"schema_version": 1, "synced_at": datetime.now().astimezone().isoformat(),
            "categories": CATEGORIES, "counts": dict(counts), "venues": venues,
            "sources": {"conferences": {"name": "CCF-DDL", "url": "https://ccfddl.com", "repo": REPO,
                                         "commit": commit, "files": receipts,
                                         "notice": "社区维护截稿记录；时区及未注明时间可能使用上游约定，投稿前需核会议官网。未公布不推算。"},
                        "journals": {key: value for key, value in journal_data.items() if key != "journals"}},
            "policies": {"journal_dates": "未核期刊征稿/常规投稿日期；目录资料链接不等于投稿系统。",
                         "rank": "会议等级来自对应 CCF-DDL 快照；期刊等级来自 CCF 2026 PDF 镜像。",
                         "refresh": "网页只读取本地快照；运行 sync_venues.py --refresh 更新会议来源，不调用模型或启动实验。"}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--source", type=Path, default=ROOT / "cache/venue_sources/ccfddl")
    parser.add_argument("--commit")
    args = parser.parse_args()
    source = args.source
    commit = args.commit
    if args.refresh:
        meta = json.loads(get(f"https://api.github.com/repos/{REPO}/commits/main"))
        commit = meta["sha"]
        archive = get(f"https://codeload.github.com/{REPO}/tar.gz/{commit}")
        if len(archive) > 25 * 1024 * 1024:
            raise ValueError("Source archive exceeds bounded download size")
        source = ROOT / "cache/venue_sources" / commit
        with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
            for member in bundle.getmembers():
                path = Path(*Path(member.name).parts[1:])
                if not member.isfile() or ".." in path.parts:
                    continue
                if path.parts[0:1] == ("conference",) and path.suffix in {".yml", ".yaml"}:
                    target = source / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(bundle.extractfile(member).read())
    if not commit or not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ValueError("Supply the exact source commit, or --refresh")
    assert (source / "conference").is_dir(), "Missing source conference directory"
    data = catalogue(source, commit)
    target = ROOT / "data/submission_venues.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(target)
    print(json.dumps({"venues": len(data["venues"]), "counts": data["counts"], "commit": commit}, ensure_ascii=False))


if __name__ == "__main__":
    main()
