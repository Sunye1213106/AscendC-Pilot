---
name: tg-probe
description: >-
  Run tiling probe to obtain observed tiling_key. MVP supports --mock.
  Use when the user runs /tg-probe.
disable-model-invocation: true
argument-hint: "[path] [--op-name <name>] [--mock]"
---

# tg-probe — 探测 observed tiling_key

```powershell
python "$SCRIPT_DIR/tg_probe.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --mock
```

输出 `probe/observed_keys.jsonl`。

`--mock` 时必须在报告中标注 `mock_probe: true`、`coverage_verified: false`。

见 `prompts/05_probe_contract.md`。
