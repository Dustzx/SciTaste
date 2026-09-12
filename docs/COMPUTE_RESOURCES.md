# Shared compute resources

SciTaste maintains compute resources above individual research projects. A GPU
host or API model can serve several projects, while each project keeps its own
experiment proposal, approval, result, and paper evidence.

The implementation has two planes:

- `configs/resources/compute_catalog_v3.yaml` is the tracked, secret-free index
  of stable resource identity and capability. Each API model, GPU host, and
  checkpoint has its own hash-bound manifest below `configs/resources/api/` or
  `configs/resources/gpu/`; v1 and v2 remain readable history.
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
| API | `deepseek-v4-flash` | current official candidate; identity and pricing verified, local credential and authenticated response absent |
| API | `deepseek-v41-flash` | retained historical identity only; not silently relabeled as the current official model |
| API | `zhipu-glm53-flash` | current official multimodal candidate and locally bound key; current connectivity unprobed |
| API | `bailian-qwen38-max` | historical provenance only; blocked by the latest recorded arrearage response |
| GPU | `gpu-host-local-3090` | verified local 1×RTX 3090 development/preflight host |
| GPU | `gpu-host-3090-2` | verified remote 8×RTX 3090 host; all devices idle and 311,710,777,344 storage bytes free at the read-only observation |
| checkpoint | `qwen3-vl-2b-local-47f9c0e0` | verified current local Qwen3-VL-2B-Instruct tree |
| checkpoint | `qwen3-5-4b-local-b4e05070` | content-verified local Qwen3.5-4B asset; not selected for an experiment |
| checkpoint | `qwen3-5-4b-remote-b4e05070` | host-scoped replica of the same Qwen3.5-4B bytes; not selected for an experiment |

The remote scale-out manifest explicitly resolves SSH alias `3090-2` to host
`10.7.33.15`, port 22, user `ubuntu`, password binding
`SCITASTE_GPU_3090_2_SSH_PASSWORD`, and RemoteForward `7891 ->
127.0.0.1:7890`. These fields describe how an authorized scheduler could reach
the host; they do not perform a login or persist the password.

`configs/resources/projects/scitaste_self_development_v3.yaml` explicitly binds
all nine current and historical resources to the self-development project. The
two Qwen3.5-4B paths carry `asset-inventory` roles only; availability cannot
select the paper backbone. The registered copy
lives at `outputs/resources/projects/scitaste-self-development/`; it does not
duplicate the resources inside the project paper/run tree.

## Discovered assets versus selected experimental resources

`configs/resources/assets/model_asset_catalog_v1.yaml` content-binds two bounded
inventories. The local weights root contains 18 top-level assets: 15 model or
vision-component candidates and three experiment/project directories. The
bounded remote search found eight model paths. Qwen3.5-4B was independently
full-tree hashed on both hosts and produced the same digest; the remote
Qwen3.5-9B directory is blocked because one of four weight shards, the index,
and tokenizer files are absent. Other models remain structurally discovered but
unhashed.

This inventory is deliberately not an experiment menu. The ICLR design first
chooses an estimand, comparison systems, task distribution, and model-control
policy. Only then may an already present asset receive license review, a full
hash, a bounded load check, and an experimental role. This prevents hardware
convenience from determining the scientific question.

## Current observations

The 2026-09-12 read-only SSH observation supersedes the earlier capacity report:
all eight RTX 3090 devices exposed 24,576 MiB total and 24,124 MiB free at zero
utilization, driver 570.211.01, Python 3.12.3, Docker, and bubblewrap. The
`/media/sdb` mount had 311,710,777,344 bytes free. No remote file was changed,
no checkpoint was transferred, and no model was loaded.

A new read-only local inventory verifies one RTX 3090, 24,576 MiB total VRAM,
22,947 MiB free at capture, and 155,972,894,720 bytes free on the weights
filesystem. Full-byte hashing of the current Qwen3-VL-2B-Instruct directory
returned `47f9c0e0e48a54c74fb0b2b0ffa7a182fed381d5ed49a0200872038d1c286d34`
for 4,266,653,057 bytes. The older GPU experiment proposal names
`8e95e5f6...`; this mismatch remains visible and requires a new proposal or the
exact old snapshot rather than silent substitution.

The live official DeepSeek table was re-inspected on 2026-09-12. It currently
names callable ID `deepseek-v4-flash`, version `DeepSeek-V4-Flash-0731`, a 1M
context window, and tool calls. The catalog uses the current peak prices—USD
0.014/M cached input, USD 0.44/M uncached input, and USD 1.32/M output—as
conservative ceilings; off-peak execution can cost less. The earlier `deepseek-flash` /
`DeepSeek-V4.1-Flash` record remains in v3 as historical provenance, not as the
current identity. Because no DeepSeek credential is locally bound, the current
model remains pending until a separately approved authenticated identity probe.
The future probe must use the sentinel-bracketed temporal protocol in
`docs/API_MODEL_IDENTITY.md`; a returned alias alone is not a frozen checkpoint.

The official Zhipu page now identifies `glm-5.3-flash` as a native multimodal
model with a 1M context window, 128K maximum output, thinking, function calling,
caching, and structured output. The retained 2026-09-05 Zhipu recording verifies one authenticated
`glm-5.3-flash` request and response, including a provider request ID and 1,588
reported tokens. The shared observation binds the raw response hash and the
recording's self-reported hash without copying response content or credentials.
This is historical access evidence, not a fresh connectivity result; the
project binding therefore remains `pending` until a separately approved current
preflight is performed.

## Commands

Validate the shared catalog and its local evidence without contacting anything:

```bash
scitaste resource inspect \
  --catalog configs/resources/compute_catalog_v3.yaml \
  --evidence-root .
```

Create the project-superordinate local registry and register existing bounded
observations:

```bash
scitaste resource update-catalog \
  --catalog configs/resources/compute_catalog_v3.yaml \
  --evidence-root . --outputs-root outputs

scitaste resource bind-project \
  --catalog configs/resources/compute_catalog_v3.yaml \
  --binding configs/resources/projects/scitaste_self_development_v3.yaml \
  --outputs-root outputs

# After a content-bound catalog change, archive and replace an existing binding:
scitaste resource update-project-binding \
  --catalog configs/resources/compute_catalog_v3.yaml \
  --binding configs/resources/projects/scitaste_self_development_v3.yaml \
  --outputs-root outputs

scitaste resource status \
  --catalog configs/resources/compute_catalog_v3.yaml \
  --outputs-root outputs

scitaste resource access-status \
  --catalog configs/resources/compute_catalog_v3.yaml \
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
