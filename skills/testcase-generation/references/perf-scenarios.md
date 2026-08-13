# Performance scenarios (distilled)

**When to load**: constructing cases for `F-*` ids. Distilled from
four-layer tiling/pipeline thinking and profiling metrics. Do not copy
msprof command lines or simulator charts here.

## Four-layer cue → what to measure

| Layer (theory) | If the slice hits | scenario_id |
| --- | --- | --- |
| Tiling model (split, core count, UB) | split-field rhs / usedCoreNum | `F-SPLIT`, `F-BALANCE` |
| Inter-core | CrossCore / multi-core predicate | `F-BALANCE` |
| In-core / buffer | BUFFER, QUEUE, InitBuffer | `F-BUFFER` |
| Dtype throughput | compute dtype path | `F-DTYPE` |

Always include `F-SHAPE-TYPICAL` (L1 intent: competitive / network shapes)
when any perf scenario attaches. Add `F-SHAPE-TAIL` when tail or
non-divisible tile is in the slice.

## Budgets

- Typical perf subset: **3–8** cases. Never enumerate legal keys.
- Same shape across dtypes when `F-DTYPE` is present.
- Oracle is harness `profiler` (kernel time / pipe metrics). Host replay
  HIT does not close `F-*`.

## What “good enough” means (for selecting cases, not scoring)

Prefer cases that expose:

- Task duration vs expected bound class
- Load balance (single-core vs full-core)
- Bandwidth / UB pressure from buffer direction

Closing `V` still requires a profiling receipt (`ce-external-evidence/v1`).
