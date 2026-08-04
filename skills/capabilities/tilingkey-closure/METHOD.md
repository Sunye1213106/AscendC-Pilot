# TilingKey 全覆盖闭环

## Purpose

把 FlashAttentionScoreGrad arch35 已跑通的闭环方法论固化为 **共享 capability**，供 `tg-solve` 的 closure actions 引用。禁止在单个 Action prompt 里复制一套证据规则。

权威文档：`docs/workflows/tilingkey-closure-agent.md`、`docs/fag/tilingkey-closure-report.md`。

## 权威与不变量

```text
D  从当前 kernel TilingKey 声明展开（带 header hash）
R  只来自真实 Host verdict
E  只来自 SOUND_GRADES（source_lemma | solver_derived）且过反例检验
Corpus  Host 已裁决输入（裁决 ≠ 跑过）
Models  仅候选生成与排序
RuleBook  lead → candidate → reviewed → active → (refuted → revoked)
```

每步检查：

1. `R ∩ E = ∅`
2. R 只能由真实 witness 增长
3. 模型结果不得进入 E
4. E 中每条规则有源码证据
5. 每条规则通过全部现有 witness 反例检验
6. `D = (R ∩ D) ∪ E` 才允许 certify

## Use When

- `tg-init` mode = `tilingkey_full_coverage`
- 执行 `closure_*` / `lemma_*` / `oracle_probe` / `closure_certify`

## Method（Agent 主循环）

```text
gate → oracle → ledger → search_round → residual_route
  ├─ SEARCH_PROGRESS → search_round
  ├─ CONSTRUCT_TARGETS → construct → explain → residual_route
  ├─ NEED_LEMMA → lemma_leads → lemma_mine → lemma_review → lemma_apply → ledger
  ├─ ORACLE_SUSPECT → escalate / human_required
  └─ GAP_ZERO → closure_audit → closure_certify
```

### search_round（有界，不在单 action 内无限循环）

`corpus_sync → dedup → assess → fit/refit(仅 fingerprint 变) → pool → rank → random_control_arm → replay → verdict_filter → corpus_commit → ledger → progress`

饱和判据：连续 N 轮 `new_R==0` **且** 残差距离分布无改善。

### assess 三数解读（FAG 实测校准；阈值非通用常量，但方向通用）

对每个难节点同时报 `majority` / `static` / `all_knob`（外推另计）：

| 关系 | 下一步 |
|---|---|
| `all_knob − majority < 0.02` | 该粒度下不是输入的函数 → 停拟合，转源码证明 |
| `all_knob − static > 0.05` | 静态丢了父节点 → 写 `uo_parent_gap_candidates`（observation_only） |
| `static ≈ all_knob ≫ majority` | 骨架可用，可反推输入 |

FAG arch35 对照：模型定向相对同池随机约 **11×** 单位产出且两臂 Key 零重叠；从 witness 变异后接受率约 **10% → 80~88%**；`mutate_share` 默认 **0.65**（探索臂用 0）。这些是校准值，不是硬门禁。

### Corpus 准入

只进 `Result.verdict == true`（Host 接受或明确拒绝）。排除：`HOST_CRASHED` / `NOT_RUN` / 截断未跑 / 超时 / 解析失败。

### 写回分层

| 层 | 路径 |
|---|---|
| Corpus | `tg/closure/corpus/**` |
| Models | `tg/closure/models/**` |
| Active lemmas | `tg/closure/lemmas/active_rules.yaml` |
| 静态父节点缺口观测 | `tg/feedback/uo_parent_gap_candidates.yaml`（observation_only，交 uo-update） |

## Hard Constraints

- MUST NOT：用模型准确率、统计共现、「跑了很多次没出现」排除 Key。
- MUST NOT：producer 直接写 `excluded.txt` / active RuleBook。
- MUST NOT：继承 `proof_rules.yaml` 为 active；只能作 seed_candidates，重走审查+反例。
- MUST：`R − D` 单独报 undeclared-key defect，不计入 D 闭合。
- MUST：新 witness 反驳规则时 **撤销并重新开账**，不得 gate 报错后死锁。

## Roles

- deterministic engine：ledger / search / residual / construct / explain / lemma_apply / certify
- producer（`tg-lemma-producer`）：只写 staging parts
- referee（`tg-closure-referee`）：`lemma_review` + `closure_audit` 只写 review.yaml

引理证明纪律见同目录 `LEMMA.md` 与 `PROOF.md`。
Oracle / 观测纪律见同目录 `ORACLE.md`。
