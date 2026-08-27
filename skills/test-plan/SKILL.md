---
name: test-plan
description: 把测试要求编译为 Target、Dimension、Guard 与 Exclusion。init 已有、要规划覆盖时使用。
---

# 白盒测试规划

本 Action 负责写出 Coverage IR：测什么、怎么切、哪些组合已证明不可能。产出一份 `schema: tg-plan/v3` YAML（机器合同 `schemas/tg/plan-v3.yaml`）。禁止 Write `tg/plan.md`。散文由 Engine `render_plan_prose` 生成。义务条数由引擎展开，plan 里不写数字。

Plan 交 IR。Solve 逐格判定 SAT / UNSAT / UNCONSTRUCTIBLE。Plan 不因为 corpus=0 删除格，也不能提前替 Solve 求解。Packet 字段合同随 `packet.usage` 注入，不要到本 Skill 找第二份。

CodeMap 已编进 packet。只读 packet，不要再查图。激活列不在 `controls.case_allowed` → 只写 `untestable`（`kind: control_gap`）并停，禁止用 replay / probe 绕过 construct。

## 输入 / 输出 / 停

读：`init.yaml`、`plan_scope_packet.yaml`、packet / FOCUS 给出的 `file:line`。写：无。最终消息正文就是 YAML 全文。

缺一门 Target 门就写 `untestable`，不要猜 partition。形式错误由 `plan_validate` 拒绝。不要为了过校验去发明 exclusion 或脑补 constructibility。

## 步骤

1. **识别 PR-owned 可观测行为。** 每个独立可观测行为一个 Target。共享 observation 且语义等价才合并。不要默认 1 个，也不要用 `packet.identifiers` 卡成「只点名新赋值」。
2. **过 Target 门。** 必答：Ownership、Construct、Reachability、Observation。缺一门就写 `untestable`。Seed 与 Oracle 可选，见 Target 判据。
3. **从 Target 可达性推导 Guard。** 启用条件 → Guard（翻 `negate_hint` 则 Target 必须 MISS）。只记录会改变能否到达本写点的条件。
4. **推导实现 Dimension。** 实现分岔 → Dimension（每维 ≥2 格，两格都能 HIT）。可切的 host 局部量不要只写在 `constraints`。
5. **只加路径上恒成立的 constraint。** 命中行恒成立的派生等式 → `constraints`。平台常量 → `environment`。`constraints`、Guard 的 `controls`、以及任何 Dimension 正在切的列，三者互不相交。
6. **提名 L0/L1/L2/L3 覆盖交互。**
   - L0：本 Target 的维清单。
   - L1：语义上值得 pairwise 的两维。入口开关维 × 只在该入口才生效的维，不要配成 L1。格子 SAT 交给 Solve。
   - L2：只交叉同一 Target 的维。`exclusions` 只收 packet 里已经接受的静态证明；判不准留给 Solve。空列表合法。
   - L3：Guard 证伪。
7. **选合法观测。** 每个正式 Target 必须能回答跑完 Replay 看什么。字段只认 packet 观测词表。精度 / md5 进 `oracle`，不是 evidence。
8. **表面化未决缺口。** 路径闭包上 construct 未闭合 → `kind: control_gap` + `needs_binding`。本质不可控 / 不可观测 → `harness_gap` / `opaque`。ownership 未闭合 → `unverified`。身份缺口（空 `uo.id` + `candidate`）只要 `confirmed` 就不进 `untestable`。
9. **写出 tg-plan/v3 IR。** 谓词语法与骨架见 coverage-ir。不要写 `obligations`、不要写义务条数、不要写散文。

## 缺口怎么写

`untestable[]` 是 legacy gap bucket，不能看到这个数组名就直接推断「静态不可达」。一律进该数组，用 `kind` 区分，不要自造顶层键：

| kind | 何时 |
| --- | --- |
| `control_gap` | 理论上可构造，当前 binding 未闭合。必填 `needs_binding` |
| `harness_gap` / `opaque` | 当前 harness / 环境本质无法控制或观察 |
| `unverified` | packet 无法闭合 ownership |

## 常驻判断

```text
Plan = 哪些维值得交叉
Solve = 逐格 SAT / UNSAT / UNCONSTRUCTIBLE
```

UNSAT → exclusion / 源码证明。SAT 但无构造行 → constructibility gap。SAT 且可构造 → 具体 case。

两侧合取仍是 candidate obligations。只有 packet 里已经接受的静态证明才能在规划期压掉某一侧；否则 Solve 判定 SAT / UNSAT。

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
| 字段不在 packet 观测词表 | 标 observation / packet gap，不要再查 UO |

## 完成勾选

- [ ] 每个 Target 过了四道必答门，或已写入对应 `untestable`
- [ ] Dimension / Guard / Constraint 列互不相交
- [ ] L1 只表达交互，没有声称每格 SAT
- [ ] L2 exclusions 只有已证不可能的组合（允许 `[]`）
- [ ] 正文是 `tg-plan/v3` YAML，没有散文、没有义务数字
- [ ] 没有重新 query UO

## 指针

- IR 语法与骨架：`references/coverage-ir.md`
- Target 门与切分语义（立 Target 时必读）：`references/target-planning.md`
- 命中观测（写 `evidence` / `classifier.requires` 时读）：`references/evidence.md`
- 机器合同：`schemas/tg/plan-v3.yaml`
