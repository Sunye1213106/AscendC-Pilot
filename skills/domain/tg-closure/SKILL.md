---
name: tg-closure
description: >
  基于 approved target set 的 TilingKey 闭环方法：真实 Host witness 增长 R，源码引理增长 E，
  构造/搜索与局部证明交替，直到目标 T 闭合；不描述 Pilot 编排。
---

# TilingKey Target Closure

集合：

- `D`：Kernel 当前声明的全部 legal Key；
- `T`：tg-plan 批准的目标，`T ⊆ D`，默认 `T=D`；L3 时 T 的元素是 `(key, site, outcome)`；
- `R`：真实 Host replay 产生过的 Key（或 L3 下经 TD dump + `branch_eval` 见证的 outcome）；
- `E`：对 T 中元素的源码证明不可达集（含字段 pin → `key_determined`）。

完成条件：

```text
T = (R ∩ T) ∪ E
R ∩ E = ∅
```

## L3：分支结局闭环（复用本相位机）

不另开 td-init/td-solve。Plan level=`L3` 或 mode=`branch_outcome_coverage`：

1. UO 提供 steerable BRANCH + tilingdata `value_defining_sites`（含 `guards` / `caller_guards`）；
2. Host replay dump TD → decode → `closure.branch_eval` / `branch_outcome.close_key` 增长 R；
3. Lemma 字段 pin（`field_pins.load_pinned`）使条件 `key_determined` → 对侧 outcome 入 E；
4. 浅 writer 不得单独入 E（见 `code-access` / `evidence`）。

## Key ↔ Data 耦合复用（`closure.key_data_coupling`）

TilingKey 闭环的产出不是一次性的，三处可直接折算成 TilingData / 分支闭环的进度：

| 复用 | 机制 | 纪律 |
|---|---|---|
| **同根 pin 线索** | key 维打包表达式（`packing_value_sites`）与字段守卫（`guards`/`caller_guards`）共享 host 状态 → `derive_pin_leads` 产出候选 | 只产 **LEAD**：仍需 `dim_value_implies_all_guards_false` + 源码窗口 + referee + 对 R 反证，才能入 E |
| **免费见证** | key 搜索的 replay 已经产出该 key 的 TilingData；`REPLAY_DUMP_TD` 默认开，`harvest_td_observations` 从同一批日志收割 | 观测只增长 R，不改变 T |
| **继承不可达** | key 入 E ⇒ 其 per-key 分支/字段义务子树整体消失（`prune_outcomes_by_e_keys`） | E 的来源仍是 key 的原证明，不新增断言 |

反例边界：某 outcome 若**没有**共享根的 key 维（如需要新可选输入才能触发），耦合不会给线索——那是必须 **construct**（R）而非 lemma（E）的信号。

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

## round_analysis 与 guard-family leads

- `closure_residual` 必须写入 `tg/closure/round_analysis.yaml` 与 `round_analysis.stamp`；`closure_construct` 在 stamp 缺失或 corpus 比 analysis 新时拒绝执行（可用 `TG_SKIP_ANALYSIS_GATE=1` 绕过测试）。
- `lemma_leads` 按 guard **家族**聚类（kind + mismatch + rewrite + reject_family），`when` 为成员交集；`instances` 保留具体 when 供 mine 引用，禁止把历史 guard 证书直接当 E。
