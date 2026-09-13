# H1/H2 human preference analysis

The H1/H2 pipeline has two distinct boundaries. `human-outcome-audit` verifies
that every reviewer saw condition-blinded, budget-matched outputs, that all
primary reviews were locked before the committed key was opened, and that the
opened conditions form the registered H1 and H2 contrasts. For formal work it
also replays a private generation ledger opened with the key: every reviewed
output must bind one exact formal SciTasteBench v3 case, reference-treatment
manifest, construction receipt, request fingerprint, execution trace, seed,
candidate order, provider, and model.

For byte compatibility, the blind-key fields retain the historical
`*_generation_trace_sha256` names. In a schema-1.2 study they must contain the
self-hash of the full generation record, which in turn binds the execution-trace
file; a bare trace-file digest is insufficient.

`human-preference-analyze` then computes the effect; readiness to analyze is not
itself an effect.

The analysis command accepts the original locked-review set and blind opening,
not a caller-supplied outcome table. It reruns the integrity audit internally so
that forged `ready` flags or relabeled outcomes cannot enter inference.

## Preparing the blind package

`scitaste evaluation human-study-prepare` closes the gap between an already
recorded benchmark run and reviewer delivery. It accepts one exact v3 suite,
its typed treatment manifest, and a timestamped `benchmark run --record` JSONL.
For the selected seed and candidate order, the recording must contain every
matched-abstracted, same-source-raw, and source-disjoint-mismatched request
exactly once; an exact Base record is allowed, while duplicates, missing arms,
foreign requests, untimestamped legacy records, or mixed models fail closed.
Formal rows must also retain raw provider/model response bytes with a matching
digest; a reconstructed rationale alone is not accepted as execution evidence.

The command writes one atomic package:

- `reviewer/outputs/` contains opaque-path JSON decisions with no condition,
  provider, or model field;
- `public/study.json` contains the reviewer assignments and only commitments to
  private evidence;
- `private/traces/`, `private/generation-ledger.json`, and
  `private/blind-key.json` retain the condition-bearing generation chain;
- `private/blinding-secret.json` prevents the published default randomization
  seed and known compiler algorithm from making opaque IDs enumerable; and
- `PREPARATION.json` binds all inputs and package identities.

The two preassigned reviewer pseudonyms receive deterministically randomized and
counterbalanced X/Y order. The compiler does not recruit or contact them and
does not call a model, API, GPU, or experiment. Condition-bearing private files
must remain inaccessible until all primary reviews are locked.

## Running and locking reviewer sessions

`scitaste evaluation human-review-session-prepare` builds one offline workspace
for one of the two reviewer pseudonym hashes already assigned in the public
study. It rechecks the treatment-bound suite identity, committed rubric and
interface bytes, every assigned output digest, and exact half-study coverage.
The resulting `review.html` is self-contained: the reviewer sees the shared
decision context and two equal-layout outputs in a fixed-height workspace, can
navigate assigned comparisons without one long document, saves drafts only in
browser-local storage, and exports a JSON submission only after every response,
rationale, missingness reason when applicable, and independence/blinding
attestation is complete.

The two exported submissions are inputs to
`scitaste evaluation human-review-lock`. The command rejects a foreign session,
reviewer mismatch, missing or duplicate comparison, invalid response, future
submission time, overlapping assignment, or a lock timestamp preceding a
submission. Its schema-1.1 review set content-addresses both session JSON files
and both raw submissions. A treatment-bound formal study will not become ready
to open its key from a legacy hand-authored review set lacking these bindings.
Neither command recruits or contacts reviewers; informed consent, qualification,
conflict clearance, compensation, and owner recruitment approval remain
external human-resource gates.

A schema-1.2 formal human study binds its scope, exact post-pilot analysis
contract, power-analysis bytes, formal v3 suite identity, treatment-manifest
identity, and generation-ledger commitment before outcome review. The ledger is
private until all primary reviews are locked. On opening, exact case populations
and reviewer-visible output bytes are checked against the committed condition
records. Schema 1.1 remains readable for historical pilot evidence, but cannot
enter the formal title gate. The analysis contract fixes response coding, the
independent unit, aggregation, missingness ceiling, minimum source-group count,
minimum effect, interval/test seeds, alpha, and Holm family. Pilot and formal
studies remain separate.

The primary response is coded as 1 when matched abstracted Taste is preferred,
0.5 for a tie, and 0 when the registered comparator is preferred. The engine
averages the two blinded reviewers within a case, averages cases within a source
group, and gives source groups equal weight. It never treats a reviewer rating,
candidate-order repeat, or case from the same source group as an independent
sample. It reports raw review counts, missingness, source-group effects, reviewer
diagnostics, source-group bootstrap intervals, paired source-group sign-flip
p-values, and Holm-adjusted H1/H2 decisions.

The joint title gate passes only for a treatment-bound schema-1.2 formal study
when both H1 and H2 clear their preregistered minimum effect and adjusted alpha
threshold. A pilot report or legacy formal manifest cannot pass the formal gate.
The analyzer recruits no reviewer, opens no blind key, invokes no model, spends
no API budget, and allocates no GPU.

The shipped estimator is the design-based, source-group-clustered option already
described by the protocol. The final formal contract must be selected after the
pilot and before formal outcomes. If pilot diagnostics show that repeated
reviewer effects materially dominate despite randomized X/Y order, the formal
study must be frozen under a new contract with an appropriate crossed-effects
model; SciTaste must not silently switch estimators after opening outcomes.
The excluded pilot report feeds the separate
[`CLUSTERED_POWER_ANALYSIS.md`](CLUSTERED_POWER_ANALYSIS.md) planner, which uses
source-group dispersion but never the observed pilot mean as its effect target.
