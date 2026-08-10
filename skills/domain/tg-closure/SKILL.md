---
name: tg-closure
description: >
  基于 approved target set 的 TilingKey 闭环方法：真实 Host witness 增长 R，源码引理增长 E，
  构造/搜索与局部证明交替，直到目标 T 闭合；不描述 Pilot 编排。
---

# TilingKey Target Closure

集合：

- `D`：Kernel 当前声明的全部 legal Key；
- `T`：tg-plan 批准的目标，`T ⊆ D`，默认 `T=D`；
- `R`：真实 Host replay 产生过的 Key，可包含 T 外的真实 witness；
- `E`：对 T 中 Key 的源码证明不可达集。

完成条件：

```text
T = (R ∩ T) ∪ E
R ∩ E = ∅
```

## 核心循环

```text
approved T
  → oracle
  → rebuild R from raw replay
  → search / construct against open(T)
  → Host verdict
     ├─ HIT      → R
     ├─ REWRITE  → residual / explain
     ├─ REFUSE   → residual / explain
     └─ CRASH/NOT_RUN → oracle/tool issue, never E
  → repeated stable residual
     → query UO producer/all-writes/guards/source
     → source lemma candidate
     → counterexample check against all real R
     → referee
     → E
  → certify T
```

## 纪律

- 预测、统计模型、Z3-approx、长期未命中都只能帮助**生成/排序**，不能进入 E。
- Lemma 必须有源码引用，并检查入口分支、early return、all writers、execution order、exception branches。
- 任何真实 witness 推翻 lemma 时立即撤销该 rule 并重建 E。
- Solve 不因额外命中 `D-T` 而扩大 T；它们可进入 Corpus/R，下一次 Plan 可以选择复用。
- 需要改变 T 时回到 tg-plan，不在 tg-solve 内改计划。

## UO 的使用方式

UO（CodeMap `.uo`）提供结构证据，不提供全局 19 维 closed-form：Key producer、Host CALLS/READS/WRITES、all writes、guards、TilingData flow、Template/Kernel、source span。

查代码纪律：**先 `CodeMapQuery`，再最小源码窗口验证**。定向构造主路径是
`dim → packing → producer/guards → reads → knobs → Case`；`construction_hints` 仅兜底。
「没找到 hint」≠ 不可达。

安全不变量：`references/closure-safety.md`；搜索/构造：`references/search.md`；oracle：`references/oracle.md`；签发：`references/certificate.md`。
