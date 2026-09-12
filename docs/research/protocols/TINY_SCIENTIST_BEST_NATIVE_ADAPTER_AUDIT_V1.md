# TinyScientist best-native adapter audit v1

Audit date: 2026-09-12

Scope: static inspection of the official TinyScientist `v0.1.3` source at
commit `9c4f1a89411e05857c748db9731c33500516e9c6`. This record authorizes no
checkout, installation, provider call, data acquisition, generated-code
execution, Docker action, or experiment.

## Identity and license

The archival EMNLP 2025 System Demonstrations paper links the
`ulab-uiuc/tiny-scientist` repository. The pinned root `LICENSE` is an MIT
license naming Haofei Yu and has SHA-256
`389d00652aaea7a870e1128c95df7171580f347856b3993f8a0890f1a1cf09ae`.
That file is the applicable notice for use of the covered repository source.
Its copyright and permission notice must be preserved.

The same commit's `pyproject.toml` says `Apache 2.0 License`, while the root
license says MIT. This packaging-metadata inconsistency is retained as a
disclosure and should be corrected upstream or reviewed before redistributing a
wheel. It does not justify erasing the explicit root MIT grant or treating the
source as proprietary. Dependencies, generated experiment code, downloaded
datasets, paper templates, and third-party assets remain separately licensed.

## Native execution behavior

The pinned `TinyScientist` constructor propagates one model string to safety,
thinking, coding, writing, and reviewing modules. The documented default is
`gpt-4o`; the fixed registry also lists `gpt-4o-2024-08-06`,
`deepseek-chat`, and `deepseek-reasoner`. The DeepSeek client is hard-coded to
`https://api.deepseek.com`, but it does not register the current
`deepseek-flash`/`deepseek-v4-flash` callable identifier. A generic
OpenAI-compatible route prefixes the supplied model name and has not been shown
to preserve the exact DeepSeek request identity. No current DeepSeek model is
therefore considered an unchanged-core matched backbone.

The coder delegates edits to Aider, generates `experiment.py`, prefers Docker,
falls back to host execution, may install missing Python packages, and removes
failed run directories. The thinker and reviewer perform live literature
searches. These are meaningful parts of the real system, but they conflict with
SciTaste's frozen-network, failure-retention, and complete-telemetry contract
until an isolated adapter demonstrates otherwise.

Static source identities used by this audit:

- `tiny_scientist/scientist.py`:
  `ee7257076a503b8f72819195cde17d88be00dcdf66591410e1deac5fae5c0001`;
- `tiny_scientist/utils/llm.py`:
  `c64792389add5b2fc45636f1b55527fcf3b6bd9469defbbbdfb060cb59cba644`;
- `tiny_scientist/coder.py`:
  `c027188280d79c215d7d5e8fdccf71dc021dc8f629d5199649d15a781b579124`.

## Gate verdicts

- License identity and local non-redistributive code use: verified for the
  MIT-covered root source; preserve the metadata conflict as a limitation.
- Core unchanged: pending an isolated exact-commit checkout and zero-diff
  attestation.
- Task mapping: blocked until an MLRC task package can be translated to the
  native intent/idea interface without withholding or adding information.
- Model mapping: a best-native `gpt-4o-2024-08-06` candidate is statically
  accepted by the code but has no authenticated availability observation or
  project credential. The current DeepSeek identity is not natively supported.
- Sandbox: blocked because network search, Aider, Docker/host fallback, package
  installation, and generated-code execution need explicit isolation.
- Telemetry: blocked because calls, retries, token classes, searches,
  experiments, cost, wall time, GPU allocation/use, and interventions are not
  aggregated into a SciTaste cell receipt.
- Artifacts: pending a failure-inclusive mapping of idea, source, experiment,
  paper, review, logs, and environment bytes.
- Failure/resume: blocked because failed directories may be deleted and no
  content-bound cell resume contract has been demonstrated.

## Scientific use

TinyScientist may enter only a separately preregistered `best_native` external
lane after the remaining adapter gates pass. That lane must set
`model_effects_confounded=true`; it can provide ecological comparison and
failure evidence, not a causal estimate of Scientific Taste. It must never be
replaced by a pseudo-implementation, nor may a source patch be called
unchanged-core.
