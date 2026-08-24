# 绑定列

只 Edit 引擎已写出的本路 `parts/bindN.yaml` 语义格（FOCUS / stub 里的路径）。不要新建空白 YAML，不要改列名、`schema`、`run_id`、`artifact_identity`。不要 Write 合并后的 `bind.yaml`，不要写 `harness.yaml`，不要写其它 `bindN.yaml`。

本路只填这份草稿里已有的 mapping key（每路 ≤20 列）。`call` / `call_args` 仍覆盖最富调用的每一个实参——接线需要全貌，列格子只写本路。

## 硬规则

- **status 只看调用点，不看 CodeMap。** 禁止用 `dim_names` / AttrIndex 有无改 `control.status`。图上没有某名字，列仍可能是 active。
- **查图只用 `pilot_cli uo-query`。** 无参一次即可拿到开关维。禁止用 `Dim=` 把 `dim_names` 扫一遍。禁止 Grep / 通读 `op_host` 代替 identifier 查询。卡片已有 `file:line` + snippet 视为已读。
- **kwargs 的 source 列必须有 `uo.id`。** 禁止因为「不在 dim_names 里」就标 `partial` 并留空 `uo.id`。`partial` 不是逃避绑名的出口。
- **开关维不是 dtype / shape / layout 的身份。** 投影写 `domains.projection`（如 `Input_Layout → IsTnd`），不要当 `uo.id`。
- **两列不许共用一个 `uo.id`。** dtype 与 shape 必须分开。
- **metadata 只有 Enable / 用例名 / 是否跑这行。** 确定性、设备等运行上下文 host 会读 → `active`，绑该开关维，不是 metadata。

## 路径（一次做完就停）

1. **并行：** 无参 `pilot_cli uo-query --project <算子绝对路径>`（只要 `dim_names` / `hint` / `canonical`）+ 读 `repo_scan.yaml` 表头。不要通读 CSV，不要读对轴产物。
2. **最富调用一个窗口**（精度入口 / 非 profiler）+ 读表函数映射段。先写 `call` + `call_args.sources[]`。这一步完成前不要给列写 `control`。
3. **本路每列**写 `control.status` + `relation`。
4. **仅 active：** 缺哪个短名就 `uo-query` 哪个标识符。不要先规划查询次数。够闭合就停。
5. **立刻 Edit 一次**本路 YAML 语义格。不要为拼 old_string 再读整份草稿，不要规划几十刀 Edit。
6. `pilot_cli inspect yaml --rel <本路 bindN.yaml 相对 .ascendc-pilot 的路径>` 返回 ok → 立刻 summary。没 ok 就还没做完。

## 分类

`control.status`：`active` | `fallback` | `shadowed` | `unwired` | `result` | `metadata`

`relation`：`direct` | `derived` | `tensor_shape` | `tensor_dtype` | `presence`（分不清就留空 + `confidence: unresolved`）

- 出现在任一 `call_args.sources[].column` → `active`。`.pt` 加载不把维 / dtype / layout 改成 metadata。
- 表 100% 空且 runner 从另一列重算 → 空列 `shadowed`，源列 `active` + `derived`。
- API 语义对但表全空、调用没接 → `unwired`。
- `Actual_` / 期望 / 实测写回 → `result`。
- Enable / 用例名 / 是否跑行 → `metadata` + 空 relation + `unresolved`，禁止 `uo.id`。
- 不进 kwargs、但改写另一列或驱动 host 运行上下文（确定性）→ `active`（`derived` / `presence`），要绑 UO。

unwired / shadowed / fallback / result / metadata 停在分类，不要为它们填 `uo.id`。

## 对名（第一命中）

`uo.id` 填短名 / `canonical`。禁止 `TDF::` 和 tiling 结构名。禁止把 `candidate` 升格成 `uo.id`。

1. identifier `uo-query` 命中**这一列的量**（尺寸列绑该维字段，不绑用它算出来的 kwargs）。
2. 否则：该列是某个 kwargs 的 source → `uo.id` = 该 `call_args.name`。禁止空。
3. 列本身就是开关（无参查询 `dim_names` 里那一维）→ 抄那维。
4. 对不上 → 空 + `unresolved` + findings `PARTIAL`。不借邻居。

CSV→API→Host 整条闭合且 `uo.id` 非空 → `confidence: confirmed`。只碰到相似符号 → `uo.candidate` + `unresolved`。不要用 `partial` 代替「kwargs 列必须有短名」。

`operator` / `compare` 只对 active。`compare=match` 仅当 `operator` 非空。不要改引擎已写入的 `domains.profile`。

## 完成

- 每个 mapping key 都有 `control.status` + `relation` + `confidence`
- 每个 kwargs source 列有非空 `uo.id`；两列不共 id；开关维没写成 dtype/shape 身份
- 做过一次无参 `uo-query`；没有 `Dim=` 扫目录；没有 Grep 算子源代替查图
- inspect ok 后立刻停

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
    relation: direct             # direct|derived|tensor_shape|tensor_dtype|presence
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

## 反模式

- `Dim=` 把开关维查一遍再宣布「没有 UO」
- Grep `op_host` / 通读 tiling 代替 identifier `uo-query`
- active kwargs 列 `partial` + 空 `uo.id`
- 尺寸列绑派生 kwargs（scale 一类）；layout / seqlens 绑开关维
- dtype 与 shape 共 `uo.id`
- 确定性列标 metadata
- 规划几十刀 Edit；inspect 没 ok 就停；读对轴 `bind.yaml` / `harness.yaml`
