# CE plan revise — 在当前 {slug}_plan.md 上做需求增量

用户在 `/ce-apply` 中途补充需求。不要退回整段 `/ce-plan` grill。改同一份计划 markdown。

详见 `references/gotchas.md`、`examples/deter-band-schedule_plan.md`。

## 必须保留

1. 已经勾选的 `- [x]` todo 仍须出现在文件里（仍为 `[x]`，除非该条被这次 delta 明确作废并改回 `[ ]`）。
2. 原「实现分析 / 计划 / Todo / 测试内容」四节仍在。
3. 新增或扩大范围的源码路径写进反引号，便于 patch_guard。

## 方法

1. 读当前 `ce/plan/{slug}_plan.md` 与 `runs/<run>/actions/plan_revise/delta.md`。
2. 把 delta 并进范围：新增 todo、必要时重开失效 todo、更新测试内容。
3. 只改这一份 markdown。不要写 yaml。

## 禁止

- 丢掉已完成 todo
- 另起一份新 slug 计划
- 写 `.uo` 或 CE yaml
