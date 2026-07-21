# Subagent Dispatch Protocol

Understand Operator uses subagents sparingly in the layered KB pipeline.

The specialized subagents required by `/uo-init` are:

- `uo-semantic-resolve` — entrypoint confirmation, extract plan confirmation,
  residual resolve, consistency review
- `uo-kb-review` — final KB product review (`review/kb_product_review.yaml`)

Do **not** dispatch retired extractors (`uo-boundary-agent`, `uo-host-extraction`,
`uo-flow-extraction`, kernel-slice / fact-review / graph-review agents).

Before the first subagent dispatch, run:

```powershell
python -X utf8 "$SCRIPT_DIR/verify_required_subagents.py" --platform cursor
```

If preflight fails, stop and tell the user to reinstall the plugin. Do not fall
back to a general agent for the same structured patch writes.

## Dispatch Identity and Resume

Each specialized task has a stable dispatch identity:

```text
<run_id>:<phase-or-step>:<owner>:<target-path-or-slice-id>
```

Examples:

- Entrypoint confirm: `<run_id>:extract:uo-semantic-resolve:ir/entrypoint_confirm.yaml`
- Extract plan confirm: `<run_id>:extract:uo-semantic-resolve:ir/extract_plan.yaml`
- Residual resolve: `<run_id>:resolve:uo-semantic-resolve:ir/resolution_patch.yaml`
- KB product review: `<run_id>:review:uo-kb-review:review/kb_product_review.yaml`

Before opening a subagent task, check whether a task with the same identity is
already open or has already returned earlier in this run. Resume that same
subagent context for continuation or repair.
Do not open another task window for the same identity.

If the runtime cannot resume the original subagent context after a failed apply
or validation, stop and report `SUBAGENT_RESUME_UNAVAILABLE` with the dispatch
identity. Do not spawn another fresh subagent to redo the same files.

Always pass `PLUGIN_ROOT`, `PROMPT_DIR`, and `SCRIPT_DIR` explicitly. If a
subagent cannot find prompts from `PROMPT_DIR`, provide the source checkout
fallback path for the installed plugin. Do not let a subagent resolve
`prompts/...` relative to `PROJECT_ROOT`.

## Ownership

`uo-semantic-resolve` may write only:

- `ir/entrypoint_confirm.yaml`
- `ir/extract_plan.yaml`
- `ir/resolution_patch.yaml`

Apply patches with `apply_resolution.py` / `apply_extract_plan.py` / entrypoint
confirm flags. Never let the subagent rewrite `contracts/`, `tiling/`,
`kernel/`, or source trees.

## Extract plan dispatch (mandatory template)

After `propose_extract_plan.py --write`, dispatch extract-plan confirmation.
The **Task prompt body must** include the following block verbatim (fill paths
only):

```text
Follow agents/uo-semantic-resolve.md exactly.

Task: extract plan confirmation (task C).
- Read only: <UO_ROOT>/ir/extract_plan_candidates.yaml
- Optional: one MCP get_code_snippet for a thin candidate
- Write only: <UO_ROOT>/ir/extract_plan.yaml

Schema (ONLY):
  version: 1
  confirmed_by: llm
  writers: [{name, file_path, start_line, role}]
  receivers: [{name, is_tiling_sink}]
  aliases: [{local, tdf_leaf}]
  non_sink_roots: []
  extra_host_entries: []
  derived_roots: []

Hard rules:
- Do NOT invent names absent from candidate lists
- role ∈ tiling_writer | key_writer | workspace_writer | provenance_helper | ignore
- Prefer Chinese brief notes only if you add rationale fields; schema above is enough
- Cap ~12 tool calls

After write, stop. Parent will run apply_extract_plan.py --check.
```

Parent gate:

```powershell
python -X utf8 "$SCRIPT_DIR/apply_extract_plan.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --check
```

- If rejected: resume the **same** dispatch identity with only the `rejected`
  list; ask for a minimal fix. Do not reopen a fresh full confirm.
- If check passes: `apply_extract_plan.py --write` (or keep the written plan),
  then continue host/kernel extract.

## Residual resolve dispatch (mandatory template)

When dispatching residual + consistency review, the **Task prompt body must**
include the following block verbatim (fill paths only). Do **not** invent
alternate schemas such as `residuals:` / `resolution: warning` / `branches:`.

```text
Follow agents/uo-semantic-resolve.md exactly.

Task: residual resolve + optional branch consistency review.
- Read only: <UO_ROOT>/ir/unresolved.yaml (and snippets therein)
- Optional skim: <UO_ROOT>/ir/kernel_subgraph.yaml branch rows (binding_time/condition/file:line)
- Write only: <UO_ROOT>/ir/resolution_patch.yaml

Schema (ONLY):
  version: 1
  node_patches: []
  unresolved_resolutions:
    - id: <id from unresolved.yaml>
      status: resolved | accepted | false_positive | alias
      rationale: <Chinese brief>
      resolution: {kind, label, evidence}   # optional
  consistency_diffs: []
  escalate_keys: []   # KEY ids that need per-KEY uo-query (complex / shape expr)

Hard caps:
- At most 12 unresolved_resolutions entries (sample by pattern for *simple* FP/host-only)
- At most ~15 tool calls; prefer MCP codebase-memory-mcp for one symbol
- Do NOT hand-count ids or require 1:1 coverage of unresolved.yaml
- Do NOT emit residuals:/resolutions:/branches:/decision:/resolution:warning
- Do NOT leave complex KEY/shape gaps as silent unsolved — list them in escalate_keys

After write, stop. Parent will run apply_resolution.py --check, then escalate escalate_keys.
```

## Complex KEY escalation (parent, parallel uo-query)

After residual sample apply (or when `escalate_keys` / remaining gaps are
KEY/shape-complex), parent **must not** treat “left unsolved” as done.

Follow `skills/uo-query/references/complex-unresolved-escalation.md`:

1. Group complex open items by **KEY id**.
2. Dispatch **one subagent per KEY in parallel** (cap 8), identity
   `<run_id>:resolve:uo-query-key:<KEY_ID>`.
3. Each KEY task body (fill paths / KEY only):

```text
Follow skills/uo-query/SKILL.md + references/source-lookup-gate.md +
references/complex-unresolved-escalation.md exactly.

Task: per-KEY shape expression resolve.
- KEY_ID: <KEY_ID>
- PROJECT_ROOT / OP_NAME / UO_ROOT / SCRIPT_DIR / QUERY_CLI as provided by parent
- Read: key_cards for this KEY (only after uo_kb_query graph patterns)
- Related unresolved ids (optional): <ids>

Must run:
  uo_kb_query --status-only
  uo_kb_query --pattern branches_for_key --target <KEY_ID>
  uo_kb_query --pattern affected_shapes --target <KEY_ID>
  uo_kb_query --pattern neighbors_of --target <KEY_ID or setter SYM>
Then MCP loop to high confidence (default non-fast).

Write only: <UO_ROOT>/ir/key_shape_resolve/<KEY_ID>.yaml
(schema in complex-unresolved-escalation.md)

Hard rules:
- One KEY only — do not resolve other KEYs
- Do NOT return bare unsolved; status is resolved | needs_human with evidence
- Do NOT invent then==else / fake domains
- Cap ~20 tool calls

After write, stop. Parent merges patches.
```

4. Parent merges `ir/key_shape_resolve/*.yaml` → `ir/resolution_patch.yaml`,
   then `apply_resolution.py --check` / apply.
5. `needs_human` KEYs → AskQuestion; never silent drop.

## Apply gate (parent, not subagent)

After the residual subagent returns, parent **must** validate before treating resolve as done:

```powershell
python -X utf8 "$SCRIPT_DIR/apply_resolution.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --patch "$UO_ROOT/ir/resolution_patch.yaml" --check
```

- If `rejected_count > 0`: resume the **same** dispatch identity with only the
  `rejected` list; ask for a minimal fix patch. Do not reopen a fresh full resolve.
- If check passes: apply without `--check`.
- If `escalate_keys` non-empty or KEY/shape-complex items remain: run **Complex KEY
  escalation** (parallel per-KEY uo-query) above, merge, apply again.
- Then continue export/validate.

Never ask the subagent to PowerShell-diff id lists against `unresolved.yaml`.
Never treat “sample left the rest untouched” as success when those leftovers are
KEY/shape-complex.

## KB product review dispatch (mandatory template)

After integrity scripts pass, dispatch **one** `uo-kb-review` using this body
(fill paths only). Do **not** ask it to edit `ir/**`.

```text
Follow agents/uo-kb-review.md exactly.

Task: final KB product review.
- Read: <UO_ROOT>/summary/human_overview.md
- Read: <UO_ROOT>/checks/integrity.yaml and checks/final.yaml
- Read: <UO_ROOT>/ir/resolution_ledger.yaml (or confirm empty open unresolved)
- Read: <UO_ROOT>/ir/unresolved.yaml (must be empty)
- Read: <UO_ROOT>/ir/entrypoints.yaml roles status
- Run: python -X utf8 <SCRIPT_DIR>/uo_kb_query.py <PROJECT_ROOT> --op-name <OP_NAME> --status-only
- Optional: 1–2 directed uo_kb_query patterns; optional one CBM symbol check
- Write only: <UO_ROOT>/review/kb_product_review.yaml

Schema (ONLY):
  version: 1
  verdict: pass | fail
  summary: <Chinese one line>
  findings:
    - id: KBR_...
      severity: error | warning
      rework_stage: phase0_scope | entrypoints | extract_plan | residual_resolve | export_graph | none
      message: <Chinese>
      evidence: <path or query>

Hard caps:
- At most ~15 tool calls
- Do NOT dump operator_graph / exhaustive / full testcase
- Do NOT modify ir/**

After write, stop. Parent routes rework_stage (max 2 loops).
On verdict=pass parent MUST run export_human_views.py so overview reflects kb_review.
```

Parent routing after review:

| rework_stage | action |
|---|---|
| phase0_scope | return to Phase0 confirm / `--replace-initial` then restage |
| entrypoints | resolve_entrypoints + semantic-resolve entrypoint task |
| extract_plan | propose/confirm extract_plan → build_layered_kb |
| residual_resolve | residual resolve + apply_resolution (propagate) |
| export_graph | export_kb_graph + check_kb_integrity |
| none | record warning only |

Same `uo-init` run: at most **2** kb-review rework loops; third fail → stop and
show `review/kb_product_review.yaml` (do not pretend success).

