# Bounded native code repair acceptance — 2026-09-09

## Scope

This is an offline engineering acceptance of one conditional native-source
repair inside Full Workflow. It tests orchestration, evidence integrity,
readmission, isolated execution, recovery semantics, and project packaging. It
does not test live-model repair quality or scientific effectiveness.

## Registered condition

- Full Workflow config:
  `configs/workflows/full_offline_code_repair_v1.yaml`
- Initial source fixture:
  `configs/experiments/native_code_generation_scripted_rejected_v1.yaml`
- Repair fixture:
  `configs/experiments/native_code_repair_scripted_support_v1.yaml`
- Project: `scitaste-offline-code-repair-full`
- Run:
  `2026-09-09__scitaste-native__bounded-code-repair-v1__seed-07`
- Workflow config SHA-256:
  `6a431d46966cb5fd6e69c54797ec097462c77c2b796d72fb3a077d2c906cb5b5`

The initial output deliberately imported `os`, which is outside the unchanged
admission allowlist. Its static verdict was `rejected`; no initial source was
admitted. The configured repair node was then invoked once and only once.

## Result

- Full Workflow status: `complete`
- Initial static verdict: `rejected`
- Repair readmission verdict: `accepted`
- Repair attempts: `1 / 1`
- Native execution records: `18`
- Evidence primary metric, `correct_pivot_delta`: `0.10000000000000002`
- Model-node ledger: `2` accepted entries, `0` pending entries, `0` attempts
  requiring recovery
- Ledger tokens: `1,100` input, `1,150` output, `2,250` total
- Ledger cost: `$0.00` scripted
- Ledger head SHA-256:
  `df3e40c18e7bd48a4fa3f3c0c7e7c3adfd823f6e04d9f47cd81c8dbffd234aaa`
- Full-run summary SHA-256:
  `dd0c9e16828781bb19bd7fc953af76ab94d3d522cd1e35725d4bd5cf6bf844b9`

The rejected source SHA-256 is
`1a27f97e689cf0572dae85f83d245a8e3ce8eef34b4899e373ad7875ec558518`.
The repair source and the executed admitted source are byte-identical at
`ad9a1cf5aa91606a8c68943685d858ffcf0bbaa31e6fd0f9a2c58f8a96bdfd33`.
The original generation record and repair record remain separate physical
artifacts with file SHA-256 values
`ae878dabce1cacdd279c968495d1ad878e9cc932cd562e095810270723badf23`
and `fdf22826ae657a2599b404b63c36ba1be1b791ecb80fbf86cc6a239b69230011`.

The project owns the complete run under
`outputs/projects/scitaste-offline-code-repair-full/`, including the four stage
records and an integration-fixture paper bundle with Markdown, TeX, PDF,
assessment, build record, and editable figure. Its 63-word paper is correctly
registered as `integration-fixture`, not a substantive research manuscript.

## Automated checks

- Focused native generation/repair and Full Workflow tests: `20 passed`
- Full repository suite with statement and branch coverage: `983 passed`, `83%`
- Ruff: passed
- `git diff --check`: passed

The tests additionally establish that an accepted initial proposal makes zero
repair calls, a completed repair is reused without a second backend call, a
replacement that still violates policy remains durably rejected, and no rejected
source reaches the admitted execution path.

## Remaining gates

- Run the same bounded contract with a priced live model and externally auditable
  cost evidence.
- Add runtime-failure diagnosis and repair as a separate policy, budget, and
  recovery contract; it is intentionally not implied by static repair.
- Evaluate repair success and scientific correctness on registered blinded tasks.
- Do not use this scripted fixture as evidence that SciTaste outperforms another
  research system.
