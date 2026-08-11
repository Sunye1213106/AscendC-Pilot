# AscendC-Pilot 系统设计

> 描述系统**如何设计、如何工作**：UO 如何从源码建成知识库，TG 如何用知识库做 TilingKey 全覆盖。  
> 闭环认知见 `skills/testcase-generation` 与 `skills/source-proof`；现状架构见 [architecture.md](./architecture.md)；UO 控制闭合见 [control-closure.md](./control-closure.md)。

---

## 1. 一句话与目标

**AscendC-Pilot** 是面向 Ascend C 算子的控制面产品：先从源码抽出可审计的算子知识库（UO），再据此驱动 TilingKey 全覆盖闭环（TG），直到每个声明 Key 要么被真实 Host 跑出来，要么被源码证明不可达。

```text
算子源码 + CANN 头文件
        │  /uo-init（CodeMap + TPL ARGS_SEL）
        ▼
   .uo 权威（view_blob 含 D / tg_host_view / operator_graph）
        │  /tg-init → /tg-plan → /tg-solve（CodeMap 定向构造）
        ▼
   gap=0 证书：D = (R ∩ D) ∪ E
```

| 符号 | 含义 | 唯一合法来源 |
| --- | --- | --- |
| **D** | 内核声明的 TilingKey 集合（TPL ARGS_SEL 展开） | `.uo` view_blob `tiling/exhaustive_key_space` |
| **R** | 真实 Host 跑出过的 Key | Host oracle verdict |
| **E** | 有源码证明不可达的 Key | 经审查的 sound 规则 |

**闭合目标**：`D = (R ∩ D) ∪ E` 且 `R ∩ E = ∅`。  
「跑了很多次没出现」不是归宿；近似模型只能生成/排序，**不能**进 E。

---

## 2. 系统分层

```text
┌─────────────────────────────────────────────────────────┐
│  Skills / acp CLI（工作流编排、阶段门禁、人机确认）         │
│  pilot/  — state · gate · route · lease                   │
├─────────────────────────────────────────────────────────┤
│  engines/understand-operator  (uo_init)   ← 建 KB         │
│  engines/testcase-generation  (testcase_agent) ← 覆盖闭环 │
│  engines/code-engineering     (CE)        ← 代码工程/审查  │
├─────────────────────────────────────────────────────────┤
│  engines/common (acp_common)  — Constraint IR + Z3 语义   │
└─────────────────────────────────────────────────────────┘
```

产物布局：

```text
<算子目录>/.ascendc-pilot/
├── uo/<op>.<arch>.uo     # 唯一 CodeMap 权威（含 TG view_blob）
└── <arch>/
    ├── tg/               # 合同 / plan / closure / solve
    ├── ce/
    └── memory/ context/ state/ runs/
```

默认工作流：`/uo-init` → `/tg-init` → `/tg-plan` → `/tg-solve`。  
命令形态：`acp start <workflow>` → `acp next` → `acp run-action <id>`。

角色三分：

| 角色 | 权限 | 例 |
| --- | --- | --- |
| deterministic_engine | 写正式产物 | `derive_key_fields`、`closure_search` |
| producer | 只写 staging / parts | `resolve_gaps`、`lemma_mine` |
| referee | 只写 review | `kb_review`、`lemma_review`、`closure_audit` |

Primary 控制器**禁止**直接改 `uo/ir/**` 救场。

---

## 3. 端到端数据流

```text
[算子 Host/Kernel 源码]
        │ CodeMap passes（含 tpl_schema：ARGS_DECL + ARGS_SEL）
        ▼
.ascendc-pilot/uo/<op>.<arch>.uo          ← 权威 CodeMap
  view_blob:
    tiling/exhaustive_key_space.yaml      ← D
    tiling/legal_key_index.jsonl
    ir/tg_host_view.yaml                  ← packing / producer / predicates
    ir/operator_graph.yaml                ← fingerprint / 闭包身份
        │ tg-init（tilingkey_full_coverage）读 view_blob
        ▼
.ascendc-pilot/<arch>/tg/
  contract/tilingkey_contract.yaml
        │ tg-solve：CodeMap 定向 construct + Host replay
        ▼
  closure/
    R.txt  excluded.txt  open.txt  closure.csv
    corpus/  models/  rounds/  lemmas/
    construct/trace.yaml                  ← 定向构造审计
```

**单向反馈**：运行发现缺口 → 源码验证 → 更新 `.uo` → TG 重读 view_blob。  
禁止 TG 模型直接改写 UO CodeMap。

---

## 4. UO：如何提取信息、建成知识库

### 4.1 目标

`/uo-init` 产出的不是普通调用图，而是**控制来源闭合图**：每个影响生产路径的分支条件，都有一条可审计路径回到某种根 Source；闭合不了则留下稳定的 unresolved 原因，禁止静默丢失。

分析宇宙限定为 **PRODUCTION**（目标架构下可编译、从已注册实例可达、影响控制/内存/计算/同步/输出）。不做「仓库所有 if」闭合。

### 4.2 流水线阶段

```text
prepare → extract → analyze → resolve → commit → review
```

`prepare` 内部：`prepare_layout` → `scope_scan`（layout + Clang dependency closure）→ `scope_validate`（机器 gate，非人工确认）。

| 阶段 | 关键 Action | 做什么 |
| --- | --- | --- |
| prepare | `prepare`（内部：`prepare_layout` → `scope_scan` → `scope_validate`） | 机器建立 Source Scope + BuildVariant；失败记 blocker |
| extract | `extract_host` | libclang 建 HostIR + 分支清单 |
| | `extract_tiling_key` | TPL DSL ↔ Host 编码点绑定 |
| | `extract_registry` | 注册表 / IsCapable |
| | `extract_kernel` | Kernel 分支 fold |
| normalize | `derive_key_fields` | 各 TilingKey 维回溯到输入根 |
| | `normalize_predicates` | 谓词归一，未决守卫进 gap |
| | `resolve_gaps` / `apply_gap_patch` | LLM 补洞 → 确定性打补丁（须改表达式） |
| export | `export_kb` | 组装图 → 写 sqlite 权威库（可选 YAML，`UO_KB_YAML`） |
| | `build_index` | 从 YAML 重建 sqlite，或确认 DB-only 产品就绪 |
| | `export_tg_host_view` | TG 搜索投影 |
| | `export_integrity` | 指纹一致性 |
| review | `kb_review` | 质量门禁（referee） |

### 4.3 抽取管线（模块视角）

```text
源码
  │ clang_walk（libclang 单遍）
  │   控制节点 · PathCond · 写点 · 容器变更 · early-return/bailout
  ▼
HostIR
  │ source_resolver：叶子 → 根 Source
  │ derive_key_fields：沿守卫赋值做表达式替换（DAG）
  │ variable_model：命名变量 + 域（opdef / TPL / enum）
  │ predicate：SMT-lite 归一
  ▼
每维 FieldDerivation
  │ host_derivation 聚合
  │ materialize_tiling：TPL 组笛卡尔 → 合法 key 表 D
  │ key_reachability：共享 acp_common Z3 判静态可达性
  ▼
分层 KB（kb_export → sqlite authority: db；YAML 可选）
```

| 模块 | 职责 |
| --- | --- |
| `clang_walk` | AST 写点、路径守卫、复合赋值、容器 mutator、RETURN_SLOT |
| `host_ir` | 写点 IR、controls、legality_premises |
| `branch_inventory` | PRODUCTION 控制节点全量清单（禁止按 cannot_reach_sink 删） |
| `tpl_dsl` / `tpl_bind` | AscendC TilingKey DSL 解析与 encode 绑定 |
| `derive_key_fields` | 维值表达式 DAG、exactness、cut point / 循环摘要 |
| `host_derivation` | 整算子派生编排；产出 `host_derivation.yaml` |
| `variable_model` | 变量域；`completeness: open` 时不发明值 |
| `materialize_tiling` | 声明 key 空间 + 覆盖义务 |
| `key_reachability` | 多维联合 Z3：reachable / unreachable / unknown / underivable |
| `kb_export` / `commit` | 写入 `.uo` CodeMap；YAML 仅为 dump/调试 |

### 4.4 能提取什么

#### 根 Source（合法终点）

```text
INPUT_SHAPE / INPUT_DTYPE / INPUT_FORMAT / INPUT_VALUE
OPTIONAL_INPUT_PRESENCE
ATTRIBUTE
PLATFORM_ARCH / PLATFORM_CORE_COUNT / PLATFORM_MEMORY_SIZE
COMPILE_INFO / COMPILE_DEFINE
TILING_KEY / TILING_DATA
TEMPLATE_LITERAL
KERNEL_BUILTIN / EXECUTION_ROLE
LOOP_INDUCTION / LOOP_DERIVED
CONSTANT
EXTERNAL
UNKNOWN          # 必须带稳定 reason
```

#### 每维派生结果

| 字段 | 含义 |
| --- | --- |
| `value_expr` | 从 encode 点回溯得到的表达式 DAG |
| `exactness` | `exact` / `constant` / `overapproximated` / `partial` / `unresolved` |
| `input_closure` | `controllable` / `platform_locked` / `host_state` / `none` |
| `input_derivable` | exact/constant 且根不在 host_state —— **下游可用性真值** |
| `root_vars` | 表达式依赖的输入/平台/状态根 |
| `undecided_guards` | 未决守卫（含 `blocked_on`） |
| `def_sites` | 赋值点文件行号（引理证明起点） |

**口径**：`exact` ≠ 测试可驱动。根停在 `TILING_DATA` 的维表达式可能精确，但旋钮拧不动；消费侧看 `input_derivable`。

#### 分支可控性

| 类 | 含义 |
| --- | --- |
| `INPUT_DERIVED` | 输入可直接/间接覆盖 |
| `TILING_DERIVED` | 输入间接控制的派生量 |
| `KEY_OR_BUILD` | TilingKey / 编译变体决定 |
| `RUNTIME_INTERNAL` | 测试无法指定（如 blockIdx） |

#### 静态 key 可达性（UO 侧 Z3）

对声明集合 D 中每个 key，用共享 Constraint IR 联合求解各维表达式：

| 判决 | 条件 | 可信度 |
| --- | --- | --- |
| `unreachable` | UNSAT | 可信（软守卫只会放宽，仍矛盾则真不可达） |
| `reachable` | SAT 且相关维皆 exact/constant 且 input 可控 | 可信 |
| `unknown` | SAT 但含过近似 | 不可当可达证明 |
| `underivable` | 无派生 | 不得默认可达 |

UO 的 Z3 **不是**全覆盖终点，而是给 TG 的静态骨架与剪枝证据。

### 4.5 KB 主要产物

权威产品：`.ascendc-pilot/uo/<op>.<arch>.uo`（SQLite CodeMap）。

| view_blob / 表 | 内容 |
| --- | --- |
| graph entities/relations | Host/Kernel/Tiling/compile-time 图 |
| `tiling/exhaustive_key_space.yaml` | D 的计数与索引指针 |
| `tiling/legal_key_index.jsonl` | 声明集 D 逐行 |
| `ir/tg_host_view.yaml` | TG：字段 → roots → writers → knobs |
| `ir/operator_graph.yaml` | fingerprint / 闭包身份 |
| `ir/host_derivation.yaml` 等 | 派生与审计（可由 `uo-dump` 展开为临时 YAML） |

### 4.6 UO 能力边界

**已做到**：Host/Kernel libclang 主链；TPL 编码绑定；按维表达式派生；合法性前提（bailout）；程序点敏感展开；变量身份消歧；分层导出与 TG 投影。

**有意过近似 / 未闭合**：shape 依赖的循环元素（如区间覆盖、前缀和末项）；无界量词不进共享 IR；部分维 `host_state` 不可输入驱动。  
解析层已知坑见 [../debug/handoff.md](../debug/handoff.md)。

---

## 5. TG：如何实现 TilingKey 全覆盖

### 5.1 两种模式

| 模式 | 何时 | 主路径 |
| --- | --- | --- |
| **`tilingkey_full_coverage`（默认）** | 无 CSV consumer 要求时 | Host oracle 抬 R + 源码引理抬 E |
| **`csv_consumer`** | 有测试脚本根 | 经典 encode → `z3_solve` → cover |

全覆盖**不**靠 TG 再跑一遍 UO 式 Z3 判完 D。`z3_solve` 在 full 模式下是旁路/no-op；真正闭合靠下面的闭环。

### 5.2 为什么需要动静结合

| 纯静态 | 纯黑盒 |
| --- | --- |
| 循环/自由变量导致维过近似，SAT 不可信 | 无法证明不可达；稀有 Key 采样极慢 |
| 表达式解不出时仍有**依赖骨架** | 历史语料覆盖远小于 \|D\| |

结合方式：

- **静态骨架**（来自 UO）：每维读哪些输入/状态、可解到什么程度 → 代理模型特征与构造影响锥  
- **真实 Host**：唯一抬 R 的证据  
- **源码引理**：唯一抬 E 的证据  

### 5.3 前置：tg-init / tg-plan

**tg-init**（full）：读 `.uo` view_blob 中的 `operator_graph`、`exhaustive_key_space`、`tg_host_view`（缺则 TPL backfill），写出 `tilingkey_contract` 与 semantic bind。不强制 CSV。

**tg-plan**：覆盖义务矩阵与范围；full 模式可跳过部分 consumer 门禁。

### 5.4 tg-solve 闭环状态机

维护状态：`(D, R, E, Corpus, Models, RuleBook, Open, …)`。

```text
solve_precheck → oracle_probe → closure_ledger
        → closure_search → closure_residual
                │
                ├─ SEARCH_PROGRESS  → rework search（有界 round）
                ├─ CONSTRUCT_TARGETS → construct → explain → residual
                ├─ NEED_LEMMA → lemma_leads → evidence → mine → review → apply → ledger
                └─ GAP_ZERO → audit → certify
```

路由由 `closure_residual` 写 `route.yaml`，外层 `acp rework` 驱动，**单 action 内不死循环**。

#### 阶段职责

| 阶段 | Action | 作用 |
| --- | --- | --- |
| Oracle | `oracle_probe` | 确认 Host replay 可信（Key / 维 / 拒绝原因可读） |
| 账本 | `closure_ledger` | 从原始 verdict 重建 R；不采信无证据的历史结论 |
| 定向搜索 | `closure_search` | 一轮：评估/重训模型 → 候选池 → A/B（模型臂+随机臂）→ replay → 提交 corpus → 更新 R |
| 残差路由 | `closure_residual` | 决定继续搜 / 构造 / 挖引理 / 结案 / 升级 |
| 构造收尾 | `closure_construct` / `explain` | 按目标维反推 knobs；稳定替换 → lemma lead |
| 引理 | `lemma_leads` → `evidence` → `mine` → `review` → `apply` | observation lead；证据包；producer 只证；referee 审查；engine 写入 E |
| 结案 | `closure_audit` / `closure_certify` | 不变量 + gap=0 证书 |

#### 有界 search round

```text
corpus_sync → assess → fit/refit（指纹变化才训）
→ candidate_pool → rank + random_control_arm
→ oracle_replay → verdict_filter → corpus_commit
→ ledger_rebuild → progress_report
```

- **进 Corpus**：仅 Host 明确接受或明确拒绝；崩溃 / 未跑 / 截断不得当负样本。  
- **停搜**：连续多轮 `new_R==0` 且残差分布无改善，再转 construct/lemma。  
- **A/B 臂必须有**：区分「模型有用」与「多跑了几批」。

#### 引理纪律

```text
lead → candidate → source_supported → counterexample_checked
    → reviewed → active → (refuted → revoked)
```

| 等级 | 能否进 E |
| --- | --- |
| `solver_derived` / `source_lemma` | 能（sound） |
| human / llm / 统计挖掘 | 否（仅线索） |

写入 E 前：源码证明 + 全部现有 witness 反例检验 + referee。  
蕴含证明必须查**全部赋值点、early return、分流、后续覆盖**（单点阅读会误杀可达 Key）。

### 5.5 UO 产物在 TG 中的用法

| UO 产物 | TG 用途 |
| --- | --- |
| `exhaustive_key_space` / `legal_key_index` | 定义 D |
| `key_derivations` / `tg_host_view` | 旋钮 → 维；影响锥；静态父节点特征 |
| `key_reachability` | 静态剪枝线索（不可单独签发 E） |
| `def_sites` / predicates | 引理源码锚点 |
| `input_derivable` | 哪些维能靠输入构造，哪些只能观测/过近似 |

### 5.6 闭环不变量

```text
I1  R ∩ E = ∅
I2  R 只来自真实 Host witness
I3  模型结果不得进入 E
I4  E 中每条规则须有源码证据
I5  每条规则须通过全部现有 witness 反例检验
I6  仅当 D = (R ∩ D) ∪ E 才允许 certify
```

额外：`R − D`（Host 产出未声明 Key）是算子/dispatch 缺陷，**不计**闭合成功。

### 5.7 落盘（closure）

```text
.ascendc-pilot/<arch>/tg/closure/
├── state.yaml
├── R.txt  excluded.txt  open.txt  closure.csv
├── corpus/
├── models/
├── rounds/round_NNNN/
└── lemmas/{leads,candidates,reviews,active_rules,revoked_rules}
```

---

## 6. 共享约束层（acp_common）

路径：`engines/common/acp_common/`。

| 模块 | 内容 |
| --- | --- |
| `constraint_ir` | 归一表达式；`bool/int/enum`；比较/逻辑/算术/`if_then_else` |
| `z3_backend` | IR→Z3；timeout / rlimit；`prove_implies` / `prove_equivalent` |

**设计意图**：UO 判可达与 TG 实现输入共用同一语义，避免「UO 说 reachable、TG 构造不出」。

当前限制：无聚合/量词节点；循环出口摘要无法闭式进 IR —— 这正是部分维停在 overapproximated、必须靠 Host/引理收口的原因。

---

## 7. 权威与指纹

| 层 | 权威 | 派生 |
| --- | --- | --- |
| UO 语义 | `uo/ir/operator_graph.yaml` | SQLite、`tg_host_view` |
| 声明 Key 集 D | TPL header → `exhaustive_key_space` | `legal_key_index.jsonl` |
| 可达 R | Host oracle | — |
| 不可达 E | 经审查的 sound RuleBook | — |

`export_integrity` / fingerprint 用于发现「KB 已更新、投影仍旧」。  
TG 投影必须从当前 KB 派生，不得与 probe pickle 形成第二套权威。

---

## 8. 工作流速查

```text
# 建库
acp start uo-init --project <算子目录> --architecture arch35

# 合同与绑定
acp start tg-init --project <算子目录> --architecture arch35

# 覆盖计划（可选义务层）
acp start tg-plan ...

# 全覆盖闭环
acp start tg-solve ...
# closure_residual 非 GAP_ZERO → acp rework --reason <code>
```

调试派生（非生产契约）：`scripts/_probe_derive.py`；现状数字以 `docs/debug/current-status.md` 为准。

---

## 9. 设计原则（摘要）

1. **单边原则**：近似只放宽可行域；UNSAT/排除只能来自证明或真实矛盾。  
2. **标签诚实优于账面闭合**：`derived 19/19` 若含自由变量是假成功；看 `exactness` + `input_derivable`。  
3. **过近似必须留痕**：表达式里的自由变量必须有 undecided 记录。  
4. **Oracle 可信先于覆盖数字**：批次截断、宽表错位、环境漏填都会伪造「不可达」。  
5. **公共能力进共享模块**：校验、证据、租约不进单个 Action prompt。  
6. **算子知识不进通用 engine**：旋钮网格 / 维名映射应落在算子 adapter，而非 `closure/generate` 硬编码。

---

## 10. 相关文档

| 文档 | 内容 |
| --- | --- |
| [control-closure.md](./control-closure.md) | UO 控制来源闭合图细节 |
| `skills/testcase-generation` / `skills/source-proof` | 闭环与引理认知 |
| [architecture.md](./architecture.md) | 现状架构（UO / TG / 三域） |
| [../fag/tilingkey-closure-report.md](../fag/tilingkey-closure-report.md) | 历史校准报告（非 Skill） |
| Pilot Spec + generated entry wrappers | 各工作流 Harness 入口 |
