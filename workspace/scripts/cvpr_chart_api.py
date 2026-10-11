"""New CVPR study: bounded Bailian vision calls, with no local GPU or training.

Each paid attempt is reserved durably before POST. Unknown outcomes are never
retried. The project-wide ledger covers every run/model under the new ¥300 grant.
"""
import argparse
import base64
import concurrent.futures
import fcntl
import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from PIL import Image

from cvpr_chart_binding import repair
from cvpr_chart_run import ROOT, PROJECT, EXTRACT, SOLVE, REASON, ANSWER_RULES, atomic_json, context, parse_json, sha

ENDPOINT = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
PRICES = {"qwen3.8-flash": (0.8, 2.7), "qwen3.8-max-0902": (12.0, 36.0), "qwen3.8-27b": (3.0, 12.0)}
ARMS = ["direct", "review", "structure", "pixel_match"]


def now():
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()


def credential():
    """Explicit caller environment only; never search a developer account file."""
    value = os.environ.get("DASHSCOPE_API_KEY")
    if not value:
        raise RuntimeError("Set DASHSCOPE_API_KEY explicitly after resource admission")
    return value


class Budget:
    def __init__(self, retained_unknown=None, *, retry_own_failures=False, phase_run_ids=None):
        authorization = json.loads((PROJECT / "API_AUTHORIZATION.json").read_text())
        self.cap = authorization["authorized_cny"]
        if self.cap != 300 or authorization["previous_blink_budget_inherited"]:
            raise RuntimeError("Unexpected authorization scope")
        self.path = PROJECT / "API_LEDGER.json"
        self.mutex = threading.Lock()
        self.retained_unknown = retained_unknown or {}
        self.retry_own_failures = retry_own_failures
        self.phase_run_ids = set(phase_run_ids) if phase_run_ids else None

    def change(self, key, record=None, settle=None, phase_cap=None, run_id=None):
        with self.mutex, (PROJECT / ".api-ledger.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            ledger = json.loads(self.path.read_text()) if self.path.exists() else {
                "authorization_sha256": sha((PROJECT / "API_AUTHORIZATION.json").read_bytes()),
                "cap_cny": self.cap, "scope": "new CVPR study; excludes stopped BLINK", "attempts": {}}
            entries = ledger["attempts"]
            if record is not None:
                if key in entries:
                    raise RuntimeError("Paid attempt already exists; replay outputs rather than repost")
                if any(e["status"] != "settled" for e in entries.values()):
                    # Other in-flight calls in this live process are safe and bounded;
                    # unresolved attempts from another process always fail closed.
                    if any((e["pid"] != os.getpid() or e["status"] == "unknown") and
                           self.retained_unknown.get(k) != e
                           for k, e in entries.items() if e["status"] != "settled"):
                        raise RuntimeError("Unresolved billing outcome; new calls held")
                total = sum(e.get("cost_cny", e["reserved_cny"]) for e in entries.values())
                phase_total = sum(e.get("cost_cny", e["reserved_cny"]) for e in entries.values()
                                  if (e["run_id"] in self.phase_run_ids if self.phase_run_ids else e["run_id"] == run_id))
                if total + record["reserved_cny"] > self.cap or phase_total + record["reserved_cny"] > phase_cap:
                    raise RuntimeError("Budget reservation exceeds authorized/project or phase cap")
                entries[key] = record
            if settle is not None:
                entries[key].update(settle)
                if (self.retry_own_failures and settle.get('automatic_retry_eligible') is True
                        and entries[key]['status'] == 'unknown' and entries[key]['pid'] == os.getpid()):
                    # Explicit bounded-retry authorization. Every failed attempt
                    # retains its full reservation; later attempts use new keys.
                    self.retained_unknown[key] = dict(entries[key])
            ledger["estimated_settled_cny"] = sum(e.get("cost_cny", 0) for e in entries.values())
            ledger["unresolved_reserved_cny"] = sum(e["reserved_cny"] for e in entries.values() if e["status"] != "settled")
            ledger["conservative_total_cny"] = ledger["estimated_settled_cny"] + ledger["unresolved_reserved_cny"]
            ledger["updated_at"] = now()
            atomic_json(self.path, ledger)
            return ledger


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--model", choices=PRICES, default="qwen3.8-flash")
    parser.add_argument("--stop-after", type=int, default=40)
    parser.add_argument("--workers", type=int, choices=[1, 2], default=2)
    parser.add_argument("--phase-cap-cny", type=float, default=20)
    parser.add_argument("--recovery-from", help="New run only; reuse responses and exclude unresolved sample IDs")
    args = parser.parse_args()
    if not 1 <= args.stop_after <= 40 or not 0 < args.phase_cap_cny <= 300:
        raise ValueError("Development screen/phase cap out of bounds")
    if not args.run_id.replace("-", "").replace("_", "").isalnum():
        raise ValueError("Unsafe run ID")
    run = PROJECT / "runs" / args.run_id
    run.mkdir(parents=True, exist_ok=True)
    run_lock = (run / ".run.lock").open("a")
    fcntl.flock(run_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    ordered = json.loads((PROJECT / "data/screen_ids.json").read_text())
    ids = [ordered[j * 8 + i] for i in range(8) for j in range(5)]
    rows = {r["id"]: r for r in map(json.loads, (PROJECT / "data/development_inputs.jsonl").read_text().splitlines())}
    retained_unknown, recovery = {}, None
    if args.recovery_from:
        if args.recovery_from == args.run_id or not args.recovery_from.replace('-', '').replace('_', '').isalnum():
            raise ValueError('Recovery requires a distinct safe source run')
        source = PROJECT / 'runs' / args.recovery_from
        source_protocol = json.loads((source / 'PROTOCOL.json').read_text())
        source_status = json.loads((source / 'STATUS.json').read_text())
        pid = source_status.get('pid')
        if pid and Path(f'/proc/{pid}').exists():
            raise RuntimeError('Source process still exists; do not recover concurrently')
        ledger = json.loads((PROJECT / 'API_LEDGER.json').read_text())
        retained_unknown = {k: v for k, v in ledger['attempts'].items() if v['status'] != 'settled'}
        if not retained_unknown or any(v['run_id'] != args.recovery_from for v in retained_unknown.values()):
            raise RuntimeError('Recovery does not cover the unresolved project cohort')
        old_calls = [json.loads(s) for s in (source / 'calls.jsonl').read_text().splitlines()]
        if any(c['status'] != 'ok' for c in old_calls):
            raise RuntimeError('Failed response recovery is not authorized')
        old_by_key = {c['key']: c for c in old_calls}
        for key, entry in ledger['attempts'].items():
            if entry['run_id'] == args.recovery_from and entry['status'] == 'settled':
                c = old_by_key.get(entry['key'])
                if not c or c['response_id'] != entry['response_id'] or c['api_cost_cny'] != entry['cost_cny']:
                    raise RuntimeError('Settled response/ledger mismatch')
        excluded = sorted({v['key'].split('|')[0] for v in retained_unknown.values()})
        if any(v['key'] in old_by_key for v in retained_unknown.values()):
            raise RuntimeError('Reconcile persisted responses before recovery')
        recovery = {'source_run_id': args.recovery_from, 'source_protocol_sha256': sha((source / 'PROTOCOL.json').read_bytes()),
                    'source_calls_sha256': sha((source / 'calls.jsonl').read_bytes()),
                    'source_predictions_sha256': sha((source / 'PREDICTIONS.json').read_bytes()),
                    'retained_unknown': retained_unknown, 'excluded_sample_ids': excluded,
                    'authorization': '2026-10-10 user: 继续推进实验; bounded no-retry continuation within existing ¥300',
                    'policy': 'Keep full unknown reservations; never repost attempted stages; exclude whole affected samples; development only'}
        if source_protocol['model'] != args.model or source_protocol['sample_ids'] != ids:
            raise RuntimeError('Source model or assignment differs')
        ids = [k for k in ids if k not in excluded]
        if not (run / 'RECOVERY.json').exists():
            if any(run.iterdir()):
                if set(p.name for p in run.iterdir()) != {'.run.lock'}:
                    raise RuntimeError('Recovery destination must be new')
            atomic_json(run / 'RECOVERY.json', recovery)
            inherited = [{**c, 'inherited_from_run': args.recovery_from} for c in old_calls if c['sample_id'] in ids]
            (run / 'calls.jsonl').write_text(''.join(json.dumps(c, ensure_ascii=False)+'\n' for c in inherited))
            atomic_json(run / 'PREDICTIONS.json', [p for p in json.loads((source / 'PREDICTIONS.json').read_text()) if p['id'] in ids])
        elif json.loads((run / 'RECOVERY.json').read_text()) != recovery:
            raise RuntimeError('Recovery evidence changed')
    selected = [rows[k] for k in ids[:args.stop_after]]
    for row in selected:
        if row["partition"] != "development" or "Answer" in row or "answer" in row:
            raise RuntimeError("Wrong partition or target leaked into inputs")
        if sha((ROOT / row["image_path"]).read_bytes()) != row["image_png_sha256"]:
            raise RuntimeError("Image changed")
    protocol = {
        "model": args.model, "weight_revision": None, "returned_model_logged_per_call": True,
        "model_alias_policy": "Rolling flash alias; dated max identifier; served weight revision unknown",
        "backend": "Bailian-China-compatible-API", "endpoint": ENDPOINT,
        "training": False, "local_gpu": False, "thinking": False, "temperature": 0,
        "provider_determinism_guaranteed": False, "response_format": "json_object",
        "max_new_tokens_total_per_arm": 1792, "two_pass_allocation": [1280, 512],
        "image_input": "original PNG, each logical call", "arms": ARMS, "sample_ids": ids,
        "scope": "development-only internal ChartQAPro screen", "phase_cap_cny": args.phase_cap_cny,
        "project_budget_cny": 300, "prices_cny_per_million_input_output": PRICES[args.model],
        "price_source": "https://help.aliyun.com/zh/model-studio/model-pricing",
        "price_snapshot_sha256": sha((PROJECT / "sources/bailian_price.html").read_bytes()),
        "data_manifest_sha256": sha((PROJECT / "data/MANIFEST.json").read_bytes()),
        "source_sha256": {p.name: sha(p.read_bytes()) for p in [Path(__file__), ROOT / "scripts/cvpr_chart_run.py", ROOT / "scripts/cvpr_chart_binding.py"]},
        "prompts": {"extract": EXTRACT, "solve": SOLVE, "reason": REASON, "answer_rules": ANSWER_RULES},
        "shared_extraction": "One actual call reused; full logical cost charged to both arms",
        "unchanged_intervention": "Remove algorithm audit from model input; identical structure/pixel prompts reuse the exact response",
        "rate": {"global_interval_seconds": 2.5, "maximum_concurrency": args.workers},
        "retry": "none; failed/unknown outcomes retained and held",
    }
    if recovery:
        for field in ['model', 'prompts', 'max_new_tokens_total_per_arm', 'two_pass_allocation', 'data_manifest_sha256', 'prices_cny_per_million_input_output']:
            if json.loads(json.dumps(protocol[field])) != source_protocol[field]:
                raise RuntimeError('Frozen scientific protocol changed in recovery')
        for name, digest in source_protocol['source_sha256'].items():
            if sha((source / name).read_bytes()) != digest:
                raise RuntimeError('Source snapshot changed')
        protocol['recovery'] = recovery
        protocol['scope'] = 'interrupted development screen recovery; two unknown-outcome samples excluded'
    if (run / "PROTOCOL.json").exists():
        if json.loads((run / "PROTOCOL.json").read_text()) != json.loads(json.dumps(protocol)):
            raise RuntimeError("Protocol changed; use a new run ID")
    else:
        atomic_json(run / "PROTOCOL.json", protocol)
        for source in protocol["source_sha256"]:
            (run / source).write_bytes((ROOT / "scripts" / source).read_bytes())
    budget = Budget(retained_unknown)
    key_secret = credential()
    records_path = run / "calls.jsonl"
    records = [json.loads(s) for s in records_path.read_text().splitlines()] if records_path.exists() else []
    done = {r["key"]: r for r in records if r["status"] == "ok"}
    if any(r["status"] != "ok" for r in records):
        raise RuntimeError("Previous failed call; no automatic retry")
    predictions = json.loads((run / "PREDICTIONS.json").read_text()) if (run / "PREDICTIONS.json").exists() else []
    completed = {p["id"] for p in predictions if sum(x["id"] == p["id"] for x in predictions) == len(ARMS)}
    mutex, rate_lock, halted = threading.Lock(), threading.Lock(), threading.Event()
    last_start = [0.0]
    started = time.monotonic()
    atomic_json(run / "STATUS.json", {"state": "running", "pid": os.getpid(), "started_at": now(),
        "planned_samples": 40, "checkpoint_samples": args.stop_after, "completed_samples": len(completed), "local_gpu": False})

    def call(row, stage, prompt, cap, image_uri):
        key = row["id"] + "|" + stage
        prompt_digest = sha((prompt + row["image_png_sha256"] + str(cap)).encode())
        if key in done:
            if done[key]["prompt_sha256"] != prompt_digest:
                raise RuntimeError("Cached request changed")
            return done[key]
        if halted.is_set():
            raise RuntimeError("Sibling call failed; no more requests")
        if len(prompt.encode()) > 65536:
            raise RuntimeError("Prompt bound exceeded")
        # Reserve the documented maximum 1M context, not a guessed image-token
        # formula, to cover even failed/timeout calls conservatively.
        input_price, output_price = PRICES[args.model]
        reserve = input_price + cap * output_price / 1e6
        ledger_key = args.run_id + "|" + key
        with rate_lock:
            time.sleep(max(0, 2.5 - (time.monotonic() - last_start[0])))
            if halted.is_set():
                raise RuntimeError("Sibling call failed; request held")
            budget.change(ledger_key, record={"run_id": args.run_id, "key": key, "pid": os.getpid(),
                "model": args.model, "reserved_cny": reserve, "status": "pending", "started_at": now()},
                phase_cap=args.phase_cap_cny, run_id=args.run_id)
            last_start[0] = time.monotonic()
        body = {"model": args.model, "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": image_uri}}, {"type": "text", "text": prompt}]}],
                "max_tokens": cap, "temperature": 0, "enable_thinking": False, "response_format": {"type": "json_object"}}
        tick = time.monotonic()
        response_status, provider_code = None, None
        try:
            response = requests.post(ENDPOINT, headers={"Authorization": "Bearer " + key_secret}, json=body, timeout=(15, 180))
            response_status = response.status_code
            obj = response.json()
            if response.status_code != 200:
                err = obj.get("error", {})
                provider_code = str(err.get("code", "unknown"))[:100]
                raise RuntimeError("Provider HTTP %s code %s" % (response.status_code, err.get("code", "unknown")))
            usage = obj["usage"]
            input_tokens, output_tokens = int(usage["prompt_tokens"]), int(usage["completion_tokens"])
            cost = (input_tokens * input_price + output_tokens * output_price) / 1e6
            if input_tokens > 1000000 or output_tokens > cap or cost > reserve:
                raise RuntimeError("Usage outside reservation")
            choice = obj["choices"][0]
            response_text = choice["message"]["content"]
            if not isinstance(response_text, str) or choice["message"].get("reasoning_content"):
                raise RuntimeError("Unexpected content/thinking mode")
            item = {"key": key, "sample_id": row["id"], "stage": stage, "status": "ok", "created_at": now(),
                "prompt_sha256": prompt_digest, "input_tokens": input_tokens, "output_tokens": output_tokens,
                "token_cap": cap, "finish_reason": choice.get("finish_reason"), "truncated": choice.get("finish_reason") == "length",
                "elapsed_seconds": time.monotonic() - tick, "peak_mib": None, "local_gpu": False,
                "requested_model": args.model, "returned_model": obj.get("model"), "response_id": obj.get("id"),
                "usage": usage, "api_cost_cny": cost, "cost_basis": "published undiscounted China-region token prices; not invoiced cost",
                "text": response_text, "parsed": parse_json(response_text)}
            with mutex:
                with records_path.open("a") as output:
                    output.write(json.dumps(item, ensure_ascii=False) + "\n")
                    output.flush()
                    os.fsync(output.fileno())
                records.append(item)
                done[key] = item
            budget.change(ledger_key, settle={"status": "settled", "cost_cny": cost, "settled_at": now(),
                          "response_id": obj.get("id"), "usage": usage})
            print(json.dumps({k: item[k] for k in ["key", "returned_model", "input_tokens", "output_tokens", "elapsed_seconds", "api_cost_cny", "truncated"]}), flush=True)
            return item
        except Exception as exc:
            halted.set()
            budget.change(ledger_key, settle={"status": "unknown", "exception_type": type(exc).__name__, "failed_at": now()})
            # Do not log requests objects, headers, credentials, or response bodies.
            failure = {"key": key, "status": "unknown", "exception_type": type(exc).__name__, "reserved_cny": reserve,
                       "http_status": response_status, "provider_code": provider_code, "created_at": now()}
            with mutex, records_path.open("a") as output:
                output.write(json.dumps(failure) + "\n")
                output.flush()
                os.fsync(output.fileno())
            raise RuntimeError("Paid request failed; outcome retained, no retry") from None

    def process(row):
        blob = (ROOT / row["image_path"]).read_bytes()
        image_uri = "data:image/png;base64," + base64.b64encode(blob).decode("ascii")
        base = context(row)
        shared = call(row, "extract", base + "\n\n" + EXTRACT, 1280, image_uri)
        local_rows, structure_graph, structure_final = [], None, None
        for arm in ARMS:
            audit = []
            if arm == "direct":
                final = call(row, "direct", base + "\n\n" + REASON, 1792, image_uri)
                charge = [final]
            elif arm == "review":
                first = call(row, "reason", base + "\n\n" + REASON, 1280, image_uri)
                final = call(row, "review", base + "\n\n" + SOLVE + "\n" + first["text"], 512, image_uri)
                charge = [first, final]
            else:
                graph = shared["parsed"] or {"notes": shared["text"], "panels": []}
                if arm == "pixel_match":
                    with Image.open(ROOT / row["image_path"]) as im:
                        graph, audit = repair(im.convert("RGB"), graph)
                    graph.pop("pixel_binding_audit", None)
                if arm == "pixel_match" and graph == structure_graph:
                    final = structure_final
                else:
                    final = call(row, arm, base + "\n\n" + SOLVE + "\n" + json.dumps(graph, ensure_ascii=False), 512, image_uri)
                if arm == "structure":
                    structure_graph, structure_final = graph, final
                charge = [shared, final]
            answer = final["parsed"].get("answer") if final["parsed"] else None
            answer = repr(answer) if isinstance(answer, list) else (str(answer) if answer is not None else None)
            local_rows.append({"id": row["id"], "image_group": row["image_group"], "question_type": row["question_type"],
                "arm": arm, "answer": answer, "valid": answer is not None and bool(answer.strip()) and not final["truncated"],
                "logical_input_tokens": sum(x["input_tokens"] for x in charge),
                "logical_output_tokens": sum(x["output_tokens"] for x in charge), "logical_calls": len(charge),
                "logical_seconds": sum(x["elapsed_seconds"] for x in charge),
                "logical_api_cost_cny": sum(x["api_cost_cny"] for x in charge),
                "actual_call_keys": [x["key"] for x in charge], "pixel_audit": audit})
        with mutex:
            predictions.extend(local_rows)
            predictions.sort(key=lambda p: (ids.index(p["id"]), ARMS.index(p["arm"])))
            atomic_json(run / "PREDICTIONS.json", predictions)
            complete_count = len(predictions) // len(ARMS)
            atomic_json(run / "STATUS.json", {"state": "running", "pid": os.getpid(), "updated_at": now(),
                "planned_samples": 40, "checkpoint_samples": args.stop_after, "completed_samples": complete_count,
                "actual_calls": len(records), "predictions": len(predictions), "local_gpu": False,
                "elapsed_seconds_this_session": time.monotonic() - started,
                "api_cost_cny": sum(x["api_cost_cny"] for x in records), "scientific_score_computed": False})

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(process, row) for row in selected if row["id"] not in completed]
        try:
            for future in concurrent.futures.as_completed(futures):
                future.result()
        except Exception:
            halted.set()
            for future in futures:
                future.cancel()
            raise
    atomic_json(run / "STATUS.json", {"state": ("completed_recovery_predictions" if recovery else "completed_predictions") if args.stop_after == 40 else "checkpoint_predictions",
        "pid": os.getpid(), "completed_at": now(), "planned_samples": 40, "completed_samples": len(predictions) // len(ARMS),
        "actual_calls": len(records), "predictions": len(predictions), "elapsed_seconds_this_session": time.monotonic() - started,
        "local_gpu": False, "api_cost_cny": sum(x["api_cost_cny"] for x in records), "scientific_score_computed": False})


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        import sys
        if "--run-id" in sys.argv:
            run_id = sys.argv[sys.argv.index("--run-id") + 1]
            if run_id and run_id.replace("-", "").replace("_", "").isalnum():
                run = PROJECT / "runs" / run_id
                if run.is_dir():
                    path = run / "STATUS.json"
                    previous = json.loads(path.read_text()) if path.exists() else {}
                    atomic_json(path, {**previous, "state": "held_execution_failure", "exception_type": type(exc).__name__,
                                      "pid": os.getpid(), "retry_authorized": False, "updated_at": now()})
        print("Execution held: " + type(exc).__name__, file=sys.stderr)
        sys.exit(1)
