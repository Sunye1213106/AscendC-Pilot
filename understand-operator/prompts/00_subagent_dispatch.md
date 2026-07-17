# Subagent Dispatch Protocol

Understand Operator uses subagents sparingly in the layered KB pipeline.

The only specialized subagent required by `/uo-init` is:

- `uo-semantic-resolve` — entrypoint confirmation, residual resolve, consistency review

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
- `ir/resolution_patch.yaml`

Apply patches with `apply_resolution.py` / entrypoint confirm flags. Never let
the subagent rewrite `contracts/`, `tiling/`, `kernel/`, or source trees.
