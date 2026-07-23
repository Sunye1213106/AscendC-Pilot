# /tg-init 人类说明（非可执行状态机）

**控制面权威**：Harness。测项合同真源：`.ascendc-agent/tg/`（非 UO `contracts/**`）。

## 循环

`harness start tg-init` → `harness next` → Action → `complete`。

## 中文阶段

KB 检查 → 合同构建 → 语义绑定 → 绑定合并 → 中间量闭合 → 完整性校验 → 人工确认。

首阶段「KB 检查」只校验 `uo_ready`；TG fingerprint 在确认后才存在。

## 角色

| id | role |
|---|---|
| tg-csv-contract | producer |
| tg-init-audit | referee（审计，不是人工确认） |
| deterministic-tg-engine | deterministic_engine |
| 人工确认 | 用户操作 |

## 边界

- 只读 UO；不回写 `$UO_ROOT/**`
- Gate 复用 TG Engine 真校验（merge / symmetry / csv_closure / audit / init_confirmed）
- 详见 [overview/workflows.md](./overview/workflows.md)
