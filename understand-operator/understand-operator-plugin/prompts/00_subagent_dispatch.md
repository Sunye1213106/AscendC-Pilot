# Subagent Dispatch Protocol

Understand Operator uses subagents only where parallel extraction is useful in
the Phase 0-3 workflow.

Specialized source-fact extraction workers are OpenCode subagents. Phase 1
boundary extraction uses `uo-boundary-agent` because the strict schema/source
anchor contract is too detailed for ad hoc parent-agent YAML editing.

Before the first subagent dispatch, run the subagent preflight. If any required
specialized agent is missing or is not typed as `subagent`, stop
immediately. Do not fall back to a general agent.

## Parallel Points

1. Phase 1:
   - `uo-boundary-agent`
2. Phase 2:
   - `uo-host-extraction`
   - `uo-flow-extraction`
   - `uo-kernel-overview-agent`
3. Phase 3:
   - `uo-kernel-slice-agent` for each approved slice from
     `facts/kernel/slice_manifest.yaml`

All tasks are foreground tasks. Wait for every task to return before reading
its artifacts or advancing the workflow.

Do not open a second task window for the same `(phase, owner, target files)`.
If the runtime cannot resume the original subagent context after a validator
failure, stop and report `SUBAGENT_RESUME_UNAVAILABLE` with the failed report
path. Do not spawn another fresh subagent to redo the same files.

Dispatch prompts must not restate extraction details by hand. Pass the run
context and require the subagent to read its installed agent file, Phase 0
receipt, scope scan, catalog, schemas, and current validator report. A dispatch
prompt must not tell a subagent to write final fact YAML directly, create
generator/fixer scripts, or run broad `Glob "**/*"` scans. Model-authored
temporary merge-batch YAML remains allowed by the agent IO protocol.

## Ownership

Subagents write only paths allowed by `spec/ownership.yaml`.

- Host writes `facts/host.yaml` sections.
- Boundary writes `facts/operator/**`.
- Compute writes `facts/compute.yaml` sections.
- Kernel overview writes `facts/kernel/overview.yaml` sections.
- Slice planner writes `facts/kernel/slice_manifest.yaml` and
  `facts/kernel/slice_interfaces.yaml`.
- Slice agents write the assigned `facts/kernel/slices/<slice_id>.yaml` partition.
- Review agents write only `checks/step2/review.yaml` or
  `checks/step3/review.yaml`.

No subagent writes proposals, canonical promotion files, route files,
contracts, tiling archive files, impact graphs, or generated tests.

## Barrier

After Phase 1 `uo-boundary-agent` returns, run:

```powershell
python -X utf8 "$SCRIPT_DIR/validate_facts.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --stage step1 --scope boundary --write-report
```

If it fails, resume `uo-boundary-agent` with the validator report, exact schema,
file catalog entry, stable ID rules, and current file content.

After Phase 2 tasks return, run the three scoped `validate_facts.py` commands,
then `uo-step2-fact-review-agent`, then `write_step2_receipt.py`.

After Phase 3 slice tasks return, run Step 3 validation, then
`uo-step3-fact-review-agent`, then `write_step3_receipt.py`.

If a barrier fails, resume the owning subagent. The orchestrator must not edit a
subagent-owned fact file to force a pass.

If a fact write or validator fails, resume the same owning subagent with the
validator report, target schema, file catalog entry, stable ID rules, and the
current file content. Do not spawn a new general agent for repair.

Use `merge_fact_entries.py --batch <temp_batch.yaml>` for repairs. The obsolete
`--entries-file` spelling is not part of the dispatch contract.

## CBM

Use MCP `codebase-memory-mcp` for symbol/call/source behavior checks. Do not use
local CLI fallback commands.

