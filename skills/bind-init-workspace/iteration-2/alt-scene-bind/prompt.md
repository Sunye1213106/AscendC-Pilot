# alt-scene bind accuracy

Time pressure: one shot. Different operator than any previous example. FACTS below are observations from the call window, the case-builder mapping window, and one header Read — not a binding key.

## Call (richest precision entry, not profiler)

```python
torch_npu.npu_block_matmul(
    left,
    right,
    batch=Batch,
    scale=1.0 / math.sqrt(Width),
    packed=normalize(segs),
)
```

No CSV column is named `scale`. `Width` in `math.sqrt(Width)` is the CSV column `Width`. `mask` is not a kwarg of this call.

## How the script uses the five columns

- `Width`: last dim when building `left` / `right`; also the Python name inside `math.sqrt(...)`.
- `Batch`: CSV cell is passed as `batch=`.
- `segs`: input to `normalize(...)` that becomes `packed`. This branch runs only under Packed layout.
- `pad_tail`: `real_n = Batch - pad_tail`; `segs` is then sliced to `real_n` before `normalize`. `pad_tail` does not appear in the call.
- `gate_on`: if set, Python builds a `mask` tensor used only in the Python pre-step. `mask` does not appear in the call.

## Header fields (one Read of the tiling_data `.h`, with the comments that are on those lines)

```
b          // batch
width      // last dim of left/right
width1     // aligned width
scaleValue // kernel scale
packedSeg  // packed segment descriptor
maskOuter  // generate outer mask
padToken   // padding token id
```

## dim_names

`Packed`, `DType`

Identifier query budget remaining: 8. You feel tempted to spend all 8 and leave the rest as PARTIAL with empty `uo_id`.

## Output (exactly this shape)

```yaml
plan_tools:   # ordered list of tools you WOULD use on the real task, max 6 bullets
mapping:
  Width: {role: ..., uo_id: ..., encoding: ...}
  Batch: {role: ..., uo_id: ..., encoding: ...}
  segs: {role: ..., uo_id: ..., encoding: ...}
  pad_tail: {role: ..., uo_id: ..., encoding: ...}
  gate_on: {role: ..., uo_id: ..., encoding: ...}
domains:
  Width: {operator: ..., compare: ...}
  Batch: {operator: ..., compare: ...}
  segs: {operator: ..., compare: ...}
  pad_tail: {operator: ..., compare: ...}
  gate_on: {operator: ..., compare: ...}
findings: [...]
verify:     # one line: how you confirm the yaml before handoff
```

Fill every field. If PARTIAL, still fill `uo_id` the way the method says.
