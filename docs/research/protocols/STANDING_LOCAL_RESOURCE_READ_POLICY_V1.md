# Standing local-resource read policy v1

The project owner established a standing rule on 2026-09-13: already-local
SciTaste resources do not need a new conversational approval each time they are
read. The machine-readable scope is
`configs/evaluation/acquisition/standing_owner_local_read_policy_v1.yaml`.

This removes a coordination bottleneck, not the evidence boundary. A reader
still binds an acquisition receipt or existing artifact hash, enforces byte and
item limits, rejects symlinks and path escape, treats content as inert data, and
keeps derived outputs inside the owning project. These records make the read
reproducible; they are not requests for another owner decision.

The standing rule covers bounded parsing, structure/identity inspection,
archive member listing without extraction, local visual inspection, and
deterministic projection into a project-owned derivative. It does not authorize
new downloads, uploads, external-link resolution, archive extraction, source or
archive execution, API/model calls, GPU jobs, human recruitment, source
admission, or formal experiment launch. Those state-changing operations retain
their existing gates.

For the AAAR pilot, the prior per-run approval files remain immutable provenance.
New local reads do not wait for another approval. The content audit and quality
projection still verify the exact request, receipt, source hashes, and complete
sixteen-item population before reading any record.
