---
name: tg-solve
description: TilingKey 全覆盖闭环：动态运行抬 R、源码引理抬 E，直至可审计 gap=0。用户说求解、 tg-solve、tilingkey
  闭环、生成 csv 时加载。Pilot 管阶段；加载后 acp start tg-solve。
---

# tg-solve

合法增长可达集 R 与排除集 E，直至可审计 gap=0。

领域方法：

- 闭环策略：`skills/domain/tg-closure/SKILL.md`
- 源码引理：`skills/domain/source-lemma-proof/SKILL.md`

链路：`uo-init → tg-init → tg-plan → tg-solve`。

## Pilot

1. `acp start` → `acp next` → `acp run-action` →（语义则 finalize）→ `acp advance`
2. `closure_residual` 给出非 `GAP_ZERO` 时按 route 执行 `acp rework`（勿在单 action 内死循环）
3. 近似模型只排序候选；排除必须有可审计证明

## Actions

<!-- BEGIN GENERATED ACTIONS -->

| action_id | execution_mode | agent | role | method | prompt | output_contract |
|---|---|---|---|---|---|---|
| `solve_precheck` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-solve/solve-precheck` | `-` | `solve-precheck-v1` |
| `oracle_probe` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-solve/oracle-probe` | `-` | `oracle-probe-v1` |
| `closure_ledger` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-solve/closure-ledger` | `-` | `closure-ledger-v1` |
| `closure_search` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-solve/closure-search` | `-` | `closure-search-v1` |
| `closure_residual` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-solve/closure-residual` | `-` | `closure-residual-v1` |
| `closure_construct` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-solve/closure-construct` | `-` | `closure-construct-v1` |
| `closure_explain` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-solve/closure-explain` | `-` | `closure-explain-v1` |
| `lemma_leads` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-solve/lemma-leads` | `-` | `lemma-leads-v1` |
| `lemma_evidence` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-solve/lemma-evidence` | `-` | `lemma-evidence-v1` |
| `lemma_mine` | `subagent` | `tg-lemma-producer` | `producer` | `tg-solve/lemma-mine` | `tg/lemma-mine` | `lemma-mine-v1` |
| `lemma_review` | `subagent` | `tg-closure-referee` | `referee` | `tg-solve/lemma-review` | `tg/lemma-review` | `lemma-review-v1` |
| `lemma_apply` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-solve/lemma-apply` | `-` | `lemma-apply-v1` |
| `closure_audit` | `subagent` | `tg-closure-referee` | `referee` | `tg-solve/closure-audit` | `tg/closure-audit` | `closure-audit-v1` |
| `closure_certify` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-solve/closure-certify` | `-` | `closure-certify-v1` |
| `z3_solve` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-solve/z3-solve` | `-` | `z3-solve-v1` |
| `cover_confirm` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-solve/cover-confirm` | `-` | `cover-confirm-v1` |

<!-- END GENERATED ACTIONS -->
