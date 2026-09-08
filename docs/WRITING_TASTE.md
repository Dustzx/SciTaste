# Writing Taste

Writing Taste is the decision layer that determines **what scientific story the
registered evidence supports, how that story should be organized, and how it
should be expressed without weakening or inflating it**. It is larger than style
editing and larger than any single prompt or critic.

## Scope and precedence

SciTaste evaluates writing at paper, section, paragraph, sentence, and phrase
levels. Version 1 separates twelve dimensions:

1. scientific integrity;
2. claim calibration;
3. precision and scope;
4. scientific positioning;
5. narrative focus;
6. argumentative structure;
7. evidence prioritization;
8. global coherence;
9. reader guidance;
10. anti-defensive style;
11. venue fit;
12. voice and terminology.

The order is an authority rule, not a cosmetic preference. Persuasive framing
cannot override evidence, hide a material limitation, discard counterevidence,
expand a claim, or turn an engineering fixture into a scientific result.

## Anti-defensive writing as one component

The positive-scope, strength-centered, and no-project-log principles were adapted
at the principle level from
[Adkid-Zephyr/anti-defensive-writing-Skill](https://github.com/Adkid-Zephyr/anti-defensive-writing-Skill)
at commit `b32067b3055d356e007c6986775fee069da3891a` under its MIT license. The
source text is not vendored or copied. Each derived Taste Case records the exact
source, commit, license, and derivation method.

SciTaste does not adopt absolute instructions such as hiding every unfavorable
result or withholding every weakness. Those rules conflict with scientific
integrity when a result or limitation changes validity, scope, safety, ethics, or
reproducibility. The integrated policy is:

- state supported scope positively;
- remove redundant anticipatory disclaimers;
- organize the paper around its strongest supported contribution;
- keep material limitations once, precisely, where they change interpretation;
- retain the complete evidence and failure history in the project record;
- route a real evidence gap to new evidence or a narrower claim, never to prose
  camouflage.

## Implemented architecture

```text
registered claims, evidence, limitations, and venue
→ Narrative Spine
→ section and paragraph contracts
→ hierarchical Writing Taste retrieval
→ deterministic Writing Taste assessment
→ optional proposal-only semantic Writing Taste node
→ decomposed claim/evidence and style critics
→ evidence action, contract revision, or bounded prose revision
→ human and venue review
```

`TasteCase` now indexes writing level, section type, rhetorical role, transition
pattern, claim strength, citation density, Writing Taste dimensions, and style
tags. `WRITING_DECISION` retrieval uses those fields while preserving provenance.

The deterministic assessor emits self-hashed findings and currently detects
project-status headings, project-log Results sections, process chronology,
defensive framing in high-attention sections, missing abstract contribution or
evidence cues, conclusion self-negation, and overloaded paragraphs. It is an
advisory writing signal, not a scientific-quality score.

Every ordinary manuscript bundle and venue-native submission bundle now owns a
`WRITING_TASTE_ASSESSMENT.json`. Project paper dry-runs expose the same
assessment before mutation, and registered paper manifests bind its record
hash and artifact locator. This makes Writing Taste inspectable beside the
source, TeX, PDF, mechanical manuscript assessment, and venue assessment; its
advisory verdict remains separate from `eligible_for_submission`.

The optional `writing-taste` model node handles the semantic decisions that
cannot be reduced to regular expressions. Its input contains only registered
sections, claim IDs, evidence IDs, headline candidates, and material
limitations. Its typed output may propose reframing, reordering, section naming,
claim narrowing, or an evidence request. Deterministic admission rejects unknown
references, a changed manuscript identity, an incomplete section order, or any
attempt to omit or demote a registered material limitation. The node cannot edit
files, mutate state, call tools, accept evidence, or execute an action.

Two bounded profiles are provided:

- `profile_writing_taste_scripted_v1.yaml` for offline acceptance;
- `profile_writing_taste_zhipu_glm53_flash_v1.yaml` for opt-in live review with
  `glm-5.3-flash`.

The live profile admits up to 6,000 output tokens within an 8,192-token provider
generation ceiling. The limit is per semantic review invocation, not a global
development or manuscript length limit.

## SciTaste self-iteration

The tracked SciTaste manuscript is the first dogfooding target. The initial
assessment correctly identified `Current Results`, `Artifact-level validation`,
and `End-to-end engineering preacceptance` as project-report headings, along with
project-status framing in the abstract, introduction, and conclusion. The source
was reorganized around two evaluation questions and positive evidence scope.

Passing the deterministic advisory means only that the registered surface
antipatterns are absent. Expert judgment, semantic model comparison, citation
verification, venue review, and the registered effectiveness study remain
separate evidence requirements.
