# /tg-plan 人类说明（非可执行状态机）

**控制面权威**：Harness。人工批准不是 Referee Agent。

## 循环

`harness start tg-plan` → plan_build / plan_approve → `complete`。

## 中文阶段

规划范围 → 前置门禁 → 生成义务 → 过滤裁剪 → 规划审查 → 人工批准。

## 边界

- `plan_approved` 校验真实 snapshot/plan hash、`allow_solve`、blockers
- 详见 [overview/workflows.md](./overview/workflows.md)
