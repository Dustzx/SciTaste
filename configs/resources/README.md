# Resource catalog layout

`compute_catalog_v10.yaml` is the current project-superordinate resource index.
Every entry binds one independently reviewable resource manifest by SHA-256.

```text
configs/resources/
├── compute_catalog_v10.yaml
├── assets/
│   └── model_asset_catalog_v1.yaml
├── api/
│   ├── deepseek_v4_flash_v3.yaml       # current V4 identity and tariff
│   ├── deepseek_v4_flash*.yaml         # immutable earlier V4 snapshots
│   ├── deepseek_v41_flash*.yaml        # immutable V4.1 snapshots
│   ├── zhipu_glm53_flash_v3.yaml
│   └── bailian_qwen38_max.yaml
├── gpu/
│   ├── hosts/
│   │   ├── local_3090.yaml
│   │   └── remote_3090_2_verified_20260912.yaml
│   └── checkpoints/
│       ├── qwen3_vl_2b_instruct_local.yaml
│       ├── qwen3_5_4b_local.yaml
│       └── qwen3_5_4b_remote.yaml
├── projects/
│   └── scitaste_self_development_v10.yaml
└── observations/
    ├── *.yaml                 # historical API and remote-host observations
    ├── v2/                    # local v2 observations
    ├── v3/                    # immutable v3 observations
    ├── v4/                    # earlier official/API facts
    ├── v5/                    # current official/API facts
    └── v8/                    # authenticated Generation as Content use
```

API manifests store endpoints, model identities, public pricing state, and
credential environment-variable names, never credential values. The current
bindings use `DEEPSEEK_API_KEY`, `ZAI_API_KEY`, and `DASHSCOPE_API_KEY`, matching
the executable backend configurations. GPU host manifests store capabilities,
content-bound inventory references, and non-secret connection metadata. The
remote `3090-2` entry also declares its SSH alias, host, port, user, password
environment-variable name, and RemoteForward topology.

Checkpoint manifests store exact content identity separately from host
presence. Host-scoped checkpoints name their owning GPU resource, so a remote
path is never probed as though it were a local directory. Project bindings state
why and at what evidence status each project can use a shared resource.

`compute_catalog_v1.yaml` through `compute_catalog_v8.yaml` remain immutable
history. V3 added the then-current DeepSeek V4 Flash identity, the refreshed
GLM-5.3-Flash identity, a verified remote-host snapshot, and content-identical
local and remote Qwen3.5-4B replicas. V4 records the short-lived DeepSeek V4
Flash snapshot. V5 follows the then-observed official alias change back to
`deepseek-flash` / `DeepSeek-V4.1-Flash`. It retains the retired alias only so
historical observations remain addressable; project binding v5 excludes it from
the then-current candidate set. V6 follows the later official change to
`deepseek-v4-flash` / `DeepSeek-V4-Flash`, removes V4.1 from current project
bindings, and preserves every prior file as a historical stratum. V7 and V8
record subsequent project-binding and observation advances. V9 introduces an
explicit selection lifecycle: `current` entries may be newly attached to a
project, `historical` entries remain visible only for provenance, and `disabled`
entries cannot be selected for new work. New work uses v9 instead of relabeling
prior records.
V10 registers a current authenticated GLM-5.3-Flash Generation as Content
generation/edit observation and advances only that project binding to verified.
It does not change DeepSeek availability, select an experiment model, or claim
scientific quality.

Generation as Content projects both a project's attached resources and compatible
catalog alternatives. A user-reviewed, model-authored resource directive may add
only a `current` catalog entry to an existing compatible project role and may
reorder role-local priorities. Applying that directive archives the predecessor
binding and creates a project-owned receipt. It does not read a credential, probe
a host, contact a provider, reserve compute, launch a workload, or authorize an
experiment. Shared endpoint definitions, observations, and secret-value
administration remain outside the project surface.

`assets/model_asset_catalog_v1.yaml` indexes bounded local and remote discovery
inventories. Discovery records what already exists, not what the ICLR experiment
should use. Only content-verified snapshots enter the compute catalog;
structurally complete but unhashed models remain candidates, and the partial
remote Qwen3.5-9B snapshot is explicitly blocked. Scientific design selects a
model first, after which exact license, hash, loading, and runtime preflights are
completed only for selected candidates.

The catalog is stable identity; observation files are time-stamped facts. The
runtime copies accepted observations into `outputs/resources/observations/`, so
their source version remains auditable without turning an observation into a
reservation or experiment approval.

The Zhipu observations separate the retained 2026-09-05 authenticated response,
the official identity snapshot, and the 2026-09-14 project-owned Generation as
Content generation/edit. The newest observation establishes current product-path
availability only; it is not a formal experiment result.

Machine-local access material belongs only in the ignored runtime plane:

```text
outputs/resources/access/
├── credentials.env   # mode 0600; values never enter status JSON
└── STATUS.json       # explicit bound/missing partition, no secret values
```

`scitaste resource access-status` reads only credential names declared by the
catalog. It rejects symlinks, permissive file modes, duplicate assignments, and
unscoped variables. A bound credential is not a connectivity result or
experiment authorization.
