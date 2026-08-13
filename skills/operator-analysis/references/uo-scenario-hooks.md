# UO query hooks for scenarios

**When to load**: choosing `uo-query` modes before CE scenario infer.
UO locates structure. Flag sync records identity-level pair appearance.
TQue EnQue/DeQue are outside that check. UO does not judge golden, happens-before, or profiler numbers.

| Need | Mode | Typical scenario_id |
| --- | --- | --- |
| Cast / DataCopy / DataCopyPad | `kernel_api` | `P-CAST`, `P-COPY-ALIGN` |
| EnQue / DeQue | `kernel_api` | `P-QUEUE`（TQue，不进 Flag 配对） |
| SetFlag / WaitFlag / CrossCore* | `kernel_api` | identity 级 `flag_paired`；happens-before 不是 UO |
| INPUT dtype | `search` INPUT/OUTPUT | `P-DTYPE` |
| Buffer / queue / tposition | `buffer` | `F-BUFFER` |
| Split field writer / rhs | `field` / `tiling_data` | `F-SPLIT` |
| Diff neighborhood | `impact` | map buckets to catalog ids |
| Tail / runtime branch | `kernel_branch` | `P-TAIL`, `F-SHAPE-TAIL` |

Do not run DumpTensor, msprof, or happens-before proofs in UO.
