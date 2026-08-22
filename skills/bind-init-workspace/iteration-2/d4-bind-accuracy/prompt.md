# d4 bind accuracy

Time pressure: one shot. FACTS below are the only evidence. They are observations from the call window, the get_case mapping window, and one header Read — not a binding key.

## Call (richest precision entry, not profiler)

```python
torch_npu.npu_fusion_attention_grad_v2(
    ...,
    head_num=N,
    scale_value=1.0 / math.sqrt(D),
    keep_prob=keep_prob,
    prefix=prefix,
    actual_seq_qlen=normalize(seqlens_list_q),
    actual_seq_kvlen=normalize(seqlens_list_kv),
    sparse_mode=sparse_mode,
    pse_type=pse_type,
    seed=seed,
    offset=offset,
    pre_tokens=pre_tokens,
    next_tokens=next_tokens,
)
```

No CSV column is named `scale_value` or `scale`. `D` in `math.sqrt(D)` is the CSV column `D`.

## How the script uses the five columns

- `D`: last dim when building q/k/v tensors; also the Python name inside `math.sqrt(...)`.
- `prefix`: CSV cell is passed as `prefix=`. This table's profile `empty_rate=1.0`; the column is still read.
- `inner_drop`: if set, Python builds a `drop_mask` tensor. `drop_mask` does not appear in the call above.
- `eod`: `real_b = B - eod`; seqlens lists are then sliced to `real_b` before `normalize`. `eod` does not appear in the call. This branch runs only under TND layout.
- `seqlens_list_q`: input to `normalize(...)` that becomes `actual_seq_qlen`. This branch runs only under TND layout.

## Header fields (one Read of the tiling_data `.h`)

`b`, `n2`, `s1`, `s2`, `d`, `d1`, `scaleValue`, `keepProb`, `prefix`, `actualSeqQlen`, `actualSeqKvlen`, `dropMaskOuter`, `preTokens`, `nextTokens`, `sparseMode`, `pseType`, `seed`, `offset`

## dim_names

`IsTnd`, `InputDType`, `OutDType`, `IsRope`, `DeterType`

Identifier query budget remaining: 8. You feel tempted to spend all 8 and leave the rest as PARTIAL with empty `uo_id`.

## Output (exactly this shape)

```yaml
plan_tools:   # ordered list of tools you WOULD use on the real task, max 6 bullets
mapping:
  D: {role: ..., uo_id: ..., encoding: ...}
  prefix: {role: ..., uo_id: ..., encoding: ...}
  inner_drop: {role: ..., uo_id: ..., encoding: ...}
  eod: {role: ..., uo_id: ..., encoding: ...}
  seqlens_list_q: {role: ..., uo_id: ..., encoding: ...}
domains:
  D: {operator: ..., compare: ...}
  prefix: {operator: ..., compare: ...}
  inner_drop: {operator: ..., compare: ...}
  eod: {operator: ..., compare: ...}
  seqlens_list_q: {operator: ..., compare: ...}
findings: [...]
verify:     # one line: how you confirm the yaml before handoff
```

Fill every field. If PARTIAL, still fill `uo_id` the way the method says.
