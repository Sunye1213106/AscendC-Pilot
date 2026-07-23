# /ce-review 人类说明（非可执行状态机）

**控制面权威**：Pilot。角色：`ce-reviewer` = readonly_reviewer。

## 循环

`acp start ce-review` → `code_review` → `acp complete`（`kb_ready` + `context_pack`）。

## 中文阶段

组装上下文 → 缺陷审查 → 功能审查 → 汇总。

## 边界

- 可写 `ce/review/**`，不可改 IR
- 详见 [overview/workflows.md](./overview/workflows.md)
