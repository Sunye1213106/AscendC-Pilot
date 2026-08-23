# 绑定列

只 Edit 引擎已写出的本路 `parts/bindN.yaml` 语义格（FOCUS / stub 里的路径）。不要新建空白 YAML，不要改列名、`schema`、`run_id`、`artifact_identity`。不要 Write 合并后的 `bind.yaml`，不要写 `harness.yaml`，不要写其它 `bindN.yaml`。

本路只填这份草稿里已有的 mapping key（每路 ≤20 列）。`call` / `call_args` 仍覆盖最富调用的每一个实参——接线需要全貌，列格子只写本路。

查图只用 `pilot_cli uo-query`。缺哪个查哪个，不要先规划查询次数。

## 6 步

1. **打开 richest runtime call，抄真实 API args。** 禁止造伪 kwargs。先写 `call` + `call_args`，这一步完成前不要给列写 `control` / `relation`。
2. **每个 API arg 反向追踪：** `arg ← runtime ← transform ← CSV column(s)`。张量用 `sources[]`（shape / dtype / layout 分条），不要压成单个 `source_column`。没有 CSV 列的字面量 / `None` / 现场公式进 findings，不要发明表头。
3. **每列分类 `control.status` + `relation`。**
   - `control.status`：`active` | `fallback` | `shadowed` | `unwired` | `result` | `metadata`
   - `relation`：`direct` | `derived` | `tensor_shape` | `tensor_dtype` | `presence` | `candidate`
   - 表 100% 空且 runner 另有来源 → `shadowed` / `unwired`，不是 active 控制。
   - 不进调用的 harness 标志 → `metadata` + `candidate`。
4. **只有 `control.status: active` 才继续绑 UO。** unwired / shadowed / fallback / result / metadata 停在第 3 步，不要为它们填 `uo.id`。
5. **追 CSV → API/input → Host → implementation state。** 整条闭合 → `confidence: confirmed` 且 `uo.id` 填短名；只碰到相似 UO 符号 → `uo.candidate` + `unresolved`。禁止把 `candidate` 升格成 `uo.id`。禁止 `TDF::` id 和 tiling 结构名。
6. **plan 只消费 confirmed。** 本路不写 plan。未闭合的轴留给 review / plan 标 `untestable + needs_binding`。

## 输入 / 输出 / 停

读：`repo_scan.yaml` 表头与 `tables[].profile`。有仓则打开入口脚本的最富调用（精度入口 / 非 profiler）。不要发明 CSV 列名。不要通读 CSV。不要读对轴产物。

完成：本路每个 mapping key 都有 `control.status` + `relation` + `confidence`；`call_args` 用 `sources[]`；`pilot_cli inspect yaml --rel <本路 bindN.yaml 相对 .ascendc-pilot 的路径>` 返回 ok。

## domains

不要改引擎已写入的 `profile`。`applicability` / `value` / `projection` 分开写：`Input_Layout → IsTnd` 是 projection，不是 equality。`operator` / `compare` 只对 active 控制列。`compare` ∈ {`match`, `tighter_profile`, `tighter_operator`, `mismatch`}。**`compare=match` 仅当 `operator` 非空。**

## 循环

1. 打开 scan 入口 + 最富调用 + 读表函数。
2. 抄 `call_args`（`sources[]`）→ 再给本路列写 control/relation。
3. 仅 active 列查 UO；缺哪个标识符查哪个；停。
4. Edit 已有本路 YAML 的语义格。不要读对轴文件。

## 输出形状

```yaml
call:
  kind: pta                 # pta | aclnn | mixed
  api: torch_npu.<fn>
  site: path.py:LINE
call_args:
  - name: query
    runtime_expr: q
    sources:
      - {column: B, relation: tensor_shape}
      - {column: Dtype, relation: tensor_dtype}
mapping:
  ColName:
    control: {status: active}    # active|fallback|shadowed|unwired|result|metadata
    relation: direct             # direct|derived|tensor_shape|tensor_dtype|presence|candidate
    confidence: confirmed        # confirmed|partial|unresolved
    runtime: {target: ..., path: []}
    uo: {id: ident, candidate: ''}
    evidence: path.py:LINE
    encoding: 字面量或一句
domains:
  ColName:
    applicability: ''
    value: ''
    projection: ''
    operator: ...
    compare: match
findings: []
```
