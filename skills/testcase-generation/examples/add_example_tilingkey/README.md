# add_example — two-dim tiling key (real TEST material)

## Source

Copied from `TEST/ops-transformer/examples/add_example/` (not invented).

## Given

- Host sets tiling key from dtype (`SetTilingKey` / `GET_TPL_TILING_KEY`).
- Kernel selects float vs int32 path via `if constexpr (schMode == …)`.

## Task (TG)

Bind the `schMode` / dtype dimension so CSV or full-coverage planning can emit the two keys without inventing column names.

## Correct outcome

- Two concrete keys: mode 0 (float) and mode 1 (int32).
- Host writer sites and kernel `if constexpr` arms must both appear in the binding evidence.

## Why correct

Host and kernel agree on the same two-valued `schMode` list declared in `add_example_tiling_key.h`.
