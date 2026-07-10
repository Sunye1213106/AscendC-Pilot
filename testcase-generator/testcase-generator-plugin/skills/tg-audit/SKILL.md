---
name: tg-audit
description: >-
  Coverage audit using observed_key only. Use when the user runs /tg-audit.
disable-model-invocation: true
argument-hint: "[path] [--op-name <name>]"
---

# tg-audit — 覆盖审计

仅用 `observed_keys.jsonl` 计算覆盖；`expected_key` 仅用于 mismatch。

```powershell
python "$SCRIPT_DIR/tg_audit.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
```

输出 `audit/coverage_audit.yaml`、`audit/coverage_matrix.md`。

见 `prompts/06_audit_contract.md`、`prompts/03_tilingkey_coverage_rules.md`。
