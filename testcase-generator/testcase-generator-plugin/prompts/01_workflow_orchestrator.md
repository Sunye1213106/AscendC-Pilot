# Workflow Orchestrator

对齐 `ascendc-st-design` 的「校准 → 因子 → 约束 → 求解 → L0/L1/L2 → 总结」，但输入是 understand KB。

```text
Prerequisite: /uo-init 或 /uo-update 产出 canonical tiling KB

tg-init
  校准 UO KB（quality + tiling 四件套）
  -> kb_snapshot.yaml, route.md

tg-plan
  展开 coverage obligations（family / key field / relation / tilingdata / unreachable）
  -> plan/coverage_obligations.yaml
  -> Human Review STOP
     approve | approve_with_extra_constraints | add_obligation | remove_obligation | stop

tg-generate --level L0,L1[,L2]
  1) factor_space   （ST: 04_测试因子）
  2) rule_model     （ST: 05_约束定义）
  3) solver anchors （ST: 06_求解配置）
  4) candidates     （L0 seed/family；L1 targeted+pairwise；L2 unreachable/负例）
  5) prune          （确定性裁剪）
  6) set cover      （最小正向用例集；L2 不参与 cover）
  7) realize        （key → 真实输入）
  -> generate/*, probe_cases.jsonl

tg-probe [--mock]
  -> observed_keys.jsonl   # 覆盖证据唯一来源

tg-audit
  -> coverage_audit.yaml, coverage_matrix.md

tg-report
  -> report/final_report.md

可选:
  tg-repair  缺失补测（最多 3 轮）
  tg-pr      PR 增量（读 change_set）
```

## 关键规则

1. Family coverage ≠ tiling_key coverage
2. expected_key 只是目标；observed_key 才是证据
3. mock probe => verified=false
4. L2 = 异常/不可达，**不是** pairwise
5. Python 算覆盖；LLM 只解释/建议

详见：

- `references/st-alignment.md`
- `references/coverage-levels.md`
- `references/factor-extraction.md`
- `references/constraint-types.md`
