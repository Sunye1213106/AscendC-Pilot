# Code-access invariants (model-facing, short)

1. Semantic lookup uses `uo-query`. Primary may Read / Glob / list operator source. Grep of operator source remains denied when a CodeMap exists (`SOURCE_READ_USE_UO_QUERY`).
2. No unbounded repo / parent-repo scans; no whole-file dumps into context.
3. Empty UO graph ≠ symbol does not exist; fall back to scoped source read.
4. Shallow ABI `set_*` writers without value-defining sites → PARTIAL/UNKNOWN, not “unreachable”.

Full detail: `pilot/policies/code-access/POLICY.md` (host/Windows path tips live in docs).
