---
name: workflow-orchestration
description: >
  AscendC-Pilot 主控编排：把用户交付目标整理成一次性的 Goal Contract，
  对照 slash I/O 与产品依赖形成 TaskPlan；后续由 runtime 推进，不重复解释自然语言。
  不是算子领域方法。
---

# Workflow orchestration

主控编排地图。**不是**五个认知 skill 之一。自然语言入口只读一次；显式 slash 不建跨 workflow Goal。

| 需要 | 读取 |
|---|---|
| 每个 slash 的入/出 | `references/slash-io.md` |
| 交叉流水线 | `references/product-pipelines.md` |
| Goal Contract / deliverable 选择 | `routing/resolve-intent.md` |
| 易错 | `references/gotchas.md` |

## 硬规则

- 显式 `/uo-init` `/tg-plan` `/ce-review` 等：只运行该节点，不替用户扩展其他交付。
- 自然语言：Primary 一次性产出 `pilot-goal-contract/v1`，调用 reserved `goal-intake`；runtime 校验、展开依赖并持久化 TaskPlan。之后只跟随 `next_workflow_id`。
- `source.kind=pull_request` 表示远端 PR 是事实源：必须 exact head 隔离 workspace；不能用当前本地 fork 冒充。
- PR 上的测试规划必须先有 review planning context：依赖顺序为 UO → CE review → TG init → TG plan → TG solve。Review 负责改动范围/影响范围/测试意图；TG plan 再与 `tg/init.yaml` 合成精度、性能、覆盖与 solve 指标。
- review-only 的 PR 只交付 CE review（另补它自身必要的 UO 前置），不因为出现 PR 就自动生成测试。
- 非 PR 的 TG 可使用用户意图、CE plan、review planning context 或 handoff；不强制额外 CE review。
- `/uo-query` 走 `pilot_cli` / Task，禁止 `pilot_run`。CE/TG 语义查询统一经 `/uo-query`，禁止 Grep 算子仓。
- `/ce-apply` 改变算子源码后，CodeMap 必须刷新；不得拿旧 UO 继续 TG。
- `/tg-init` 的测试脚本仓来自 Goal constraints / 显式参数；同一轮已提供就不得再次询问。
- 图上没有的 workflow id 不准发明；不得默认 architecture。

不存在生产态“黄金句”或固定短语匹配。例句只属于 `evals/` 回归样例，不能参与运行时路由。
