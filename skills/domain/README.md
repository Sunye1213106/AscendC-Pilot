# Domain Skills（Agent 认知层）

本目录是语义 Agent 的**主入口**。Workflow Skill（`skills/workflows/`）属于 Pilot Harness，不教审查/证明算法。

## 规则

- 每个 `SKILL.md` ≤ 200 行，含 frontmatter `name` + `description`
- 禁止 Harness 词：`run_id`、`action_id`、`finalize`、`advance`、`acp start`、`acp next`
- 复杂规则、Schema、领域检查、示例放 `references/`，按需读取
- Task Prompt 只指向一个 domain skill；到方法最多一次跳转

## 目录

| id | 用途 |
|---|---|
| `source-lemma-proof` | 源码语义命题证明/反驳 |
| `code-review` | 代码审查与影响分析 |
| `tg-closure` | TilingKey 闭环：R/E 增长与停止条件 |
| `tg-init` | TG 初始化：契约、绑定、审计、确认 |
| `tg-plan` | TG 计划意图与批准 |
| `uo-kb-build` | UO KB 建立：范围、gap、审查 |
| `uo-kb-query` | UO KB 查询回答 |
| `uo-kb-update` | UO KB 增量更新 |
| `operator` | 算子级入口：选对 workflow |
