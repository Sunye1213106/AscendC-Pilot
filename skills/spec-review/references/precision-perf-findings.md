# Precision / perf findings (review only)

**When to load**: `/ce-review` when the window contains Cast, copy, queue,
or tiling-split code. Findings are H0/H1 clues. They do **not** enter CE
`V`.

## Side

`op_kernel/` → kernel numeric / copy / queue. `op_host/` → split formula /
optional-input guards. State both sides if both moved.

## H0 / H1 cues

| Window | H1 (needs path:line) | Related scenario clue |
| --- | --- | --- |
| `Cast` | wrong dst dtype or skipped path | `P-CAST`, `P-DTYPE` |
| `DataCopy` last dim not 32B and not Pad | misaligned copy | `P-COPY-ALIGN` |
| compute without EnQue/DeQue | stale UB / zeros | `P-QUEUE` |
| long reduce without stable acc dtype | drift on large S | `P-REDUCE-LONG` |
| split-field rhs change | tile/core bound shift | `F-SPLIT` |
| InitBuffer / queue tposition | UB pressure | `F-BUFFER` |

No `path:line` → not a finding. Point to CE scenario infer for test
obligations; do not claim golden or profiler results from review.
