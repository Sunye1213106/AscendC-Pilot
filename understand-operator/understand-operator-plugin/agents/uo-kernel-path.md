---
name: uo-kernel-path
description: "RETIRED: old kernel path agent. Use uo-kernel-overview-agent plus uo-kernel-slice-agent."
model: inherit
---

This agent is retired in the Phase 0-3 workflow.

Do not run kernel path tasks, dispatch reviews, proposal promotion, canonical
kernel files, cross-layer files, or route/contract builders.

Use:

- `uo-kernel-overview-agent` in Phase 2 for global kernel overview facts.
- `uo-kernel-slice-planner` in Phase 3 for slice planning.
- `uo-kernel-slice-agent` in Phase 3 for slice facts.

