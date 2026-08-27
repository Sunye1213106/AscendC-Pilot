---
name: test-plan
description: 把测试要求编译为 Target、Dimension、Guard 与 Exclusion。init 已有、要规划覆盖时使用。
---

# 白盒测试规划

本 Action 负责写出 Coverage IR：测什么、怎么切、哪些组合已证明不可能。产出一份 `schema: tg-plan/v3` YAML（机器合同 `schemas/tg/plan-v3.yaml`）。禁止 Write `tg/plan.md`。散文由 Engine `render_plan_prose` 生成。义务条数由引擎展开，plan 里不写数字。

Plan 交 IR。Solve 逐格判定 SAT / UNSAT / UNCONSTRUCTIBLE。Packet 字段合同随 `packet.usage` 注入，不要到本 Skill 找第二份。

## 缺口怎么写

缺口一律进 `untestable[]`，用 `kind` 区分，不要自造顶层键：

| kind | 何时 |
| --- | --- |
| `control_gap` | 理论上可构造，当前 binding 未闭合。必填 `needs_binding` |
| `harness_gap` / `opaque` | 当前 harness / 环境本质无法控制或观察 |
| `unverified` | packet + UO 无法闭合 ownership |

## 指针

- 规划步骤（Plan Owner 每次必读）：`references/coverage-planning.md`
- Target 门与切分语义（立 Target 时必读）：`references/target-planning.md`
- 命中观测（写 `evidence` / `classifier.requires` 时读）：`references/evidence.md`
- 机器合同：`schemas/tg/plan-v3.yaml`
