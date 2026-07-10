---
name: tg-generate
description: >-
  Generate tilingkey candidates and realized input cases from coverage obligations.
  Levels align with ascendc-st-design: L0 threshold, L1 pairwise/functional, L2 negative.
  Use when the user runs /tg-generate.
disable-model-invocation: true
argument-hint: "[path] [--op-name <name>] [--level L0,L1]"
---

# tg-generate — 生成候选与用例

对齐 ST：因子提取 → 约束 → 求解/采样 → L0/L1/L2。

## 级别（重要）

| Level | 含义 | 候选 |
|---|---|---|
| L0 | 门槛 | seed + family 代表 + 关键单字段 |
| L1 | 功能组合 | targeted obligations + **pairwise** |
| L2 | 异常/不可达 | unreachable + legal 负例（`expect_reject`） |

**L2 ≠ pairwise。** Pairwise 属于 L1。

## 流水线（Python 确定性）

```text
factor_space → rule_model → candidates(level) → prune → set_cover(L0/L1) → realize
```

```powershell
python "$SCRIPT_DIR/tg_generate.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --level L0,L1
# 含异常文档化：
python "$SCRIPT_DIR/tg_generate.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --level L0,L1,L2
```

## 输出

- `generate/factor_space.yaml`（含 solver anchors）
- `generate/rule_model.yaml`（constraints 带 type）
- `generate/candidate_keys_*.yaml`
- `generate/selected_targets.yaml`
- `generate/realized_cases.yaml`
- `generate/probe_cases.jsonl`（仅正向；L2 不进 probe）
- `generate/l2_negative_cases.yaml`（若启用 L2）

LLM 不可参与 set cover。见：

- `prompts/10_generate_contract.md`
- `prompts/09_factor_space.md`
- `prompts/04_rule_model.md`
- `references/st-alignment.md`
