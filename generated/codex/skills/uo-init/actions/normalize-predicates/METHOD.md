# 谓词归一化

> **`acp` 是真实 CLI。** 本 Action 走 `uo_init.pilot_engines.normalize_predicates`（确定性）。

## Goal

合并两类缺口为 blocker 列表，写出 `uo/ir/unresolved.yaml`：

1. 谓词/可控性 gap（`gaps.build_gap_report` 聚类）
2. KeyField 派生 undecided/escalating（`DERIVATION_UNDECIDED`）

并附带 `closed_vocabulary`，供后续 `resolve_gaps` 封闭决策。

## Domain Procedure

```text
acp run-action normalize_predicates --project <算子目录>
```

## Output

- `uo/ir/unresolved.yaml`（合同 `normalize-predicates-v1`）
- 含 `blocker_count` / `derivation_blocker_count`
