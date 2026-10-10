"""Bounded, resumable local development study; final target labels stay out of generation."""
import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image

from cvpr_chart_binding import repair

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "outputs/projects/fastresearch-cvpr2027/research"
MODEL_REVISION = "851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a"
EXTRACT = '''Read the chart and question carefully. Return ONLY a JSON object, without markdown, using this schema:
{"panels":[{"id":"p0","legend":[{"id":"l0","label":"exact label","swatch":[x0,y0,x1,y1]}],"marks":[{"id":"m0","description":"visible mark and relevant observed values","sample":[x0,y0,x1,y1],"claimed_legend":"l0"}]}],"notes":"concise reasoning","answer":"short provisional answer"}.
All boxes use normalized coordinates 0..1000 relative to the complete image. A swatch box tightly encloses the colored sample next to the legend label; a mark sample box tightly encloses a small colored bar or line segment in the plot. Include up to 3 relevant panels and at most 6 legend entries/marks per panel. Distinct series in one panel must have distinct mark IDs. A panel's legend list and marks should describe the same series when observable. Never invent pixels, labels, coordinates, or values. For missing legends, grayscale/style-only evidence or nonstandard charts, use empty lists and explain uncertainty. Solve the question in notes and answer even if no supported boxes exist.'''
SOLVE = '''Solve the chart question using the image and provisional observations below. They may contain errors; recheck visually. Return ONLY a JSON object with "reasoning" (at most 100 words) and "answer" (the final short answer). Do not copy a provisional answer uncritically.'''
REASON = '''Solve the chart question carefully, checking relevant series, axes, units and arithmetic. Return ONLY a JSON object with "reasoning" (at most 200 words) and "answer" (the final short answer).'''
ANSWER_RULES = '''Follow the chart's scale notation. Do not add units unless a scale notation such as million, billion, m, B or K is part of the answer. Multiple answers must be a list in a string, e.g. "['x', 'y']". For multiple choice return only the option letter. For fact checking return true, false, or unanswerable. If the chart does not support an answer, say unanswerable.'''


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def atomic_json(path, value):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temp.replace(path)


def parse_json(text):
    value = text.strip()
    if value.startswith("```json") and value.endswith("```"):
        value = value[7:-3].strip()
    elif value.startswith("```") and value.endswith("```"):
        value = value[3:-3].strip()
    try:
        obj = json.loads(value)
        return obj if isinstance(obj, dict) else None
    except (ValueError, TypeError):
        return None


def context(row):
    parts = ["Question type: " + row["question_type"], ANSWER_RULES]
    if row.get("paragraph"):
        parts.append("Supplied paragraph: " + row["paragraph"])
    if row.get("history"):
        parts.append("Supplied conversation history: " + json.dumps(row["history"], ensure_ascii=False))
    parts.append("Question: " + row["question"])
    return "\n\n".join(parts)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--arms", nargs="+", choices=["direct", "review", "structure", "pixel_match"], default=["direct", "review", "structure", "pixel_match"])
    parser.add_argument("--max-new-tokens", type=int, default=1792)
    args = parser.parse_args()
    if not 1 <= args.limit <= 40 or args.max_new_tokens != 1792:
        raise ValueError("Only the frozen <=40-question development screen and 1792-token cap are supported")
    if not args.run_id.replace("-", "").replace("_", "").isalnum():
        raise ValueError("Unsafe run ID")
    run = PROJECT / "runs" / args.run_id
    run.mkdir(parents=True, exist_ok=True)
    lock = (run / ".run.lock").open("w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    ids = json.loads((PROJECT / "data/screen_ids.json").read_text())
    # Round robin task types rather than completing one category before another.
    ids = [ids[j * 8 + i] for i in range(8) for j in range(5)][:args.limit]
    rows = {r['id']: r for r in map(json.loads, (PROJECT / "data/development_inputs.jsonl").read_text().splitlines())}
    selected = [rows[k] for k in ids]
    for row in selected:
        assert row['partition'] == 'development' and 'Answer' not in row and 'answer' not in row
        assert sha((ROOT / row['image_path']).read_bytes()) == row['image_png_sha256']
    protocol = {"model": "Qwen/Qwen3.5-4B", "revision": MODEL_REVISION, "training": False,
                "backend": "transformers-local", "dtype": "bfloat16", "thinking": False,
                "deterministic_generation": True, "max_pixels": 640000,
                "max_new_tokens_total_per_arm": 1792, "two_pass_allocation": [1280, 512],
                "arms": args.arms, "sample_ids": ids, "scope": "development-only internal ChartQAPro subset",
                "data_manifest_sha256": sha((PROJECT / "data/MANIFEST.json").read_bytes()),
                "source_sha256": {p.name: sha(p.read_bytes()) for p in [Path(__file__), ROOT / 'scripts/cvpr_chart_binding.py']},
                "prompts": {"extract": EXTRACT, "solve": SOLVE, "reason": REASON, "answer_rules": ANSWER_RULES},
                "api_cost_cny": 0, "local_vram_cap_gib": 16,
                "shared_extraction": "Cached once across paired structure/pixel_match; both arms charged the full logical extraction budget"}
    if (run / "PROTOCOL.json").exists():
        if json.loads((run / "PROTOCOL.json").read_text()) != protocol:
            raise RuntimeError("Run protocol differs; use a new run ID")
    else:
        atomic_json(run / "PROTOCOL.json", protocol)
    record_path = run / "calls.jsonl"
    records = [json.loads(line) for line in record_path.read_text().splitlines()] if record_path.exists() else []
    done = {r['key']: r for r in records if r['status'] == 'ok'}
    started = time.monotonic()
    process_rows = subprocess.check_output(["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader,nounits"], text=True).strip()
    if process_rows:
        raise RuntimeError("Foreign GPU compute process present; no launch")
    atomic_json(run / "STATUS.json", {"state": "loading_model", "pid": os.getpid(), "samples": len(selected),
                                        "started_at": datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()})
    import torch
    import transformers
    from transformers import AutoProcessor, Qwen3_5ForConditionalGeneration
    torch.set_num_threads(4)
    torch.cuda.set_per_process_memory_fraction(2 / 3, 0)
    model_path = PROJECT / "models/Qwen3.5-4B"
    processor = AutoProcessor.from_pretrained(model_path, local_files_only=True,
                                             min_pixels=65536, max_pixels=640000)
    model = Qwen3_5ForConditionalGeneration.from_pretrained(model_path, dtype=torch.bfloat16,
                    device_map={"": "cuda:0"}, attn_implementation="sdpa", local_files_only=True).eval()
    for param in model.parameters():
        param.requires_grad_(False)
    atomic_json(run / "BACKEND.json", {"torch": torch.__version__, "transformers": transformers.__version__,
                  "device": torch.cuda.get_device_name(0), "trainable_parameters": sum(p.numel() for p in model.parameters() if p.requires_grad),
                  "load_seconds": time.monotonic() - started,
                  "allocated_mib_after_load": torch.cuda.memory_allocated() / (1 << 20)})

    def call(row, stage, prompt, cap):
        key = row['id'] + "|" + stage
        prompt_digest = sha((prompt + row['image_png_sha256'] + str(cap)).encode())
        if key in done:
            if done[key]['prompt_sha256'] != prompt_digest:
                raise RuntimeError("Cached request changed")
            return done[key]
        if any(r['key'] == key and r['status'] != 'ok' for r in records):
            raise RuntimeError("Failed call retained; no silent retry")
        with Image.open(ROOT / row['image_path']) as im:
            image = im.convert("RGB")
        messages = [{"role": "user", "content": [{"type": "image", "image": image}, {"type": "text", "text": prompt}]}]
        batch = processor.apply_chat_template(messages, tokenize=True, add_generation_prompt=True,
                      return_dict=True, return_tensors="pt", enable_thinking=False).to(model.device)
        if batch['input_ids'].shape[1] > 4096:
            raise RuntimeError("Frozen input-token cap exceeded")
        torch.cuda.reset_peak_memory_stats()
        tick = time.monotonic()
        with torch.inference_mode():
            output = model.generate(**batch, max_new_tokens=cap, do_sample=False, use_cache=True)
        torch.cuda.synchronize()
        generated = output[0, batch['input_ids'].shape[1]:]
        response = processor.decode(generated, skip_special_tokens=True)
        item = {"key": key, "sample_id": row['id'], "stage": stage, "status": "ok",
                "prompt_sha256": prompt_digest, "input_tokens": batch['input_ids'].shape[1],
                "output_tokens": len(generated), "token_cap": cap, "truncated": len(generated) == cap,
                "elapsed_seconds": time.monotonic() - tick, "peak_mib": torch.cuda.max_memory_allocated() / (1 << 20),
                "text": response, "parsed": parse_json(response), "api_cost_cny": 0}
        with record_path.open('a') as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        records.append(item)
        done[key] = item
        print(json.dumps({k: item[k] for k in ['key','output_tokens','elapsed_seconds','peak_mib','truncated']}, ensure_ascii=False), flush=True)
        return item

    predictions = []
    for number, row in enumerate(selected):
        base = context(row)
        shared = None
        if 'structure' in args.arms or 'pixel_match' in args.arms:
            shared = call(row, 'extract', base + "\n\n" + EXTRACT, 1280)
        for arm in args.arms:
            if arm == 'direct':
                final = call(row, arm, base + "\n\n" + REASON, 1792)
                charge = [final]
                audit = []
            elif arm == 'review':
                first = call(row, 'reason', base + "\n\n" + REASON, 1280)
                final = call(row, arm, base + "\n\n" + SOLVE + "\n" + first['text'], 512)
                charge = [first, final]
                audit = []
            else:
                graph = shared['parsed'] or {"notes": shared['text'], "panels": []}
                audit = []
                if arm == 'pixel_match':
                    with Image.open(ROOT / row['image_path']) as im:
                        graph, audit = repair(im.convert('RGB'), graph)
                final = call(row, arm, base + "\n\n" + SOLVE + "\n" + json.dumps(graph, ensure_ascii=False), 512)
                charge = [shared, final]
            obj = final['parsed']
            answer = obj.get('answer') if obj else None
            if isinstance(answer, list):
                answer = repr(answer)
            elif answer is not None:
                answer = str(answer)
            predictions.append({"id": row['id'], "image_group": row['image_group'], "question_type": row['question_type'],
                "arm": arm, "answer": answer, "valid": answer is not None and bool(answer.strip()) and not final['truncated'],
                "logical_input_tokens": sum(x['input_tokens'] for x in charge),
                "logical_output_tokens": sum(x['output_tokens'] for x in charge), "logical_calls": len(charge),
                "logical_seconds": sum(x['elapsed_seconds'] for x in charge), "pixel_audit": audit})
        atomic_json(run / "PREDICTIONS.json", predictions)
        atomic_json(run / "STATUS.json", {"state": "running", "pid": os.getpid(), "completed_samples": number + 1,
                  "samples": len(selected), "actual_calls": len(records), "elapsed_seconds": time.monotonic() - started,
                  "peak_mib": max(r['peak_mib'] for r in records), "scientific_score_computed": False})
    atomic_json(run / "STATUS.json", {"state": "completed_predictions", "pid": os.getpid(), "completed_samples": len(selected),
              "samples": len(selected), "actual_calls": len(records), "predictions": len(predictions),
              "elapsed_seconds": time.monotonic() - started, "peak_mib": max(r['peak_mib'] for r in records),
              "api_cost_cny": 0, "scientific_score_computed": False})


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        if '--run-id' in sys.argv:
            index = sys.argv.index('--run-id') + 1
            run_id = sys.argv[index] if index < len(sys.argv) else ''
            if run_id and run_id.replace('-', '').replace('_', '').isalnum():
                run = PROJECT / 'runs' / run_id
                if run.is_dir():
                    path = run / 'STATUS.json'
                    previous = json.loads(path.read_text()) if path.exists() else {}
                    atomic_json(path, {**previous, 'state': 'held_execution_failure',
                                'exception_type': type(exc).__name__, 'pid': os.getpid(),
                                'retry_authorized': False, 'scientific_score_computed': False})
        raise
