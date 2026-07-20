# Subagent Dispatch Protocol

Understand Operator uses subagents sparingly in the layered KB pipeline.

The only specialized subagent required by `/uo-init` is:

- `uo-semantic-resolve` — entrypoint confirmation, extract plan confirmation,
  residual resolve, consistency review

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

Hard caps:
- At most 12 unresolved_resolutions entries (sample by pattern; leave the rest)
- At most ~15 tool calls; prefer MCP codebase-memory-mcp for one symbol
- Do NOT hand-count ids or require 1:1 coverage of unresolved.yaml
- Do NOT emit residuals:/resolutions:/branches:/decision:/resolution:warning

After write, stop. Parent will run apply_resolution.py --check.
```

## Apply gate (parent, not subagent)

After the subagent returns, parent **must** validate before treating resolve as done:

```powershell
python -X utf8 "$SCRIPT_DIR/apply_resolution.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --patch "$UO_ROOT/ir/resolution_patch.yaml" --check
```

- If `rejected_count > 0`: resume the **same** dispatch identity with only the
  `rejected` list; ask for a minimal fix patch. Do not reopen a fresh full resolve.
- If check passes: apply without `--check`, then continue export/validate.

Never ask the subagent to PowerShell-diff id lists against `unresolved.yaml`.
