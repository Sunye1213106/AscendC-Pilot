---
name: test-plan
description: 把测试要求编译为 Target、Dimension、Guard 与 L0–L3 覆盖义务。init 已有、要规划覆盖时使用。
---

# 白盒测试规划

本目录是 family manifest，不是某一窗的方法。Primary 原生 `Task(agent=tg-analyst)` 派**一个 Plan Owner**：同一窗内答完「测什么」与覆盖模型，只交 `schema: tg-plan/v3` YAML 全文。Engine 确定性 narrate 三节散文并写入 `tg/plan.md`。

## 边界

Plan 立账，Solve 结账。

Plan 交的是账本：Target（测什么）、Dimension 的 arms（怎么切）、Guard（哪些门整体关断）、L2 exclusions（哪些组合明显冲突）。Solve 逐格求解：每格到底可不可达、用什么列值构造、行怎么落表。

L0–L3 的义务条数由引擎从 IR 机械展开，plan 里不写数字。L2 是各 Dimension 的全交叉，plan 的分析价值落在 exclusions 上 —— 空 exclusions 等于交出裸笛卡尔积。

## 参考

- 形式规范（谓词语法、骨架、形式规则、常见返工）：`references/coverage-planning.md`
- 观测种类：`references/evidence.md`
- 「测什么」四项必答：`references/target-planning.md`

散文由 Engine `render_plan_prose` 确定性生成，Plan Owner 不写散文。
