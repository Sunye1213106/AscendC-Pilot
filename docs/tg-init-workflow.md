# /tg-init 人类说明（非可执行状态机）

**控制面权威**：Harness。测项合同真源：`.ascendc-agent/tg/`（非 UO `contracts/**`）。

## 循环

`harness start tg-init` → `harness next` → Action → `complete`。

## 前置条件

- 定稿 UO KB（`uo_ready`）
- **测试脚本根目录**（`test_script_root` / `csv_consumer_root` / `ASCENDC_TEST_SCRIPT_ROOT`）
  - 缺失 → `TEST_SCRIPT_ROOT_REQUIRED`（在 `contract_build` 前置失败，而非静默跳过）

## 中文阶段

KB 检查 → 合同构建 → 语义绑定 → 绑定合并 → 中间量闭合 → 完整性校验 → 人工确认。

首阶段「KB 检查」只校验 `uo_ready`；TG fingerprint 在确认后才存在。

## 角色（与 Workflow Spec 一致）

| id | role | 典型 Action |
|---|---|---|
| deterministic-tg-engine | deterministic_engine | kb_check / contract_build / bind_merge / … |
| tg-semantic-bind | producer | semantic_bind（只写 patch；finalize 应用） |
| tg-init-audit | referee | init_audit |
| 人工确认 | 用户操作 | human_confirm |

> `tg-csv-contract` 为历史 producer 名；当前 `contract_build` 由确定性 Engine 执行。

## 边界

- 只读 UO；不回写 `$UO_ROOT/**`
- Gate 复用 TG Engine 真校验（merge / symmetry / csv_closure / audit / init_confirmed）
- 详见 [overview/workflows.md](./overview/workflows.md)
