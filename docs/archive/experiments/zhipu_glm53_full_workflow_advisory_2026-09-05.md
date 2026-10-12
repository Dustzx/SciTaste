# GLM-5.3-Flash Full Workflow advisory engineering run

Date: 2026-09-05

Project: `scitaste-glm53-full-advisory-probe`

Run: `glm53-full-advisory-20260905`

Condition: `full_scitaste_glm53_unpriced_advisory`

## Scope

This is the first real provider-backed bounded model node inside `scitaste run
full`. Discovery, Evidence, Communication and Figure remain deterministic; one
post-interpretation `interpretation-threat` advisory uses Zhipu
`glm-5.3-flash`. The run tests provider connectivity, structured parsing,
project ownership, immutable input publication, ledger accounting, paper
packaging and verification. It is not a model-quality or SciTaste-effectiveness
experiment.

The advisory configuration and profile both enable live execution, and the
caller supplied `--allow-live-model-nodes`. The credential came only from
`ZAI_API_KEY`; it is absent from configuration and run evidence.

## Result

The endpoint returned HTTP 200 and a schema-valid structured response. The Full
Workflow completed all four stages, registered its paper, compiled a one-page
PDF with XeLaTeX, published a project snapshot binding, and passed independent
model-node ledger verification with zero pending or archived attempts.

| Measure | Observed |
|---|---:|
| Provider calls | 1 |
| Input tokens | 1,422 |
| Output tokens | 514 |
| Total non-cached tokens | 1,936 |
| Provider latency | 6,238.41 ms |
| Measured USD cost | unavailable |
| Unknown-cost entries | 1 |
| Advisory outcome | rejected |
| Full Workflow status | complete |
| PDF build | succeeded |

The deterministic advisory gates rejected the proposal for three retained
reasons: API cost telemetry was unavailable; the proposed
`ACKNOWLEDGE_LIMITATION` action was outside the narrow `ANALYZE` / `PIVOT` /
`REPRODUCE` allowlist; and cumulative project cost was therefore unknown. The
parsed value remains untrusted and receives no state-transition, tool, or
execution authority. The deterministic paper pipeline continues independently,
so a rejected optional advisory does not make the project output a model-written
paper.

The real run exercised the ordinary live path. No deliberate crash was injected
into a paid provider call. Automated integration tests separately inject an
interruption after durable response publication and prove that resume consumes
the recorded response with no second transport call and counts usage once.

## Evidence hashes

All paths are under
`outputs/projects/scitaste-glm53-full-advisory-probe/` and are intentionally
excluded from Git; this document is the tracked index.

| Evidence | SHA-256 |
|---|---|
| `runs/glm53-full-advisory-20260905/full_run_summary.json` | `b8f57e7de3410a8f1ca3f30ae14b42cab08b026c860fc4ceea2aea8a6307648c` |
| `runs/glm53-full-advisory-20260905/stages/evidence/model_advisory_input.json` | `36163ce9830ec1187298bd91aa51120a8cc0a8ceef17feb8281cff5695cbb0b3` |
| `runs/glm53-full-advisory-20260905/stages/evidence/model_advisory.json` | `ff70533afafb9c0cbf8fea0d9322d9faf88f4d76beb59f6d4efbfb3cef1d6f32` |
| `runs/glm53-full-advisory-20260905/stages/evidence/STAGE.json` | `438aa2a3f1aba6fc810816ed2f72e067df4c8e7fcc825c5723ab8518a404986e` |
| `runs/glm53-full-advisory-20260905/model_nodes/recordings/evidence-interpretation-threat-glm53-p2-s12.jsonl` | `aabcccee5ddf6a85bb21910174744d344a214fc493dfb77317589b752fe3ae65` |
| `runs/glm53-full-advisory-20260905/model_nodes/ledger/00000000__evidence-interpretation-threat-glm53-p2-s12.json` | `d8c63a4a03425361f45b302bf30fe92cfe25935d06b2ddba64b7642de18ff265` |
| `papers/glm53-recoverable-advisory-probe-draft/main.pdf` | `922679f4d8b897295172310f00e59cf91b78a376de5f875d5d10defeff59b70a` |
| `surfaces/glm53-full-advisory-20260905-snapshot-binding.json` | `f08ca8f48e4b8f113bcc4e795cbe250291c9570dfac5d5fa48faca0195c8a23f` |

## Promotion boundary

This condition is permanently labelled `engineering-only-unpriced-live-semantic-advice`
and `effectiveness_claim: false`. Promotion requires verified price provenance,
a newly registered priced condition, independent outcome review and the
predeclared ADR-022 intervention/safety/effectiveness gates. The present run does
not modify the Phase 9 matched-budget protocol.
