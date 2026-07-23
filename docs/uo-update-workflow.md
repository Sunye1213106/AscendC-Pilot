# /uo-update 人类说明（非可执行状态机）

**控制面权威**：Harness。`/uo-diff` 仅为 Router 兼容入口 → `uo-update` + intent=`diff_only`（不进入完整更新链）。

## 循环

`harness start uo-update [--intent diff_only]` → `harness next` → Action → `advance` / `complete`。

## 中文阶段

变更检测 → 更新计划 → 应用变更 → 语义闭合 → 导出与校验 → 差异摘要。

`diff_only`：直接差异摘要，不跑 KEY/完整性完整门禁。

## 边界

- 无独立 `/uo-diff` Skill
- KEY / 置信度链与 uo-init 相同（Producer → 确定性报告 → Referee）
- 详见 [overview/workflows.md](./overview/workflows.md)
