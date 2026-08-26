---
name: test-plan
description: 把测试要求编译为 Target、Dimension、Guard 与 Exclusion。init 已有、要规划覆盖时使用。
---

# 白盒测试规划

本 Action 负责写出 Coverage IR：测什么、怎么切、哪些组合不可能。Primary 原生 `Task(agent=tg-analyst)` 派一个 Plan Owner，只交 `schema: tg-plan/v3` YAML 全文。Engine 确定性写入 `tg/plan.md`。

## 边界

Plan Owner 交 IR。Solve 逐格求解。义务条数由引擎展开，plan 里不写数字。

## 参考

- 形式规范：`references/coverage-planning.md`
- 观测种类：`references/evidence.md`
- Target 判据：`references/target-planning.md`

散文由 Engine `render_plan_prose` 确定性生成，Plan Owner 不写散文。Packet 字段合同随 packet.usage 注入，不要到本 Skill 里找第二份。
