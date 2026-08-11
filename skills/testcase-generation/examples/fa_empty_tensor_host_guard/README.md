# flash_attn_example — empty-tensor host guard (real TEST material)

## Source

`TEST/ops-transformer/examples/flash_attn_example/.../torch_interface.cpp`

## Given

Host rejects empty q/k/v tensors before launch.

## Task (TG)

Treat empty-tensor as a **host-side precondition**, not a TilingKey dimension to cover with synthetic empty GM shapes unless the contract says so.

## Correct outcome

Document the guard as an input constraint / exclusion lead with source span; do not invent a tiling key for `numel()==0`.

## Why correct

The check is in torch host validation (`q.numel() == 0` …), not in AscendC tiling-key template args.
