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
    ├── *.yaml                 # v1-compatible API/remote-host observations
    └── v2/
        ├── gpu_host_local_3090_20260912_v1.yaml
        └── qwen3vl2b_local_20260912_v1.yaml
```

The API manifests store endpoints, model identities, public pricing state, and
credential environment-variable names, never credential values. GPU host
manifests store capabilities and content-bound inventory references. Checkpoint
manifests store exact current tree identity separately from host presence.
Project bindings state why and at what evidence status each project uses a
shared resource.

`compute_catalog_v1.yaml` remains readable as the immutable first inline-layout
snapshot. New work uses v2; do not edit v1 into the new structure.

The catalog is stable identity; observation files are time-stamped facts. The
runtime copies accepted observations into `outputs/resources/observations/`, so
their source version remains auditable without turning an observation into a
reservation or experiment approval.
