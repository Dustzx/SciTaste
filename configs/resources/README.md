# Resource catalog layout

`compute_catalog_v2.yaml` is the current project-superordinate resource index.
Every entry binds one independently reviewable resource manifest by SHA-256.

```text
configs/resources/
├── compute_catalog_v2.yaml
├── api/
│   ├── deepseek_v41_flash.yaml
│   ├── zhipu_glm53_flash.yaml
│   └── bailian_qwen38_max.yaml
├── gpu/
│   ├── hosts/
│   │   ├── local_3090.yaml
│   │   └── remote_3090_2.yaml
│   └── checkpoints/
│       └── qwen3_vl_2b_instruct_local.yaml
├── projects/
│   └── scitaste_self_development.yaml
└── observations/
    ├── *.yaml                 # API and remote-host observations
    └── v2/
        ├── gpu_host_local_3090_20260912_v1.yaml
        └── qwen3vl2b_local_20260912_v1.yaml
```

The API manifests store endpoints, model identities, public pricing state, and
credential environment-variable names, never credential values. The current
bindings use `DEEPSEEK_API_KEY`, `ZAI_API_KEY`, and `DASHSCOPE_API_KEY`, matching
the executable backend configurations. GPU host manifests store capabilities,
content-bound inventory references, and non-secret connection metadata. The
remote `3090-2` entry also declares its SSH alias, host, port, user, password
environment-variable name, and RemoteForward topology. Checkpoint manifests
store exact current tree identity separately from host presence. Project
bindings state why and at what evidence status each project uses a shared
resource.

`compute_catalog_v1.yaml` remains readable as the immutable first inline-layout
snapshot. New work uses v2; do not edit v1 into the new structure.

The catalog is stable identity; observation files are time-stamped facts. The
runtime copies accepted observations into `outputs/resources/observations/`, so
their source version remains auditable without turning an observation into a
reservation or experiment approval.

The Zhipu observation records the retained 2026-09-05 authenticated
`glm-5.3-flash` response by its provider-response and recording hashes. It
establishes historical model access only; it does not claim that the account is
reachable today and does not perform a new provider call.

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
