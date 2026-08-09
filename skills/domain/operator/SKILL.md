---
name: operator
description: >
  算子级入口：根据用户目标选择正确的理解/初始化/计划/求解/审查工作流，
  并保持领域工作与编排分离。
---

# 算子入口

## 目标

帮助选择正确工作流，而不是在本 Skill 内完成全部分析。

## 选择指引

| 用户目标 | 工作流 |
|---|---|
| 首次建库 / 抽 Host 投影 | uo-init（认知：`uo-kb-build`） |
| 查 KB / 问结构 | uo-query（认知：`uo-kb-query`） |
| 源码变更后更新 KB | uo-update（认知：`uo-kb-update`） |
| TG 契约与绑定 | tg-init（认知：`tg-init`） |
| 求解计划 | tg-plan（认知：`tg-plan`） |
| TilingKey 闭环求解 | tg-solve（认知：`tg-closure` + `source-lemma-proof`） |
| 代码审查 | ce-review（认知：`code-review`） |

## 原则

- 领域方法读对应 `skills/domain/*/SKILL.md`
- 不要在入口层展开证明或审查长文
- 一次只推进一个明确目标
