# PROVED — dtype selects schMode (real TEST pair)

## Source

Host + kernel excerpts from `TEST/.../add_example/`.

## Proposition

`P`: host sees `dataType == ge::DT_FLOAT` ⇒ `Q`: kernel float arm (`TILING_KEY_EXAMPLE_FLOAT` / schMode 0) is the selected template path.

## Correct verdict

`PROVED` with host SetTilingKey window + kernel `if constexpr` window.

## Why

Both sides cite the same `ELEMENTWISE_TPL_SCH_MODE_0` / enum float arm; no counterexample arm for float→int32.
