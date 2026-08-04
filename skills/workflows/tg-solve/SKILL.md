---
name: tg-solve
description: TilingKey 全覆盖闭环（维护 R/E 直至可审计 gap=0）。用户说求解、tg-solve、tilingkey 闭环、生成 csv
  时加载。Pilot 管阶段；加载后执行 acp start tg-solve。
---

# tg-solve

维护 `(D, R, E, Corpus, Models, RuleBook)`：靠 Host 裁决抬 R，靠源码证明抬 E，反例时撤销，直到签发可审计的 gap=0 certificate。

默认 mode = `tilingkey_full_coverage`（不强制 CSV consumer）。`csv_consumer` 仍走 encode/solve/cover。

本 Skill 不定义工作流阶段。执行时：

1. 调用 `acp start`（同 workflow 活动 run 则复用）；
2. 调用 `acp next`；
3. 对返回的 action_id 调用 `acp run-action <action_id>`（prepare；确定性 Action 会自动 finalize）；
4. 语义 Action：按 Runtime Bundle 派发声明 actor，产出后调用 `acp run-action <action_id> --finalize`；
5. `closure_residual` 写出 `tg/closure/route.yaml`：若 reason 不是 `GAP_ZERO`，执行 `acp rework --reason <code>`（勿在单 action 内死循环）；
6. 调用 `acp advance`（仅消费 run-action 签发的可信收据）。

证据与引理纪律见 capability `tilingkey-closure`，勿在 Action prompt 复制。

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
| `lemma_mine` | `subagent` | `tg-lemma-producer` | `producer` | `tg-solve/lemma-mine` | `tg/lemma-mine` | `lemma-mine-v1` |
| `lemma_review` | `subagent` | `tg-closure-referee` | `referee` | `tg-solve/lemma-review` | `tg/lemma-review` | `lemma-review-v1` |
| `lemma_apply` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-solve/lemma-apply` | `-` | `lemma-apply-v1` |
| `closure_audit` | `subagent` | `tg-closure-referee` | `referee` | `tg-solve/closure-audit` | `tg/closure-audit` | `closure-audit-v1` |
| `closure_certify` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-solve/closure-certify` | `-` | `closure-certify-v1` |
| `z3_solve` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-solve/z3-solve` | `-` | `z3-solve-v1` |
| `cover_confirm` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-solve/cover-confirm` | `-` | `cover-confirm-v1` |

<!-- END GENERATED ACTIONS -->
