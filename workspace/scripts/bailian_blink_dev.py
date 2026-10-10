"""Bounded, resumable API screening. No GT enters any generation request."""
import argparse
import base64
import concurrent.futures
import fcntl
import hashlib
import json
import os
import re
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports/bailian_blink_dev_v1"
FINAL = 'Use the images to choose the correct option. Return only a JSON object with exactly one key, "answer", and its value the chosen option letter, e.g. {"answer":"A"}. No reasoning or other fields.'
NOTES = {
    "reason_review": "Develop a concise solution, checking the alternatives. Record your reasoning as provisional notes in at most 120 words. Do not write a final answer line yet.",
    "visual_evidence": "Before solving, list only visible facts relevant to the question, with image number and observable location or feature for each. Mark ambiguous facts UNKNOWN. Do not infer unsupported geometry, invent coordinates, or select an answer. Use at most 120 words."
}


def sha(payload):
    return hashlib.sha256(payload).hexdigest()


def parse_answer(text, choices):
    permitted = set(chr(65 + i) for i in range(len(choices)))
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and set(obj) == {"answer"} and obj["answer"] in permitted:
            return obj["answer"]
    except (ValueError, TypeError):
        pass
    matches = re.findall(r"(?im)^\s*FINAL\s*:\s*\(?([A-Z])\)?\s*[.!]?\s*$", text)
    if len(matches) == 1 and matches[0] in permitted:
        return matches[0]
    if re.fullmatch(r"\s*\(?[A-Z]\)?\s*", text):
        match = re.search(r"[A-Z]", text)[0]
        return match if match in permitted else None
    return None


def vision_message(sample, suffix):
    assert "answer" not in sample and "explanation" not in sample
    parts = [{"type": "text", "text": sample["prompt"] + "\n\n" + suffix}]
    for i, entry in enumerate(sample["images"], 1):
        payload = (ROOT / entry["path"]).read_bytes()
        assert sha(payload) == entry["sha256"]
        parts.append({"type": "text", "text": f"Image {i}:"})
        parts.append({"type": "image_url", "image_url": {"url":
            "data:" + entry["mime"] + ";base64," + base64.b64encode(payload).decode()}})
    parts.append({"type": "text", "text": suffix})
    return {"role": "user", "content": parts}


def credential(path):
    value = os.environ.get("DASHSCOPE_API_KEY")
    if value:
        return value
    for line in Path(path).read_text().splitlines():
        if line.strip().startswith("DASHSCOPE_API_KEY="):
            return line.split("=", 1)[1].strip().strip("\"'")
    raise RuntimeError("DASHSCOPE_API_KEY is unavailable")


class Runner:
    def __init__(self, cfg, key):
        self.cfg, self.key = cfg, key
        self.lock, self.stop = threading.Lock(), threading.Event()
        self.ledger_path = OUT / "calls.jsonl"
        self.records = [json.loads(x) for x in self.ledger_path.read_text().splitlines()] if self.ledger_path.exists() else []
        if any(x["status"] != "ok" for x in self.records):
            raise RuntimeError("Prior paid request failed: no automatic restart, retry, or model fallback")
        self.success = {x["call_key"]: x for x in self.records if x["status"] == "ok"}
        # Unknown billing on a failed request is conservatively reserved, never treated as free.
        self.cost = sum(x.get("estimated_cny", x.get("reserved_cny", 0)) for x in self.records)
        self.calls, self.reserved = len(self.records), 0.0
        self.started = time.monotonic()
        self.next_request_at = 0.0
        self.rate_lock = threading.Lock()
        if list(OUT.glob("pending_*.json")):
            raise RuntimeError("Unknown prior request outcomes: reconcile pending records before any restart")

    def write(self, record):
        with self.ledger_path.open("a") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self.records.append(record)

    def call(self, model, sample, arm, stage, messages, max_tokens):
        call_key = f"{model}|{sample['id']}|{arm}|{stage}"
        body = {"model": model, "messages": messages, "temperature": self.cfg["temperature"],
                "max_tokens": max_tokens, "enable_thinking": arm == "thinking", "stream": False}
        if stage == "final" and arm != "thinking":
            body["response_format"] = {"type": "json_object"}
        digest = sha(json.dumps(body, sort_keys=True).encode())
        prices = self.cfg["models"][model]
        reserve = (self.cfg["input_reservation_tokens"] * prices["input_cny_per_million"] * 2
                   + max_tokens * prices["output_cny_per_million"] * 2) / 1e6
        with self.lock:
            if call_key in self.success:
                existing = self.success[call_key]
                assert existing["request_sha256"] == digest, "Request changed: version a new protocol"
                return existing
            if self.stop.is_set():
                raise RuntimeError("new submissions stopped")
            if self.calls >= self.cfg["total_call_limit"] or self.cost + self.reserved + reserve > self.cfg["total_estimated_cost_limit_cny"]:
                self.stop.set()
                raise RuntimeError("finite budget exhausted")
            self.calls += 1
            self.reserved += reserve
        with self.rate_lock:
            delay = max(0.0, self.next_request_at-time.monotonic())
            if self.stop.wait(delay):
                with self.lock:
                    self.calls -= 1
                    self.reserved -= reserve
                raise RuntimeError("new submissions stopped while rate-limited")
            self.next_request_at = time.monotonic() + self.cfg["minimum_request_interval_s"]
        started = time.monotonic()
        record = {"call_key": call_key, "requested_model": model, "sample_id": sample["id"],
                  "task": sample["task"], "arm": arm, "stage": stage,
                  "utc": datetime.now(timezone.utc).isoformat(), "request_sha256": digest,
                  "max_tokens": max_tokens, "status": "error", "reserved_cny": reserve}
        pending = OUT / ("pending_" + sha(call_key.encode()) + ".json")
        pending.write_text(json.dumps(record))
        try:
            response = requests.post(self.cfg["endpoint"] + "/chat/completions", json=body,
                                     headers={"Authorization": "Bearer " + self.key}, timeout=(15, 180))
            record["http_status"] = response.status_code
            if not response.ok:
                # Never log response body, headers, URL exceptions, or credentials.
                try:
                    err = response.json().get("error", {})
                    record["provider_error_code"] = str(err.get("code", "unknown"))[:100]
                except ValueError:
                    record["provider_error_code"] = "non_json_error"
                raise RuntimeError("provider rejected request")
            result = response.json()
            usage = result["usage"]
            message = result["choices"][0]["message"]
            answer = message.get("content")
            if not isinstance(answer, str):
                answer = ""
            if not answer.strip() and not message.get("reasoning_content"):
                raise RuntimeError("missing visible completion")
            prompt_tokens = usage["prompt_tokens"]
            completion_tokens = usage["completion_tokens"]
            # Doubled rates conservatively cover the next input tier; normal panel inputs stay <=32K.
            multiplier = 1 if prompt_tokens <= 32768 else 2
            estimated = (prompt_tokens * prices["input_cny_per_million"] * multiplier
                         + completion_tokens * prices["output_cny_per_million"] * multiplier) / 1e6
            record.update(status="ok", returned_model=result.get("model"), response_id=result.get("id"),
                          usage=usage, estimated_cny=estimated, text=answer,
                          finish_reason=result["choices"][0].get("finish_reason"),
                          response_sha256=sha(json.dumps(result, sort_keys=True).encode()),
                          reasoning_content_present=bool(message.get("reasoning_content")))
        except Exception as err:
            record["error_type"] = type(err).__name__
            self.stop.set()
        record["elapsed_s"] = time.monotonic() - started
        with self.lock:
            self.reserved -= reserve
            self.cost += record.get("estimated_cny", reserve)
            self.write(record)
            pending.unlink()
            if record["status"] == "ok":
                self.success[call_key] = record
            if self.calls % 12 == 0 or record["status"] != "ok":
                print(json.dumps({"calls": self.calls, "estimated_cny": round(self.cost, 6),
                                  "elapsed_s": round(time.monotonic()-self.started, 2),
                                  "status": record["status"]}), flush=True)
        if record["status"] != "ok":
            raise RuntimeError("API stage failed; no retry or fallback")
        return record

    def example(self, job):
        model, sample, arm = job
        if arm in ("direct", "thinking"):
            messages = [vision_message(sample, FINAL)]
        else:
            messages = [vision_message(sample, NOTES[arm])]
            notes = self.call(model, sample, arm, "notes", messages, self.cfg["notes_max_tokens"])
            messages = messages + [{"role": "assistant", "content": notes["text"]},
                                   {"role": "user", "content": "Treat the previous notes as fallible. Re-check the original images when needed. " + FINAL}]
        final_budget = self.cfg["thinking_max_tokens"] if arm == "thinking" else self.cfg["max_tokens"]
        return self.call(model, sample, arm, "final", messages, final_budget)


def summarize(cfg, samples, records):
    # This function is separate from request construction; only the scorer reads GT.
    answers = {x["id"]: re.search(r"[A-Z]", x["answer"])[0] for x in json.loads((OUT / "answers.json").read_text())}
    by_id = {x["id"]: x for x in samples}
    groups = defaultdict(list)
    for record in records:
        if record["status"] == "ok" and record["stage"] == "final":
            parsed = parse_answer(record["text"], by_id[record["sample_id"]]["choices"])
            item = {"id": record["sample_id"], "task": record["task"], "parsed": parsed,
                    "correct": parsed == answers[record["sample_id"]], "invalid": parsed is None,
                    "finish_reason": record["finish_reason"]}
            groups[(record["requested_model"], record["arm"])].append(item)
    summary = {"protocol": cfg["protocol"], "scope": cfg["scope"], "calls": len(records),
               "successful_calls": sum(x["status"] == "ok" for x in records),
               "estimated_cny": sum(x.get("estimated_cny", x.get("reserved_cny", 0)) for x in records),
               "actual_account_bill_verified": False, "groups": []}
    for (model, arm), items in sorted(groups.items()):
        tasks = defaultdict(list)
        for item in items:
            tasks[item["task"]].append(item)
        summary["groups"].append({"model": model, "arm": arm, "n": len(items),
            "correct": sum(x["correct"] for x in items), "invalid": sum(x["invalid"] for x in items),
            "task_scores": {t: {"n": len(xs), "correct": sum(x["correct"] for x in xs),
                                 "invalid": sum(x["invalid"] for x in xs)} for t, xs in sorted(tasks.items())},
            "predictions": items})
    (OUT / "SUMMARY.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main():
    global OUT
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", choices=["bailian_blink_dev_v3"], default="bailian_blink_dev_v3")
    parser.add_argument("--phase", choices=["baseline", "refine", "thinking", "summary"], default="summary")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--credential-file", default="/home/good/zfx/papers/SciTaste/.env")
    args = parser.parse_args()
    OUT = ROOT / "reports" / args.protocol
    cfg_path = ROOT / "configs" / (args.protocol + ".json")
    cfg = json.loads(cfg_path.read_text())
    samples = json.loads((OUT / "samples.json").read_text())
    if args.phase == "summary":
        records = [json.loads(x) for x in (OUT / "calls.jsonl").read_text().splitlines()]
        summary = summarize(cfg, samples, records)
        print(json.dumps({k:v for k,v in summary.items() if k != "groups"}))
        return
    arms = ["direct"] if args.phase == "baseline" else (["thinking"] if args.phase == "thinking" else list(NOTES))
    if args.phase in ("refine", "thinking"):
        summary = json.loads((OUT / "SUMMARY.json").read_text())
        primary = next(x for x in summary["groups"] if x["model"] == "qwen3.5-35b-a3b" and x["arm"] == "direct")
        candidates = [(v["correct"] / v["n"], t) for t,v in primary["task_scores"].items()
                      if v["invalid"] == 0 and t in cfg["refinement_eligible_tasks"]]
        selected = [t for _, t in sorted(candidates)[:cfg["refinement_tasks"]]]
        path = OUT / "refinement_selection.json"
        if path.exists():
            selected = json.loads(path.read_text())["tasks"]
        else:
            path.write_text(json.dumps({"tasks": selected, "selection_scope": "development-only, outcome-adaptive task selection"}, indent=2))
        samples = [x for x in samples if x["task"] in selected]
    jobs = [(m, s, a) for m, model_cfg in cfg["models"].items() for s in samples
            if s["sample_order"] < model_cfg["samples_per_task"] for a in arms
            if args.phase != "thinking" or m == "qwen3.5-35b-a3b"]
    if args.smoke:
        jobs = [next(j for j in jobs if j[0] == m) for m in cfg["models"]]
    print(json.dumps({"phase": args.phase, "jobs": len(jobs), "execute": args.execute,
                      "potential_calls": len(jobs) * (2 if args.phase == "refine" else 1)}), flush=True)
    if not args.execute:
        return
    run_lock = (OUT / "runner.lock").open("w")
    fcntl.flock(run_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    runner = Runner(cfg, credential(args.credential_file))
    snapshot = {"config_sha256": sha(cfg_path.read_bytes()), "runner_sha256": sha(Path(__file__).read_bytes()),
                "samples_sha256": sha((OUT / "samples.json").read_bytes()), "config": cfg}
    snapshot_path = OUT / "PROTOCOL.json"
    if snapshot_path.exists():
        assert json.loads(snapshot_path.read_text()) == snapshot, "Protocol changed: version a new run"
    else:
        snapshot_path.write_text(json.dumps(snapshot, indent=2))
    failures = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=cfg["max_inflight"]) as pool:
        futures = [pool.submit(runner.example, job) for job in jobs]
        for future in concurrent.futures.as_completed(futures):
            try:
                future.result()
            except Exception as err:
                failures.append(type(err).__name__)
                runner.stop.set()
    full_samples = json.loads((OUT / "samples.json").read_text())
    summary = summarize(cfg, full_samples, runner.records)
    status = {"phase": args.phase, "complete": not failures, "failed_jobs": len(failures),
              "calls": summary["calls"], "estimated_cny": summary["estimated_cny"],
              "elapsed_s": time.monotonic() - runner.started}
    (OUT / (args.phase + ("_smoke" if args.smoke else "") + "_status.json")).write_text(json.dumps(status, indent=2))
    print(json.dumps(status), flush=True)
    if failures:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
