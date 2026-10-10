"""Replay the pinned, recommended upstream ChartQAPro scorer on development outputs."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "outputs/projects/fastresearch-cvpr2027/research"
SCORER_SHA = "9bfa75feb8c70341f788a7d85095df9a18cca08c04a7ab793d802b66afd2db83"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--partial-diagnostic", action="store_true", help="Score existing complete pairs; never mark the screen complete")
    args = parser.parse_args()
    if not args.run_id.replace("-", "").replace("_", "").isalnum():
        raise ValueError("Unsafe run ID")
    run = PROJECT / "runs" / args.run_id
    status = json.loads((run / "STATUS.json").read_text())
    if status['state'] not in ['completed_predictions', 'completed_recovery_predictions', 'completed_diagnostic_predictions'] and not args.partial_diagnostic:
        raise RuntimeError("Partial predictions cannot be presented as a completed screen")
    scorer_path = PROJECT / "sources/vlmeval_chartqapro_utils.py"
    if hashlib.sha256(scorer_path.read_bytes()).hexdigest() != SCORER_SHA:
        raise RuntimeError("Pinned official scorer changed")
    spec = importlib.util.spec_from_file_location("pinned_chartqapro", scorer_path)
    scorer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scorer)
    predictions = json.loads((run / "PREDICTIONS.json").read_text())
    protocol = json.loads((run / 'PROTOCOL.json').read_text())
    arms_expected = set(protocol['arms'])
    keys = [(p['id'], p['arm']) for p in predictions]
    if len(keys) != len(set(keys)) or any(p['id'] not in protocol['sample_ids'] for p in predictions):
        raise RuntimeError('Duplicate or unassigned prediction')
    present = {p['id'] for p in predictions}
    if not present or any({p['arm'] for p in predictions if p['id'] == k} != arms_expected for k in present):
        raise RuntimeError('Scoring requires complete paired arms')
    if not args.partial_diagnostic and present != set(protocol['sample_ids']):
        raise RuntimeError('Incomplete planned ID coverage')
    labels = {x['id']: x for x in json.loads((PROJECT / "data/development_labels.json").read_text())}
    by_arm, details = {}, []
    for pred in predictions:
        target = labels[pred['id']]
        if target['partition'] != 'development':
            raise RuntimeError("Confirmation label access is forbidden in this scorer")
        primary = scorer.evaluate_predictions_chartqapro([{**target, 'prediction': pred['answer'] if pred['valid'] else ''}])['Overall']
        strict = primary
        if pred['question_type'] in ['Fact Checking', 'Multi Choice']:
            strict = float(pred['valid'] and target['Answer'][-1].strip().lower().rstrip('.') == pred['answer'].strip().lower().rstrip('.'))
        row = {**pred, "score": primary, "strict_category_diagnostic": strict}
        by_arm.setdefault(pred['arm'], []).append(row)
        details.append(row)
    arms = {}
    for name, rows in by_arm.items():
        types = sorted({r['question_type'] for r in rows})
        arms[name] = {"n": len(rows), "score_mean": float(np.mean([r['score'] for r in rows])),
                      "valid": sum(r['valid'] for r in rows),
                      "strict_category_mean": float(np.mean([r['strict_category_diagnostic'] for r in rows])),
                      "types": {t: {"n": sum(r['question_type'] == t for r in rows),
                                     "score_mean": float(np.mean([r['score'] for r in rows if r['question_type'] == t]))} for t in types},
                      "logical_calls": sum(r['logical_calls'] for r in rows),
                      "logical_input_tokens": sum(r['logical_input_tokens'] for r in rows),
                      "logical_output_tokens": sum(r['logical_output_tokens'] for r in rows),
                      "logical_seconds": sum(r['logical_seconds'] for r in rows),
                      "logical_api_cost_cny": sum(r.get('logical_api_cost_cny', 0) for r in rows)}
    pairs = {}
    comparison_arm = 'pixel_match' if 'pixel_match' in by_arm else 'answer_blind_structure' if 'answer_blind_structure' in by_arm else None
    if comparison_arm:
        ours = {r['id']: r for r in by_arm[comparison_arm]}
        for name, rows in by_arm.items():
            if name == comparison_arm:
                continue
            shared = [r for r in rows if r['id'] in ours]
            if len(shared) != len(ours) or len(shared) != len(rows):
                raise RuntimeError("Paired arm ID coverage differs")
            # Cluster resampling stays valid if future dev batches have multiple questions/image.
            groups = sorted({r['image_group'] for r in shared})
            vectors = {g: np.array([ours[r['id']]['score'] - r['score'] for r in shared if r['image_group'] == g]) for g in groups}
            rng = np.random.default_rng(17)
            draws = [np.concatenate([vectors[g] for g in rng.choice(groups, size=len(groups), replace=True)]).mean() for _ in range(5000)]
            pairs[name] = {"delta": float(np.mean([ours[r['id']]['score'] - r['score'] for r in shared])),
                           "cluster_bootstrap_95ci": np.percentile(draws, [2.5, 97.5]).tolist(),
                           "groups": len(groups), "replications": 5000, "seed": 17,
                           "improved": sum(ours[r['id']]['score'] > r['score'] for r in shared),
                           "regressed": sum(ours[r['id']]['score'] < r['score'] for r in shared)}
    audits = [a for r in by_arm.get('pixel_match', []) for a in r['pixel_audit']]
    summary = {"run_id": args.run_id, "scope": "exploratory development-only internal ChartQAPro screen",
               "screen_complete": len(present) == 40 and not args.partial_diagnostic and comparison_arm=='pixel_match',
               "planned_samples": status.get('planned_samples', 40), "paired_samples": len(present),
               "excluded_unknown_sample_ids": protocol.get('recovery', {}).get('excluded_sample_ids', []),
               "missing_assigned_ids": sorted(set(protocol['sample_ids'])-present),
               "expansion_gate_authorized": False,
               "official_test_score": False, "confirmation_evaluated": False,
               "scorer": {"repository": "open-compass/VLMEvalKit", "commit": "98fdc2384730e39a5a4db5695bfffca756018aac",
                           "path": "vlmeval/dataset/utils/chartqapro.py", "sha256": SCORER_SHA,
                           "unchanged_upstream": True,
                           "caveat": "Upstream computes always_use_exact_match but does not pass it to helper. Primary preserves this behavior; strict categorical exact match is a separately labelled diagnostic."},
               "arms": arms, "paired_vs_"+(comparison_arm or 'none'): pairs,
               "pixel_binding": {"proposed_panels": len(audits), "accepted": sum(a['status'] == 'accepted' for a in audits),
                                 "changed_panels": sum(bool(a.get('changes')) for a in audits),
                                 "verified_grounding": False},
               "api_cost_cny": status.get('api_cost_cny', 0),
               "actual_calls": status.get('actual_calls'),
               "model": protocol['model'],
               "budget_scope": "Equal generated-token ceilings; actual usage and image-prefill differ and are reported",
               "publication_ready": False}
    prefix = 'PARTIAL_' if args.partial_diagnostic else ''
    (run / (prefix+"SCORED_PREDICTIONS.json")).write_text(json.dumps(details, ensure_ascii=False, indent=2) + '\n')
    (run / (prefix+"SUMMARY.json")).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
