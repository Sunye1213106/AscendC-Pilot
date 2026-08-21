# Split-field diff infers perf scenarios

## Given

A TilingData / FIELD writer named `usedCoreNum` (or another split hint) appears in the slice.

## Task (CE)

Map to catalog perf ids. Budget is a handful of profiler rows, not all legal keys.

## Correct outcome

`F-SPLIT`, `F-SHAPE-TYPICAL`, and `F-BALANCE` when the name contains core/block. Oracle is `profiler`.
