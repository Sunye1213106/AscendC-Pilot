---
name: uo-diff
description: 已并入 /uo-update。本 Skill 仅重定向：请使用 harness route "/uo-diff …" → uo-update。
disable-model-invocation: true
argument-hint: '[path] [--op-name <name>]'
---

# Skill: uo-diff（已弃用，并入 uo-update）

## Harness control plane（唯一权威）

本 Skill **不**拥有阶段/门禁/完成态。每一轮只做：

1. `harness start <workflow_id> --project $PROJECT_ROOT`（若无活动 run）或读 `harness status`
2. `harness next --project $PROJECT_ROOT` → 取 `phase_label_zh`、`allowed_actions`、`open_items`
3. 按返回的 **一个** `action_id` 执行对应领域方法（见 references / prompts）
4. 需要时 `harness advance <next_phase>` / `harness rework --reason <code>`
5. 终态仅 `harness complete`；禁止自行宣布 done / `passed`

Gate 失败 → 保持 phase，status=`rework_required` 或 `human_required`；勿当作立即 blocked。


`/uo-diff` 由 Harness 路由到 **`uo-update`** 工作流。

请执行：

```bash
harness route "/uo-diff $ARGUMENTS"
harness start uo-update --project $PROJECT_ROOT
harness next --project $PROJECT_ROOT
```

只读变更摘要：在 uo-update 的 detect 阶段使用 `detect_kb_changes.py`，**不要**写 `diff/**` 产品包（见 uo-update「diff-only / 只读摘要」模式）。