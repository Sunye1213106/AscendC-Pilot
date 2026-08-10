---
name: tg-solve
description: >
  执行已批准 TG Plan：对 target set T 构造/replay case，用真实 Host witness 扩大 R，
  对残差按需推导源码引理扩大 E，直到 T=(R∩T)∪E。未指定目标由 tg-plan 默认 T=D。
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

`lemma*`：leads → evidence → mine → review → apply。

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
