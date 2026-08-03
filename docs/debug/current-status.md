# UO current status (generated)

> Written by `scripts/_probe_derive.py` on every full run. Do not edit.
> Numbers quoted anywhere else are commentary and may lag this file.

- run: `2026-08-03T10:41:32.960741+00:00`  op: `FlashAttentionScoreGrad`  arch: `arch35`

| metric | value |
| --- | ---: |
| CLOSED (exact + constant) | **14/19** |
| INPUT_DERIVABLE | **12/19** |
| unique free_vars | **10** |
| unrecorded free_vars (must be 0) | **0** |
| implicit_defaults | 8 |
| domain_violations | 1 |
| max expanded chars | 123039 |
| total seconds | 57.3 |

## Remaining free variables

| variable | where | blocks | dimensions |
| --- | --- | ---: | --- |
| `VAR_AUX_DOBN2S2SPARSE_BLOCKOUTER` |  | 2 | IsBn2MultiBlk, IsTndSwizzle |
| `VAR_AUX_FBASEPARAMS_DETERSPARSETYPE` |  | 1 | IsNzOut |
| `VAR_AUX_FBASEPARAMS_ISDETERMINISTIC` |  | 1 | SplitAxis |
| `VAR_INIT_88BC16D7A53A` |  | 2 | IsNzOut, IsTndSwizzle |
| `VAR_INIT_D322285C4E66` |  | 3 | IsBn2MultiBlk, IsTndSwizzle, SplitAxis |
| `invalidS1Array[j]` | FillBlockInfoLoadBalanceForBn2 @ flash_attention_score_grad_tiling_varlen_regbase.cpp:899 | 3 | IsBn2MultiBlk, IsTndSwizzle, SplitAxis |
| `invalidS1Array[j]` | GetParseS1S2OuterInfo @ flash_attention_score_grad_tiling_normal_regbase.cpp:1546 | 3 | IsBn2MultiBlk, IsTndSwizzle, SplitAxis |
| `parseInfo[(s2Outer(fBaseParams) - 1)][LENGTH_IDX]` | GetSparseBlockInfo | 4 | IsBn2MultiBlk, IsNzOut, IsTndSwizzle, SplitAxis |
| `(coreIdx >= CORE_LIST_NUM)` | flash_attention_score_grad_tiling_varlen_regbase.cpp:1279 | 4 | IsBn2MultiBlk, IsNzOut, IsTndSwizzle, SplitAxis |
| `CheckExceedL2Cache()` | 235C48CE5B99 | 2 | IsNzOut, IsTndSwizzle |

## Per-dimension

| # | dimension | exactness | input_derivable | free |
| ---: | --- | --- | --- | ---: |
| 0 | IsEmptyTensor | exact | yes | 0 |
| 1 | SplitAxis | overapproximated | no | 6 |
| 2 | InputDType | exact | yes | 0 |
| 3 | IsTnd | exact | no | 0 |
| 4 | IsDrop | exact | yes | 0 |
| 5 | IsPse | exact | yes | 0 |
| 6 | IsAttenMask | exact | yes | 0 |
| 7 | S1TemplateNum | exact | yes | 0 |
| 8 | S2TemplateNum | exact | yes | 0 |
| 9 | DTemplateNum | exact | yes | 0 |
| 10 | DeterType | overapproximated | no | 0 |
| 11 | IsNEqual | exact | no | 0 |
| 12 | IsBn2MultiBlk | overapproximated | no | 6 |
| 13 | IsDNoEqual | exact | yes | 0 |
| 14 | IsRope | exact | yes | 0 |
| 15 | OutDType | exact | yes | 0 |
| 16 | IsNzOut | overapproximated | no | 5 |
| 17 | IsTndSwizzle | overapproximated | no | 8 |
| 18 | IsRegbase | constant | yes | 0 |
