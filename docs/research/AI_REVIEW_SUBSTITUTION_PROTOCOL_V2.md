# AI review operational-finality protocol v2

Status: **active review policy; AI/nonhuman operational finality; objective
evidence still required for scientific claims and title authority**.

This protocol supersedes v1 prospectively. It does not modify v1, any completed
review, or any historical result. The machine-readable authority is
[`iclr2027_scitaste_ai_review_finality_v2.yaml`](../../configs/evaluation/programs/iclr2027_scitaste_ai_review_finality_v2.yaml),
with semantic hash
`ffdcb1927e162708c594603963505c37c0065e8f330da239e7dd16d6c88070e4`.
It binds lifecycle evidence program v2 and grants no download, API, GPU, or
experiment authority.

## Operational finality

Protocol, source, abstraction, outcome-attribution, and paper-review nodes use
the same terminal panel rule:

1. two primary agents review identical, content-bound subject bytes;
2. reviewer, provider/model revision, run, and raw-response identities are
   distinct;
3. a third identity-distinct agent adjudicates if and only if the primaries
   disagree;
4. deterministic code verifies the exact policy, subject, response identities,
   roles, and panel decision;
5. agreement, or the valid adjudicator decision after disagreement, ends the
   review node.

An accept verdict closes the node and permits the already defined deterministic
admission transition. A reject verdict also closes the review node, but blocks
that subject from admission. Rejection therefore creates a scientific/data
blocker, not a request for an unavailable human reviewer. Malformed, duplicate,
or incomplete panels remain fail-closed.

Every closure records `reviewer_kind=ai`, `not_human_review=true`,
`human_assessment_count=0`, `human_validity_claim_allowed=false`, and
`human_or_expert_validity_claimed=false`. AI agreement is mechanism/proxy
evidence. It is never renamed human preference, expert agreement, or independent
human construct validation.

The generic closure can be checked without a provider call:

```bash
.venv/bin/scitaste evaluation review-finality \
  --policy configs/evaluation/programs/iclr2027_scitaste_ai_review_finality_v2.yaml \
  --closure /path/to/content-bound-ai-closure.yaml
```

## Separate title authority

Lack of a human review no longer freezes the candidate title
*SciTaste: Improving Autonomous Research through Scientific Taste*. AI review
also cannot unlock it. The title has a separate, stricter authority path:

- the registration covers every and only title-critical claim in the bound
  evidence program;
- each claim is prospectively bound to an exact formal prelaunch proposal and
  planned project result before prelaunch approval;
- each prelaunch binds the same evidence-program hash, a scorer-owned objective
  endpoint, and an explicit claim-admission contract;
- each result is a project-registered, byte-revalidated result rather than a
  loose report;
- every planned unit is complete under the registered failure rule; and
- every registered confirmatory Taste causal contrast is valid and supports the
  claim on held-out objective outcomes.

Only that complete conjunction authorizes the candidate title. A missing claim,
late registration, non-objective endpoint, incomplete result, invalid contrast,
null/negative contrast, drifted artifact, or unregistered result selects the
fallback title. An AI panel cannot fill any missing objective cell or convert a
proxy endpoint into an objective outcome.

The prospective title registration is itself self-hashed and names
`claim_id`, `study_id`, `evaluation_id`, planned `result_id`, the exact prelaunch
file hash, and its proposal hash. After results are registered in the project,
the gate can be replayed with:

```bash
.venv/bin/scitaste evaluation title-authority \
  --policy configs/evaluation/programs/iclr2027_scitaste_ai_review_finality_v2.yaml \
  --program configs/evaluation/programs/iclr2027_scitaste_lifecycle_evidence_program_v2.yaml \
  --registration /path/to/prospective-title-registration.yaml \
  --outputs-root outputs --require-authorized
```

This rule makes review staffing non-blocking while keeping the central
effectiveness and title claim fail-closed.
