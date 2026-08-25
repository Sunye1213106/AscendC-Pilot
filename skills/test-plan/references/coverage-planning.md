# 覆盖模型形式规范（查阅用）

`tg-plan/v3` 的谓词语法、骨架与形式规则。方法与步骤在 Plan Owner 任务提示里，这份文档只回答「怎么写对」。

## 谓词

`op` 取值：`eq ne in not_in lt le gt ge mod_eq is_null is_present and or not`

```yaml
{op: eq, field: case.{column}, value: {scalar}}
{op: in, field: replay.{field}, values: [1, 2, 3]}
{op: mod_eq, left: case.{column}, divisor: 2, value: 0}
{op: and, args: [{predicate}, {predicate}]}
{op: not, arg: {predicate}}
```

字段恰好两段，三种前缀：

| 前缀 | 含义 | 取值来源 |
| --- | --- | --- |
| `case.{column}` | 测试表列 | init 列名原文 |
| `replay.{field}` | 落盘的 tiling 字段 | 跑完回读 |
| `probe.{name}` | host 局部量 | 源码里的 `{name} =`，用有辨识度的长名 |

字面量类型对齐 init 的 `inferred_type`：整数列写 int，不加引号。

精度/md5 一类的结果字段属于 `oracle`，不做 `evidence.field`。

## 各段职责

| 段 | 放什么 |
| --- | --- |
| `targets` | 本次改动写入的行为面。默认 1 个；`packet.identifiers` 非空时只点名其中的新赋值 |
| `dimensions` | 写点里的实现分岔，每维 ≥2 个可达 partition |
| `guards` | 使整个 Target 不成立的门。谓词根是 `case.*`，带 `negate_hint` |
| `constraints` | 所有命中行都成立的派生等式。默认 `[]` |
| `environment` | 平台/UT 常量，整数，指得出 file:line |
| `untestable` | 缺绑定的列（`control_gap`，点名列）或真正不可观测的量（`opaque`） |
| `oracle` | 正确性判据（精度、逐位复现、性能记账） |

`constraints` 与 Guard 的 `controls`、以及任何 Dimension 正在切的列，三者互不相交 —— 被钉住的列构造不出对照行。

## 形式规则

| # | 规则 |
| --- | --- |
| F1 | `controls` / `construct_hint.columns` / `case.*` 只用 confirmed + active 的列 |
| F2 | 每个 Target 被某个 Dimension 的 `target` 指向（Guard 指向不算） |
| F3 | `untestable` 与 `targets` 不重叠 |
| F4 | 一个 Dimension 的各 partition 切在同一组字段上；某格多用的列，另一格给一个仍能命中的合法值 |
| F5 | 同一条 L1 里两个 Dimension 的谓词字段集合不相交；跨 `case` / `probe` / `replay` 可以配 |
| F6 | 同维两格谓词互斥且互不蕴含；`in` 的 values 不重叠 |
| F7 | 多值字段：Target 用 `derived` + `in`，Dimension 每值 `eq` 一格。`replay_field` 的 `expected` 是标量 |
| F8 | L1 每对的笛卡尔每格都能与 Target 同时成立 |
| F9 | L2 用 `mode: full_cross`，exclusions 非空，每条 ≥2 维 partition 组合 + reason |
| F10 | 每个 unresolved + active 的列名原样出现在 `untestable` |

L0–L3 的义务条数由引擎从这份 IR 机械展开，plan 里不写数字，也不写 `obligations`。

## 骨架

```yaml
schema: tg-plan/v3
requirement:
  id: R-{slug}
  text: >
    {requirement_text}

targets:
  - id: T-{slug}
    evidence: {kind: replay_field, field: replay.{tiling_field}, expected: 1}
  # 多值字段：
  #   evidence:
  #     kind: derived
  #     predicate: {op: in, field: replay.{field}, values: [1, 2, 3]}
  # 该字段还有兄弟写点时，观测本次 helper 的赋值：
  #   evidence:
  #     kind: derived
  #     predicate: {op: gt, field: probe.{helper_local}, value: 0}

dimensions:
  - id: D-{two_arms}
    target: T-{slug}
    controls: [{column}]
    classifier: {requires: [case.{column}]}
    partitions:
      - {id: p-{arm_a}, predicate: {op: eq, field: case.{column}, value: {value_a}}
      - {id: p-{arm_b}, predicate: {op: eq, field: case.{column}, value: {value_b}}
  - id: D-{multi_value_field}
    target: T-{slug}
    controls: [{column}]
    classifier: {requires: [replay.{tiling_field}]}
    partitions:
      - {id: p-1, predicate: {op: eq, field: replay.{tiling_field}, value: 1}}
      - {id: p-2, predicate: {op: eq, field: replay.{tiling_field}, value: 2}}
  - id: D-{host_local}
    target: T-{slug}
    controls: [{column}]
    classifier: {requires: [probe.{name}]}
    partitions:
      - {id: p-on, predicate: {op: eq, field: probe.{name}, value: 1}}
      - {id: p-off, predicate: {op: eq, field: probe.{name}, value: 0}}

guards:
  - id: G-{slug}
    target: T-{slug}
    controls: [{column}]
    predicate: {op: eq, field: case.{column}, value: {miss_value}}
    negate_hint: {{column}: {reachable_value}}

coverage:
  L0:
    dimensions: [D-{a}, D-{b}, D-{c}]
  L1:
    combinations:
      - {dims: [D-{a}, D-{b}], reason: "{why_they_interact}"}
  L2:
    mode: full_cross
    exclusions:
      - partitions: {D-{a}: p-{x}, D-{b}: p-{y}}
        reason: "{why_impossible}"
  L3:
    guards: [G-{slug}]

oracle: []
constraints: []
environment:
  {platform_const}: {int_from_file_line}

untestable:
  - id: u-{column}
    kind: control_gap
    reason: "{what_this_column_blocks}"
    needs_binding:
      - {column: {column}, want: "confirmed+active"}
```

## 常见返工

| 现象 | 改法 |
| --- | --- |
| 同一层 `\|\|` 拆成两个 on/off 维 | 合成同一维两格互斥 ON |
| 多层 `\|\|` 折进一个维的 `and` | 拆成各自的维 |
| 同维两格谓词字段集合不同 | 缺列的那格补一个仍能命中的合法值 |
| 仍能命中的枚举被写成 Guard | 改 Dimension，两格都是 ON |
| 可切的 host 局部量只出现在 `constraints` | 改成 Dimension，classifier 用 `probe.{name}` |
| 杀整 Target 的量只出现在 `constraints` | 升到驱动它的列写 Guard |
| `constraints` 钉住了 Guard 或 Dimension 正在切的列 | 删这条 constraint |
| L1 某格与 Target 不可同时成立 | 删这条 combination |
| L2 exclusions 为空 | 做互斥分析；判不准的留给 Solve |
| Target 指向未改动的兄弟 helper | 只点名 packet 里的新增/改动赋值 |
| `replay` 字段有兄弟写点仍用它当 Target | 改观测本次 helper 的 `probe.{name}` |
| 两格只改幅度、没有实现分岔 | 去切尚未覆盖的 `if` / min-max / helper |
