## Task

Bundle identity is authoritative.
Do not replace, infer, normalize, or copy identity from old artifacts.

Review the patches in **one shard's part file** against the source they claim
to read. You did not write them and you are not here to improve them: for each
patch, say whether the code supports it.

The mechanical checks already ran. They can tell that a condition is
well-formed, mentions readable variables, decides something, and keeps the
dimension inside its declared values. They cannot tell whether it is the
condition the code actually implements. That is this review.

## Mode

- mode: `task`
- task_id: `review-gap-patches`
- workflow_id: `<WORKFLOW_ID>`
- action_id: `<ACTION_ID>`
- run_id: `<RUN_ID>`
- shard_id: `<SHARD_ID>`

## Target

- Patches: `runs/{run_id}/actions/resolve_gaps/parts/part_<SHARD_ID>.yaml`
- Questions: `runs/{run_id}/actions/resolve_gaps/inputs/batches/batch_<SHARD_ID>.yaml`
- Write: `runs/{run_id}/actions/resolve_gaps/reviews/review_<SHARD_ID>.yaml`

Read those two files and the source they point at. Nothing else.

## What to check, in order

For each patch, against the `source` window of its blocker:

1. **Does it answer the question asked?** A patch on the wrong blocker, or one
   that restates the blocker without deciding it, is `reject`.
2. **Is the quoted line really the reason?** The snippet has already been
   matched to the file; what matters here is whether that line supports the
   claim, or merely sits near it.
3. **Is the condition the one the code tests?** Walk the branch. A condition
   that is *necessary* but weaker than the code's own test is `accept` — it
   only ever widens the feasible set. A condition that is *stronger* than the
   code's is `reject`: it excludes inputs the operator accepts, and every key
   that needed them silently becomes unreachable.
4. **Is anything read from outside the window?** An answer that requires a file
   the worker was not given is a guess, however plausible. `reject`.

Direction is the point of this review. Too weak is a smaller claim. Too strong
is a wrong one, and it is wrong in the direction nothing downstream can catch.

## Output

```yaml
version: 1
shard_id: "<SHARD_ID>"
reviews:
  - blocker_id: BLK_…
    verdict: accept | reject
    # required on reject: what the code does that the patch does not
    reason: "…"
    # required on reject when you can point at it: the line that shows it
    evidence:
      file: <path>
      line: <int>
```

One entry per patch in the part file, same order. No entry for a blocker with
no patch. Do not edit the part file, do not write `uo/ir/**`, do not finalize.

An `accept` you are unsure of is worse than a `reject` with a thin reason: a
rejected patch costs one round trip, an accepted wrong one is baked into every
key that touches the dimension.
