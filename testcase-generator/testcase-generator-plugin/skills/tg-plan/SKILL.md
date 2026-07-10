---
name: tg-plan
description: >-
  Generate coverage obligations plan from kb_snapshot. Human review gate.
  Use when the user runs /tg-plan.
disable-model-invocation: true
argument-hint: "[path] [--op-name <name>]"
---

# tg-plan — 覆盖计划

对齐 ST「测试因子/覆盖目标声明」：展开 obligations，不生成真实 case。

## 展开内容

1. family obligations（可达 / 不可达分开）
2. key field-value obligations
3. key relation obligations
4. tilingdata obligations
5. unreachable proof obligations

```powershell
python "$SCRIPT_DIR/tg_plan.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
```

输出：

- `plan/coverage_obligations.yaml`
- `plan/coverage_plan_summary.md`

然后 **STOP** 等人审（见 `prompts/02_plan_human_review.md`）。

摘要必须提醒：

- family ≠ tiling_key
- 默认后续 `--level L0,L1`
- L2 = 异常/不可达，不是 pairwise

参考：`references/coverage-levels.md`、`prompts/03_tilingkey_coverage_rules.md`
