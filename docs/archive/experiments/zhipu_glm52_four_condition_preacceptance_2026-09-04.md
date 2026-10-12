# Zhipu GLM-5.2 four-condition preacceptance — 2026-09-04

## Status

The four enabled core conditions completed the same frozen diagnosis task through
AutoResearchClaw Stage 18 using Zhipu GLM-5.2. This clears the Phase 9
four-condition engineering preacceptance gate. It does not establish a SciTaste
advantage: only one of the four registered task families and one outer runner
seed were exercised, the cells were continued after gate-driven adapter fixes,
and the original Full SciTaste cell contained a generated-code performance
anomaly before the replacement rerun.

## Registered execution

- Protocol: `configs/experiments/matched_budget_study_zhipu_glm52_preacceptance_v1.yaml`
- Launcher: `configs/experiments/study_launchers_zhipu_glm52_preacceptance_v1.yaml`
- Provider/model: Zhipu `glm-5.2`
- Protocol SHA-256: `43e0e87319c469c8d70378405bf56d10f0a078226e331ea2a27343e4c9ba10a2`
- Task/outer seed: `diagnosis-friendly-v1`, seed 7
- AutoResearchClaw commit: `12d3fd809fa9658e91a0328c3280a0e462c78386`
- Canonical project output: `outputs/projects/floor-factorial-claim-verification/`
- Raw output remains in the isolated, Git-ignored execution worktree so its
  absolute paths and hashes remain valid.
- The replacement Full cell is stored separately under
  `outputs/zhipu-glm52-full-scitaste-performance-rerun-v2-2026-09-04/`.

## Results

| Condition | Cell | Status | Primary aggregate | Tokens | Estimated API cost | Open review concerns |
|---|---|---:|---:|---:|---:|---:|
| AutoResearchClaw | `cell-5f2bba14c33ea6ff6526` | succeeded | 0.6169298915 | 124,705 | $0.33930833 | 18 |
| Knowledge RAG | `cell-4a8c7e417934abf65578` | succeeded | 0.0000000000 | 117,429 | $0.31478167 | 23 |
| Taste Library | `cell-6b87d15938f94e2b0954` | succeeded | 0.8471774161 | 122,738 | $0.33666667 | 20 |
| Full SciTaste rerun | `cell-5b0a4ea2e11807ea5bab` | succeeded | 0.9386853333 | 134,652 | $0.36568333 | 20 |

Using the replacement Full cell, the four conditions consumed 499,524 wire
tokens with an adapter estimate of $1.35644000. Every cell records one real
successful experiment, evidence sufficiency 1.0, seven audited manuscript
claims, zero unsupported claims, a source-verified three-seed matrix, and a
Markdown/TeX/PDF paper package. The primary aggregate is a synthetic benchmark
measurement, not a score of GLM-5.2 or a direct measure of research quality.

## Defects exposed and retained

The run sequence and performance rerun exposed adapter, prompt, and generated
program defects:

1. A fresh cell given a late resume hint skipped missing analysis stages. Resume
   selection now rewinds to the earliest absent publication prerequisite.
2. Corrective prose saying a prior critique "incorrectly asserted N=1" was
   rejected as an affirmative single-seed claim. Negated/corrective adverb forms
   are now regression-tested while bare `N=1` remains invalid.
3. Full SciTaste initially hard-coded 6,480 packets although the frozen grid has
   648 packets per seed and 1,944 across three seeds. Every generation and repair
   prompt now receives the contract-derived total.
4. The successful Full program rebuilt its training matrix and refit a linear
   rule for every test example. Its selected execution took 734.58 seconds and
   Stage 13 required runtime repair for an empty topology slice. New prompts
   require feature reuse and at most one fit per seed and condition. The fresh
   replacement selected experiment completed in 0.63 seconds with the full
   1,944-packet, three-seed evidence matrix.
5. The replacement output used `mean_balanced_accuracy` in condition-first seed
   rows and described stale cached/fabricated metrics only to reject them. The
   scanner now accepts that metric alias, and failure-claim auditing recognizes
   explicit corrective/superseded context while preserving true failure gates.
6. Repeated references to the same real figure produced duplicate artifact-path
   entries. Manuscript packaging now returns each copied asset once.

The failed and slow Full attempts remain in their original raw locations rather
than being overwritten. They are dogfooding evidence for SciTaste usability and
defect discovery; they are not automatically promoted to retrieval-eligible
Taste Cases.

## Remaining Phase 9 boundary

The remaining exit work is to execute all 48 commit-pinned cells without manual
continuation, audit the complete artifact set, and collect valid external blinded
expert reviews. The registered Qwen study remains separate; these pilot-scoped
GLM results must not be mixed into its headline comparison. Stage 18 papers are
peer-reviewed drafts with open concerns, not publication-ready manuscripts.
