# 绑定列

只 Edit 引擎已写出的本路 `parts/bindN.yaml` 语义格（FOCUS / stub 里的路径）。不要新建空白 YAML，不要改列名、`schema`、`run_id`、`artifact_identity`。不要 Write 合并后的 `bind.yaml`，不要写 `harness.yaml`，不要写其它 `bindN.yaml`。

本路只填这份草稿里已有的 mapping key（每路 ≤20 列）。`call` / `call_args` 仍覆盖最富调用的每一个实参——接线需要全貌，列格子只写本路。

## 硬规则

- **status 只看调用点，不看 CodeMap。** 禁止用 `dim_names` / AttrIndex 有无改 `control.status`。图上没有某名字，列仍可能是 active。
- **查图只用 `pilot_cli uo-query`。** 无参一次只看 `dim_names`（开关/模板分档）。标识符是位置参数：`uo-query --project <算子路径> <ident>`。禁止 `Dim=` 扫目录。禁止 Grep / 通读 `op_host`。禁止把 `dim_names` 里的名字拿去当尺寸/dtype 列的查询词。
- **尺寸列 identifier = 列名。** 多卡片只取 `kind: TILING_FIELD` 的 `.name` 作 `uo.id`（禁止 `TDF::`）。不要绑 INPUT/OUTPUT/VARIABLE 操作数，不要绑 `*TemplateNum`。
- **标量 kwargs 的 source 列 `uo.id` = 该 `call_args.name`。** 判断看 arg **名字**（`num_heads` / `keep_prob` / `input_layout` 及同类标量），不要看 sources 写成了 `direct` 还是 `tensor_shape`。该列即使同时还是张量维，也抄 kwargs 名。禁止 id 空、禁止只把短名放 `candidate`。inspect 前必须回扫。
- **开关维 / 模板分档不是 dtype、shape、layout 的身份。** `Is*`、`*DType`、`*TemplateNum` 只有「列本身就是该开关」才能当 `uo.id`。投影写 `domains.projection`。
- **两列不许共用一个 `uo.id`。** dtype 与 shape 必须分开。
- **metadata 只有 Enable / 用例名 / 是否跑这行。** 确定性等 host 会读的运行上下文 → `active`，绑该开关维。
- **`call_args.sources[].column` 出现的列必须是 `active`。** `.pt` 加载不把维 / dtype / layout 改成 `metadata` 或 `unwired`。`unwired` 仅当最富调用里根本没有对应实参（只进 golden / JSON）。

## 路径（一次做完就停）

1. **并行：** 无参 `uo-query`（只要 `dim_names`；hint 里的 `Dim=` 不要跟）+ 读 `repo_scan.yaml` 表头。不要通读 CSV，不要读对轴产物或仓外笔记。
2. **最富调用一个窗口**（精度入口 / 非 profiler）+ 读 `repo_scan.yaml` 表函数映射段。先写 `call` + `call_args.sources[]`。不要扫整个测试仓。这一步完成前不要给列写 `control`。
3. **本路每列**写 `control.status` + `relation`。
4. **仅 active 查 identifier。** 标量 kwargs **查 kwargs 名**（不要用 CSV 列名去碰尺寸字段）。没有 `TILING_FIELD` 也立刻把 `uo.id` 写成该 `call_args.name`，禁止空。尺寸列才查**列名**。dtype 列不要查 `*DType` / `Is*`。命中 `TILING_FIELD` 后，snippet 里同 struct 的邻维可分给本路其它尺寸列。够闭合就停。
5. **立刻 Edit 一次**本路 YAML 语义格。不要为拼 old_string 再读整份草稿。
6. **写后核对（不过就不能 inspect）：** 打开刚写的 YAML，只扫 `call_args`。每个 **名字是标量/layout** 的 arg（不是 query/key/value/grad 张量）：其每个 `sources[].column` 若 `uo.id` 为空，改成该 `name`，`confidence: confirmed`。`candidate` 不能代替 id。encoding/runtime 已出现该 arg 名而 id 仍空 → 同样改。每个 `sources[].column` 必须 `active`。改完再走 7。
7. `inspect yaml --rel <本路 bindN.yaml 相对 .ascendc-pilot 的路径>` 返回 ok → 立刻 summary。

## 分类

`control.status`：`active` | `fallback` | `shadowed` | `unwired` | `result` | `metadata`

`relation`：`direct` | `derived` | `tensor_shape` | `tensor_dtype` | `presence`（分不清就留空 + `confidence: unresolved`）

- 出现在任一 `call_args.sources[].column` → **必须 `active`**。`.pt` 加载不把维 / dtype / layout 改成 metadata 或 unwired。
- 表 100% 空且 runner 从**另一列**重算 → 空列 `shadowed`，源列 `active` + `derived`。
- 调用里根本没有对应实参、只进 golden / JSON → `unwired`。
- `Actual_` / 期望 / 实测写回 → `result`。
- Enable / 用例名 / 是否跑行 → `metadata` + 空 relation + `unresolved`，禁止 `uo.id`。
- 不进 kwargs、但改写另一列或驱动 host 运行上下文（确定性）→ `active`（`derived` / `presence`），要绑 UO。

unwired / shadowed / fallback / result / metadata 停在分类，不要为它们填 `uo.id`。

## 对名（按列类型，第一命中）

`uo.id` 填短名 / `canonical`。禁止 `TDF::` 和 tiling 结构名。禁止把 `candidate` 升格成 `uo.id`。

**先看该列是否出现在「标量 / layout kwargs」的 `sources[]`。是 → 走 1，不要走 2。**

1. **标量 kwargs 列**（接到 `num_heads`、`keep_prob`、`input_layout` 这类标量/layout 名）：`uo.id` **等于** 该 `call_args.name`。禁止空。→ `confirmed`。不要改用同维 tiling 字段候选。
2. **仅作为张量维的 tensor_shape 列**（没有标量 kwargs source）：`uo.id` = 列名查到的 `TILING_FIELD.name`。禁止操作数名、禁止 `*TemplateNum`、禁止 `TILING_KEY`。对不上 → 空 + `unresolved`。
3. **tensor_dtype 列**：不要绑 `*DType` / `Is*`。对不上 → 空 + `unresolved`，不要 `confirmed`。
4. **列本身就是开关**（无参 `dim_names` 那一维，且列控制的就是它）→ 抄那维。
5. 对不上 → 空 + `unresolved` + findings `PARTIAL`。不借邻居。

CSV→API→具名 kwargs 闭合且 `uo.id` 非空 → `confirmed`。只碰到相似符号 → `uo.candidate` + `unresolved`。dtype/shape 不要用开关维凑 `confirmed`。

`operator` / `compare` 只对 active。`compare=match` 仅当 `operator` 非空。不要改引擎已写入的 `domains.profile`。

## 完成

- 每个 mapping key 都有 `control.status` + `relation` + `confidence`
- 每个标量 kwargs 的 source 列 `uo.id` 等于该 `call_args.name`；纯尺寸列是 `TILING_FIELD` 短名；两列不共 id
- 做过 call_args 回扫；做过一次无参 `uo-query`；没有 `Dim=`；没有 Grep 算子源
- inspect ok 后立刻停

## 输出形状

```yaml
call:
  kind: pta                 # pta | aclnn | mixed
  api: torch_npu.<fn>
  site: path.py:LINE
call_args:
  - name: x
    runtime_expr: x
    sources:
      - {column: BatchCol, relation: tensor_shape}
      - {column: InDtype, relation: tensor_dtype}
  - name: num_heads
    runtime_expr: nh
    sources:
      - {column: HeadCol, relation: direct}
mapping:
  BatchCol:
    control: {status: active}
    relation: tensor_shape
    confidence: confirmed
    uo: {id: batch, candidate: ''}   # TILING_FIELD.name
  HeadCol:
    control: {status: active}
    relation: direct
    confidence: confirmed
    uo: {id: num_heads, candidate: ''}  # 抄标量 call_args.name
  InDtype:
    control: {status: active}
    relation: tensor_dtype
    confidence: unresolved
    uo: {id: '', candidate: ''}
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

- 用 `dim_names`（`*TemplateNum` / `*DType` / `Is*`）当尺寸或 dtype 列的查询词或 `uo.id`
- `Dim=` 扫目录；Grep `op_host` 代替 identifier 查询
- 尺寸列绑操作数名 / `TILING_KEY` / 派生 kwargs（scale 一类）
- 标量 kwargs 的 source 列 `uo.id` 为空（encoding 里写了 kwargs 名也不算）；只把短名放 `candidate`
- 回扫没做就 inspect
- 张量已进调用，却把该张量的 dtype/shape 列标 `unwired`（`.pt` 加载不是未接线）；调用没有的 out-dtype 标 active
- 确定性列标 metadata
- 规划几十刀 Edit；inspect 没 ok 就停；读对轴产物 / 仓外笔记
