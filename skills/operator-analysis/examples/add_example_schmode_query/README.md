# Query → ANSWERED — AddExample schMode list (real TEST)

## Source

`TEST/.../add_example/op_kernel/add_example_tiling_key.h`

## Question

What values can `schMode` take for AddExample?

## Correct answer

`ANSWERED`: `{0, 1}` via `ASCENDC_TPL_UINT_DECL` / `ASCENDC_TPL_UI_LIST`, with file span.

## Why

Template arg declaration is the structural authority for the dimension domain.
