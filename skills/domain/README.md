# Domain Skills（Agent 认知层）

Workflow Skill 只做编排。Domain Skill 是唯一领域 authority。

## 规则

- `SKILL.md` ≤ 200 行；禁止 Harness 词
- 可引用 `_shared/` 与本 Skill `references/`；**禁止** include 另一 Domain `SKILL.md`
- 跨领域协作用 **task delegation**（工作流派发另一 Action），用结构化产物交接
- Capability 只保留检索/导航类；领域推理不得放在 `skills/capabilities/`

## 目录

| id | 用途 |
|---|---|
| `_shared/` | 证据、完整性、新鲜度、C++、finding 格式 |
| `source-lemma-proof` | 源码命题证明 |
| `code-review` | 代码审查 |
| `tg-closure` | 闭环 R/E（含 examples 适配器样例） |
| `tg-init` / `tg-plan` | 初始化 / 计划（薄） |
| `uo-kb-build` / `uo-kb-query` / `uo-kb-update` | UO KB |
