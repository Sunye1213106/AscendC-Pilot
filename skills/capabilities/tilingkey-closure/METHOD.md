# TilingKey 全覆盖闭环

## Purpose

把 FlashAttentionScoreGrad arch35 已跑通的闭环方法论固化为 **共享 capability**，供 `tg-solve` 的 closure actions 引用。禁止在单个 Action prompt 里复制一套证据规则。

权威文档：`docs/design/tilingkey-closure-agent.md`、`docs/fag/tilingkey-closure-report.md`。

## 权威与不变量

```text
D  从当前 kernel TilingKey 声明展开（带 header hash）
R  只来自真实 Host verdict（命中目标 key）
E  只来自 SOUND_GRADES（source_lemma | solver_derived）且过反例检验
Corpus  Host 已裁决输入（命中 / 拒绝 / 改写 均可入观测）
Models  仅候选生成与排序
RuleBook  lead → candidate → reviewed → active → (refuted → revoked)
```

每步检查：

1. `R ∩ E = ∅`
2. R 只能由真实 witness 增长
3. 模型结果、统计共现、`construct_reasons` **不得**进入 E
4. E 中每条规则有源码证据，且由**构造→回放结果**触发追查
5. 每条规则通过全部现有 witness 反例检验
6. `D = (R ∩ D) ∪ E` 才允许 certify

## Use When

- `tg-init` mode = `tilingkey_full_coverage`
- 执行 `closure_*` / `lemma_*` / `oracle_probe` / `closure_certify`

## Method（Agent 主循环）

```text
gate → oracle → ledger → construct/search → replay → classify
  ├─ HIT（key ∈ open）     → commit R → residual_route
  ├─ REWRITE（key≠target） → 记观测；agent 查源码为何改写 → lemma 候选
  ├─ REFUSE / FAIL         → 记观测；agent 查源码为何拒绝 → lemma 候选
  ├─ SEARCH_PROGRESS       → 继续 construct/search-round
  ├─ NEED_LEMMA            → lemma_leads → lemma_mine → lemma_review → lemma_apply
  ├─ ORACLE_SUSPECT        → escalate / human_required
  └─ GAP_ZERO              → closure_audit → closure_certify
```

### 构造→回放→分类（引理的唯一合法起点）

对每个 open target：

1. **构造**：`construct` / `generate` 必须给出 best-effort case。  
   `construct_reasons` 只是改写风险**诊断假设**，**禁止**因此返回空、禁止据此写 E。
2. **回放**：Host oracle 给出 hit / refuse / rewrite / crash。
3. **分类**：
   - hit → 进 R
   - rewrite（要的维 → 给的维）→ 观测包，供 agent 溯源
   - refuse/fail（非 crash）→ 观测包，供 agent 溯源
4. **证明**：agent 读源码，解释为何被拒绝或被改写；填满 LEMMA/PROOF 清单后才可进 staging。

饱和判据：连续 N 轮对剩余 open **已构造且已回放** 仍无新 R，且残差不再改善 → 才进入 `NEED_LEMMA`（基于上述失败/改写观测，而不是“构造器先验拒采”）。

### assess 三数解读（FAG 实测校准；数值非通用常量）

对每个难节点同时报 `majority` / `static` / `all_knob`（外推另计）：

| 关系 | 下一步 |
|---|---|
| `all_knob − majority < 0.02` | 该粒度下不是输入的函数 → 停拟合，转「构造+回放+源码证明」 |
| `all_knob − static > 0.05` | 静态丢了父节点 → 写 `uo_parent_gap_candidates`（observation_only） |
| `static ≈ all_knob ≫ majority` | 骨架可用，可反推输入再构造 |

### Corpus 准入

- 进 R：仅 `verdict` 给出的 **declared key 命中**。
- 进观测（供 lemma）：拒绝原因、改写前后维、稳定「要的→给的」统计。
- 排除：`HOST_CRASHED` / `NOT_RUN` / 截断 / 超时 / 解析失败（先修 oracle）。

### 写回分层

| 层 | 路径 |
|---|---|
| Corpus | `tg/closure/corpus/**` |
| Models | `tg/closure/models/**` |
| Active lemmas | `tg/closure/lemmas/active_rules.yaml` |
| 构造/回放观测 | `tg/closure/construct/**`、`explain` 产物 |
| 静态父节点缺口观测 | `tg/feedback/uo_parent_gap_candidates.yaml`（observation_only） |

## Hard Constraints

- MUST NOT：用模型准确率、统计共现、「跑了很多次没出现」排除 Key。
- MUST NOT：用 `construct_reasons` / 构造器空返回 / pair-mine 单独晋升 E。
- MUST NOT：producer 直接写 `excluded.txt` / active RuleBook。
- MUST NOT：继承 `proof_rules.yaml` 为 active；只能作 seed_candidates，重走审查+反例。
- MUST：先构造再回放；无 oracle 结果不得声称不可达。
- MUST：`R − D` 单独报 undeclared-key defect，不计入 D 闭合。
- MUST：新 witness 反驳规则时 **撤销并重新开账**，不得 gate 报错后死锁。

## Roles

- deterministic engine：ledger / search / residual / construct / explain / lemma_apply / certify
- producer（`tg-lemma-producer`）：只写 staging parts（基于失败/改写观测 + 源码）
- referee（`tg-closure-referee`）：`lemma_review` + `closure_audit` 只写 review.yaml

引理证明纪律见同目录 `LEMMA.md` 与 `PROOF.md`。  
Oracle / 观测纪律见同目录 `ORACLE.md`。
