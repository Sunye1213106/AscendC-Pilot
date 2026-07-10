---
name: tg-repair
description: >-
  Repair missing coverage obligations. MVP stub with repair_plan.yaml.
  Use when the user runs /tg-repair.
disable-model-invocation: true
argument-hint: "[path] [--op-name <name>] [--max-rounds 3]"
---

# tg-repair — 缺失补测（MVP stub）

```powershell
python "$SCRIPT_DIR/tg_repair.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --max-rounds 3
```

读 `audit/coverage_audit.yaml`，写 `repair/repair_plan.yaml`。

3 轮仍缺失时可 LLM 诊断（仅建议）。见 `prompts/07_repair_diagnosis.md`。
