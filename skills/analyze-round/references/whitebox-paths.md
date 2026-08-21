# Whitebox paths (distilled)

**When to load**: a slice hits kernel/host control flow that blackbox
shapes would miss. Distilled from whitebox path enumeration. Do not
re-walk the whole kernel CFG in the Agent; start from CodeMap
`kernel_branch` / `kernel_api`.

## Live-path cues → scenario

| Path | Source cue | scenario_id |
| --- | --- | --- |
| Tail core | `blockIdx` last block / remainder | `P-TAIL`, `F-SHAPE-TAIL` |
| Remainder tile | `count = (i==tileNum-1) ? tail : TILE` | `P-TAIL` |
| Unaligned copy | non-32B last dim → DataCopyPad | `P-COPY-ALIGN` |
| Single vs multi core | total vs `blockNum` threshold | `F-BALANCE` |
| dtype / template | `if constexpr` / TILING_KEY | `P-DTYPE`, dispatch overlay |
| Empty / min | shape `[1]` or zero axis | `P-TAIL` |

Every path obligation needs a source span. No span → not a path.

## Construction

Invert the predicate: remainder shape = `TILE*n+k` (`k≠0`); unaligned =
last dim +1; threshold = `{T-1, T, T+1}`. Keep the same TilingKey if the
scenario is runtime-under-key; otherwise it is dispatch, not `P-*`/`F-*`.
