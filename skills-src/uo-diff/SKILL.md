---
name: uo-diff
description: >-
  已并入 /uo-update。本 Skill 仅重定向：请使用 harness route "/uo-diff …" → uo-update。
disable-model-invocation: true
argument-hint: "[path] [--op-name <name>]"
---

# Skill: uo-diff（已弃用，并入 uo-update）

`/uo-diff` 由 Harness 路由到 **`uo-update`** 工作流。

请执行：

```bash
harness route "/uo-diff $ARGUMENTS"
harness start uo-update --project $PROJECT_ROOT
harness next --project $PROJECT_ROOT
```

只读变更摘要：在 uo-update 的 detect 阶段使用 `detect_kb_changes.py`，**不要**写 `diff/**` 产品包（见 uo-update「diff-only / 只读摘要」模式）。
