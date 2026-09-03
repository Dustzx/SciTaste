# Phase 9-B local RTX 3090 pilot plan

- Date: 2026-09-03
- Protocol: `scitaste-local-3090-pilot-v1`
- Scope: `pilot` (permanently non-headline)
- Model: `Qwen/Qwen3-VL-4B-Instruct`
- Model revision: `ebb281ec70b05090aa6165b016eac8ec08e71b17`
- Tasks: four registered categories
- Core conditions: AutoResearchClaw, Knowledge RAG, Taste Library, Full SciTaste
- Seeds: 7
- Planned cells: 16
- Per-cell ceiling: 0.5 allocated GPU-hours, 0.5 wall-hours, 2 experiments,
  20,000 LLM tokens, 0 search queries, and USD 0.01 API cost

## Acceptance result

The planner generated 16 deterministic cells with no model/search readiness
blockers. Selecting the diagnosis-friendly task produces four isolated launch
plans, one for every core condition. Dry-run created no cell directories and
started no process.

The runner acceptance suite covers successful real-shaped results, independent
artifact hashing, measured GPU/wall allocation, restricted environment
inheritance, atomic result checkpoints, successful-cell resume, timeout failure,
path traversal rejection, missing launchers/credentials, pilot-scope headline
exclusion, and one real subprocess writing the standard contract.

The committed launcher commands are explicit placeholders. Therefore no system
cell has yet executed and no research-yield result exists. Replacing those four
commands with real first-party adapters is the next implementation step; this is
kept visible instead of using a synthetic condition implementation.

## Integrity

| Artifact | SHA-256 |
|---|---|
| Pilot protocol YAML | `2f03e0e0fa65e337c79762237dd3d4db908bb3d09f20b42aa5d7994e33d4d2e7` |
| Validated protocol payload | `0e9917a19f91ab7fef6400b4ff84d05334f52410d86a40488f07344281f379c1` |
| Validated plan payload | `054c7a967e62a22bd93db60db81569508cddf12db810c03c610fd0a2ee184948` |
| Generated plan file | `9b283e8ad9b83c6fdbb9e0ef0f8df3da821329b3ddb11d36e3c97e6e7249985a` |

Generated plans remain under ignored `outputs/`.
