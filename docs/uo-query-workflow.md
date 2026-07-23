# /uo-query 人类说明（非可执行状态机）

**控制面权威**：Pilot。角色：`uo-query` = readonly_analyst。

## 循环

`acp start uo-query` → `kb_lookup` → `acp complete`（门禁仅 `kb_ready`）。

## 中文阶段

问题路由 → 知识检索 → 回答。

## 边界

- 不写正式 IR/summary/review
- 不附加 uo-init KEY 完成门禁
- 详见 [overview/workflows.md](./overview/workflows.md)
