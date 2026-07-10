---
name: tg-pr
description: >-
  PR incremental testcase generation. MVP stub when change_set missing.
  Use when the user runs /tg-pr.
disable-model-invocation: true
argument-hint: "[path] [--op-name <name>]"
---

# tg-pr — PR 增量测试（MVP stub）

读 `cbm/change_set.yaml`、`summary/update_plan.yaml`，展开 impacted obligations。

```powershell
python "$SCRIPT_DIR/tg_pr.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
```

见 `prompts/08_pr_mode.md`。
