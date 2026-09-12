# AAAR post-acquisition pipeline v1

Status: **transition contract frozen; no content access or execution authorized**.
The machine-readable contract is
`configs/evaluation/admission/aaar_post_acquisition_pipeline_v1.yaml`.

This closes the planning gap between an approved download and a real Taste
pilot. Downloaded files do not become model context. They first remain immutable
and quarantined while the receipt, exact local bytes, item set, and absence of
unregistered files are verified without parsing source content.

Content access is a second owner decision. Once approved, a deterministic audit
may parse only the sixteen local JSON files under bounded depth and string-size
limits. It inventories the observed schema, checks embedded paper identity, and
never resolves links or fetches adjacent assets. The audit cannot decide that a
paper's observed action is correct.

That boundary is now executable in `scitaste.evaluation.json_content_audit`.
`scitaste evaluation acquisition-content-approve` creates a new immutable
authorization bound to the approved acquisition-request file, self-hashed
receipt, exact item order, auditor source hash, and JSON limits without reading
source bodies.
`scitaste evaluation acquisition-content-audit` then requires both that artifact
and `--allow-local-content-read`. It rehashes the local inventory, rejects extra
or symlinked files, duplicate keys, non-finite numbers, non-object roots, and
depth/container/node/string ceilings. It records normalized JSON-pointer shapes,
embedded arXiv identity observations, and external-locator counts while never
opening a connection or following a locator.

The resulting self-hashed report can make records eligible for a separate source
admission proposal. It cannot project fields into model context, admit a source,
call GLM-5.3-Flash, ask a reviewer, or run an experiment.

After a real receipt exists, the operator first creates a project-owned approval:

```bash
.venv/bin/scitaste evaluation acquisition-content-approve \
  --approved-request <approved-request.yaml> \
  --receipt <RECEIPT.json> \
  --confirm-request-sha256 <request-sha256> \
  --confirm-receipt-sha256 <receipt-sha256> \
  --approved-by <owner> --approved-at <timezone-aware-time> \
  --output outputs/projects/<project>/runs/<run>/content_audit/APPROVAL.json
```

Only a separately invoked audit may then read the local content:

```bash
.venv/bin/scitaste evaluation acquisition-content-audit \
  --approved-request <approved-request.yaml> \
  --receipt <RECEIPT.json> \
  --approval outputs/projects/<project>/runs/<run>/content_audit/APPROVAL.json \
  --workspace-root . --audited-at <timezone-aware-time> \
  --allow-local-content-read \
  --output outputs/projects/<project>/runs/<run>/content_audit/REPORT.json \
  --require-source-admission-ready
```

Every source then needs three independent admission arguments: rights and
attribution; evidence that it is a high-quality scientific source; and source-
group isolation from held-out decisions and the SciTaste self-development
effectiveness evidence. Failure is recorded as rejection, not repaired by a
model or replaced after inspecting downstream results.

That admission boundary is executable in `scitaste.evaluation.source_admission`.
The proposal must retain every item in the content-audit report, bind the audit's
self hash, and freeze the population before abstraction or downstream outcomes.
Each admitted item requires a content-bound rights argument, a separate quality
argument accepted by exactly two independent reviewers, and a content-bound
isolation check against both held-out cases and self-development effectiveness
evidence. Curators cannot review their own source. Rejected items remain in the
report, so a failed source cannot disappear through post-audit cherry-picking.

```bash
.venv/bin/scitaste evaluation source-admission \
  --proposal outputs/projects/<project>/runs/<run>/source_admission/PROPOSAL.yaml \
  --evidence-root . \
  --output outputs/projects/<project>/runs/<run>/source_admission/REPORT.json \
  --require-projection-proposal-ready
```

Passing the command means only that the predeclared minimum number of sources
may enter a separately approved projection proposal. The inspector never opens
source bodies, recruits reviewers, projects fields, calls a model, or authorizes
execution.

Only admitted fields can enter a content-addressed model projection. The exact
JSON pointers, excluded outcome information, normalized bytes, hashes, and real
token counts are frozen before a resource request is prepared. The preferred
abstraction model is the user-selected GLM-5.3-Flash, but that name cannot be
silently mapped to another model: an authenticated provider catalog and a
sentinel-bracketed identity window must first show what was actually served.

Each admitted source receives at most one recorded abstraction response. Two
independent humans judge source fidelity and transfer boundaries. A split corpus
admission vote may use one new adjudicator; this is distinct from the H1/H2
outcome study, where disagreements are retained and never adjudicated. Even an
accepted sixteen-source corpus remains an excluded instrument pilot rather than
formal effectiveness evidence or a benchmark training set.
