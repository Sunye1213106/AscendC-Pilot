# 绑定列

只 Edit 引擎已写出的本路 `parts/bindN.yaml` 语义格。机器合同：`schemas/tg/bind-part-v1.yaml`（`schema: tg-bind-part/v1`）。不要新建空白 YAML，不要改列名、`schema`、`run_id`、`artifact_identity`。不要 Write 合并后的 `bind.yaml`、`harness.yaml` 或其它 `bindN.yaml`。

草稿里 `call` 与 `call_args[].name` 已按 `repo_scan.canonical_call` 填好。本路只给 `chunk.columns` 写格子，并只给这些列补 `call_args.sources[]`。合并后的 union 才覆盖完整 API。`call.kind` ∈ {`pta`, `aclnn`, `mixed`}。不要写 `attr` 或 `pta_direct`。

Harness 回答「这个 CSV 列控制 API 的什么」；UO 回答「这个控制在算子语义图里是谁」。前者可以 `confirmed`，后者仍可为空。

## 判断（遇冲突只认这一节）

- **status 只看调用点，不看 CodeMap。** 禁止用 `dim_names` / AttrIndex 有无改 `control.status`。禁止造伪 kwargs。某 mode 省略了 kwargs → findings 记未接线，列仍按草稿 `call_args` 分类。
- **禁止追加、删除、改名 `call_args`。** 窗口里多出来的实参记 findings，不要改草稿 API 面。
- **尺寸列不是标量实参。** 禁止把纯 `tensor_shape` 列写进标量 / layout / 派生 kwargs（`scale` / `keep_prob` 一类）的 `sources[]`。尺寸列 identifier = 列名，只取 `kind: TILING_FIELD` 的 `.name`（禁止 `TDF::`、操作数、`*TemplateNum`）。
- **construct ≠ identity。** 1:1 `sources[]` 只证明 CSV→API construct。`confidence` 只表示 construct confidence。`uo.id` 只填写身份解析得到的 canonical / 短名；未闭合时 `uo.id: ''`，相似实体写 `candidate`。禁止把 `call_args.name` / `runtime_expr` 抄进 `uo.id`。空 id 不把 construct 降成 `unresolved`。
- **两列不许共非空 `uo.id`。** 撞了说明至少一条身份没闭合：改成空 id + `candidate`，不要改成另一个 arg 名。
- **开关维不是 dtype / shape / layout 的身份。** `Is*`、`*DType`、`*TemplateNum` 只有「列本身就是该开关」才能当 `uo.id`。投影写 `domains.projection`。
- **metadata 只有 Enable / 用例名 / 是否跑这行。** 确定性等 host 会读的运行上下文 → `active`。
- **`call_args.sources[].column` 必须 `active`，且必须是本路 mapping key。** shadowed 列禁止进入 `sources[]`。全空 ≠ `unwired`。`unwired` 仅当草稿 `call_args` 里没有对应实参。
- **仅 active 列做 semantic identity resolution**（按 `code-access`）。不要用 `dim_names`（`*TemplateNum` / `*DType` / `Is*`）当尺寸或 dtype 的查询词或 `uo.id`。

## 路径

1. **读 `repo_scan.yaml` 表头。** 不要通读 CSV，不要读对轴产物。需要 `dim_names` 或标识符时按 `code-access` 查图。
2. **打开草稿 `call.site` 那一个窗口**（同一文件内即可）。对本路每一列名搜赋值：它进了哪个局部变量、该变量进了调用的哪个**已有**关键字或第几个位置。位置实参的 `call_args.name` 用草稿已有签名名，`runtime_expr` 用局部变量。给本路列补 `call_args.sources[]`，再写列 `control`。
3. **本路每列**写 `control.status` + `relation`。先看 `domains.<col>.profile.empty_rate`：全空且窗口里的局部是从另一列重算 → 空列 `shadowed`；kwargs 的 source 写有数的那一列，不要把空列写进 `sources[]`。
4. **仅 active 解析身份。** 查列名或相关 ident，把命中的 canonical / 短名写入 `uo.id`。不要把 `call_args.name` 填进 `uo.id`。只作为张量维的列查列名，取 `TILING_FIELD.name`。dtype 不要查 `*DType` / `Is*`。同 struct 邻维只当阅读上下文，不写进其它列的 `uo.id`。一个张量实参对应多列时，全部进该 arg 的 `sources[]`，不要挑一列当「这个张量的 uo.id」。够闭合就停。
5. **Edit 本路语义格**，然后 `inspect yaml --rel <本路 bindN.yaml>`。失败就改到 ok。不要读对轴产物。

## 分类

`control.status`：`active` | `fallback` | `shadowed` | `unwired` | `result` | `metadata`

`relation`：`direct` | `derived` | `tensor_shape` | `tensor_dtype` | `presence`（分不清就留空 + `unresolved`）。张量的 shape / dtype 列用 `tensor_shape` / `tensor_dtype` / `presence`。`derived` 只给标量非 identity 变换（`1/sqrt`、prefix-sum）。输出 dtype 若只做 `tensor.to(...)` → `tensor_dtype`，不是 `direct`。

- 出现在 `call_args.sources[]` → **必须 `active`**（`.pt` 加载、生成器按别的列合成，都不改成 metadata / unwired）
- 表全空（`empty_rate==1.0`）且 runner 从**另一列**重算 → 空列 `shadowed`，源列 `active`；kwargs 的 source 写有数的那一列。列名像 API 参数但表全空，仍 shadowed。
- 调用没有对应实参、只进 golden / JSON → `unwired`
- 改写另一列（dropout / keep_prob / 截短 / 过滤 / 重映射）→ `active` + `derived`，绑被改写对象，不是 `unwired`，不借邻居
- `Actual_` / 期望 / 实测写回 → `result`
- Enable / 用例名 / 是否跑行 → `metadata` + 空 relation + `unresolved`，禁止 `uo.id`
- 不进 kwargs、但驱动 host 运行上下文（确定性）→ `active`（`derived` / `presence`）。`confidence` 按 harness 证据；对不上 UO 只填 `uo.candidate`，不要把 construct 降成 unresolved

unwired / shadowed / fallback / result / metadata 停在分类，不要填 `uo.id`。

## 对名（第一命中）

`uo.id` 填短名 / `canonical`。禁止 `TDF::`、tiling 结构名、把 `candidate` 升格成 id、把 `call_args.name` 当 id。

1. **标量 / layout / 位置实参列：** 1:1 `sources[]` 只证明 construct → 有 harness 证据就 `confirmed`。身份另做 semantic identity resolution；未命中 → 空 id，有相似符号则 `candidate`。
2. **tensor_shape：** `uo.id` = 列名查到的 `TILING_FIELD.name`。对不上 → 空 id + `candidate`，construct 仍按 harness 证据 `confirmed`。
3. **tensor_dtype：** 不要绑 `*DType` / `Is*`。对不上 → 空 id + `candidate`，construct 仍按 harness 证据 `confirmed`。
4. **列本身就是开关**（无参索引里的 `dim_names` 且列控制的就是它）→ 抄那维。
5. 对不上 → 空 id + `candidate`，**construct 仍按 harness 证据 confirmed**。不借邻居。

只碰到相似符号 → `uo.candidate`，construct 仍按 harness 证据；不要用开关维给 dtype/shape 凑身份。

`operator` / `compare` 只对 active。`compare=match` 仅当 `operator` 非空。不要改引擎写入的 `domains.profile`。

## 完成

- 每个 mapping key 都有 `control.status` + `relation` + `confidence`
- `uo.id` 来自身份解析（允许空）；本路非空 id 互不重复
- `confirmed` 有 `evidence`
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
    evidence: runner.py:10 BatchCol -> x.shape[0]
    uo: {id: batch, candidate: ''}   # TILING_FIELD.name
  HeadCol:
    control: {status: active}
    relation: direct
    confidence: confirmed
    evidence: runner.py:40 HeadCol -> nh -> num_heads
    uo: {id: '', candidate: ''}      # construct 已闭合；禁止抄 call_args.name
  InDtype:
    control: {status: active}
    relation: tensor_dtype
    confidence: confirmed
    evidence: runner.py:123 InDtype -> input.dtype -> x.to(dtype)
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
- 追加或改写 `call_args`；造伪 kwargs
- 尺寸列绑操作数名 / `TILING_KEY` / 派生 kwargs（scale 一类）
- 把 `call_args.name` / `runtime_expr` 抄进 `uo.id`
- 两列共一个非空 `uo.id`
- 因空 `uo.id` 把 construct 改成 `unresolved`
- `confirmed` 空 `evidence`；shadowed 列进 `sources[]`；sources 列因表全空标成 `unwired`
- 确定性列标 metadata
- inspect 没 ok 就停；读对轴产物
