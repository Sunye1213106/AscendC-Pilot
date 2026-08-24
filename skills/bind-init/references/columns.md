# 绑定列

只 Edit 引擎已写出的本路 `parts/bindN.yaml` 语义格（FOCUS / stub 里的路径）。不要新建空白 YAML，不要改列名、`schema`、`run_id`、`artifact_identity`。不要 Write 合并后的 `bind.yaml`、`harness.yaml` 或其它 `bindN.yaml`。

本路只填草稿里已有的 mapping key（每路 ≤20 列）。`call` / `call_args` 仍覆盖最富调用的每一个实参；列格子只写本路。

## 硬规则

- **status 只看调用点，不看 CodeMap。** 禁止用 `dim_names` / AttrIndex 有无改 `control.status`。
- **查图只用 `pilot_cli uo-query`。** 无参一次只看 `dim_names`。标识符：`uo-query --project <算子路径> <ident>`。禁止 `Dim=`、禁止 Grep / 通读 `op_host`、禁止拿 `dim_names` 当尺寸/dtype 查询词。
- **尺寸列 identifier = 列名。** 只取 `kind: TILING_FIELD` 的 `.name`（禁止 `TDF::`、操作数、`*TemplateNum`）。
- **标量 kwargs 的 source 列 `uo.id` = 该 `call_args.name`。** 看 arg 名（`num_heads` / `keep_prob` / `input_layout` 一类），不看 relation。禁止空 id、禁止只放 `candidate`。inspect 前按 `call_args` 回扫。
- **入边数压过抄名。** 一列进多个标量 arg 时，只抄 `sources[]` 长度为 1 的那个。两列以上共喂的聚合 arg（长度求和、元素总数、workspace）谁都不抄。**两列不许共 `uo.id`**：抄名会撞就换成 1:1 的；只剩聚合 → 空 + `unresolved`。
- **开关维不是 dtype / shape / layout 的身份。** `Is*`、`*DType`、`*TemplateNum` 只有「列本身就是该开关」才能当 `uo.id`。投影写 `domains.projection`。
- **metadata 只有 Enable / 用例名 / 是否跑这行。** 确定性等 host 会读的运行上下文 → `active`。
- **`call_args.sources[].column` 必须 `active`。** 全空 ≠ `unwired`。`unwired` 仅当最富调用里根本没有对应实参。

## 路径（一次做完就停）

1. **并行：** 无参 `uo-query`（只要 `dim_names`）+ 读 `repo_scan.yaml` 表头。不要通读 CSV，不要读对轴产物。
2. **最富调用一个窗口**（精度入口 / 非 profiler）+ scan 的表函数映射。先写 `call` + `call_args.sources[]`，再写列 `control`。
3. **本路每列**写 `control.status` + `relation`。
4. **仅 active 查 identifier。** 标量 kwargs 查 kwargs 名；没有 `TILING_FIELD` 也立刻把 `uo.id` 写成该 `call_args.name`。尺寸列查列名。dtype 不要查 `*DType` / `Is*`。命中后 snippet 里同 struct 邻维可分给本路其它尺寸列。够闭合就停。
5. **立刻 Edit 一次**本路语义格。
6. **写后核对：** 扫 `call_args`。标量/layout arg 的每个 source 列：id 空则写成该 `name` 并 `confirmed`；必须 `active`；`confirmed` 必须有一行 `evidence`（`file:line` 或 TILING_FIELD 短名）。本路 `uo.id` 重复按入边数改。然后 `inspect yaml --rel <本路 bindN.yaml>` ok → summary。

## 分类

`control.status`：`active` | `fallback` | `shadowed` | `unwired` | `result` | `metadata`

`relation`：`direct` | `derived` | `tensor_shape` | `tensor_dtype` | `presence`（分不清就留空 + `unresolved`）

- 出现在 `call_args.sources[]` → **必须 `active`**（`.pt` 加载、生成器按别的列合成，都不改成 metadata / unwired）
- 表全空（`empty_rate==1.0`）且 runner 从**另一列**重算 → 空列 `shadowed`，源列 `active` + `derived`
- 调用没有对应实参、只进 golden / JSON → `unwired`
- `Actual_` / 期望 / 实测写回 → `result`
- Enable / 用例名 / 是否跑行 → `metadata` + 空 relation + `unresolved`，禁止 `uo.id`
- 不进 kwargs、但改写另一列或驱动 host 运行上下文（确定性）→ `active`（`derived` / `presence`），要绑 UO

unwired / shadowed / fallback / result / metadata 停在分类，不要填 `uo.id`。

## 对名（第一命中）

`uo.id` 填短名 / `canonical`。禁止 `TDF::`、tiling 结构名、把 `candidate` 升格成 id。

**先看该列是否出现在标量 / layout kwargs 的 `sources[]`。是 → 走 1，不要走 2。**

1. **标量 kwargs 列：** `uo.id` = 该 `call_args.name` → `confirmed`。多候选取 1:1；只剩聚合 → 空 + `unresolved`。
2. **仅 tensor_shape（无标量 kwargs source）：** `uo.id` = 列名查到的 `TILING_FIELD.name`。对不上 → 空 + `unresolved`。
3. **tensor_dtype：** 不要绑 `*DType` / `Is*`。对不上 → 空 + `unresolved`。
4. **列本身就是开关**（无参 `dim_names` 且列控制的就是它）→ 抄那维。
5. 对不上 → 空 + `unresolved` + findings `PARTIAL`。不借邻居。

CSV→API→具名 kwargs 闭合且 id 非空 → `confirmed`。只碰到相似符号 → `uo.candidate` + `unresolved`。不要用开关维给 dtype/shape 凑 `confirmed`。

`operator` / `compare` 只对 active。`compare=match` 仅当 `operator` 非空。不要改引擎写入的 `domains.profile`。

## 完成

- 每个 mapping key 都有 `control.status` + `relation` + `confidence`
- 标量 kwargs source 的 `uo.id` 是 1:1 的 `call_args.name`；纯尺寸列是 `TILING_FIELD` 短名；本路 id 互不重复
- `confirmed` 有 `evidence`；做过 call_args 回扫与一次无参 `uo-query`
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

- 用 `dim_names`（`*TemplateNum` / `*DType` / `Is*`）当尺寸或 dtype 的查询词或 `uo.id`
- `Dim=`；Grep `op_host`
- 尺寸列绑操作数名 / `TILING_KEY` / 派生 kwargs（scale 一类）
- 标量 kwargs source 空 id，或两列共一个聚合 arg 名
- `confirmed` 空 `evidence`；sources 列因表全空标成 `unwired`
- 确定性列标 metadata
- inspect 没 ok 就停；读对轴产物
