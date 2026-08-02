## Task

Bundle identity is authoritative.
Do not replace, infer, normalize, or copy identity from old artifacts.

Perform `resolve_gaps` for blockers listed in **this shard's batch only**.

Follow the assigned role contract and loaded capabilities
(`bounded-semantic-batch`, `sharded-llm-producer`, `semantic-resolution`).
Do not manage workflow state or declare completion.

## Mode

- mode: `task`
- task_id: `resolve-gaps`
- workflow_id: `<WORKFLOW_ID>`
- action_id: `<ACTION_ID>`
- run_id: `<RUN_ID>`
- shard_id: `<SHARD_ID>`

## Target

`<TARGET_IDS_OR_FILES>`

Only process the listed blocker ids from the assigned batch file.
Write one part file for this shard:

`runs/{run_id}/actions/resolve_gaps/parts/part_<SHARD_ID>.yaml`

## Context

- Project root: `<PROJECT_ROOT>`
- UO root: `<UO_ROOT>`
- Topic: `<TOPIC>`
- Context pack: `<CONTEXT_PACK_PATH>`
- Batch: `runs/{run_id}/actions/resolve_gaps/inputs/batches/batch_<SHARD_ID>.yaml`

## Closed vocabulary (mandatory)

Each patch MUST use:

```yaml
blocker_id: BLK_…
classification: scheduling | input_derived | validation_assumption | genuinely_unknown
binding:   # one test — use when classification == input_derived
  var_id: <from this blocker's own readable_vars list — nothing else exists>
  op: eq | ne | lt | le | gt | ge | in
  value: <literal or enum member inside the var domain>
evidence:
  - file: <path>
    line: <int>
    snippet: "<must match source; quote if contains ! & *>"
```

When one test is not the answer, give `condition` **instead of** `binding`
(never both). Same rules at every leaf — declared `var_id`, value in domain:

```yaml
condition:
  op: and            # and | or  → args: [...]
  args:              # not       → arg: {...}
    - {op: eq, var: VAR_ATTR_SPARSE_MODE, value: 3}
    - op: not
      arg: {op: in, var: VAR_DTYPE_QUERY, value: [DT_FLOAT8_E5M2, DT_FLOAT8_E4M3FN]}
```

At most 64 nodes, 6 deep. A guard is a guard, not a program: if the answer
does not fit, say `genuinely_unknown` and write why in `notes`.

## Reading the batch

Blockers that need code read carry a `source` list: the enclosing function or
loop, with `line_start` / `line_end`. That is the code the question is about,
and it is the code your `snippet` is checked against — quote any line inside
it, not necessarily the blocker's own line. Do not open other source files to
answer; if `source` is absent or does not settle it, that is
`genuinely_unknown`.

Each blocker also carries `readable_vars`: **the only variable names that
exist** for that blocker. Any other name is rejected as invented, however
right it looks — there is no way to declare a new one from here. If nothing in
that list can express the answer, the answer is `genuinely_unknown`, and
saying so is the correct outcome rather than a failure.

Read the names before reasoning about the code: they tell you what the
analysis already understands. `inputLayout[0] == 'B'` is a question about
`VAR_ATTR_INPUT_LAYOUT` and about nothing else, because that is the only name
on the list that could hold a layout.

## Required Procedure

1. Read **only** this shard's batch YAML (and session prompt/method/bundle).
2. For each assigned blocker, propose a source-backed patch inside the closed vocabulary.
3. Do not invent TILING_DATA / INPUT_* / VAR_* symbols absent from the whitelist.
4. Do not read other batches, other parts, or write `uo/ir/**`.
5. Write `parts/part_<SHARD_ID>.yaml` with a top-level `patches: [...]` list.
6. Stop after producing the part and a concise task result. Do not finalize.

## Questions about the derivation itself

Two `reason_code`s are not about an unreadable guard but about something the
derivation had to assume. They use the same patch shape; what differs is what
the answer means.

**`UNWRITTEN_INITIAL_VALUE`** — a member is read on a path where the analysis
could not prove anything wrote it, so it stands for "whatever it held before".
`text` names the member; `source` is the function that reads it.

- If the writes really do cover every path that reaches the read, and the
  guards say which one, answer `input_derived` with the condition under which
  the value is what it is. That removes the assumption.
- If the member has a declared initial value (a default member initializer, a
  memset, a constructor) and no write on this path, that value is the answer:
  `input_derived` with `{op: eq, var: …, value: …}` on the variable it is
  derived from, or `validation_assumption` when nothing input-side reaches it.
- If a write really can be skipped and the value then read, say
  `genuinely_unknown` — that is a finding about the operator, not a gap in the
  analysis, and it should not be papered over.

**`LOOP_SUMMARY_NEEDED`** — a value comes out of a loop the solver cannot
unroll (a prefix sum, a coverage scan, a filtered count). `source` carries the
whole loop.

- Answer with what the loop *computes*, expressed over declared variables:
  the count of a filtered range, a bound the result must satisfy. A condition
  that is implied by the loop for every input is sound even if it does not
  pin the value down — `{op: ge, var: …, value: 0}` on a counter is worth more
  than a guess at its exact value.
- Never state something the loop only happens to produce for typical shapes.
  The check enumerates legal inputs and will find the exception.

## What gets a patch rejected

Every patch is checked mechanically before it is merged. Knowing the checks is
the cheapest way to pass them:

- **A variable the code does not read.** The condition may only mention
  variables the blocker's own code touches. Correct-but-unrelated is rejected.
- **A condition that decides nothing.** If it is true for every legal input, or
  false for every one, it replaces a branch with a constant. That is not a
  reading of the guard, it is a deletion of it.
- **Values outside what the template declares.** Substituted back, the
  dimension must still be able to take a declared value, and must be able to
  take at least one.

A rejection comes back with a concrete input that shows the problem. An honest
`genuinely_unknown` costs nothing; a guess that passes review and fails here
costs a round trip.

## Output

Staging part only under `runs/{run_id}/actions/resolve_gaps/parts/part_<SHARD_ID>.yaml`.
