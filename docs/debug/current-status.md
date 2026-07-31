# UO current status (generated)

> Written by `scripts/_probe_derive.py` on every full run. Do not edit.
> Numbers quoted anywhere else are commentary and may lag this file.

- run: `2026-07-31T10:30:20.564402+00:00`  op: `FlashAttentionScoreGrad`  arch: `arch35`

| metric | value |
| --- | ---: |
| CLOSED (exact + constant) | **14/19** |
| INPUT_DERIVABLE | **12/19** |
| unique free_vars | **3** |
| unrecorded free_vars (must be 0) | **0** |
| implicit_defaults | 135 |
| domain_violations | 1 |
| max expanded chars | 80462 |
| total seconds | 38.0 |

## Remaining free variables

| variable | where | blocks | dimensions |
| --- | --- | ---: | --- |
| `invalidS1Array[j]` | FillBlockInfoLoadBalanceForBn2 @ flash_attention_score_grad_tiling_varlen_regbase.cpp:899 | 5 | DeterType, IsBn2MultiBlk, IsNzOut, IsTndSwizzle, SplitAxis |
| `invalidS1Array[j]` | GetParseS1S2OuterInfo @ flash_attention_score_grad_tiling_normal_regbase.cpp:1546 | 5 | DeterType, IsBn2MultiBlk, IsNzOut, IsTndSwizzle, SplitAxis |
| `parseInfo[(s2Outer(fBaseParams) - 1)][LENGTH_IDX]` | GetSparseBlockInfoBn2 | 2 | IsBn2MultiBlk, SplitAxis |

## Per-dimension

| # | dimension | exactness | input_derivable | free |
| ---: | --- | --- | --- | ---: |
| 0 | IsEmptyTensor | exact | yes | 0 |
| 1 | SplitAxis | overapproximated | no | 3 |
| 2 | InputDType | exact | yes | 0 |
| 3 | IsTnd | exact | no | 0 |
| 4 | IsDrop | exact | yes | 0 |
| 5 | IsPse | exact | yes | 0 |
| 6 | IsAttenMask | exact | yes | 0 |
| 7 | S1TemplateNum | exact | yes | 0 |
| 8 | S2TemplateNum | exact | yes | 0 |
| 9 | DTemplateNum | exact | yes | 0 |
| 10 | DeterType | overapproximated | no | 2 |
| 11 | IsNEqual | exact | no | 0 |
| 12 | IsBn2MultiBlk | overapproximated | no | 3 |
| 13 | IsDNoEqual | exact | yes | 0 |
| 14 | IsRope | exact | yes | 0 |
| 15 | OutDType | exact | yes | 0 |
| 16 | IsNzOut | overapproximated | no | 2 |
| 17 | IsTndSwizzle | overapproximated | no | 2 |
| 18 | IsRegbase | constant | yes | 0 |
