---
name: workflow-orchestration
description: >
  AscendC-Pilot 主控编排：对照每个 slash 的输入输出和交叉流水线，
  决定自然语言或专家路径的下一步。分析 PR 并生成测试用例时走
  ce-review、tg-plan、tg-solve；语义一律 uo-query。不是算子领域方法。
---

# Workflow orchestration

主控编排地图。**不是**五个认知 skill 之一。Primary 对照磁盘产物选下一步，一次只跑一个用户 slash。

| 需要 | 读取 |
|---|---|
| 每个 slash 的入/出 | `references/slash-io.md` |
| 交叉流水线 | `references/product-pipelines.md` |
| 怎么选下一步 | `routing/resolve-intent.md` |
| 易错 | `references/gotchas.md` |

## 硬规则

- 无 `.uo` 才 `/uo-init`。已有 `.uo` 且出现 diff 才 `/uo-update`。
- `/uo-query` 走 `pilot_cli` / Task，禁止 `pilot_run`。
- CE/TG 凡要算子语义都经 `/uo-query`，禁止 Grep 算子仓。
- `/ce-apply` 的 diff 回到变更入口，下一步 `/uo-update`。
- `/ce-review` 与 `/ce-plan` 都能接到 `/tg-plan`。
- `.uo` 产物边进入 `/tg-init`。
- `/tg-init` 先问有没有测试脚本仓：有则原绑定；无则按输入 API 设计 `init.yaml`。
- 图上没有的 id 不准发明。不要 `pilot_run workflow=auto` 再开一轮意图理解。

## 黄金 NL

「分析这个 PR 并生成对应测试用例」交付：`/ce-review` + `/tg-plan` + `/tg-solve`。先补 UO，TG 前补 `/tg-init`，语义走 `/uo-query`。
