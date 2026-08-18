---
name: testcase-generation
description: >
  AscendC 测试生成：`tg/init.yaml` 绑定测试 harness；`tg/plan.md` 将已确定的
  Planning Context 与 init 控制面融合成精度/性能/覆盖义务；solve 生成脚本可读 cases 与 worklog。
---

# Testcase Generation

正式产物只有三份（外加脚本可直接吃的 cases 表）：

| 阶段 | 产物 |
| --- | --- |
| init | `tg/init.yaml` |
| plan | `tg/plan.md`（上半散文，下半 YAML 义务表） |
| solve | `tg/worklog.md` + `tg/cases.csv` 或 `.xls` / `.xlsx` |

草稿只留 `runs/`。不要 inventory / audit / review / fingerprint / dimensions / confirmation 旁路 YAML。

## 阶段边界

- `/tg-init`：只建立测试 harness contract。测试脚本仓存在时，将脚本/CSV/XLS 列、值域、生成器、golden/compare、精度/性能入口绑定到 CodeMap；mapping 空则失败。没有测试仓时以 `/uo-query` 的输入 API 设计可执行控制面。
- `/tg-plan`：核心输入必须是 **`tg/init.yaml` + Planning Context**。Planning Context 来自前置 `/ce-review`、`/ce-plan`、用户显式测试计划或等价 handoff；PR 测试链中由 `/ce-review` 先给 changed_scope / affected_scope / risks / test_intent / validation_targets。TG 不重新做 PR review，也不重新解释原始 NL。
- `/tg-solve`：只消费已验证 plan + init，构造 cases、Host replay、闭合 worklog；`test_harness_gap` 未落地时禁止 solve。

`.uo` 是 TG 的语义事实权威：plan/solve 需要语义时统一用 `uo-query`，但它不替代 Planning Context。

## Plan 应补齐什么

Planning Context 说明“为什么测、改了什么、影响什么”；`tg/init.yaml` 说明“脚本能控制/执行什么”。plan 将两者结合，形成：

- 改动直接范围与影响范围对应的覆盖义务；
- 必要边界、反例和组合覆盖；
- 基于 init compare/golden 能力的精度验证计划；
- 只有 harness 真正支持时才规划性能执行与阈值，否则明确 gap；
- 每条可自动闭合义务的 replay / derived 命中判据与 solve 完成条件。

义务必须 root 到 `init.yaml` 的 CSV/XLS 列。缺列/生成器 → `test_harness_gap`；无法控制 → `untestable` + reason。全量 tilingkey 只在 Planning Context 明确要求时做，不是默认模式。

## 核心循环

```text
Planning Context + init.yaml
        ↓
      plan.md
        ↓
construct cases → Host Replay → worklog
        ↓
     open: []
```

Primary 负责自然语言和跨 workflow Task Plan；本 skill 只定义 TG 领域方法，不承担编排路由。TG 内部 `bind_init` / `plan_fuse` / `construct_cases` 等名称都是 Action，不是用户 skill 或 slash。

## 按需参考

| 需要 | 读取 |
|---|---|
| 绑定测试 harness | `capabilities/bind-init/METHOD.md` |
| 融合义务 | `capabilities/plan-fuse/METHOD.md` |
| 构造用例 | `capabilities/construct-cases/METHOD.md` |
| 写 worklog | `capabilities/analyze-round/METHOD.md` |
| 测试脚本仓 | `references/test-script-repo.md` |
| 规划启发式 | `references/plan-heuristics.md` |
| Host replay | `references/oracle.md` |
| 踩坑 | `references/gotchas.md` |
