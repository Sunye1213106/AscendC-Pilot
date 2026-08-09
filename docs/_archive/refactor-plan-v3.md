# AscendC-Pilot 重构方案 v3：把闭环变成 `tg-solve`

本版的主设计依据是[TilingKey 全覆盖闭环方法论](../workflows/tilingkey-closure-agent.md)和[实际闭合报告](../fag/tilingkey-closure-report.md)——不是"参考文档"，是**规格书**。FAG arch35 上 8705 个声明 Key 判定完毕（R=4227、E=4536、gap=0）的那次过程里，每一个起作用的机制都必须在产品结构里找到对应物；文档里没有的东西不要加。

**一句话结论**：engine 零件已经落了七成，但文档里真正跑通的那条**「学习—运行—反例回流—重训—构造—引理证明—重新开账」**闭环，一行都没有进 `tg-solve`。现在的形态是"工具箱有了"，不是"Agent 能反复执行的方法"。

因此 `tg-solve` 的定义要改写：

> 从「求解一次覆盖计划」改成：**维护 `(D, R, E, Corpus, Models, RuleBook)`，靠真实 Host 裁决持续学习，靠源码证明持续缩小 open set，在证据失效或出现反例时自动撤销结论，直到拿到可审计的 gap=0 certificate。**

---

## 0. 与 v2 的差异

v2 把重点放在 codemap schema 和控制面权限上。那个方向没错，但它没有表达闭环里最关键的东西：语料更新、模型重训触发、按 round 的搜索、反例解释、规则撤销、harness 缺口升级。v2 的 `ledger → search → residual → lemma → apply → audit → certify` 方向对，但太粗——真实过程根本不是"阶段 4 全做完再阶段 6"，而是：

```text
R 增长 → 发现新反例 → 修正或撤销引理 → E 增长 → gap 缩小 → 再定向搜索
```

报告第 5 节的账本演进印证了这一点：E 有三次跃升（0→3632、3968→4344、4344→4536），分别来自"重推继承规则"、"三元挖掘"、"运行时反例定位"——三条不同的推导路径，交替插在推 R 的过程中间。

同时 v2 里有四项**已经做完了**，本版不再列入：

| v2 条目 | 现状 |
| --- | --- |
| P0 沉淀 `.probe_cache/vg_*.py` | 已完成。仓库里 `vg_*.py` 数量为 0，能力已进 `testcase_agent/closure/`（14 个模块） |
| P2 codemap v2 schema | 已完成。`host_codemap.py:25-27` 已是 `codemap/v2`，顶层为 `fields/predicates/declared_keys/platform_gates`，`calls`/`functions` 已删 |
| 新增 `scikit-learn` 依赖 | 已完成。`engines/testcase-generation/pyproject.toml` 已声明 `scikit-learn>=1.3` |
| P5 CE 引擎从零建 | 已起步。`engines/code-engineering/code_engineering/` 包已存在，不再是只有 README |

**注意**：codemap 的问题已经不是 schema，而是**出处**——它到底是不是 KB 的派生。这是本版 P0-1。

---

## 1. 现状核查（实测）

### 1.1 engine 零件：约七成

| 文档阶段 | 当前实现 | 状态 |
| --- | --- | --- |
| 阶段 0 oracle | `scripts/replay/runner.py`、`closure/workspace.py:replay_runner()` | 基础设施在，缺正式 oracle gate |
| 阶段 1 账本 | `closure/ledger.py`（195 行） | 已实现 |
| 阶段 2 静态骨架 | UO derivation + `host_codemap.yaml` | 已实现 |
| 阶段 3 代理模型 | `closure/corpus.py`、`features.py`、`models.py` | 已实现，**无持久化** |
| 阶段 4 定向生成 | `closure/generate.py`（294 行） | 候选池在，**search/refit 循环不在** |
| 阶段 5 构造式收尾 | `closure/construct.py`、`explain.py` | 已实现，**未编排** |
| 阶段 6 引理封口 | `closure/mine.py`、`lemma.py`、`scripts/replay/rule_engine.py`、`report.py` | 部分实现，**缺源码证明 Agent 与审查前置** |

`models.py:119-174` 的 `assess` 已经如实报四个数（`majority` / `static` / `all_knob` / `extrapolated`），和文档第 2 节的表格口径一致——静态父节点是否够用这件事，代码已经能自己回答。`corpus.py` 已经会修历史宽表的 tag 逗号错位、按真实输入去重、区分 accepted/refused。`explain.py` 会真跑 replay 并统计"Host 坚持替换哪一维"，这正是 fp32 大 D 引理的发现路径。

**零件是够的，缺的是调度。** 佐证：`models.fit` 在整个仓库里零外部引用；`generate.pool` / `construct.build` 没有任何 CLI 或编排器调用。

closure CLI 今天只有 8 个子命令：

```text
rebuild  apply-rules  report  residual  mine  state  assess  corpus
```

没有 `fit` / `generate` / `replay` / `commit` / `refit` / `construct` / `explain` / `route`，也没有 `run-round`。

### 1.2 四个结构性缺口

#### P0-1 Codemap 与 KB 是两套平行权威

`kb_export.py:1-7` 明确写了 YAML 图是唯一真源、SQLite 是可丢弃派生；`manifest.yaml` 里写 `authority: yaml`。但 `host_codemap.py:1` 的第一句是：

```python
"""Persist HostIR as a queryable codemap (YAML authority + SQLite index)."""
```

它把自己也声明成 authority，且**不读** `ir/operator_graph.yaml`——输入是 HostIR 或 `.probe_cache/fag_bundle.pkl`。结果是同一个字段的 roots / exactness / predicate 在 KB 和 codemap 里可能不一致，而 `uo-update` 更新 KB 之后 codemap 仍是旧的，consumer 看不出来。

**今天不存在任何 KB 图 ↔ codemap 的指纹校验**：`kb_index.py:94-97` 会把 `graph_fingerprint` 写进 sqlite 的 `meta` 表，但 `host_codemap.yaml` 里没有这个字段，也没有任何代码比较过两者。

更硬的一处：v2 计划里"`uo-init` 新增 `export_codemap`，复用 `TK_ENGINES.export_codemap`"这条**不能直接做**。`tk_cover_engines.py:132-173` 的输入顺序是：

```text
1. 已存在的 uo/ir/host_codemap.yaml（且未 force）→ 直接 reuse
2. ctx["bundle"] 指定的 pickle
3. {project_root}/.probe_cache/fag_bundle.pkl
4. 都没有 → 报错
```

而 `pilot_engines.py:195-227` 的 `prepare_layout` 会 `shutil.rmtree` 掉 `ir/` 和 `indexes/`。所以一次真正的 fresh init 里：旧 codemap 被删了、`fag_bundle.pkl` 不一定在、`export_kb` 刚生成的新 KB 它又不读——**要么失败，要么偷偷复用旧 probe 产物**。

#### P0-2 全量模式仍被 CSV consumer 卡在 `tg-init`

`actions/engines.py:333-343` 的 `_require_consumer_root` 被这些 action 调用：

| Workflow | Action | 要 consumer |
| --- | --- | --- |
| `tg-init` | `contract_build` | 是（engines.py:352） |
| `tg-init` | `semantic_bind` | 是（engines.py:393） |
| `tg-plan` | `plan_scope` / `plan_build` | 是（492 / 532） |
| `tg-solve` | `solve_precheck` / `z3_solve` | 是（571 / 587） |

v2 只说"`tilingkey_full` 时 `plan_scope` / `solve_precheck` 可跳过 consumer"，不够——**`contract_build` 自己就要 consumer**。而当前流程里 `plan_intent` 要到 `tg-plan` 才生成，执行 `tg-init` 时根本还不知道后面是全量 TilingKey 还是 CSV consumer。所以"默认全量"写在 `tg-plan` 里没用，前面的 `tg-init` 先跑不起来。

#### P0-3 `E` 实际接受所有 grade 的规则

`scripts/replay/rule_engine.py:21-23` 已经正确定义了等级白名单：

```python
# Grades that may shrink the sound upper bound U_sound. Human/LLM rules are
# reviewed evidence only until separately checked; they must not default into U.
SOUND_GRADES = frozenset({"solver_derived", "source_lemma"})
```

`RuleBook` 也同时提供了 `excluded_by(inst, grades=None)` 和 `excluded_by_sound(inst)`。但正式写 E 的那一行用的是前者：

```python
# closure/lemma.py:103 —— 函数 docstring 写的是 "write E_sound"
labels = book.excluded_by(inst)
```

`report.py:42` 同样。**整个 closure 包里 `excluded_by_sound` 和 `SOUND_GRADES` 的调用次数是 0。** 也就是 human / llm 等级的规则今天可以直接进 E。

`apply_rules` 确实有 `R ∩ E = ∅` 的反例门禁（`lemma.py:107-117`），历史上真拦下过一条会误杀 512 个 key 的规则。但那只能证明"当前 replay 没找到反例"，不能证明规则由源码成立——这正是单边原则要防的那种"假 100%"。

顺带，v2 提的执行顺序 `lemma_mine → lemma_apply → lemma_audit` 与"producer 不得直接进入 E"的 policy 自相矛盾，必须拆开（见第 5 节）。

#### P0-4 closure core 仍与 FAG input model 耦合

```python
# closure/generate.py:214-226
NEAREST_KNOBS = {
    "DTemplateNum": [("d", [64, 128, 192, 256, 512])],
    "IsDrop": [("keep_prob", [1.0, 0.5])],
    "IsAttenMask": [("atten_mask", ["none", "ss", "bnss", "b1ss", "11ss"])],
    "DeterType": [("deterministic", [0, 1]), ("sparse_mode", [0, 1, 2, 3, 4, 5, 6])],
    ...
}

# closure/construct.py:18-30
DTYPE   = {"1": "FLOAT", "2": "BF16", "3": "FLOAT16"}
D_FOR   = {"64": [64, 63], "128": [128, 96, 72], ..., "768": [320, 512, 384, 768]}
DETER_FOR = {"0": [(0, 0), (0, 2), (0, 3)], "1": [(1, 6), (1, 5)], ...}
S1_FOR  = {"128": [1024, 2048, 512, 256], "64": [256, 2048, 1024], "0": [0]}
```

`generate.DEFAULT_GRID`、`features.STATIC_PARENTS` 同理。`construct.build()` 直接按名字读 15 个 FAG 维度。这些都是算子知识，不该留在通用 engine 里。

### 1.3 语料准入没有把关

`corpus.py:133-134` 的准入判据是：

```python
def accepted(df): return df[df.ok == 1]
```

它不看 `Result.verdict`（定义在 `scripts/replay/runner.py:55-58`），也不看 `HOST_CRASHED` / `NOT_RUN` 前缀。R 侧只认 `ok==1` 所以崩溃不会污染 R，但**崩溃和没跑到的行会以 `ok=0` 进 corpus 当负样本**，直接污染 `__accept__` 模型——教它躲开完全正常的输入。

报告 §3.3 已经证明这不是小概率事件：driver 崩溃后批次静默截断，一批 1500 个用例只跑了 249，其余 1251 个被记成"拒绝"。

---

## 2. 权威与不变量

这一段是所有 closure action 共享的前提，必须写在 Skill 开头，不靠人记。

```text
D        从当前 kernel TilingKey 声明重新展开，带 header hash
R        只来自真实 Host verdict
E        只来自经过源码证明 + 全量反例检验的规则
Corpus   Host 已裁决的输入记录（裁决 ≠ 跑过）
Models   仅用于候选生成和排序
RuleBook 候选、审查、激活、撤销都有状态
```

每步之后检查：

```text
I1  R ∩ E = ∅
I2  R 只能由真实 witness 增长
I3  模型结果不得进入 E
I4  E 中每条规则必须有源码证据
I5  每条规则必须通过全部现有 witness 的反例检验
I6  D = (R ∩ D) ∪ E 时才允许完成
```

方法论文档说得很直白：**"跑了很多次没出现"不是不可达证明**。代理模型只允许生成和排序。

---

## 3. Agent 状态与落盘

状态不只是三个集合：

```text
ClosureState = {
  D, R, E,
  Corpus, ModelRevision, RuleBook, Open,
  SearchHistory, ResidualHistory,
  OracleStatus, SourceFingerprint, UoGraphFingerprint
}
```

落盘布局（沿用现有 `.ascendc-pilot/tg/closure/`，由 `workspace.py:94-97` 定义，`TG_CLOSURE_STATE` 可覆盖）：

```text
.ascendc-pilot/tg/closure/
├── state.yaml                  # 上面这个结构的当前快照
├── R.txt  excluded.txt  excluded_why.csv  open.txt  closure.csv
├── corpus/{manifest.yaml, verdicts.csv}
├── models/{manifest.yaml, assessment.yaml, model.*}
├── rounds/round_0001/{targets.yaml, candidates.csv, replay_results.csv,
│                     corpus_delta.yaml, progress.yaml}
├── residual/{current.csv, history.yaml}
└── lemmas/{leads.yaml, candidates.yaml, reviews.yaml,
           active_rules.yaml, revoked_rules.yaml}
```

前两行今天已经有了，`rounds/` `models/` `corpus/` `lemmas/` 是新增。

---

## 4. `tg-solve` 状态机

现在的正式定义还是老路径（`specs.py:1041-1115`）：

```text
gate → encode → solve → project → cover
solve_precheck → z3_solve → cover_confirm
```

改成：

```text
gate → oracle → ledger → search → residual
```

由 `closure_residual` 做确定性路由，输出 reason code：

```text
                         ┌───────────────┐
                         │ closure_search│◀──────────┐
                         └───────┬───────┘           │
                                 ▼                   │ SEARCH_PROGRESS
gate → oracle → ledger → closure_residual ───────────┘
                         │       │       │
                         │       │       └─ GAP_ZERO
                         │       │             ↓
                         │       │        closure_audit → closure_certify
                         │       │
                         │       └─ CONSTRUCT_TARGETS
                         │               ↓
                         │        closure_construct → closure_explain
                         │               ↓
                         │        closure_residual
                         │
                         └─ NEED_LEMMA
                                 ↓
                    lemma_leads → lemma_mine → lemma_review
                                 ↓
                    lemma_apply → closure_ledger → closure_residual
```

oracle / harness 出问题时：

```text
closure_residual → closure_escalate → blocked / human_required
```

reason code 集合：`GAP_ZERO` / `SEARCH_PROGRESS` / `SEARCH_STALLED` / `CONSTRUCT_TARGETS` / `NEED_LEMMA` / `PROOF_BLOCKED` / `ORACLE_SUSPECT`。

### Actions 与角色

按仓库现有的三类角色（`ownership.py`、`authorize/__init__.py:263-271`）分配：

| 类别 | Actions | 写路径 |
| --- | --- | --- |
| deterministic engine | `solve_precheck` `oracle_probe` `closure_ledger` `closure_search` `closure_residual` `closure_construct` `closure_explain` `lemma_leads` `lemma_apply` `closure_certify` | 正式产物 |
| producer | `lemma_mine` | 只写 `runs/<run_id>/actions/lemma_mine/parts/**` + `staging.yaml` |
| referee | `lemma_review` `closure_audit` | 只写 `runs/<run_id>/actions/<action>/review.yaml` |

正式写入 `R.txt` / `excluded.txt` / `lemmas/active_rules.yaml` / `open.txt` / `closure.csv` 的**只有 deterministic engine**。这套 staged producer + merge finalizer 的机制仓库里已经有了（`specs.py:29-123` 的 `_act`、`workflows/consistency.py:100-143` 的 Mode B），照搬即可。

`lemma_review` 和 `closure_audit` 是两个不同概念：前者是规则**写入 E 之前**的资格审查，后者是规则应用**之后**的整体不变量审查。v2 只有后者。

---

## 5. `closure_search`：一个有界 round

这是当前方案缺失最明显的部分。`closure_search` 每次只执行**一个 round**，不在单个 action 内无限循环——循环由状态机的 `SEARCH_PROGRESS` 回边驱动，这样每一轮都留下可审计的 receipt。

round 内部：

```text
corpus_sync → corpus_dedup → model_assess → model_fit/refit
→ candidate_pool → model_rank → random_control_arm
→ oracle_replay → verdict_filter → corpus_commit
→ ledger_rebuild → progress_report
```

### 5.1 什么时候重训

不要每轮无条件训练。定义指纹：

```text
corpus_fingerprint = hash(所有已裁决输入, feature_schema,
                          input_semantics_version, oracle_protocol_version)
```

模型 manifest（今天完全没有，`models.py` 不落盘任何东西）：

```yaml
schema: tg-surrogate-model/v1
corpus_fingerprint: ...
feature_schema_hash: ...
uo_graph_fingerprint: ...
source_revision: ...
seed: 0
metrics:
  SplitAxis:  {majority: 0.862, static: 0.971, all_knob: 0.971,
               extrapolated: 0.96, verdict: skeleton_usable}
  DeterType:  {majority: 0.450, static: 0.668, all_knob: 0.984,
               extrapolated: 0.94, verdict: static_parent_gap}
```

只有 `corpus_fingerprint`、feature schema 或 UO static-parent projection 变了才 refit。metrics 直接复用 `models.assess` 已有的四个数。

### 5.2 什么能进 Corpus

只能进 `Result.verdict == True` 的行，即：

```text
✓ Host 接受并返回 Key
✓ Host 明确拒绝并给出拒绝原因
✗ HOST_CRASHED
✗ NOT_RUN
✗ 批次截断后未实际执行
✗ runner 自己超时
✗ 结果解析失败
```

这要求 `corpus.accepted` 改掉 `df.ok == 1` 的单一判据，改读 `reject` 前缀。同时新增 `oracle_probe` 和 `verdict_integrity`——**不能默认 replay runner 可信**。报告 §3.1/§3.3/§3.4 记了三个 oracle 层面的缺陷（宽表引号 bug 让账本少算 150 个 Key、批次静默截断、`npuArch` 漏填让一整条分支不可达），任何一个都会让结论失真。

### 5.3 什么时候停

不能写死"跑三轮"。判据是：

```yaml
search_saturation:
  zero_gain_rounds: 2                      # 连续 N 轮 new_R == 0
  distance_histogram_unchanged_rounds: 2   # 且残差距离分布没有改善
  min_judged_cases_per_round: 100          # 每轮至少这么多被裁决的用例
```

两条同时满足才从 `search` 转向 `construct` 或 `lemma`。反过来，如果引理挖掘找不到有支撑的候选，说明该回去推 R。

### 5.4 A/B control arm 是必须的

文档实测：模型定向相对同池随机是 **11 倍**单位产出，且两臂找到的 Key 零重叠。没有 control arm 就无法区分"模型有用"和"多跑了几批"。每轮 `progress.yaml` 必须写：

```yaml
model_arm:  {judged: 248, new_declared_keys: 84, yield: 0.3387}
random_arm: {judged: 405, new_declared_keys: 12, yield: 0.0296}
model_lift: 11.44
```

模型退化时 Agent 才知道该重训、补 feature、补静态父节点，还是停止拟合转源码分析。

---

## 6. `closure_construct` 与 `closure_explain`

阶段 5 不是备用脚本，它是从"搜索"切到"证明"的桥，必须正式进状态机。

```text
open key → 找最近 witness → 确定差异维度
→ 只修改影响锥内的 knobs（走 CodemapQuery.reads_of）
→ Host replay → 比较 wanted dims 与 actual dims
```

三种结果对应三条出路：

| 结果 | 动作 |
| --- | --- |
| 命中目标 Key | R 增长 |
| Host 接受但稳定替换某维 | 生成 lemma lead（推导路径 C） |
| 全部被拒绝 / 路径从未触达 | 判定 input semantics 或 harness 缺口 → `closure_escalate` |

第二条正是 fp32 大 D 引理的来源：720 个被接受的用例，Host 一律把 `S1TemplateNum` 从 128 压成 64，顺着这个现象查 `GetS1S2TemplateType` 第一个分支，一条引理关掉 192 个 Key。第三条来自最后一个 Key 的经历——`IsEmptyTensor=1` 一直产生不出来，根因是 driver 的 `compileInfo.npuArch` 漏填。**这类问题在数据上表现为"某取值永不出现"，极易被误判成不可达**，判据是：产生该取值的代码路径存在，但被环境配置挡住了。

---

## 7. 引理：从 lead 到 active，以及撤销

### 7.1 lead 是确定性生成的，不是模型发明的

`lemma_mine` 的输入必须是 `lemma_leads` 产出的封闭包，producer 不允许自己发明 lead：

```yaml
lead_id: LEAD_001
kind: triple
when: {SplitAxis: "5", IsDrop: "1", DTemplateNum: "768"}
open_keys_closed_if_true: 80
min_support: 214
runtime_observation:
  stable_substitution: {dim: DTemplateNum, asked: "768", got: "128", count: 96}
static_context:
  field_refs: [...]      # 回指 KB 节点
  predicate_refs: [...]
  def_sites: [...]
  all_write_sites: [...]  # 关键：全部赋值点，不只是第一处
```

三元组不能省。源码里的条件常是析取式 `(keepProb >= 1 || (d <= NUM128 && keepProb < 1))`，它不禁止任何一对维度，只禁止一个三元组，二元挖掘看不见。`mine.py` 今天已经同时产 `leads.csv` / `leads3.csv`，接线即可。

### 7.2 prompt 必须落实三条推导路径

| 路径 | 做法 | 例子 |
| --- | --- | --- |
| A 合取式直接证 | 读长合取的末尾项 | `isBn2MultiBlk` 末尾是 `(d == d1) && !hasRope`，与 `dNoEqual = (d1 != d) \|\| hasRope` 直接对偶 |
| B 全部赋值点 + 执行顺序 | 列全 write site、查 early return、查后续覆盖是否被 guard 排除 | `IsTnd + IsBn2MultiBlk` 要走三步，只看第一步会被第 1638 行推翻 |
| C 运行时稳定替换反查 | 从 `explain` 的替换统计回查该维的所有赋值点 | `S1TemplateNum` 想要 128、720 次都给 64 |

### 7.3 任何蕴含都要检查全部入口

写成硬规则，不留在经验文档里：

```text
对 A ⇒ B：
1. 找出 A 的所有构造入口
2. 找出相关函数的 early return
3. 找出分流调用
4. 找出 A / B 字段的全部赋值点
5. 检查后续覆盖
6. 检查例外分支
7. 最后才能形成证明
```

依据是文档 §6.5 那个真实的错误：「无 attenMask 时 DeterType 只能是 0/2」的初始理解是错的，因为 `SetSparseParams` **第一行**就分流，PREFIX(5)/PREFIX_COMPRESS(6) 会绕过 mask 判断并落到 `DETER_OLD = 1`。实际存在 261 个这样的 witness，照字面写会误杀。正确边界只能排除 3 和 4。

### 7.4 规则生命周期与撤销

```text
lead → candidate → source_supported → counterexample_checked → reviewed → active
                                                                    ↓
                                                          active → refuted → revoked
```

等级重新定义，**只有最后两级允许进入 E**：

```text
candidate                模型/统计发现，仅排序
replay_refuted           已被反例推翻
reviewed_hypothesis      有源码线索但未机械证明
source_lemma_verified    源码证明已通过        ← 可进 E
solver_unsat_verified    约束系统证明 UNSAT     ← 可进 E
```

`source_lemma_verified` 不能只要求一个非空 `reason` 字符串：

```yaml
id: LEMMA_0012
status: active
when: {IsAttenMask: "0", DeterType: "4"}
grade: source_lemma_verified
evidence_refs: [EV_0192, EV_0193]
proof:
  entry_branches_checked: true
  early_returns_checked: true
  all_writers_checked: true
  execution_order_checked: true
  exception_branches_checked: true
verification:
  witness_fingerprint: ...
  hit_count: 0
  verdict: pass
freshness:
  source_revision: abc123
  uo_graph_fingerprint: 8f...
```

**每次 Corpus 增长都要重验全部 active rules**：

```text
新 Host verdict → Corpus commit → R rebuild → 对全部 active rules 重跑反例检验
```

若 `new_R ∩ rule_excluded_keys ≠ ∅`：规则标 `refuted` → 从 active 撤销 → 重算 E → 对应 Key 回到 open → 记录反例 provenance。**不能只是让 gate 报错然后停在那里**——今天 `apply_rules` 撞到反例就直接返回 `ok: False` 不写任何东西，那是死锁不是撤销。

**继承规则不能直接 active**。`operators/<op>/<arch>/proof_rules.yaml` 在新的 source revision 下只能作为 `seed_candidates`，重走 `source evidence freshness → proof review → full witness check → active`。文档 §6.5 明确说明：本例继承的三组规则支撑着 3632 个排除，重推之后两组通过、一组的边界需要修正。

---

## 8. 学习结果写到哪一层

四层，不能全部写回 KB。

| 层 | 写到哪 | 理由 |
| --- | --- | --- |
| Runtime Corpus | `tg/closure/corpus/**` | Host 观测事实 |
| Surrogate Models | `tg/closure/models/**` | 模型不是语义权威，不进 UO KB |
| Verified Lemma | `tg/closure/lemmas/active_rules.yaml` | 引理**引用** UO evidence，不篡改 UO 抽取事实 |
| 静态骨架缺口 | `tg/feedback/uo_parent_gap_candidates.yaml` | 只是观测，交给 UO 去源码验证 |

第四层的触发条件是 `assess` 报出 `static << all_knob`：

```yaml
dim: DeterType
static_parents: [deterministic]
model_important_features: [sparse_mode, band, pre_tokens, next_tokens]
evidence: {corpus_fingerprint: ..., static_score: 0.668, all_knob_score: 0.984}
status: observation_only
```

由 `uo-update` / `uo-gap-resolve` 读取并验证源码，**不允许 TG 模型直接改 KB**。这样保持链路单向：

```text
运行数据发现问题 → UO 源码验证 → KB 更新 → TG projection 重建 → 模型重训
```

---

## 9. 失效与增量更新

| 变化 | 处理 |
| --- | --- |
| 新增已裁决 replay | 更新 Corpus、R；模型置 stale；全部规则重验 |
| UO graph fingerprint 变化 | 重建 TG Host View；模型 refit；相关引理重新 review |
| TilingKey header 变化 | 重算 D；重新计算 open / E / closure |
| input semantics 变化 | 旧 Corpus 标 `compatibility_unknown`；相关 witness 重放 |
| log protocol / driver 变化 | oracle fingerprint 变化；先跑 oracle regression |
| source evidence 行发生变化 | 引理转 stale，不允许进入 E |
| 新 witness 反驳规则 | 撤销规则，重算 E，重新打开 Key |
| 出现 `R − D` | 单独生成 undeclared-key defect，**不计入 D 闭合** |

最后一条很重要：报告 §3.5 发现了 57 个 Host 会产生但 kernel 未声明的 Key（全部是 `InputDType=1(fp32) + IsRope=1`），这是 **dispatch 缺口**，不是覆盖成功，静默吞掉就成了假闭合。

---

## 10. 通用化：operator adapter 边界

P0-4 列的那些常量表要迁到算子侧：

```text
operators/<op>/<arch>/
├── operator.yaml            算子路径、arch、driver 入口、done marker
├── log_protocol.yaml        19 维 / 中间状态 / 拒绝原因的 scrape 规则
├── input_semantics.py       Case 定义、shape 展开、dtype 规则、normalised()
├── construction_hints.yaml  dim → knob 反推表（原 construct.D_FOR / DETER_FOR / S1_FOR）
├── search_hints.yaml        探索网格与近邻扫描表（原 DEFAULT_GRID / NEAREST_KNOBS）
├── feature_bindings.yaml    静态父节点绑定（原 features.STATIC_PARENTS）
└── proof_rules.yaml         引理与源码引用（seed candidates）
```

通用 engine 只依赖统一接口：

```python
adapter.declared_keys()
adapter.decode_key(key)
adapter.sample_case() / adapter.mutate(case, knobs) / adapter.construct(target_instance)
adapter.describe(case)
adapter.replay(cases) → Result（含 verdict 三态）
adapter.actual_key(result)
adapter.generation_knobs(field_id)      # 走 CodemapQuery.reads_of
```

**至少要有一个 synthetic 第二算子 smoke**，否则很容易把"FAG 能跑"误判成"平台通用"。

---

## 11. Codemap 改成 KB 的投影

```text
ir/operator_graph.yaml          ← 唯一语义权威
        │
        ├── indexes/kb_graph.sqlite      查询索引（唯一 SQLite 生命周期）
        │
        └── ir/tg_host_view.yaml         TG/CE 的搜索投影（人类可审阅）
```

建议连名字一起改：`host_codemap.yaml` → `tg_host_view.yaml`。它现在不是一般意义的代码地图，而是「TilingKey 字段 → 输入 roots → host state → guard → testcase knob」。

新增 `export_tg_host_view_from_kb(uo_root)`，输入**只能是**：

```text
uo/ir/operator_graph.yaml
uo/tiling/key_derivations.yaml
uo/tiling/exhaustive_key_space.yaml
uo/tiling/constraints.yaml
uo/manifest.yaml
```

禁止读取 `.probe_cache/fag_bundle.pkl` 和旧 `host_codemap.yaml`。

于是 `uo-init` 的 export 顺序改为：

```text
export_kb → build_index → export_tg_host_view → export_integrity
```

而不是 v2 计划的 `export_codemap → export_kb → build_index`——**只有 KB 先生成，投影才可能是投影**。

schema 要求：

```yaml
schema: tg-host-view/v1
source:
  graph_fingerprint: 8f...       # 必须有，freshness gate 比对的就是它
  manifest_hash: 31...
  source_revision: abc123
  generated_by: export_tg_host_view
fields:
  - field_id: TKD:DeterType
    node_ref: NODE_TKD_DETER_TYPE          # 回指 KB，不复制第二套事实 ID
    exactness: overapproximated
    input_closure: controllable
    read_edge_refs:   [EDGE_READ_SESSION_DETERMINISTIC]
    writer_edge_refs: [EDGE_WRITE_DETER_TYPE_01]
    predicate_refs:   [PRED_0012]
    evidence_refs:    [EV_0192]
    generation_knobs: [deterministic, sparse_mode]
```

可以冗余少量展示字段，但**不能成为判断 authority**。`indexes/host_codemap.sqlite` 不再单独建库，改成扩展 `kb_graph.sqlite` 的表或 VIEW（`field_writer` / `field_read` / `field_predicate` / `field_generation_knob`）。

`export_integrity` 的 gate 改成检查：

```text
operator_graph 存在且 invariants PASS
kb_graph.sqlite 的 meta.graph_fingerprint == operator_graph.fingerprint
tg_host_view.source.graph_fingerprint == operator_graph.fingerprint
declared set hash 一致
view 中所有 node_ref / edge_ref / evidence_ref 可解析
```

而不是今天的"`host_codemap.yaml` 存在"。

---

## 12. `tg-init` 提前分流

必须在 `tg-init` 最开始确定 mode，新增 `init_intent`：

```text
tg-init: init_intent → kb_check → contract_build → semantic_bind
         → bind_merge → mid_nest → integrity_gate → init_audit → human_confirm
```

默认文件：

```yaml
schema: tg-init-intent/v1
mode: tilingkey_full_coverage      # 默认全量，不是 csv_consumer
source: default
consumer_root: ""
```

所有 TG action 按 mode 分流：

| Action | `tilingkey_full_coverage` | `csv_consumer` |
| --- | --- | --- |
| `contract_build` | 从 UO 建 Key / 输入 / 动态运行合同 | 现有 CSV 合同 |
| `semantic_bind` | UO roots → replay Case knobs | CSV columns → UO variables |
| `integrity_gate` | key contract / adapter completeness | domain symmetry / csv closure |
| `plan_scope` / `plan_build` | 不要求 consumer | 要求 consumer |
| `solve_precheck` | 不要求 consumer | 要求 consumer |

全量模式的合同至少要确认：D 的来源和 fingerprint、TilingKey dimensions 及 domains、UO roots → testcase knobs 映射、replay adapter 可用、oracle 能返回实际 tiling key、source revision 一致。这时不需要 CSV。

`tg-plan` 不为 8705 个 key 各复制一条 obligation，写成集合义务：

```yaml
schema: coverage-obligations/v2
mode: tilingkey_full_coverage
declared_set: {source: uo/tiling/exhaustive_key_space.yaml, fingerprint: ..., count: 8705}
obligations:
  - {id: CLOSE_DECLARED_SET,    kind: set_closure, invariant: "D = (R ∩ D) ∪ E"}
  - {id: EXCLUSION_SOUNDNESS,   kind: proof_policy, invariant: "R ∩ E = ∅"}
  - {id: WITNESS_PROVENANCE,    kind: provenance,  invariant: "every R key has successful replay evidence"}
  - {id: EXCLUSION_PROVENANCE,  kind: provenance,  invariant: "every E key has verified rule evidence"}
```

逐 key 证据放在最终 `closure.csv`，不重复塞进 plan。

---

## 13. Skill / prompt / agent 文件

**先纠正一处仓库约定**：`skills/` 下**没有** `domains/`，共享方法层叫 `capabilities/`（`skills/capabilities/<id>/{capability.yaml, METHOD.md}`），而且 `compose_runtime.py` 已经会把被引用的 capability 拷进 `generated/<host>/`。所以闭环方法论 Skill 应该落在 `capabilities/` 而不是新开一个顶层目录，否则 compose 链路要跟着改。

职责分层：

```text
skills/capabilities/tilingkey-closure/{capability.yaml, METHOD.md, LEMMA.md}
    D/R/E、学习循环、证明纪律、路由与失效策略  ← 各 closure action 共同引用

skills/workflows/tg-solve/SKILL.md
    只描述产品入口、状态、下一 Action、完成条件

skills/actions/tg-solve/<action>/{METHOD.md, action.yaml}
    每个确定性 action 如何调用 engine

prompts/tasks/tg/{lemma-mine.md, lemma-review.md, closure-audit.md}
    只处理真正需要模型推理的源码引理任务
```

这样同一套闭环规则不会被复制到 workflow skill、agent、prompt 和 Python 四处。

新增文件清单：

```text
skills/capabilities/tilingkey-closure/{capability.yaml, METHOD.md, LEMMA.md}
skills/actions/tg-solve/
├── oracle-probe/  closure-ledger/  closure-search/  closure-residual/
├── closure-construct/  closure-explain/
├── lemma-leads/  lemma-mine/  lemma-review/  lemma-apply/
└── closure-audit/  closure-certify/
agents/{tg-lemma-producer.yaml, tg-closure-referee.yaml}
prompts/tasks/tg/{lemma-mine.md, lemma-review.md, closure-audit.md}
```

`/tk-cover` 改成 command router 级 alias 指向 `/tg-solve`，**不保留独立 workflow spec**——今天它的 `prepare → derive → close → certify`（`env_probe` / `derive_fields` / `export_codemap` / `mine_recipe` / `apply_recipe` / `coverage_gate`）与 `tg-solve` 会各自漂移。其中 `export_codemap` 迁到 `uo-init`（第 11 节），`mine_recipe` / `apply_recipe` 被 `lemma_*` 取代，`coverage_gate` 被 `closure_audit` + `closure_certify` 取代。

---

## 14. certify 的十条检查

不能只检查 `open_gap_sound == 0`：

```text
I1   R ∩ E = ∅
I2   D = (R ∩ D) ∪ E
I3   每个 R key 都有成功 host replay provenance
I4   每个 E key 都由 source_lemma_verified 或 solver_unsat_verified 支持
I5   D 的 source hash / revision 与当前 kernel header 一致
I6   derived rule 的 source_graph_fingerprint 与当前 UO KB 一致
I7   所有 exclusion rule 均有可解析 evidence_refs
I8   candidate / human / llm 等级的规则没有进入 E
I9   R − D 单独报告，不得静默吞掉
I10  closure report 覆盖 D 中每个 key，且 verdict 唯一
```

`report.py` 今天已经能逐 key 产出 witnessed / excluded / OPEN / CONFLICT，底座是好的；缺的是 I4 / I6 / I7 / I8 这四条关于"什么等级的规则有资格进入 E"的检查。

---

## 15. 执行顺序与验收

顺序是硬约束：**先消除双权威，再分流 mode，再修证明链，最后才吸收 `tk-cover`。**

### Phase 1 — 消除双权威

改动：`uo_init/host_codemap.py`、`kb_export.py`、`kb_index.py`、`pilot_engines.py`、`tk_cover_engines.py`、`workflows/specs.py`

```text
KB → tg_host_view 单向投影
移除 .probe_cache 作为生产输入
增加 fingerprint freshness gate
只保留一个 SQLite（kb_graph.sqlite）
```

**验收**：fresh init（`prepare_layout` 清空 `ir/` 之后）能一次跑通 `export_kb → build_index → export_tg_host_view → export_integrity`，且 `.probe_cache` 整个目录移走后结果不变。

### Phase 2 — TG 全链路 mode-aware

```text
tg-init 增加 init_intent，默认 tilingkey_full_coverage
tilingkey_full 不要求 consumer root
tg-plan / tg-solve 读同一个 mode
conditional gates
```

**验收**：在**没有任何 CSV consumer** 的仓库上，`tg-init → tg-plan` 全绿。

### Phase 3 — 修证明链

```text
lemma_mine → lemma_review → lemma_apply 三段拆开
apply_rules / report 改用 excluded_by_sound
source proof receipt 落地
stale source hash fail closed
规则撤销路径（refuted → revoked → key 重新 open）
```

**验收**：一条 grade 为 `human` 的规则无法改变 E 的大小；构造一个反例 witness 能让对应规则自动 revoke 且 open set 相应增大（而不是流程停摆）。

### Phase 4 — 学习循环

```text
closure_search 一个有界 round
corpus verdict 准入 + oracle_probe
model manifest + corpus_fingerprint 触发 refit
A/B control arm
closure_residual 路由 + construct/explain 分支
```

**验收**：在 FAG arch35 上从 `R=0, E=0` 起跑，Agent 自主推进到 gap=0，全程不需要人工串 CLI；每轮 `progress.yaml` 都有 model_arm / random_arm 两个数。

### Phase 5 — 通用化与 smoke

算子特定内容迁到 `operators/<op>/<arch>/`，补测试：

```text
test_tg_full_mode_without_consumer
test_codemap_projection_fingerprint
test_candidate_rule_cannot_enter_E
test_lemma_review_required_before_apply
test_stale_rule_source_hash_fails
test_R_E_conflict_triggers_revoke_not_deadlock
test_declared_set_hash_mismatch_fails
test_residual_loop_budget
test_corpus_rejects_crashed_and_not_run
test_second_operator_adapter_smoke
test_tk_cover_alias_has_no_independent_pipeline
```

### Phase 6 — 清理

沿用 v2 的清理清单，前置条件全部改成"Phase 1 验收通过"：

| 目标 | 体积 | 说明 |
| --- | ---: | --- |
| `.probe_cache/`（276 项） | 643 MB | Phase 1 证明生产链不再读它之后删 |
| `.ascendc-pilot/` 从 git 移除 | 2.3 MB | **含 HMAC key，需同时轮换密钥** |
| `generated/`（702 文件） | 1.9 MB | 由 `compose_runtime` 再生 |
| `scripts/_probe_*.py`（84 个） | 0.5 MB | 探针脚本洪泛 |
| `scripts/replay_*.py`（20 个） | 0.1 MB | 合入 `scripts/replay/` 包 |
| `docs/fag/tilingkey-closure-agent.md` | — | 与 `docs/workflows/` 下同名文件 SHA256 相同，留一份 |
| `docs/fag.zip`、`templates/` 空目录 | 0.2 MB | 删 |

两项 v2 遗留决定仍然有效，与闭环无关但一并做完：**符号执行降级**（`value_expr` 66.1% + `expanded` 24.1% 实测零消费，`expanded` 直接删，`value_expr` 那条链降级为可选的 `uo-deep-solve`，默认不跑）；**测试瘦身**（116 文件里 18 个不到 60 行的纯 import / 纯 schema 存在性断言，判据是"这个测试失败时能不能定位到一个真实缺陷"）。

---

## 16. 两条守不住就白做

**单边原则**。近似模型只能生成和排序候选，**永远不能排除 Key**。排除只能由带 `file:line` 的源码证明或 solver UNSAT 给出。这条要落在 `excluded_by_sound` 和 certify 的 I8 上，不靠人记。

**审查前置于写入**。producer 提出候选、referee 验证证据与证明资格、deterministic engine 唯一写正式产物。顺序错一次，`gap=0` 就只是账面闭合。

按本版做完，才真正满足：

```text
D = (R ∩ D) ∪ E     R ∩ E = ∅     且 E 中每个元素都有源码或 solver 证明
```
