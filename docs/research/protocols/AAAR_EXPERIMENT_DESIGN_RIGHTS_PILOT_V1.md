# AAAR experiment-design rights pilot v1

Status: **exact download request prepared; owner approval required**. This
protocol authorizes no download, ingestion, human annotation, model call, GPU
work, or experiment by itself.

## Why this is the first core Taste resource

SciTaste's primary mechanism claim requires real scientific decisions rather
than synthetic prompts. AAAR-1.0 exposes experiment-design records derived from
published papers, making it a useful source for testing whether a reference can
be converted into a bounded decision precedent. It is not accepted wholesale:
the packaged dataset's MIT declaration does not replace the original paper's
license.

The v1 pilot therefore starts with the 100 pinned `Experiment_Design` JSON
records and admits only paper IDs whose arXiv OAI record explicitly declares
CC-BY-4.0 or CC0. Forty-four records pass that metadata rule. The sixteen-file
proposal enriches category diversity before looking at any source body: all
nine eligible non-`cs.CL` records are retained, and seven `cs.CL` records are
selected by a published SHA-256 key. This is instrument calibration, not a
representative prevalence sample or a formal benchmark split.

The exact population, license counts, selection key, source groups, observed
HEAD metadata, file ceilings, and stopping rules are recorded in
`docs/research/data/aaar_experiment_design_rights_pilot_scope_v1.yaml`.

## What approval permits

Approval of the later request hash permits one atomic, download-only transaction:

- sixteen pinned `data_text.json` files;
- one immutable Hugging Face dataset revision;
- no redirects and no host changes;
- 3 MiB aggregate ceiling;
- no archives, papers, figures, images, model outputs, or linked assets.

It does not permit parsing those files into cases, showing their content to a
model, asking humans to label them, transferring a checkpoint, or running an
experiment. Acquisition produces a self-hashed receipt and stops.

## Post-download admission

The downloaded bytes remain quarantined. A separate inspection must establish
record identity, field structure, attribution preservation, absence of
transitively acquired assets, and source-group isolation. Only after that audit
may SciTaste propose a new ingestion-and-curation package. The proposal must
define which exact source projection a model may see, how two independent humans
judge source fidelity and transfer boundaries, and which source groups are held
out from Taste precedents.

No observed experiment in a paper is automatically a preferred action. No model
label is accepted as ground truth. Failed, ambiguous, or rights-incompatible
records remain visible in the acquisition audit and are excluded rather than
repaired or silently replaced.

## Relationship to the ICLR evidence program

This pilot advances H1/H2 treatment construction: it supplies real candidate
source material for the reference-to-Taste abstraction chain. It cannot support
an effectiveness result. Formal SciTasteBench v2 still requires natural binary
decision cases across six families, source-group-disjoint Taste precedents, at
least two conflict-cleared human labels per case, a frozen power analysis, and
matched model conditions. ARIES and public OpenReview sources remain necessary
for writing/review decisions and for broader source diversity.

