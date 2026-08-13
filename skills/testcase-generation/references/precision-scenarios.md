# Precision scenarios (distilled)

**When to load**: constructing cases for `P-*` ids. Distilled from
precision-debug decision trees, dtype tolerances, and repo-test precision
discipline. Do not copy DumpTensor step-by-step procedures here.

## Decision cues → scenario

| Code / failure cue | scenario_id | Knobs |
| --- | --- | --- |
| Cast site or dtype branch | `P-CAST`, `P-DTYPE` | each affected dtype; same shape; prefer FP32 then FP16/BF16 |
| DataCopy vs DataCopyPad / last-dim align | `P-COPY-ALIGN` | aligned 32B multiple vs +1 |
| EnQue/DeQue missing around compute (looks like wrong numbers) | `P-QUEUE` | smallest legal shape |
| Long reduction / softmax accumulate | `P-REDUCE-LONG` | large S / reduce axis (clean values) |
| Optional mask / pse / dropout / rope | `P-OPTIONAL` | present and absent; legal shapes only |
| Combinations the host/kernel reject | `P-ILLEGAL` | Disable or exclusion; **no NPU** |
| Tail core, empty tensor, rank-0 vs empty | `P-TAIL` | `[1]`, zero-axis; empty ≠ scalar |

## Clean vs stress

- **clean** (normal / zero / near_zero / all_ones): required gate.
- **stress** (big / neg_big / denormal): informational; do not use as the
  only hard gate.

## Tolerances (class, not a second golden)

Default float compare class (authoritative tables live in ops-precision-standard):

| dtype | rtol / atol class |
| --- | --- |
| FP32 | 1e-5 |
| FP16 | 1e-3 |
| BF16 | 1e-2 |

Oracle for these scenarios is harness precision mode (`only_grad`), not
Host tiling-key replay. A key HIT does not close `P-*`.

## Illegal combos

If a combination is known unsupported (shape/type matrix, host check), emit
Disable + `block_reason` or a source exclusion. Do not send it to NPU to
“see if it crashes”.
