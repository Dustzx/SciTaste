# Shared compute resources

SciTaste maintains compute resources above individual research projects. A GPU
host or API model can serve several projects, while each project keeps its own
experiment proposal, approval, result, and paper evidence.

The implementation has two planes:

- `configs/resources/compute_catalog_v2.yaml` is the tracked, secret-free index
  of stable resource identity and capability. Each API model, GPU host, and
  checkpoint has its own hash-bound manifest below `configs/resources/api/` or
  `configs/resources/gpu/`; v1 remains readable history.
- `outputs/resources/` is the machine-local runtime registry, alongside rather
  than inside `outputs/projects/`. It stores content-bound observations of
  changing availability, catalog predecessors, and exact per-project resource
  bindings. It is ignored by Git because these are local operational state.

Provider credentials and SSH passwords never enter tracked definitions,
observations, bindings, or status records. API manifests store only
`DEEPSEEK_API_KEY`, `ZAI_API_KEY`, or `DASHSCOPE_API_KEY` as binding names; these
now match the executable DeepSeek, Zhipu, and Bailian backend contracts. GPU
manifests store a local-process profile or explicit non-secret SSH connection
metadata plus a password environment-variable name. A resource observation or
project binding cannot authorize an experiment, reserve a device, change
scientific evidence, or execute a workload.

The one exception to “no secret values in the registry” is an explicitly local,
Git-ignored access file at `outputs/resources/access/credentials.env`. It is a
mode-`0600` runtime input rather than evidence: the access inspector consumes
its values only to determine whether each declared name is non-empty and never
copies, hashes, or prints them. The neighboring `STATUS.json` contains only the
bound/missing partition. This keeps actual local usability visible without
turning a weak password hash or bearer key into a tracked artifact.

## Explicit resources

| Class | Resource | Current role/state |
|---|---|---|
| API | `deepseek-v41-flash` | primary API candidate; official identity verified and owner reports a successful current call |
| API | `zhipu-glm53-flash` | separate robustness candidate; exact GLM-5.3-Flash authenticated call still pending |
| API | `bailian-qwen38-max` | historical provenance only; blocked by the latest recorded arrearage response |
| GPU | `gpu-host-local-3090` | verified local 1×RTX 3090 development/preflight host |
| GPU | `gpu-host-3090-2` | remote 8×RTX 3090 scale-out host; approximately 200 GB free is owner-reported pending a fresh probe |
| checkpoint | `qwen3-vl-2b-local-47f9c0e0` | verified current local Qwen3-VL-2B-Instruct tree |

The remote scale-out manifest explicitly resolves SSH alias `3090-2` to host
`10.7.33.15`, port 22, user `ubuntu`, password binding
`SCITASTE_GPU_3090_2_SSH_PASSWORD`, and RemoteForward `7891 ->
127.0.0.1:7890`. These fields describe how an authorized scheduler could reach
the host; they do not perform a login or persist the password.

`configs/resources/projects/scitaste_self_development.yaml` explicitly binds all
six resources to the self-development project with primary, robustness,
historical, development, scale-out, and checkpoint roles. The registered copy
lives at `outputs/resources/projects/scitaste-self-development/`; it does not
duplicate the resources inside the project paper/run tree.

## Current observations

The tracked GPU baseline remains the read-only 2026-09-11 inventory: eight RTX
3090 devices were verified, about 59 GB root storage was then available, and
the remote Qwen checkpoint was absent. On 2026-09-12 the project owner reported
that cleanup increased free storage to approximately 200 GB. This is retained
as `reported`, not silently promoted to `verified`; an automated SSH observation
must replace it before checkpoint transfer or a GPU pilot.

A new read-only local inventory verifies one RTX 3090, 24,576 MiB total VRAM,
22,947 MiB free at capture, and 155,972,894,720 bytes free on the weights
filesystem. Full-byte hashing of the current Qwen3-VL-2B-Instruct directory
returned `47f9c0e0e48a54c74fb0b2b0ffa7a182fed381d5ed49a0200872038d1c286d34`
for 4,266,653,057 bytes. The older GPU experiment proposal names
`8e95e5f6...`; this mismatch remains visible and requires a new proposal or the
exact old snapshot rather than silent substitution.

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
  --catalog configs/resources/compute_catalog_v2.yaml \
  --evidence-root .
```

Create the project-superordinate local registry and register existing bounded
observations:

```bash
scitaste resource update-catalog \
  --catalog configs/resources/compute_catalog_v2.yaml \
  --evidence-root . --outputs-root outputs

scitaste resource bind-project \
  --catalog configs/resources/compute_catalog_v2.yaml \
  --binding configs/resources/projects/scitaste_self_development.yaml \
  --outputs-root outputs

# After a content-bound catalog change, archive and replace an existing binding:
scitaste resource update-project-binding \
  --catalog configs/resources/compute_catalog_v2.yaml \
  --binding configs/resources/projects/scitaste_self_development.yaml \
  --outputs-root outputs

scitaste resource status \
  --catalog configs/resources/compute_catalog_v2.yaml \
  --outputs-root outputs

scitaste resource access-status \
  --catalog configs/resources/compute_catalog_v2.yaml \
  --credential-file outputs/resources/access/credentials.env \
  --output outputs/resources/access/STATUS.json
```

The access-status command performs no API request, SSH login, GPU probe, model
load, reservation, or experiment. `access_binding_complete` means only that the
future executor can resolve the declared local credential name. Provider
availability and execution approval remain independent gates.

Catalog update preserves the predecessor registry and every compatible
observation. Project binding publication copies the exact YAML and records its
hash, size, catalog semantic hash, and self-hashed record. Updating a binding
moves the exact predecessor under `outputs/resources/project-binding-history/`
before publishing its replacement. Definition drift, symlinks, unknown resource
IDs, duplicate IDs, API/GPU/checkpoint type confusion, and project/catalog
mismatch fail closed.

This slice establishes inventory and observation ownership. Exclusive GPU
reservation, concurrent allocation, API quota leasing, and project usage
roll-up remain a later scheduler layer; until then the immutable evaluation
proposal and its explicit owner approval remain the execution authority.
