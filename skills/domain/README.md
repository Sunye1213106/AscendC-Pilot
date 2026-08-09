# Domain Skills（Agent 认知层）

本目录是语义 Agent 的**主入口**。Workflow Skill（`skills/workflows/`）属于 Pilot Harness。

旧闭环 Agent SOP 等第二真相源已删除；以本目录 `SKILL.md` + `references/` + `_shared/` 为准。

## 规则

- 每个 `SKILL.md` ≤ 200 行，含 frontmatter `name` + `description`
- 禁止 Harness 词：`run_id`、`action_id`、`finalize`、`advance`、`acp start`、`acp next`
- 复杂规则放 `references/`；跨 skill 共用放 `_shared/`
- Task Prompt → 一个 domain skill → 按需 reference（最多一次跳转）
- FAG 等算子只是案例来源；reference 必须可迁移到任意 AscendC/C++ 算子

## 目录

| id | 用途 |
|---|---|
| `_shared/` | 证据、完整性、新鲜度、C++ 语义 |
| `source-lemma-proof` | 源码语义命题证明/反驳 |
| `code-review` | 代码审查与影响分析 |
| `tg-closure` | TilingKey 闭环：R/E 增长与停止 |
| `tg-init` | TG 初始化（薄，本轮不扩展 FAG） |
| `tg-plan` | TG 计划（薄） |
| `uo-kb-build` | UO KB 建立 |
| `uo-kb-query` | UO KB 查询 |
| `uo-kb-update` | UO KB 更新 |
