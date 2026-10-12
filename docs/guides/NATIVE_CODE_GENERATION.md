# Native code generation

SciTaste can ask a structured model to propose one bounded CPU experiment, but
the response never becomes executable directly. The supported path is:

```text
trusted generation brief
  -> durable model-node request/raw-response ledger
  -> proposal-only generated.py + proposal.json
  -> deterministic AST/import/metric admission
  -> [on rejection only] one proposal-only repair + identical readmission
  -> byte-identical admitted/experiment.py
  -> no-network Bubblewrap execution
```

The model controls only `source_code`, a bounded rationale, and bounded
assumptions. The project configuration controls experiment and metric identity,
runtime limits, allowed imports, source limits, provider/model identity, token
and cost ceilings, and live authorization. Neither the response nor the derived
proposal contains an action, tool, command, destination path, dependency,
transition, or execution permission.

## Offline acceptance

Previewing the complete configuration performs no model call and creates no
project directory:

```bash
scitaste run full \
  --config configs/workflows/full_offline_code_generation_v1.yaml \
  --run-id generated-code-seed-07 \
  --output /tmp/scitaste-codegen-preview \
  --dry-run
```

The actual run uses a deterministic scripted backend to exercise the same
request, ledger, extraction, admission, isolation, experiment, writing, and
paper-publication path without network access:

```bash
scitaste run full \
  --config configs/workflows/full_offline_code_generation_v1.yaml \
  --run-id generated-code-seed-07 \
  --seed 7 \
  --output /tmp/scitaste-codegen-acceptance
```

The configured provider envelope allows up to 8,192 output tokens. This is a
per-request safety ceiling, not a global limit on SciTaste development or paper
generation. The static source limit remains independently fixed at 65,536
UTF-8 bytes.

The conditional repair acceptance deliberately starts from a rejected source,
performs exactly one scripted repair call, repeats the unchanged deterministic
admission policy, and executes only the readmitted replacement:

```bash
scitaste run full \
  --config configs/workflows/full_offline_code_repair_v1.yaml \
  --run-id repaired-code-seed-07 \
  --seed 7 \
  --output /tmp/scitaste-code-repair-acceptance
```

`max_attempts` is schema-fixed to `1`. This is a hard orchestration boundary,
not a tuning default. When the initial proposal is accepted, no repair input,
ledger entry, model call, or repair artifact is created.

## Evidence layout

One project run owns all generation and execution evidence:

```text
runs/<run-id>/
  model_nodes/
    ledger/
    recordings/
    pending/
    attempts/
  native_execution/context/code_generation/
    GENERATION_INPUT.json
    result/
      generated.py
      proposal.json
      GENERATION.json
    repair/                       # only after static rejection
      REPAIR_INPUT.json
      result/
        repaired.py
        proposal.json
        REPAIR.json
  native_execution/context/code/
    proposed.py
    POLICY.json
    PROPOSAL.json
    ADMISSION.json
    CODE.json
    admitted/experiment.py       # acceptance only
```

`GENERATION_INPUT.json` is written before provider access. It binds the original
project revision, stable invocation ID, full-workflow fingerprint, typed brief,
profile, and policy. The model ledger is authoritative for the exact structured
request, decoded raw response and SHA-256, provider-returned model, usage,
latency, cost evidence, and typed result.

`GENERATION.json` binds the accepted ledger entry to exact generated source and
the derived model-attributed proposal. It explicitly remains proposal-only and
non-executable. `CODE.json` belongs to the independent deterministic admission
stage. The sandbox reads only `code/admitted/experiment.py`; the native execution
record retains that exact input locator and hash.

`REPAIR_INPUT.json` binds the rejected generation record, rejected source and
admission fingerprints, typed generation brief, and static violations before
the repair call. `REPAIR.json` binds the second ledger entry to `repaired.py`,
its model provenance, and the second independent admission verdict. The
original `generated.py`, proposal, and rejection remain immutable. Repair can
replace only source, rationale, assumptions, and a bounded change summary; it
cannot replace trusted identity, metrics, policy, paths, budgets, or permission.

## Resume rules

- A complete generation record is revalidated against the full model ledger and
  reused without invoking the backend.
- If the ledger committed but result publication was interrupted, resume derives
  the same source/config from that committed result and performs no second model
  completion.
- A complete live response recording can finish the ledger through the existing
  recovery backend without contacting the provider again.
- A call that may have started but has no complete recording is unknown-cost and
  is not retried automatically.
- Rejected model output stays in the ledger. Rejected static admission retains
  its proposed source and verdict. If repair is configured, that exact rejection
  is the only trigger for one separately ledgered replacement.
- A complete repair record is revalidated and reused without invoking its
  backend. Interruption after its ledger commit follows the same recorded-response
  recovery boundary as generation.
- A second rejected static verdict is terminal: no admitted path is created and
  no additional repair call is permitted.
- Any input, ledger, generated source, proposal, policy, or admission drift fails
  closed.

## Live engineering probe

The Zhipu condition is deliberately double-gated:

```bash
export ZAI_API_KEY=...
scitaste run full \
  --config configs/workflows/full_zhipu_glm53_flash_code_generation_probe_v1.yaml \
  --run-id glm53-codegen-seed-07 \
  --output /tmp/scitaste-glm53-codegen \
  --allow-live-model-nodes
```

The config uses `glm-5.3-flash`, `thinking.type=enabled`, and
`reasoning_effort=low`; the provider reports that this model cannot disable
thinking. It is explicitly an unpriced engineering probe. The current runtime
therefore retains transport/schema evidence but rejects acceptance when no
auditable USD rate is available. Do not change the rate to zero merely to pass
the gate. Formal live acceptance requires a dated provider price source, a
confirmed pricing configuration, a fresh run identity, deterministic admission,
and successful isolated execution.

The API key is read only from `ZAI_API_KEY`. Credentials, generated outputs,
provider responses, and recordings remain outside Git.

## Current limitations

- Only one bounded Python CPU experiment proposal is integrated.
- Native code generation and built-in evidence/tool model nodes now compose on
  one ledger through a shared extension registry. Every entry remains type-
  checked; an earlier advisory receipt binds its exact historical prefix while
  final verification covers later cumulative entries.
- One conditional source-repair attempt is integrated for deterministic static
  admission failures. It preserves the original negative evidence, exposes no
  execution authority, and cannot iterate beyond one attempt.
- Dataset mounts, GPU execution, package installation, open-web access, shell
  commands, and provider tools are not exposed.
- Scripted acceptance establishes orchestration and safety properties, not model
  quality or scientific effectiveness.
- Runtime-failure diagnosis/repair, priced live repair acceptance, and matched
  external evaluation remain pending.
