# 绑定列

只改语义。引擎已写出 `parts/bind.yaml`（身份、`columns`、`profile`）。**不要 Edit / Write `bind.yaml`。**

落盘：一次 Write `parts/bind.fill.yaml`（仅 LLM 格）。然后 `pilot_cli inspect yaml --rel <bind.yaml 相对 .ascendc-pilot 的路径>`。inspect 会把 fill 合并进草稿并做结构检查。`counts` 就是普查。

本路回答：脚本怎么调算子、每个入参来自哪一列、剩下的列是什么。列值域以 `tables[].profile` 为准。身份字段由框架写入，不要从 stub 抄。

短名只从**本次**调用名、无参 `uo-query` 与字段名单抄。不要按别的算子记绑定名单。

## 路径

1. **并行**：无参 `pilot_cli uo-query --project <算子绝对路径>`（只要 `dim_names` / `hint`）+ 读 `repo_scan.yaml` 表头。这是查 UO 的唯一入口，不能用索引文件、头文件或源码阅读代替。不要 `Dim=` 把 `dim_names` 查一遍。不要通读 `bind.yaml`。
2. 字段名单：直接 Read session `refs/bind/name-index.md`（相对 `session_dir`）。不要 Glob。没有这份文件才读一次 tiling 头文件。开关维以无参查询为准。
3. 最富调用**一个窗口**（精度入口 / 非 profiler）+ 读表函数映射段。表头以 `Actual_` / `Expected_` 开头的列就是 `result_sink`，不要再 Grep 结果列。不要通读 runner / CSV。不要读对轴产物。不要 `inspect.signature` / 不要装算子 Python 包。
4. 心里两段（接线 → 对名），**立刻 Write 一次** `bind.fill.yaml`。不要第二轮 Grep。
5. inspect 返回 ok → 立刻 summary。inspect 没 ok 就还没做完，不要停。

有仓且没有任何 `api_arg` → 本切片失败。

## 一条硬规则

**role 只看 `torch_npu.*` / `aclnn*` 调用点，不看 CodeMap。**

出现在实参列表里（位置或关键字）→ 追到的 CSV 列是 `api_arg`。  
没出现 → 才考虑 `script_meta` / `result_sink` / `feature`。

禁止用 AttrIndex / TILING_KEY / `dim_names` 有无来改 role。图上没有某名字，仍然可能是 `api_arg`。

**不要用 `attr`。** 传进调用的全部是 `api_arg`。`dim_names` 是模板维宇宙，不是 role 宇宙。输入 dtype 进了传入张量 → `api_arg`。

## 接线（先想完再写）

`call.kind` ∈ {`pta`, `aclnn`, `mixed`}。`torch_npu` 且无 aclnn → `pta`。禁止 `pta_direct`。记下 `call.api` + `call.site`。

`call_args.name` 用 API 形参名：kwargs 用关键字；位置参数从调用窗口或同文件包装 / 属性表抄。

每个实参：
- 字面量 / `None` / 现场公式、没有 CSV 列 → `source_column: null`，进 findings / `test_harness_gap`。
- 能追到读表 → `source_column` 填**读表函数读到的表头**，不是 runner 局部变量名。cumsum / 切片 / 转型仍是被读的那一列。
- **尺寸列**（dtype / layout / rank / 各维）→ `api_arg`。runner 读 `.pt` 也不改。
- 最富调用里已有的 kwargs：同名表列是 `api_arg`（表全空或值从 `.pt` 来也一样）。
- **改写列**（不在实参里，只截短 / 过滤 / 重映射另一列）→ `feature`。被改写列才是 `api_arg`。

每个 mapping key 的 role：
- 出现在任一 `source_column` → `api_arg`，必须有短名。
- 结果落盘 / 期望 / 实测 → `result_sink`，禁止 `uo_id`。
- Enable / 用例名 / 是否跑这行 → `script_meta`，禁止 `uo_id`。
- 只改确定性 / 设备 / 打印 → `feature`。
- 某 mode 省略了 kwargs → findings；列仍 `api_arg`。

## 对名（查询 + 字段名单）

无参查询给出开关维。字段名来自 `name-index.md` 或一次头文件。然后对每一列只走第一条命中：

1. kwargs 的 `source_column` → 字段名有同名抄索引大小写；**否则 `uo_id` 填该实参的 `call_args.name`。禁止空，不要为此写 PARTIAL。**
2. 尺寸 / dtype / layout / 公式输入 → 字段名里**同一量**。公式算出来的 kwargs 不是本列。开关维不是 dtype / 形状列的身份，也不进它的 `operator`。
3. `feature` 改写输入生成（mask / flag）→ 抄字段名单里表示该对象的字段（含 inner/outer 两侧）。不要抄 keep/prob，也不要空着。
4. `feature` 且字段名就是这一列的开关（含两侧）→ 抄该字段。
5. 对不上 → 空，PARTIAL 进 findings。不借邻居。

变长序列列对调用里的 seqlens kwargs，不对开关维。`uo_id` 填短名 / `canonical`，禁止 `TDF::` 和结构名。尺寸列不抄张量操作数名。两列不许共用一个 `uo_id`。

`Dim=` 只写在「列本身就是该开关」上。开关维已在无参查询的 `dim_names` 里，不必再查。

`domains.profile` 不要写进 fill（合并器保留引擎 profile）。只填 `api_arg` 的 `operator` / `compare`。**`compare=match` 仅当 `operator` 非空。** `feature` 的 `operator` 留空。

## 看到这样

| 现象 | 判断 |
| --- | --- |
| kwargs 可选 / 图上无 AttrIndex | 仍 `api_arg`；名单无同名就抄 `call_args.name` |
| runner 读 `.pt` | 尺寸列与同名 kwargs 列仍 `api_arg` |
| 列只改写另一列 | `feature`，抄被改写对象的字段（inner/outer） |
| 头文件开关、列不进调用 | `feature`，抄该短名 |
| 调用硬编码 | gap，不是列 |
| 想 Edit `bind.yaml` | Write `bind.fill.yaml` |
| 想把开关维写成 dtype 列 | 留空 |
| 局部变量名碰巧等于另一列表头 | 以读表列为准 |
| inspect 已 ok | 立刻停 |

## 完成

- 每个 mapping key 有 role；`call_args` 覆盖最富调用每个实参
- 非空 `source_column` 是 `api_arg` 且 `uo_id` 非空（名单同名或 `call_args.name`）
- 只写了一次 `bind.fill.yaml`；没有 Edit `bind.yaml`；做过一次无参 `uo-query`；没有 Glob 找索引
- inspect ok 后立刻停

## 输出形状

一次 Write `parts/bind.fill.yaml`：

```yaml
call:
  kind: pta
  api: torch_npu.<fn>
  site: path.py:LINE
call_args:
  - {name: <kwarg>, source_column: <header>}
  - {name: <computed>, source_column: null}
mapping:
  ColName:
    role: api_arg           # api_arg | feature | script_meta | result_sink
    uo_id: ident            # 名单同名或 call_args.name；kwargs 禁止空
    evidence: path.py:LINE
    encoding: 一句            # ≤16 字
domains:
  ColName:
    operator: ident         # 只填 api_arg
    compare: match          # 仅 operator 非空
findings: []
```

## 反模式

- Edit / 整文件重写 `bind.yaml`；为拼 old_string 再读草稿
- 多刀 Edit；TodoWrite；`inspect.signature`
- 用 AttrIndex / `dim_names` 决定 role；`pta_direct` / `attr`
- 通读 CSV / runner；读 `harness.yaml`
- inspect 没返回 ok 就结束（只读了源码也算没做完）
- Glob 找 `name-index.md`；为 `Actual_` 结果列再 Grep；追完 source_column 仍第二轮搜
- kwargs 已有 `source_column` 仍把 `uo_id` 留空并写 PARTIAL
- 为 `dim_names` 里已有的开关维再发 `Dim=`
- `operator: ''` 配 `compare=match`；把 `Dim=` 写到「只在该开关下才出现」的列
- 把上一算子短名当答案；改写列借邻居 `uo_id` 或抄 keep/prob
