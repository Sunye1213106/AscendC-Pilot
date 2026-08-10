---
name: tg-solve
description: '执行已批准 TG Plan：对 target set T 构造/replay case，用真实 Host witness 扩大 R， 对残差按需推导源码引理扩大
  E，直到 T=(R∩T)∪E。未指定目标由 tg-plan 默认 T=D。

  '
---

# tg-solve

Solve 只执行 `tg-plan` 已批准的 `target_set.yaml`，不得自行扩大目标。

```text
precheck(target hash / UO snapshot)
  → oracle
  → ledger
  → search
  → residual
  → construct / lemma*
  → audit
  → certify
```

`lemma*`：leads → evidence → mine → review → apply → loop。

## 核心不变量

- `T ⊆ D`，T 来自 approved Plan；
- `R` 只由真实 Host replay 增长；
- `E` 只由有源码证据、经过反例检查和 referee 的 lemma 增长；
- `R ∩ E = ∅`；
- 完成条件是 `T = (R ∩ T) ∪ E`；
- Host 额外命中 `D-T` 可以记录为 corpus/witness，但不能扩大本次完成范围；
- “没找到 witness”永远不等于“不可达”。

## 求解策略

优先复用已有 constructor/generator/replay：最近 witness → 差异维度 → UO 查询 producer/all-writes/guards → 构造候选 → Host 裁决。只有重复失败或 residual 指向稳定耦合时，才进入局部 source-lemma 推理。

默认 full TilingKey mode **不运行 19 维联合 Z3 / KeyReachability**。`z3_solve` 仅保留给 `csv_consumer` 兼容模式，不属于本流程主线。

领域规则：`skills/domain/tg-closure/SKILL.md`；源码不可达证明：`skills/domain/source-lemma-proof/SKILL.md`。

## 执行强制规则

1. Host/search 后必须跑 residual 产出 round_analysis，才允许下一轮 construct
2. 连续 2 轮 new_R=0 且 rewrite 主导 → NEED_LEMMA，禁止继续狂搜
3. SEARCH_STALLED + leads → lemma 相位，不是再 search
4. lemma_mine 必须写出 P⇒Q + CodeMap 锚点 + 义务 + PROVED/REFUTED/INSUFFICIENT；空 candidates 不得 lemma_apply
5. E 只经 referee accepted 后 promote；explain 失败不算 E 证据
6. construct hook 只是 knob 实现；CodeMap 主路径与 trace.yaml 必须保留
7. 历史 guard 家族仅作假设提示，禁止直接抄旧证书

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
| `lemma_verify` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-solve/lemma-verify` | `-` | `-` |
| `lemma_review` | `subagent` | `tg-closure-referee` | `referee` | `tg-solve/lemma-review` | `tg/lemma-review` | `lemma-review-v1` |
| `lemma_apply` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-solve/lemma-apply` | `-` | `lemma-apply-v1` |
| `lemma_loop` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-solve/lemma-loop` | `-` | `lemma-loop-v1` |
| `closure_audit` | `subagent` | `tg-closure-referee` | `referee` | `tg-solve/closure-audit` | `tg/closure-audit` | `closure-audit-v1` |
| `closure_certify` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-solve/closure-certify` | `-` | `closure-certify-v1` |
| `z3_solve` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-solve/z3-solve` | `-` | `z3-solve-v1` |
| `cover_confirm` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-solve/cover-confirm` | `-` | `cover-confirm-v1` |

<!-- END GENERATED ACTIONS -->
