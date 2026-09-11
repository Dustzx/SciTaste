# Shared compute resources

SciTaste maintains compute resources above individual research projects. A GPU
host or API model can serve several projects, while each project keeps its own
experiment proposal, approval, result, and paper evidence.

The implementation has two planes:

- `configs/resources/compute_catalog_v1.yaml` is the tracked, secret-free source
  of stable resource identity and capability. It currently names DeepSeek
  V4.1 Flash, Zhipu GLM-5.3-Flash, and the eight-GPU `3090-2` host.
- `outputs/resources/` is the machine-local runtime registry, alongside rather
  than inside `outputs/projects/`. It stores content-bound observations of
  changing availability. It is ignored by Git because observations are local
  operational state.

Provider credentials and SSH passwords never enter either plane. Catalogs store
only credential environment-variable names or an operator-managed access
profile. A resource observation cannot authorize an experiment, reserve a
device, change a project, or execute a workload.

## Current observations

The tracked GPU baseline remains the read-only 2026-09-11 inventory: eight RTX
3090 devices were verified, about 59 GB root storage was then available, and
the remote Qwen checkpoint was absent. On 2026-09-12 the project owner reported
that cleanup increased free storage to approximately 200 GB. This is retained
as `reported`, not silently promoted to `verified`; an automated SSH observation
must replace it before checkpoint transfer or a GPU pilot.

The live official DeepSeek table was inspected on 2026-09-12. It names callable
ID `deepseek-flash`, served version `DeepSeek-V4.1-Flash`, and peak prices of
USD 0.006/M cached-input, USD 0.30/M uncached-input, and USD 1.20/M output
tokens. It also says retired `deepseek-v4-flash` aliases are served by V4.1.
The owner's successful same-day call is kept as a separate reported observation
without storing a key or response bytes.

## Commands

Validate the shared catalog and its local evidence without contacting anything:

```bash
scitaste resource inspect \
  --catalog configs/resources/compute_catalog_v1.yaml \
  --evidence-root .
```

Create the project-superordinate local registry and register existing bounded
observations:

```bash
scitaste resource init \
  --catalog configs/resources/compute_catalog_v1.yaml \
  --evidence-root . --outputs-root outputs

scitaste resource observe \
  --catalog configs/resources/compute_catalog_v1.yaml \
  --observation configs/resources/observations/gpu_host_3090_2_storage_owner_20260912_v1.yaml \
  --outputs-root outputs

scitaste resource status \
  --catalog configs/resources/compute_catalog_v1.yaml \
  --outputs-root outputs
```

Initialization is idempotent only when the exact catalog file and semantic
hashes still match. Observation publication copies the exact YAML, records its
hash and size, and uses a self-hashed record. Drift, symlinks, unknown resource
IDs, duplicate observation IDs, and API/GPU type confusion fail closed.

This slice establishes inventory and observation ownership. Exclusive GPU
reservation, concurrent allocation, API quota leasing, and project usage
roll-up remain a later scheduler layer; until then the immutable evaluation
proposal and its explicit owner approval remain the execution authority.
