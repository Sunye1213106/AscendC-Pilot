# 绑定列

只 Edit 引擎已写出的本路 `parts/bindN.yaml` 语义格（FOCUS / stub 里的路径）。不要新建空白 YAML，不要改列名、`schema`、`run_id`、`artifact_identity`。不要 Write 合并后的 `bind.yaml`、`harness.yaml` 或其它 `bindN.yaml`。

草稿里 `call` 与 `call_args[].name` 已按 `repo_scan.canonical_call` 填好。本路只给 `chunk.columns` 写格子，并只给这些列补 `call_args.sources[]`。合并后的 union 才覆盖完整 API。

## 硬规则

- **status 只看调用点，不看 CodeMap。** 禁止用 `dim_names` / AttrIndex 有无改 `control.status`。
- **查图只用 `pilot_cli uo-query`。** 无参一次只看 `dim_names`。标识符：`uo-query --project <算子路径> <ident>`。禁止 `Dim=`、禁止 Grep / 通读 `op_host`、禁止拿 `dim_names` 当尺寸/dtype 查询词。
- **尺寸列 identifier = 列名。** 只取 `kind: TILING_FIELD` 的 `.name`（禁止 `TDF::`、操作数、`*TemplateNum`）。
- **标量 / layout / 位置实参的 source 列 `uo.id` = 该 `call_args.name`。** 看 arg 名（`num_heads` / `keep_prob` / `input_layout` 一类），不看 relation。该列即使同时还是张量维，也抄这个名字。禁止空 id、禁止只放 `candidate`。inspect 前按 `call_args` 回扫。
- **入边数压过抄名。** 一列进多个标量 arg 时，只抄 `sources[]` 长度为 1 的那个。两列以上共喂的聚合 arg（长度求和、元素总数、workspace）谁都不抄。**两列不许共 `uo.id`**：抄名会撞就换成 1:1 的；只剩聚合 → 空 + `unresolved`。
- **开关维不是 dtype / shape / layout 的身份。** `Is*`、`*DType`、`*TemplateNum` 只有「列本身就是该开关」才能当 `uo.id`。投影写 `domains.projection`。
- **metadata 只有 Enable / 用例名 / 是否跑这行。** 确定性等 host 会读的运行上下文 → `active`。
- **`call_args.sources[].column` 必须 `active`。** 全空 ≠ `unwired`。`unwired` 仅当草稿 `call_args` 里没有对应实参。`call_args.sources[].column` 必须是本路 mapping key。

## 路径（一次做完就停）

1. **并行：** 无参 `uo-query`（只要 `dim_names`）+ 读 `repo_scan.yaml` 表头。不要通读 CSV，不要读对轴产物。
2. **打开草稿 `call.site` 那一个窗口**（同一文件内即可）。对本路每一列名搜赋值：它进了哪个局部变量、该变量进了调用的哪个关键字或第几个位置。位置实参的 `call_args.name` 用 API 签名名，`runtime_expr` 用局部变量。窗口里出现、草稿还没有的实参先追加再接线。给本路列补 `call_args.sources[]`，再写列 `control`。
3. **本路每列**写 `control.status` + `relation`。先看 `domains.<col>.profile.empty_rate`：全空且窗口里的局部是从另一列重算 → 空列 `shadowed`；kwargs 的 source 写有数的那一列。
4. **仅 active 查 identifier。** 标量 / layout / 位置实参查 **签名名**；没有 `TILING_FIELD` 也立刻把 `uo.id` 写成该 `call_args.name`。只作为张量维、且没有标量 source 的列才查列名。dtype 不要查 `*DType` / `Is*`。命中后 snippet 里同 struct 邻维可分给本路其它尺寸列。够闭合就停。
5. **立刻 Edit 一次**本路语义格。
6. **写后核对（这一步没做完不许 inspect）：** 打开刚写的 YAML，只扫 `call_args`。每个标量 / layout / 位置实参：若 `sources[]` 长度为 1，那一列的 `uo.id` **必须等于** 该 `name`，`confidence: confirmed`。`candidate` 不能代替 id。encoding / runtime_expr 已出现该 arg 名而 id 仍空 → 同样改。每个 `sources[].column` 必须 `active`。本路 `uo.id` 重复按入边数改。然后 `inspect yaml --rel <本路 bindN.yaml>` ok → summary。

## 分类

`control.status`：`active` | `fallback` | `shadowed` | `unwired` | `result` | `metadata`

`relation`：`direct` | `derived` | `tensor_shape` | `tensor_dtype` | `presence`（分不清就留空 + `unresolved`）。张量的 shape / dtype 列用 `tensor_shape` / `tensor_dtype` / `presence`。`derived` 只给标量非 identity 变换（`1/sqrt`、prefix-sum）。

- 出现在 `call_args.sources[]` → **必须 `active`**（`.pt` 加载、生成器按别的列合成，都不改成 metadata / unwired）
- 表全空（`empty_rate==1.0`）且 runner 从**另一列**重算 → 空列 `shadowed`，源列 `active`；kwargs 身份在有数列。列名像 API 参数但表全空，仍 shadowed。
- 调用没有对应实参、只进 golden / JSON → `unwired`
- 改写另一列（dropout / keep_prob 一类开关）→ `active` + `derived`，不是 `unwired`
- `Actual_` / 期望 / 实测写回 → `result`
- Enable / 用例名 / 是否跑行 → `metadata` + 空 relation + `unresolved`，禁止 `uo.id`
- 不进 kwargs、但驱动 host 运行上下文（确定性）→ `active`（`derived` / `presence`），要绑 UO

unwired / shadowed / fallback / result / metadata 停在分类，不要填 `uo.id`。

## 对名（第一命中）

`uo.id` 填短名 / `canonical`。禁止 `TDF::`、tiling 结构名、把 `candidate` 升格成 id。

**先看该列是否出现在标量 / layout kwargs 的 `sources[]`。是 → 走 1，不要走 2。**

1. **标量 / layout / 位置实参列：** `uo.id` = 该 `call_args.name` → `confirmed`。多候选取 `sources[]` 长度为 1 的那个；只剩聚合 → 空 + `unresolved`。不要改用同维 tiling 字段候选。
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
