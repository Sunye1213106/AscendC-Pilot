# 绑定列

只 Edit 引擎已写出的 `parts/bind.yaml` 语义格。不要新建空白 YAML，不要改列名、`schema`、`run_id`、`artifact_identity`。

本路回答：脚本怎么调算子、每个入参来自哪一列、剩下的列是什么。列值域以 `tables[].profile` 为准。身份字段由框架写入，不要从 stub 抄。

短名只从**本次**调用点与 tiling 头文件抄。不要按别的算子记绑定名单；换仓后那些短名会全错。

`inspect yaml` 只说明草稿能解析、能合并。空 `uo_id` 等于没绑。

## 一条硬规则

**role 只看 `torch_npu.*` / `aclnn*` 调用点，不看 CodeMap。**

出现在实参列表里（位置或关键字）→ 追到的 CSV 列是 `api_arg`。  
没出现 → 才考虑 `script_meta` / `result_sink` / `feature`。

禁止用 AttrIndex / TILING_KEY / `dim_names` 有无来改 role。图上没有某名字，仍然可能是 `api_arg`。

**不要用 `attr`。** 传进调用的全部是 `api_arg`。

`dim_names` 是模板维宇宙，不是 role 宇宙。输入 dtype 进了传入张量 → `api_arg`。

## 输入 / 输出 / 停

读：`repo_scan.yaml` 表头与 `tables[].profile`。有仓则打开入口脚本的**最富调用**（精度入口 / 非 profiler）。只开调用窗口和读表 / 造 case 的映射段，不要通读整个 runner。不要发明列名。不要通读 CSV。不要读对轴产物。

有仓且没有任何 `api_arg` → 本切片失败。

完成：`call` + `call_args` + 每列有 role；凡非空 `source_column` 都是 `api_arg` 且 `uo_id` 是调用关键字或头文件短名。PARTIAL 只进 findings。交卷即停。

## 决策树（按顺序，不许跳）

1. **打开最富调用，抄实参。** 先写 `call_args`。写完之前不给任何列写 role。
2. **每个实参追来源：**
   - 字面量 / `None` / 现场公式、没有 CSV 列 → `source_column: null`，进 findings / `test_harness_gap`。
   - 变量能追到读表 / 造 case → `source_column` 填**读表函数读到的表头**，不是 runner 局部变量名。局部变量若是对已读列做 cumsum / 切片 / 转型，来源仍是被读的那一列。局部变量名碰巧等于另一列表头，也不要改绑。
   - **尺寸列**（造张量用的 dtype / layout / rank / 各维长度）→ `api_arg`。runner 读 `.pt` 也不改。
   - 最富调用里已经出现的 kwargs：同名表列是 `api_arg` 且必须有短名。表上全空、或这个张量从 `.pt` 填，都不改 role。
   - **改写列**（本身不在实参里，只截短 / 过滤 / 重映射另一列）→ `feature`。被改写的那一列才是 `api_arg`。不要因为「间接改了 kwargs 的值」把改写列升成 `api_arg`。
3. **给每一列表头写 role（只许用第 2 步）：**
   - 出现在任一 `source_column` → **`api_arg`，必须有短名 `uo_id`**。
   - 结果落盘 / 期望输出 / 实测对照 → `result_sink`，禁止 `uo_id`。
   - Enable / 用例名 / 是否跑这行 → `script_meta`，禁止 `uo_id`。只有这三类。
   - 只改 Python / torch 运行上下文、不进调用（确定性、设备、打印）→ `feature`；头文件有对应开关字段就填 `uo_id`。不要标成 `script_meta`。
   - 只改写别的入参、本身不是 kwargs → `feature`（含改写列）。
   - 读了 CSV 但调用里对应位置是硬编码 → `script_meta` + gap。
4. **某次 mode 省略了某个 kwargs** → findings 记未接线。**列仍是 `api_arg`**，以最富调用为准。
5. **role 冻结后对名。** 按步骤里的对名规则抄进 `uo_id`。对不上 → findings 写 PARTIAL，格子留空。禁止把邻居短名借过来。

## 步骤

1. `call.kind` ∈ {`pta`, `aclnn`, `mixed`}。`torch_npu` 且无 aclnn → `pta`。禁止 `pta_direct`。记下 `call.api` + `call.site`。
   `call_args.name` 用 API 形参名：kwargs 用关键字；位置参数不要抄 runner 局部变量，查该位置在 API / 原型里的形参名（一次标识符查询即可）。该列 `uo_id` 与这个形参名对齐（头文件有同名字段则用头文件大小写）。位置实参对应的 `api_arg` 禁止空 `uo_id`。
2. 按决策树写 `call_args` 再写 `mapping`。
3. **对名**（role 已冻结）。先读一次 `tiling_data` 头文件，得到本次短名全集。然后对每一列只走第一条命中的规则：
   1. 该列是某个 kwargs 的 `source_column` → 必须有短名：头文件有同名字段就抄头文件大小写；**没有同名字段就抄调用点形参名**。形参名已经在调用窗口里，禁止因为头文件没有字段就把 `uo_id` 留空。
   2. 该列是尺寸 / dtype / layout，或只出现在某个现场公式里 → 抄头文件里表示**同一量**的短名。公式算出来的那个 kwargs 不是本列的身份。无参索引的 `dim_names` 是模板开关维，不是 dtype / 形状列的身份；对不上就留空。
   3. 该列是 `feature`，且头文件有一个字段，表示的量就是这一列（开关 / 标志）→ 抄该字段。同一开关的两侧（有/无、内外）仍是这一列，抄该字段。词形相近但量不同，才留空。
   4. 对不上 → 格子留空。PARTIAL 只进 findings。改写列尤其不要因为头文件里有一个长得像的字段就抄过来。
   无参 `uo-query` 一次（只要 `dim_names` / `hint`）。标识符查询只补头文件和调用名里都没有的洞（≤8）+ `Dim=` ≤4 + around ≤1。不要先打满 8 次再回头留空。头文件已经出现的字段禁止再查。位置实参若头文件没有同名字段，抄该形参在无参索引 / 卡片上的短名，不要改绑到邻近维。变长序列列对调用里的 seqlens kwargs，不对模板开关维。
   禁止两个不同语义的列共用一个 `uo_id`（dtype 列 vs 形状/layout 列）。`uo_id` 填卡片 `canonical` 或短 `name`，禁止 `TDF::` id 和 `tiling_data_names` 结构名。尺寸列抄维/字段短名，不抄调用里的张量操作数名。
   `Dim=` 只写在「列本身就是该开关」上。只在某种模板/layout 下才出现的列，对名仍对**该列自己的量**，不对那个开关维。`--file --line` 只从上一张卡复制。
4. `domains`：`profile` 原样留下。只改 `operator` / `compare`，且只填 `api_arg`。**`compare=match` 仅当 `operator` 非空且与 profile 对过。** `feature` 的 `operator` 留空。无参索引的模板维不进 dtype / 形状列的 `uo_id`，也不进它的 `operator`。
5. 非字面量列写一句 `encoding`。不要把列标成 PR 焦点。
6. `pilot_cli inspect yaml --rel <草稿相对 .ascendc-pilot 的路径>` 确认能解析。返回 ok 后立刻 summary 停：不要再数列、不要再对勾选、不要再通读草稿。

## 看到这样

| 现象 | 判断 |
| --- | --- |
| kwargs 有可选输入 | 对应列 `api_arg`，哪怕图上是 INPUT 不是 AttrIndex |
| 张量进调用，runner 读 `.pt` | 尺寸列仍是 `api_arg`。同名 kwargs 列也仍是 `api_arg` |
| 列只改写另一列的取值 | `feature`；被改写列才是 `api_arg` |
| 头文件有开关字段，列不进调用 | `feature`，`uo_id` 抄该短名 |
| 调用里硬编码字面量 | gap，不是列 |
| 某 mode 没传该 kwargs | findings；列仍 `api_arg` |
| 想写 `attr` / `pta_direct` | `api_arg` / `pta` |
| 想用 `mapping.columns[].name` | mapping 的 key 就是列名 |
| 查无 AttrIndex | 继续 `api_arg`；`uo_id` 用调用名 / 头文件短名 |
| 预算用完 / 图上没卡 | 对得上的短名仍填；对不上的格子留空，PARTIAL 只进 findings |
| 列拿去算另一个 kwargs | 看 `source_column`：是才绑那个 kwargs |
| 列只在某种模板/layout 下出现 | `operator` 绑该列短名，不是开关维的 `Dim=` |
| `operator` 还是空的 | `compare` 留空 |
| 想自写脚本验 YAML | `pilot_cli inspect yaml --rel …` |
| 列是 kwargs 的 `source_column`，头文件没有同名字段 | 抄该形参名；`api_arg` 禁止空 `uo_id` |
| 同一实参有两种表编码 | 两列都有表值 → 都抄该实参短名。一列全空、只当备用读入 → `feature`，不借主列短名 |
| 列只改确定性 / 设备 / 打印，不是 Enable | `feature`，不是 `script_meta` |
| 想把无参 `dim_names` 写成 dtype / 形状列的 `uo_id` | 不要；没有同量字段就留空 |
| 局部变量名碰巧等于另一列表头 | 仍以读表函数的 `cell_value` 列为准 |
| 位置实参写成了 runner 缩写局部名 | `call_args.name` 与 `uo_id` 改成 API 形参名；可发 1 次标识符查询 |
| 调用里有该 kwargs，表列全空 | 仍是 `api_arg`，抄形参名 |
| 头文件开关与列是同一开关的两侧 | 抄该字段 |
| 想整文件重写以免弄坏 profile | 只 Edit 语义格；`profile` / `schema` / `columns` 不动 |
| inspect 已返回 ok | 立刻停，下一句就是 summary |

## 完成勾选

- [ ] `call_args` 覆盖最富调用的每一个实参
- [ ] 每个非空 `source_column` 是 `api_arg`，`uo_id` 是短名不是 `''`
- [ ] 改写列是 `feature`；尺寸列是 `api_arg`
- [ ] `call.kind` ∈ {pta, aclnn, mixed}；没有 `attr` / `pta_direct` / `TDF::`
- [ ] `script_meta` / `result_sink` 无 `uo_id`
- [ ] mapping 是 `{列名: {role, uo_id, ...}}`
- [ ] `api_arg` 的 `operator` 非空才标 `compare=match`
- [ ] 对不上的 `feature` 不借用邻居 `uo_id`；`feature` 的 `operator` 留空
- [ ] 头文件只读一次；只 Edit 语义格；没有整文件重写；没有自写检查脚本
- [ ] `pilot_cli inspect yaml --rel <草稿相对 .ascendc-pilot 的路径>` 返回 ok 后立刻停

## 循环

1. 最富调用窗口 + 读表 / 造 case 的映射段。不要通读 runner。
2. `call_args` → role（尺寸 vs 改写）。
3. tiling 头文件读一次，按对名规则抄完。
4. 无参 `uo-query` 一次（只要 `dim_names` / `hint`）。头文件和调用关键字里已经有的短名禁止再查。只对剩下的洞才标识符查询（位置实参没短名就是这种洞，通常 0～2 次）。
5. 只 Edit 语义格：`call` / `call_args` / `role` / `uo_id` / `encoding` / `evidence` / `operator` / `compare` / `findings`。`profile` 一行都不要重写。
6. `inspect yaml` 返回 ok → 立刻 summary 停。

交卷路径：三处窗口 + 头文件一次 + 无参查询一次 + Edit 语义格 + inspect。整文件重写和 inspect 之后再对数列，都会超时。

## 输出形状

```yaml
call:
  kind: pta                 # pta | aclnn | mixed
  api: torch_npu.<fn>       # 或 aclnn*
  site: path.py:LINE
call_args:
  - {name: <kwarg>, source_column: <header>}
  - {name: <computed>, source_column: null}  # 现场公式，无 CSV 列
mapping:
  ColName:
    role: api_arg           # api_arg | feature | script_meta | result_sink
    uo_id: ident            # 对得上才填；feature 对不上就空
    evidence: path.py:LINE
    encoding: 字面量或一句
columns:
  - {name: ColName}
domains:
  ColName:
    profile: ...            # 抄 scan
    operator: ident         # 只填 api_arg；空则 compare 也空
    compare: match          # 仅 operator 非空
findings: []                # PARTIAL 写这里；对不上的格子留空，不借邻居
```

## 反模式

- 用 AttrIndex / `dim_names` 决定 role
- 因为 runner 读 `.pt` 就把尺寸列标成 `script_meta`
- 因为间接改了某 kwargs 的值就把改写列标成 `api_arg`
- `call.kind: pta_direct`；`role: attr`
- 通读 CSV / 通读 runner；读对轴 `harness.yaml`
- 先打满标识符查询，再把剩余列 `uo_id: ''`
- 为每列单独 `uo-query`；Write 整份 YAML 重抄 `profile`
- `operator: ''` 配 `compare: match`；把模板开关 `Dim=` 写成「只在该开关下才出现」的列的 `operator`
- 把上一算子的列名 / 短名当本题答案
- kwargs 来源列因为头文件没有字段就留空 `uo_id`
- 把运行期开关标成 `script_meta`
- 把无参索引的模板维当成 dtype 列的短名
- 按 runner 局部变量名对表头；位置实参把局部缩写写进 `call_args.name` / `uo_id`
