# /tg-solve 人类说明（非可执行状态机）

**控制面权威**：Harness。终态看真实 solver / realization / obligation 产物，不依赖可伪造 status 文件。

## 循环

`harness start tg-solve` → z3_solve / cover_confirm → `complete`。

## 中文阶段

求解前置 → 编码约束 → Z3 求解 → CSV 投影 → 覆盖确认。

## 边界

- 引擎：`deterministic-tg-engine`
- 详见 [overview/workflows.md](./overview/workflows.md)
