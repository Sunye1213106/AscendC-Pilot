# alt-scene bind: aggregate kwarg shared by two columns

One shot, different operator from any previous example. Everything below is an
observation from the call window, the case-builder window, and one header Read. None of
it is a binding key — apply the method.

## Call (richest precision entry, not profiler)

```python
torch_npu.npu_ragged_gemm(
    left,
    right,
    num_groups=Groups,
    scale=1.0 / math.sqrt(Width),
    total_elems=count_all(row_lens, col_lens),
    row_offsets=tuple(row_lens),
    col_offsets=tuple(col_lens),
    layout=Layout,
)
```

`count_all(x, y)` is `(np.array(x) * np.array(y)).sum() * Groups`. No CSV column is
named `scale` or `total_elems`.

## How the script uses the columns

- `Width`: last dim when building `left` / `right`; also the Python name inside `math.sqrt(...)`.
- `Groups`: CSV cell passed as `num_groups=`; also a factor inside `count_all`.
- `Layout`: CSV cell passed as `layout=`.
- `row_lens`: parsed from the cell into a list; passed to `count_all` AND to `row_offsets`.
- `col_lens`: parsed from the cell into a list; passed to `count_all` AND to `col_offsets`.
- `row_starts`: column exists in the header but every cell is empty
  (`domains.row_starts.profile.empty_rate` is `1.0`); the runner recomputes it from
  `row_lens` by a prefix sum when it is needed.
- `InDtype`: dtype of `left` / `right`.
- `RunName`: the case identity string.
- `Actual_gflops`: measured throughput written back after the run.

## Header fields (one Read of the tiling_data `.h`, with the comments on those lines)

```
groups      // number of groups
width       // last dim of left/right
width1      // aligned width
scaleValue  // kernel scale
elemTotal   // total element count
rowSeg      // row segment descriptor
colSeg      // column segment descriptor
padToken    // padding token id
```

## dim_names

`Ragged`, `InDType`, `IsPad`

Identifier query budget remaining: 8.

## Output (exactly this shape, current schema)

```yaml
call:
  kind: pta | aclnn | mixed
  api: torch_npu.<fn>
  site: path.py:LINE
call_args:
  - name: <arg>
    runtime_expr: <expr>
    sources:
      - {column: <Col>, relation: <relation>}
mapping:
  <Col>:
    control: {status: <status>}
    relation: <relation>
    confidence: <confidence>
    uo: {id: <short name or empty>, candidate: <or empty>}
    encoding: <one line>
    evidence: <one line>
domains:
  <Col>: {applicability: '', value: '', projection: '', operator: '', compare: ''}
findings: []
```

Cover all nine columns: `Width`, `Groups`, `Layout`, `row_lens`, `col_lens`,
`row_starts`, `InDtype`, `RunName`, `Actual_gflops`. Fill every field the method
requires. Write the YAML to the path the harness gives you, then stop.
