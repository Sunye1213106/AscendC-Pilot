# 覆盖模型形式规范（查阅用）

`tg-plan-fill/v1` 的填空语法。方法与步骤在 Plan Owner 任务提示里。引擎把填空展开成 `tg-plan/v3`（谓词、coverage 脚手架、classifier/controls、untestable）。

## 填空

`cuts` 取值：`case.{column}` / `replay.{field}` / `probe.{name}`，或不带前缀的列名（默认 `case.`）。

```yaml
# 单列
- {id: p-on, eq: 1}
# 两列合取
- {id: p-mha, eq: {N1: 4, N2: 4}}
# 奇偶
- {id: p-even, mod: 0}
# 其它比较
- {id: p-big, op: ge, value: 129}
# Guard 补集
- {id: G-not-tnd, field: Input_Layout, op: ne, value: TND, hit: BNSD}
```

字面量类型对齐 init 的 `inferred_type`：整数列写 int，不加引号。

精度/md5 一类写 `oracle: md5` 或 `oracle: precision`，不做 Target。

## 各段职责

| 段 | 谁写 | 放什么 |
| --- | --- | --- |
| `requirement` | LLM | 路径条件与源码符号 |
| `target` | LLM | 观测字段 + expected / op / in |
| `dimensions[].cuts` + `arms` | LLM | 实现分岔，每维 ≥2 个可达 arm |
| `guards` | LLM | 杀整门；`hit` 翻回可达 |
| `l1` | LLM | 字段不相交且四格都能 HIT 的维对 |
| `exclusions` | LLM | 全交叉里不可能同时成立的格子 |
| `environment` | LLM | 正整数 `aicNum` / `coreNum` |
| `oracle` | LLM | `md5` / `precision` / `[]` |
| `classifier` / `controls` / 谓词 | 引擎 | 从 cuts + arms 生成 |
| `coverage.L0` / `L2.mode` / `L3` | 引擎 | 从维/Guard id 抄出 |
| `untestable` | 引擎 | init 里 unresolved+active 的列 |

## 形式规则

引擎展开后的 v3 仍遵守 F1–F13。LLM 交卷时只要：

| # | 规则 |
| --- | --- |
| F1 | `cuts` / `eq` 的列名只用 confirmed + active |
| F5 | 同一条 L1 里两个维的 `cuts` 中 `case.*` 不相交；一列只由一个维来切 |
| F8 | L1 每对四个格子都能与 Target 同时成立 |
| F9 | exclusions 非空，每条 ≥2 个**不同** Dimension + reason |
| F12 | `environment` 含正整数 `aicNum` 与 `coreNum` |
| F13 | 默认 1 个 `target`；L1 / exclusions 不得跨 Target |

L0–L3 的义务条数由引擎从展开后的 IR 机械展开。

## 骨架

```yaml
schema: tg-plan-fill/v1
requirement: |
  {requirement_text}

target:
  field: replay.{tiling_field}
  expected: 1
  # 多值：in: [1, 2, 3]
  # helper 局部量：field: probe.{name}  op: gt  value: 0

dimensions:
  - id: D-{two_arms}
    cuts: {column}
    arms:
      - {id: p-{arm_a}, eq: {value_a}}
      - {id: p-{arm_b}, eq: {value_b}}
  - id: D-{ratio}
    cuts: [A, B]
    arms:
      - {id: p-equal, eq: {A: 4, B: 4}}
      - {id: p-unequal, eq: {A: 4, B: 2}}
  - id: D-{host_local}
    cuts: probe.{name}
    extra_controls: [{column}]
    arms:
      - {id: p-on, eq: 1}
      - {id: p-off, eq: 0}

guards:
  - {id: G-{slug}, field: {column}, eq: {miss_value}, hit: {reachable_value}}

l1:
  - {dims: [D-{a}, D-{b}], reason: "{why_they_interact}"}

exclusions:
  - {D-{a}: p-{x}, D-{b}: p-{y}, reason: "{why_impossible}"}

oracle: md5
environment:
  aicNum: {int_from_file_line}
  coreNum: {int_from_file_line}
```

## 常见返工

| 现象 | 改法 |
| --- | --- |
| 同一层 `\|\|` 拆成两个 on/off 维 | 合成同一维两格互斥 ON |
| 多层 `\|\|` 折进一个维的 `and` | 拆成各自的维 |
| 仍能命中的枚举被写成 Guard | 改 Dimension，两格都是 ON；合取早退的一支尤其不能整取值升 Guard |
| 合取早退只把其中一列的某个枚举写成 Guard | 删这条 Guard；给该枚举补 Dimension 格，或 Guard 用 `all:` 写全合取项 |
| 只杀一条 `\|\|` 支的条件和切支维做 L1 | 删这条 L1，改 exclusion |
| HIT 入口取值没出现在任何 arm | 给该列补 Dimension 见证 |
| Target 用了兄弟写点字段或自造 MaxRound 别名 | 改观测本次 helper 的 `{name} =` |
| Target 写成落盘 `gt 0`，兄弟也会写成正数 | 下沉到本次 helper 独有的返回字段 |
| L1 某格与 Target 不可同时成立 | 删这条 combination |
| exclusions 为空 | 做互斥分析；判不准的留给 Solve |
| `reason` 没加引号且以 `!` 开头 | 改成 `"..."` |
| exclusion 同一维写两次 | 改成两个不同维 |
| L2 排空全部格子 | 只排除确定不可能的，判不准的留给 Solve |
| `environment` 缺 aicNum/coreNum 或写成 0 | 从环境事实或源码读出正整数 |
| Target 指向未改动的兄弟 helper | 只点名 packet 里的新增/改动赋值 |
| `replay` 字段有兄弟写点仍用它当 Target | 改观测本次 helper 的 `probe.{name}` |
| 两格只改幅度、没有实现分岔 | 删这个维；对面走不到写点的臂升 Guard |
| 同维两格比较值相同 | 改到至少一处不同 |
| probe 维 arms 夹带了 case 构造种子 | arms 只留 probe/replay 互补取值；相关列写 `extra_controls` |
| L1 两维 cuts 都出现同一 case 列 | 删这条 L1 |
| 仍能命中的入口枚举写成 Guard | 改 Dimension 见证；只有全取值都 MISS 才 Guard |
| Target 写成 helper 的 Safe/Ok/`eq 1` | 改观测这次新写入的 replay 落盘字段 |
| 入口开关维和比率维做 L1 | 删这条 L1，改 exclusion |
| 入口开关维和该入口内部 Safe/Ok probe 做 L1 | 删这条 L1，改 exclusion |
| L1 四个格子里有一格打不到 Target | 删这条 combination |
| 只在某一臂赋值的 Ok/Better bool 开成覆盖全部 HIT 的维 | 删维，改写进 `requirement` |
| Guard 把「除 X 以外」写成 `eq` 某个其它枚举 | 改 `op: ne` + `hit: X` |
| 比率杀整只钉了一个绝对列值、正文没有源码表达式 | 正文抄源码失败侧比较（`==` / `<=`）；参与列进 Guard |
| 对「仅部分入口有定义」的内维，把该维每个 arm 都排除 | 只排除一对不可能的格；必须留下至少一个全维可达元组 |
