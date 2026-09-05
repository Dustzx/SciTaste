# Project-owned AutoResearchClaw search preacceptance

Date: 2026-09-05

This is the first live acceptance of the project-owned substrate-action
lifecycle. It tests ownership, provider invocation, completion validation,
resource telemetry, and independent status revalidation. It is not a research-
effectiveness result and it does not validate the complete AutoResearchClaw
pipeline.

## Registered identity

- Project: `scitaste-self-development`
- Run: `2026-09-05__glm-5.3-flash__selected-search__seed-07`
- Project revision after completion: `15`
- Provider/model observed on the wire: Zhipu / `glm-5.3-flash`
- Selected action/upstream stage: `SEARCH` / `SEARCH_STRATEGY` (Stage 3)
- AutoResearchClaw commit: `12d3fd809fa9658e91a0328c3280a0e462c78386`
- Imported source: historical Stage 1–3 run, 21 files and 15,981 bytes
- Source snapshot SHA-256:
  `ffd0e513efb8c932fcccdd98e866ee4f3eb9cc2411800e675ebefbd3825c3376`
- Run manifest SHA-256:
  `ff1239fe1a75d5eb8bb850e1ec66eb96e36c91ca6974ec97efbe7805cd922af5`
- Verification SHA-256:
  `9ded36b25963b12c9e60cbda3d17d9de985fdc693f916ae41561eaf4874b0f14`

The imported source remained beneath `inputs/autoresearchclaw`; the upstream
process wrote only to `work/autoresearchclaw`. The original source run and pinned
submodule were not modified. The executor configuration was copied without a
credential and bound by content hash.

## Outcome and resource evidence

The command completed successfully and an independent `substrate project status`
rehash returned `verified`. The SciTaste transition was applied exactly once and
advanced its action-local state from revision 0 to 1. AutoResearchClaw reported
one completed stage in 121.51 seconds and published a fresh Stage 3 checkpoint
under a new upstream run ID.

One model request used 4,509 tokens: 413 prompt tokens and 4,096 completion
tokens. The completion reached the configured per-request ceiling. The
100,000-token process ceiling was not approached. Wall time recorded by the
adapter was 0.03386037 hours. AutoResearchClaw did not emit `cost_log.jsonl`, so
API cost is explicitly unmeasured rather than recorded as zero. This run is
therefore ineligible for a cost-matched Phase 9 comparison.

Three exact contract artifacts passed hashing:

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `stage-03/search_plan.yaml` | 807 | `aeb4e7c63591182292a61b2ff66dda7e8214b691d2fef34dd2dd82b2836fb488` |
| `stage-03/sources.json` | 902 | `dfc827eda3329f27e3450d4e8e5a50dd66abf13188591cfab630cc6b688c1201` |
| `stage-03/queries.json` | 274 | `76418ef5e944d1d3f1b3f0cb3ffe30c2e82548e3cefda7048afbefb4cc347fb9` |

## Interpretation and limits

The run accepts the engineering lifecycle: double live authorization, immutable
input import, separate mutation workspace, exact-stage completion checks,
project registration, and later evidence verification all worked together.

It does not accept search quality. Web search was disabled, `sources.json`
declares planned endpoints rather than retrieved literature, and the generated
queries split the self-development sentence into several broad fragments. The
completion hit its token ceiling, providing a concrete reason to test a larger
per-request bound or a narrower topic before quality evaluation. No literature
was ingested, no experiment was run, and no paper was produced.
