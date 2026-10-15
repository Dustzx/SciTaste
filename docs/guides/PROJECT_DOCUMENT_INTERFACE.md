# Living project document interface

Every newly created project receives `docs/project/INDEX.json` and five phase
directories: `idea`, `experiments`, `writing`, `review`, `resources`. Existing projects
can adopt the same interface without moving legacy evidence. Excluded study CVPR is populated
from its imported records; older projects are not silently rewritten.

Each phase has exactly two managed working documents:

- `CURRENT.md`: concise observed state, limitations, and evidence locators.
- `PLAN.md`: at most eight concrete next steps or decisions.

`INDEX.json` is the typed publishing contract consumed by Generation as Content.
The Markdown files are generated readable projections, not independent authorities.
Submit a complete revised JSON packet through
`python -m scripts.project_documents --outputs outputs --input <revision.json>`.
Humans or SciTaste can author the packet. This does not yet autonomously summarize
new remote logs; stale snapshots must not be described as live monitoring. Editing
Markdown alone does not publish a new plan.

## Bounds and references

The interface accepts at most five unique phases, 3,000 characters per current-state
summary, eight next steps and twelve references per phase, and a 64 KB total index.
Additional files in managed phase directories are rejected. Evidence, datasets,
logs, TeX/PDF and experiment outputs stay in their original project-owned stores;
the summary cites project-relative paths and retains publication-time SHA-256 values.
External workspaces must first be explicitly imported; path escapes are rejected.
Hashes identify cited bytes, not scientific correctness or continued freshness.

## Archive policy

Before a changed publication, the previous complete index is appended to the single
`archive/revisions.jsonl` container, addressed by its SHA-256. Identical publication
is a no-op. No timestamped working documents are accumulated. Historical revisions
are excluded from the normal UI/model input; retrieve a specific hash only when
needed. Retired phases stay explicitly marked rather than disappearing. The archive
has a 32 MB maintenance threshold: publication stops for explicit compaction, never
silently deletes cited history. Referenced evidence is not garbage-collected by this
interface. Future compaction must preserve hash-addressable cited revisions.

## Authority and display

The project-progress model receives the bounded current packet, not the whole docs
tree. The desktop research-plan panel shows collapsible phase summaries. A verified
executable evidence program retains control precedence; living summaries provide
context and do not authorize API/GPU execution or override accepted interventions.
Publishing updates the project revision, invalidating old evidence-bound views.
