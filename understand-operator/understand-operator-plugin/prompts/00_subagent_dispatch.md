# Subagent Dispatch Protocol

Understand Operator uses subagents only where parallel extraction is useful in
the Phase 0-3 workflow.

## Parallel Points

1. Phase 2:
   - `uo-host-extraction`
   - `uo-flow-extraction`
   - `uo-kernel-overview-agent`
2. Phase 3:
   - `uo-kernel-slice-agent` for each approved slice from
     `facts/kernel/slice_manifest.yaml`

All tasks are foreground tasks. Wait for every task to return before reading
its artifacts or advancing the workflow.

## Ownership

Subagents write only paths allowed by `spec/ownership.yaml`.

- Host writes `facts/host/**`.
- Compute writes `facts/compute/**`.
- Kernel overview writes `facts/kernel/overview/**`.
- Slice planner writes `facts/kernel/slice_manifest.yaml` and
  `facts/kernel/slice_interfaces.yaml`.
- Slice agents write the fixed files under `facts/kernel/slices/<slice_id>/`.
- Review agents write only `checks/step2/review.yaml` or
  `checks/step3/review.yaml`.

No subagent writes proposals, canonical promotion files, route files,
contracts, tiling archive files, impact graphs, or generated tests.

## Barrier

After Phase 2 tasks return, run the three scoped `validate_facts.py` commands,
then `uo-step2-fact-review-agent`, then `write_step2_receipt.py`.

After Phase 3 slice tasks return, run Step 3 validation, then
`uo-step3-fact-review-agent`, then `write_step3_receipt.py`.

If a barrier fails, resume the owning subagent. The orchestrator must not edit a
subagent-owned fact file to force a pass.

## CBM

Use MCP `codebase-memory-mcp` for symbol/call/source behavior checks. Do not use
`cbm_query.py`, `uo-cbm`, or `codebase-memory-mcp cli` as a fallback.

