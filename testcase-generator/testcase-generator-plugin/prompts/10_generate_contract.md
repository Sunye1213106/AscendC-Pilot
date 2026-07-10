# Generate Contract

`tg-generate` 确定性流水线（对齐 ST 因子值求解 + L0/L1/L2 生成）。

## 步骤

```text
1. load kb_snapshot + coverage_obligations
2. build factor_space.yaml
3. build rule_model.yaml
4. build candidates by level:
     L0: seed + reachable-family reps + critical single-field
     L1: targeted obligations + family-local pairwise
     L2: unreachable proofs + legal-violation negatives (expect_reject)
5. prune -> candidate_keys_valid.yaml (+ rejected reasons)
6. greedy set cover on L0/L1 only -> selected_targets.yaml
7. realize -> realized_cases.yaml + probe_cases.jsonl
8. missing realization -> review/realization_patch_suggestion.yaml
```

## Level 选择

| --level | 行为 |
|---|---|
| `L0` | 仅门槛 |
| `L0,L1` | 默认：门槛 + 功能组合 |
| `L0,L1,L2` | 含异常/不可达文档化用例 |
| `L1` | 跳过 seed-only 强化（仍含 targeted） |

## Pairwise（仅 L1）

- 在 **family guard 局部域** 内做 pairwise，不做全局笛卡尔积
- 默认选 top 关键字段（非 constant、domain size>1）
- 上限保护（避免爆炸）；超出则依赖 set cover 压缩

## Set cover

- 只覆盖正向 obligations（family/key_field/relation/tilingdata）
- L2 / unreachable_proof 不进入 cover 目标
- LLM 不得挑选 case

## Realize

key → 输入映射优先用 `input_realization`；fallback 用默认表；缺失写 review suggestion。
