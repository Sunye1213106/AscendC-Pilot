# 绑定列

只 Edit 引擎已写出的 `parts/bind.yaml` 语义格。不要新建空白 YAML，不要改列名、`schema`、`run_id`、`artifact_identity`。

本路回答：脚本怎么调算子、每个入参来自哪一列、剩下的列是什么。列值域以 `tables[].profile` 为准。

身份字段由框架写入草稿，不要从 stub 抄进 YAML。

## 一条硬规则

**role 只看 `torch_npu.*` / `aclnn*` 调用点，不看 CodeMap。**

出现在实参列表里（位置参数或关键字）→ 追到的 CSV 列是 `api_arg`。  
没出现 → 才考虑 `script_meta` / `result_sink` / `feature`。

禁止用 AttrIndex / TILING_KEY / `dim_names` 有无来改 role。图上没有某名字，仍然可能是 `api_arg`。

**不要用 `attr`。** 传进调用的全部是 `api_arg`。

`dim_names` 是模板维宇宙，不是 role 宇宙。输入 dtype 进了传入张量 → `api_arg`。

## 输入 / 输出 / 停

读：`repo_scan.yaml` 表头与 `tables[].profile`。有仓则打开入口脚本的**最富调用**（精度入口 / 非 profiler；没有再退回默认 mode）。不要发明 CSV 列名。不要通读 CSV。不要读对轴产物。

有仓且没有任何 `api_arg` → 本切片失败。

完成：`call` + **`call_args` 清单** + 每列表头都有 role；凡 `call_args.source_column` 非空的列都是 `api_arg` 且有 `uo_id`。交卷即停。

## 决策树（按顺序，不许跳）

1. **打开最富调用，抄实参。** 先写 `call_args`。这一步做完之前禁止给任何列写 role。
2. **每个实参追来源：**
   - 字面量 / `None` / 现场公式、没有 CSV 列 → `source_column: null`，进 findings / `test_harness_gap`。
   - 变量能追到 `get_case` / `CaseConfig` → `source_column` 填表头名。
   - **张量实参** → 造这个张量用到的 dtype / layout / B / N / S / D 等也是 `api_arg`。即使 runner 从 `.pt` 加载，这些列仍是 `api_arg`。
3. **给每一列表头写 role（只许用第 2 步的清单）：**
   - 出现在任一 `source_column` → **`api_arg`，必须有 `uo_id`**。
   - 名字以 `Actual_` 开头 → `result_sink`，禁止 `uo_id`。
   - Enable / 用例名 / 是否跑这行 → `script_meta`，禁止 `uo_id`。
   - 只改 Python 上下文、不进调用 → `feature`，有标识符写 `uo_id`。
   - 只改写别的入参、本身不是 kwargs → `feature`。
   - 读了 CSV 但调用里对应位置是硬编码 → `script_meta` + gap。
4. **某次 mode 省略了某个 kwargs** → findings 记未接线。**列仍是 `api_arg`**，以最富调用为准。
5. **查图只为 `uo_id`，在 role 全部写完之后。** 查不到 → findings 写 PARTIAL；禁止把 role 改成 `script_meta`。

## 步骤

1. `call.kind` ∈ {`pta`, `aclnn`, `mixed`}。`torch_npu` 且无 aclnn → `pta`。禁止 `pta_direct`。记下 `call.api` + `call.site`。
2. 按决策树写 `call_args` 再写 `mapping`。
3. 查图（role 已冻结）：
   - 先无参 `uo-query`（只要 `dim_names` / `hint`）。
   - 具名实参转驼峰标识符。proto 输入名用脚本关键字。
   - **预算：** 无参 1 + 标识符 ≤8 + `Dim=` ≤4 + around ≤1。snippet 已出现的短名直接抄。
   - 同一列既是张量形状又是具名实参 → 具名实参赢。单字母字段只绑「列名就是那个维」的列。
   - 禁止两个不同语义的列共用一个 `uo_id`（`*Dtype` vs `*ShapeType`）。
   - `uo_id` 填卡片 `canonical` 或短 `name`，禁止 `TDF::` id。`dim_names` / `Dim=` 维名逐字抄。
   - 已为某列查过的卡，禁止换成邻居短名。`Dim=` 只进 `domains.operator`，不是 mapping（列本身就是该开关时除外）。
   - 不要用 `tiling_data_names` 结构名当 `uo_id`。形状列禁止绑 `query` / `key` / `value` / `dy`。
   - `--file --line` 只从上一张卡复制。
4. `domains` 只对 `api_arg`。`profile` 抄 scan。`compare` ∈ {`match`, `tighter_profile`, `tighter_operator`, `mismatch`}。
5. 非字面量列写一句 `encoding`。不要把列标成 PR 焦点。

## 看到这样

| 现象 | 判断 |
| --- | --- |
| kwargs 有可选输入 | 对应列 `api_arg`，哪怕图上是 INPUT 不是 AttrIndex |
| 张量进调用，runner 读 `.pt` | 造它们的维 / dtype / layout 仍是 `api_arg` |
| 调用里硬编码字面量 | gap，不是列 |
| 某 mode 没传该 kwargs | findings；列仍 `api_arg` |
| 想写 `attr` / `pta_direct` | `api_arg` / `pta` |
| 想用 `mapping.columns[].name` | 禁止；mapping 的 key 就是列名 |
| 查无 AttrIndex | 继续 `api_arg`；换 proto 名 / tiling 字段 |
| `Dim=` 有覆盖 | 只进 domains；dtype/shape 列绑字段 |
| 想绑 tiling 结构名 | 改查结构里的字段 |

## 完成勾选

- [ ] `call_args` 覆盖最富调用的每一个实参
- [ ] 每个非空 `source_column` 是 `api_arg` 且有 `uo_id`
- [ ] `call.kind` ∈ {pta, aclnn, mixed}
- [ ] `script_meta` / `result_sink` 无 `uo_id`
- [ ] mapping 是 `{列名: {role, uo_id, ...}}`
- [ ] 没有 `attr`、没有 `pta_direct`；`uo_id` 是短名不是 `TDF::` id

## 循环

1. 打开 scan 入口 + 最富调用 + `get_case`。
2. 写完 `call_args` → 再写 role。
3. 无参索引；缺哪个 `uo_id` 查哪个标识符；停。
4. Edit 已有 YAML 的语义格。不要读对轴文件。

## 输出形状

```yaml
call:
  kind: pta                 # pta | aclnn | mixed
  api: torch_npu.<fn>
  site: path.py:LINE
call_args:
  - {name: keep_prob, source_column: Drop_Out_Possibility}
  - {name: padding_mask, source_column: null}
mapping:
  ColName:
    role: api_arg           # api_arg | feature | script_meta | result_sink
    uo_id: ident
    evidence: path.py:LINE
    encoding: 字面量或一句
columns:
  - {name: ColName}
domains:
  ColName:
    profile: ...
    operator: ...
    compare: match
findings: []
```

## 反模式

- 用 AttrIndex / `dim_names` 决定 role
- 因为 runner 读 `.pt` 就把维列标成 `script_meta`
- `call.kind: pta_direct`；`role: attr`
- 通读 CSV；读对轴 `harness.yaml`

## 指针

- `references/test-script-repo.md`
- `references/column-binding-edge-cases.md`

## Materialized refs (session-local)

- `refs/bind/test-script-repo.md`
- `refs/bind/column-binding-edge-cases.md`
