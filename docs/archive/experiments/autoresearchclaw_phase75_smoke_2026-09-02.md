# AutoResearchClaw Phase 7.5 real-substrate smoke run

This manifest contains aggregate facts and hashes only. The API key, exact model
responses, generated upstream content, and SciTaste decision log remain local and
ignored.

## Run contract

- Date: 2026-09-02 (Asia/Shanghai)
- Substrate: AutoResearchClaw `v0.5.0`, commit `12d3fd8`
- Submodule modifications: none
- Provider/model: Alibaba Cloud Model Studio / `qwen3.8-max`
- Fallback models: none
- Experiment mode: simulated; experiment stages were not entered
- Web search: disabled
- Prompt contract: versioned smoke override
- Per-call output-token ceiling: 512
- AutoResearchClaw stages: `TOPIC_INIT → PROBLEM_DECOMPOSE`, then a separately
  selected `SEARCH_STRATEGY`

## Result

| Check | Result |
|---|---|
| Stage 1 | done in 18.6 s |
| Stage 2 | done in 38.5 s |
| Stage 3 session-audit run | done in 85.74 s |
| SciTaste decisions / transitions | 1 / 1 |
| Stage 3 contract artifacts | 3 / 3 validated |
| Stable SciTaste session | `arc-session-d5c360ff4fc532f1` |
| Upstream run ID changed | yes, preserved in session metadata |
| Submodule remained clean | yes |
| API cost measured | no; upstream emitted no cost log |

The first experiments with the full default topic-init prompt produced no stage
artifact within several minutes and were manually stopped. A direct short prompt
using the same key/model returned normally, isolating the issue to prompt/model
latency rather than credentials. The accepted run therefore uses an explicit,
committed short prompt contract and token ceiling. This is a compatibility smoke
condition, not an unmodified-production-prompt benchmark.

AutoResearchClaw scored the broad topic only 3/10 for specificity and suggested a
narrower adapter-preference formulation. That negative assessment is retained.
Also, Stage 3 source records are search plans only: because web search was
disabled, their `available` status was not independently checked and SciTaste did
not ingest them as factual knowledge.

## Artifact hashes

| Artifact | SHA-256 |
|---|---|
| AutoResearchClaw config | `1a5fc112e5e1b1f76129ed7551a96e8144b8dfbda36d21e9188814538ac61ec8` |
| Smoke prompt override | `f23fe02dc02054189a0d7b3249e26cfcfbb92faf908920bd72776e14e74c3913` |
| Stage 1 goal (local) | `62c84e7637b3bcf1f4ad276e4853ae01eee4509dbc974e00f2d0dc963e598b1e` |
| Stage 2 problem tree (local) | `94f4e047ec6d12eaf5d56396cf68bd56831f91162c2242537e7839798af0295d` |
| Stage 3 search plan (local) | `6d9fd0e139a668c264f63ff22327422df215a4ac7eaea2d0be30a3513113f251` |
| Stage 3 sources (local) | `56adca4f467e729764dc94608edbab244f23cbb0c9a6817f6a1bb7c1cbc84453` |
| Stage 3 queries (local) | `56210a1e15a25ea071b7cae0f089b200a1d77e86c219603d13385eb11802fbda` |
| SciTaste executor result (local) | `42f69f1b55aa3835f50e46dc2fcaf4ecd78c5605e651fa1c2cb6c2942991f3cd` |
| SciTaste decision log (local) | `0c9cd8266d173f421bf9a7c3a0beeed1cfc2153eadcd4d8301b84cad287a9a08` |

The smoke establishes live connectivity, prerequisite enforcement, stage
completion, artifact validation, session auditing, and state transition. It does
not establish literature quality or end-to-end autonomous research performance.
