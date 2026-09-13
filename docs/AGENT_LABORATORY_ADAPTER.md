# Agent Laboratory adapter

SciTaste now has a real unchanged-core preparation path for Agent Laboratory at
commit `d9017d90e329112d2a80b7712f37ee9094d2cd27`. This is the first accepted
external AutoResearch method selected because its source is MIT licensed, its
fixed Git checkout is available, and its native topic-plus-notes interface can
receive a research brief without patching upstream policy.

## Implemented boundary

`scitaste evaluation agent-laboratory-prepare` binds all of the following before
materializing a run workspace:

- the external-resource corpus and static adapter contract by byte and semantic
  hash;
- a clean upstream Git checkout at the exact accepted-method commit;
- one held-out UTF-8 task brief by path, size, and SHA-256;
- Agent Laboratory's native `o3-mini-2025-01-31` model identity; and
- one nonparallel native workflow shape with PDF compilation disabled.

The compiler copies only Git-tracked regular files into a new run-owned
workspace. It writes the original brief unchanged to `input/task.md` and places
the decoded text, with no prefix or hidden task content, in the native
`research-topic` field. It reloads the emitted YAML and requires the resulting
UTF-8 bytes to equal the original brief. Neutral task notes describe only the
visibility and asset boundary. No key is written to YAML or copied into the
workspace.

The first real compilation used MLR-Bench brief `iclr2025_bi_align.md`:

- task bytes: `2,955`;
- task SHA-256 and native-YAML round-trip SHA-256:
  `a83c1a24956b7c2136ef4fc39cbbc64c9f041a975ba58fbff3c36ac8cf78f95a`;
- upstream tracked files: `35`;
- upstream tracked bytes: `1,697,843`;
- source and materialized tree SHA-256:
  `03eaae1a56d921cd237e70cf5b13cba5f9a1cbbf2218fb0a217a535738b9faf1`.

This closes source identity and lossless starting-brief translation. It is not a
system run, adapter preflight report, benchmark result, or evidence of research
quality.

## Remaining live-execution boundary

The preparation receipt deliberately remains `ready_for_live_execution=false`.
Five requirements remain:

1. Build a dedicated Python 3.12 environment for the pinned 135-line upstream
   dependency set. The upstream file imports `tensorflow` eagerly but does not
   declare it, so the environment must add one explicit compatible pin rather
   than silently use the SciTaste environment.
2. Obtain access to the exact OpenAI `o3-mini-2025-01-31` identity. Substituting
   DeepSeek, Zhipu, or another OpenAI alias would define a different estimator.
3. Run the writable copied workspace inside a filesystem-isolated process while
   retaining the native network access required for literature and provider use.
4. Interpose a provider gateway so the real key never enters generated-code
   subprocesses and every request, retry, model identity, token count, cost, and
   ambiguous provider failure is retained and bounded.
5. Qualify the task population for the ecological package-preference lane. This
   brief has no objective executable asset and must not be reused as an
   objective-progress task.

The current static contract therefore remains a proposal, and the current
schema-1.6 prelaunch correctly refuses to treat this preparation receipt as a
ready adapter report.
