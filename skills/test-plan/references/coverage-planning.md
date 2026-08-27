# 覆盖规划

本文件是 Plan Owner 的方法：把 init + packet 编译成 `tg-plan/v3`。主控只转发本文件路径，禁止自己写 IR。本步规划交互，不证明格子可满足。同窗 refs 里有 Target 判据和命中观测；立 Target / 写 evidence 时打开，不要在本文件找第二份。

## 输入 / 输出 / 停

读：`init.yaml`、`plan_scope_packet.yaml`、packet / FOCUS 给出的 `file:line`。写：无。最终消息正文就是 YAML 全文。

CodeMap 已编进 packet。只读 packet，不要再查图。激活列不在 `controls.case_allowed` → 只写 `untestable`（`kind: control_gap`）并停，禁止用 replay / probe 绕过 construct。

## 步骤

1. **解析 PR-owned 行为。** 每个独立可观测行为一个 Target。共享 observation 且语义等价才合并。不要默认 1 个，也不要用 `packet.identifiers` 卡成「只点名新赋值」。
2. **过 Target 门。** 必答：Ownership、Construct、Reachability、Observation。缺一门就写 `untestable`，不要猜 partition。Seed 与 Oracle 可选，见 Target 判据。
3. **分开 Dimension / Guard / Constraint。** 实现分岔 → Dimension（每维 ≥2 格，两格都能 HIT）。启用条件 → Guard（翻 `negate_hint` 则 Target 必须 MISS）。命中行恒成立的派生等式 → `constraints`。平台常量 → `environment`。三者切的列互不相交。
4. **选 observation。** 每个正式 Target 必须能回答跑完 Replay 看什么。写法只认命中观测文。精度 / md5 进 `oracle`，不是 evidence。
5. **规划 L0 / L1 / L2 / L3。**
   - L0：本 Target 的维清单。
   - L1：语义上值得 pairwise 的两维。入口开关维 × 只在该入口才生效的维，不要配成 L1。格子 SAT 交给 Solve，不要预先证明笛卡尔每格都能 HIT。
   - L2：只交叉**同一 Target** 的维。`exclusions` 只收已经证明不可能的组合；判不准留给 Solve。空列表合法，表示没有已证排除。禁止把互斥行为簇拼成一张全交叉表。
   - L3：Guard 证伪。
6. **表面化缺口。** 路径闭包上 construct 未闭合 → `kind: control_gap` + `needs_binding`。本质不可控 / 不可观测 → `harness_gap` / `opaque`。ownership 未闭合 → `unverified`。身份缺口（空 `uo.id` + `candidate`）只要 `confirmed` 就不进 `untestable`。
7. **写出 IR。** 按下骨架填。不要写 `obligations`、不要写义务条数、不要写散文。
8. **交给引擎校验。** 形式错误由 `plan_validate` 拒绝。不要为了过校验去发明 exclusion 或脑补 constructibility。

## 常驻判断

```text
Plan = 哪些维值得交叉
Solve = 逐格 SAT / UNSAT / UNCONSTRUCTIBLE
```

UNSAT → exclusion / 源码证明。SAT 但无构造行 → constructibility gap。SAT 且可构造 → 具体 case。

`constraints`、Guard 的 `controls`、以及任何 Dimension 正在切的列，三者互不相交。

## 看到这样

| 现象 | 做法 |
| --- | --- |
| 同一层 `\|\|` 拆成两个 on/off 维 | 合成同一维两格互斥 ON |
| 多层 `\|\|` 折进一个维的 `and` | 拆成各自的维 |
| 仍能命中的枚举被写成 Guard | 改 Dimension，两格都是 ON |
| 可切的 host 局部量只出现在 `constraints` | 改 Dimension，classifier 用 `probe.{name}` |
| 杀整 Target 的量只出现在 `constraints` | 升到驱动它的列写 Guard |
| `constraints` 钉住了 Guard 或 Dimension 正在切的列 | 删这条 constraint |
| 为让 L1 四格都 HIT 而删交互 | 把 SAT 留给 Solve；嵌套维不要配 L1 |
| 为过校验编一条 exclusion | 删掉。未知可达性留给 Solve |
| L2 把不同 Target 的维拼进同一条 exclusion / 全交叉 | 按 Target 拆开 |
| Target 指向未改动的兄弟 helper | 只点名 PR-owned 行为 |
| `replay` 字段有兄弟写点仍用它当 Target | 改观测本次 helper 的 `probe.{name}` |
| 两格只改幅度、没有实现分岔 | 去切尚未覆盖的 `if` / min-max / helper |
| corpus 0 行写成 untestable | 0 只表示没有现成 seed，不表示不可达 |

## 完成勾选

- [ ] 每个 Target 过了四道必答门，或已写入对应 `untestable`
- [ ] Dimension / Guard / Constraint 列互不相交
- [ ] L1 只表达交互，没有声称每格 SAT
- [ ] L2 exclusions 只有已证不可能的组合（允许 `[]`）
- [ ] 正文是 `tg-plan/v3` YAML，没有散文、没有义务数字

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
