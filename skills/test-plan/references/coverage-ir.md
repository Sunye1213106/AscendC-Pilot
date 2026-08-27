# 覆盖 IR

**何时加载**：写出 `tg-plan/v3` YAML、核对谓词与字段名时。

机器合同：`schemas/tg/plan-v3.yaml`。本文件只约束怎么写对格式。规划步骤在 Skill 正文。

## 谓词与字段

`op` 取值：`eq ne in not_in lt le gt ge mod_eq is_null is_present and or not`

```yaml
{op: eq, field: case.{column}, value: {scalar}}
{op: in, field: replay.{field}, values: [1, 2, 3]}
{op: mod_eq, left: case.{column}, divisor: 2, value: 0}
{op: and, args: [{predicate}, {predicate}]}
{op: not, arg: {predicate}}
```

字段恰好两段，三种前缀：`case.{column}`（init 列名原文）、`replay.{field}`（解码器叶子）、`probe.{name}`（packet 探针名）。字面量类型对齐 `inferred_type`：整数列写 int，不加引号。

多值字段：Target 用 `derived` + `in`；Dimension 每值 `eq` 一格。`replay_field` 的 `expected` 是标量。

`replay.*` 只写 `observation_catalog.replay_allowed` 里的键。`probe.*` 只写 `probe_candidates` / `probeable: true` 的名字。`case.*` 只写 `controls.case_allowed`。

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

dimensions:
  - id: D-{two_arms}
    target: T-{slug}
    controls: [{column}]
    classifier: {requires: [case.{column}]}
    partitions:
      - {id: p-{arm_a}, predicate: {op: eq, field: case.{column}, value: {value_a}}}
      - {id: p-{arm_b}, predicate: {op: eq, field: case.{column}, value: {value_b}}}

guards:
  - id: G-{slug}
    target: T-{slug}
    controls: [{column}]
    predicate: {op: eq, field: case.{column}, value: {activation_value}}
    negate_hint: {{column}: {violating_value}}

coverage:
  L0:
    dimensions: [D-{a}, D-{b}, D-{c}]
  L1:
    combinations:
      - {dims: [D-{a}, D-{b}], reason: "{why_they_interact}"}
  L2:
    mode: full_cross
    exclusions: []
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

`untestable[]` 是 legacy gap bucket。`kind: control_gap` 表示 binding 未闭合，不是静态不可达。
