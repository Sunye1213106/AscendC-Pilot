# FlashAttentionScoreGrad（arch35）优化计划：Z3-free 主流程（已由实施版取代）

> 本文保留第一版方案的背景和设计动机；实施顺序、接口口径、失效规则和验收门槛以
> [实施版计划](fag-arch35-z3-free-implementation-plan.md) 为准。该版本明确了 CBM
> 完整退役、有限域四值语义、证书完备性要求与迁移阶段，避免把“未命中”误判为不可达。

## 1. 目的、范围与版本口径

本计划将 FAG arch35 的 UO、TG 与 full-tilingkey closure 收敛为**完全 Z3-free 的生产路径**：

1. 用有限域 predicate、确定性构造和 Host replay 完成 TilingKey 覆盖；
2. 删除默认 UO deep expression / Key reachability Z3 的计算与产物；
3. 以源码引理证书而非 solver 结果判定不可达 Key；
4. 降低 UO 初始化、导出、增量更新和测试生成的时间与内存；
5. 构建 Kernel 同步、buffer、搬运、计算语义图，并支持 diff-hunk PR 影响分析。

| 对象 | 基线 | 说明 |
| --- | --- | --- |
| AscendC-Pilot | `c099dd12c879a75dae393a31ac0419a438dd91c6` | 流程与引擎基线 |
| FAG 工作树 | `4e09c2ec15a414f6e312caf5b3da16cd965af07b` | 当前本地 arch35 源码勘察基线 |
| FAG `.ascendc-pilot/` | 未跟踪，manifest 指向 `4e09c2e` | 可再生缓存，不是提交事实 |

FAG 源码、TPL schema、BuildContext、InputSemantics 或 Oracle protocol 任一变化后，必须重算
声明集、缓存和证书；不得继承旧 `D/R/E` 数字、命中率或性能结论。

## 2. 正确性与证据口径

```text
D = TPL ARGS_SEL 展开的有限合法 TilingKey 集合
R = 真实 Host 完整执行成功、实际返回的 witness Key 集合
E = 有源码级证明并通过全量 witness 反例检查的不可达 Key 集合
U = D - R - E
完成条件：U = ∅，且 R ∩ E = ∅
```

- `D` 仅由 ARGS_SEL、离散 domain 与确定性 encode/decode 产生；不依赖 solver。
- `R` 仅由真实 Host replay 的 observed key 产生；预测 key、测试目标、surrogate 不能替代它。
- `E` 仅由源码引理证书产生。LLM、统计规律、随机搜索、有限枚举未命中、generator 失败、
  Z3 UNSAT 和模型结论都不能写入 `E`。
- 对结构化引理，在有限 `D` 上直接枚举匹配集合；激活前必须验证
  `matched(D) ∩ R = ∅`。具备构造能力时，还须对引理边界和最近 witness 执行 Host replay。
- 缺少源码证据、无法定位赋值点、predicate 不支持或构造失败时保留 `unknown`；不允许把异常
  当成 false、unreachable 或已覆盖。

### Z3 退役原则

FAG 的默认 UO、L0/L1/L2、搜索和 full closure 均不得导入、初始化或回退到 Z3。普通 TG 的
旧 Z3 backend 仅在迁移期作为显式选择的 `legacy` 对比实现：

```text
默认 backend: finite
FAG allow_z3_fallback: false
legacy Z3: 开发期对比，仅显式启用
```

有限域 realization backend 验收完成、生产路径不再导入 Z3 后，才删除旧后端与
`z3-solver` 依赖。

## 3. 有限域基础设施

### 3.1 Finite predicate engine

增加可解释、确定性的轻量解释器，只支持：

```text
eq、ne、in、not_in
and、or、not
implies、requires、mutex、compatible_set、compile_time_fixed
离散域与明确整数边界
```

它用于：TPL pruning/relation、源码引理适用范围、coverage target、candidate 静态检查和
`E∩R` 冲突检查。每次求值记录规则 id、输入、结果和求值路径。`unsupported/unknown` 必须沿途
传播；FAG 的数千规模 `D` 直接枚举，不引入符号求解。

### 3.2 源码引理证书

每条进入 `E` 的规则都需要机器可审计 schema：

```text
id、status、key pattern/predicate、可读陈述
source refs、依赖 symbol、source hash、TPL schema hash
matched D count、conflicting R count
boundary replay count、counterexample count
created revision、last verified revision
```

激活流程：结构校验 → source ref/hash 校验 → 有限 `D` 枚举 → 全量 `R` 冲突检查 → 边界/最近
witness 反例 replay → 激活或撤销。依赖源码、TPL、BuildContext、InputSemantics 或 Oracle protocol
变化后，规则标为 `needs_reverify`，不得继续作为 `E` 的权威。

## 4. 执行顺序

```text
P0.1 Oracle integrity 与 D/R/E 证书基线
P1.1 sampling schema 与未消费字段失败
P1.2 normalization-aware deterministic seed
P1.3 input-level constrained pairwise
P1.4 witness mutation 与 residual diagnostics

P2.1 删除 UO deep expression/Z3 默认路径
P2.2 provenance skeleton abstract interpretation
P2.3 消除重复 export/index/integrity
P2.4 SourceCorpus 与增量缓存
P2.5 fold 按需缓存
P2.6 finite predicate engine
P2.7 finite TG realization backend
P2.8 legacy Z3 对比与退役

P3 Kernel Semantic IR
P4 diff-hunk PR impact
```

P1 和 P2.1–P2.5 可以并行。P2.6/2.7 可与性能优化并行，但 finite backend 验收前不得删除
legacy 文件。P3 依赖稳定的字段、符号、文件索引；P4 先实现 TilingKey/TilingData/KernelBranch，
再接入 P3 语义边。

## 5. P0.1：基线、Oracle integrity 与证书门禁

### 工作项

1. 每个 run 记录 revision、UO graph fingerprint、TPL header hash、host/kernel source hash、
   BuildContext fingerprint、InputSemantics hash 和 Oracle protocol 版本。
2. 产物分为权威输入（源码、TPL、operator config）、可再生缓存（UO、SQLite、fold）和证书
   （per-key CSV、R/E、closure certificate、性能报告）。
3. 运行完整 arch35 基线，测量 `discover / parse / skeleton / materialize / export / index / seed /
   replay / lemma validation` 的时间、内存、文件数与字节数。
4. 建立 Oracle 完整性账本：

```text
judged + crashed + not_run + parse_failed = requested
```

### 硬门禁

- packed key 必须按 19 个维度 decode 后重新 encode 为相同值。
- `D` 不依赖 solver；每条 `E` 都有有效源码证书，且 `E ∩ R = ∅`。
- closure 产物不能出现以 `SAT/UNSAT` 表达的结果。
- 默认 FAG run 不导入/初始化 Z3，不产生 `value_expr`、`expanded` 或 expr shard。

## 6. P1：Z3-free 的 FAG 测试生成

### P1.1 配置 schema 与 cold-start grid

`operators/flash_attention_score_grad/arch35/search_hints.yaml` 的 `tokens` 不是 Case 直接 knob。
将其拆为真实字段，并覆盖关键冷启动旋钮：

```yaml
sampling_grid:
  pse: [false, true]
  rope: [false, true]
  deterministic: [0, 1]
  pre_tokens: [0, 1, 64, 128, 256, 512, 1024, 2048, 65536]
  next_tokens: [0, 1, 64, 128, 256, 512, 1024, 2048, 65536]
  d1: [null, 16, 32, 64, 96, 128, 192, 256]
```

`closure/generate.py` 必须检查每个 grid 键都能被 `InputSemantics.knob_schema()` 消费，或有显式
alias/展开规则；未知字段直接失败，禁止静默丢弃。

### P1.2–P1.4 无 solver 构造链

```text
Coverage obligation / open Key
→ 直接 Binding → named binding → special generator
→ ladder / presence / bool 构造 → host-state compensation
→ nearest accepted witness mutation → 有限域受限枚举
→ InputSemantics.from_knobs → repair / normalised → 去重
→ Host replay → 使用 observed key 更新 R
```

- 首个 batch 按可配置比例使用 deterministic seed、输入旋钮级 pairwise 和 fresh random；统计以
  `normalised` 后唯一 Case 为准。
- `IsBn2MultiBlk`、`SplitAxis`、`DeterType` 等派生 Key 只能作为目标，不得伪造为直接输入。
- 有 witness 后按“单位 Host 调用新增 R”动态调节 mutation 与 fresh exploration。
- `construction_gap` 只记录失败。host-state Key 还要输出尝试输入、repair 后输入、Host reject
  原因和最近 witness 距离；不得产生 `E`。

### 验收

- 固定 seed 可复现；不同 seed 有预期多样性。
- 首 batch 包含 `pse/rope/deterministic/pre_tokens/next_tokens/d1` 的非默认取值。
- 固定 Host 调用预算下，以新增真实 `R` key 数评估提升。

## 7. P2.1–P2.5：Z3-free UO 与性能优化

### P2.1–P2.2 Provenance skeleton

默认 UO 仅生成：

```text
TPL domain / ARGS_SEL / encode-decode、host encode binding
input roots、parent/provenance edges、free variables、def_sites
guard categories、status、abstract exactness、input_derivable、cut reason
predicate FeatureTerm
```

引入保守抽象域：`CONSTANT`、`DIRECT_INPUT`、`DERIVED_INPUT`、
`INPUT_DERIVED_HOST_STATE`、`PARTIAL_HOST_STATE`、`LOOP_ELEMENT`、`PLATFORM_FIXED`、
`UNKNOWN`、`CONFLICT`。传播必须单调。只有所有必要依赖闭合到输入或平台固定量时，才能得到
`input_derivable=true`；unknown/free/cycle 不能升级为 exact。auxiliary 闭合降低 partial 时必须
记录证据。

skeleton 模式不得先构造完整 `value_expr` 再 strip。默认产物完全取消 `value_expr`、`expanded`、
expr shard 与 UO Key-reachability Z3。若保留单维调试表达式，只能显式、短期产生，不进入 closure
权威产物或验收依赖。与旧 deep 路径抽样差分时，roots 可保守超集，但禁止 false-positive
`input_derivable=true`。

### P2.3–P2.5 导出、缓存与 fold

- `export_operator_kb(..., rebuild_index=False, write_integrity=False)` 只写基础图；workflow
  各运行一次 `build_index`、`export_integrity`，并以集成测试断言一次 run 中各恰为一次。
- 引入 `SourceCorpus`：按 role 文件清单、文本、content hash、line index、Clang TU/token cache；
  HostIR、VariableModel、TilingData、kernel reader、常量和 PR evidence 共用，消除重复扫描。
- 函数级 full-closure 缓存 key 为 function source hash、callee summary hash、VariableModel
  fingerprint 与 BuildContext fingerprint。交互模式只重算变更函数及反向调用闭包，最终 gate 仍 full。
- `TemplateBlock` 使用 generator，合法 key 明细仅存一份 JSONL 或 SQLite；YAML 只保留摘要、
  fingerprint 与 index path。hash 未变不写文件，`impact_graph.yaml` 不复制所有 edge。
- 日常 UO、问答和 PR impact 使用未实例化 `kernel_ir`；TG kernel coverage/最终 CI 才 fold。fold
  cache key 包含 kernel source、TPL、dtype variant、compile context hash；缺依赖显式 `skipped`。

### 验收

- skeleton 路径没有 deep expression/UO Z3，仍支持 P1 和 D/R/E。
- 缓存正确命中和失效；默认内存、字节数与 wall time 相对 P0 下降。
- 一个 run 内无重复 SQLite rebuild/integrity write，legal key 不多份常驻复制。

## 8. P2.6–P2.8：finite realization backend 与 Z3 退役

### P2.6 Finite predicate engine

实现有限操作、可解释评估记录、unsupported 传播与 finite-D 枚举测试。它负责静态目标校验，
Host replay 才负责实际 Key 裁决。

### P2.7 Finite realization backend

```text
编译有限 predicate
→ 提取直接等值赋值和目标 key pattern
→ 查询 realization map / named binding / construction hints
→ 构造 knob assignment → repair / normalised
→ predicate 静态检查 → Host replay
→ 使用 observed key 更新覆盖
```

首批支持 `optional_input_mode`、`csv_domain_cover`、`tiling_key_field_value`、有限
`tiling_key_relation`、`dtype_layout_class`、离散 `runtime_variable_state`、可映射
`kernel_branch` 和 L2 expected-key pattern。未实现时仅输出：

```text
UNSUPPORTED_FINITE_REALIZATION
NO_CONSTRUCTION_PATH
AMBIGUOUS_BINDING
HOST_REJECTED
NOT_RUN
```

不得输出 SAT/UNSAT；没有候选不得声称不可达；FAG 禁止 fallback。其他算子迁移期可显式选择
legacy Z3，系统不得静默回退。

### P2.8 删除标准

满足全部条件后删除 Z3：

1. FAG L0/L1/L2 和 full closure 默认流程不导入 Z3；
2. 固定预算下 finite 的新增真实 `R` 不低于 legacy；
3. legacy 能生成而 finite 未生成的义务均有明确 unsupported 分类；
4. 无 Z3 UNSAT 写入 `E` 的代码；
5. 所有生产测试通过，删除 `z3-solver` 后 UO、TG、closure、query 测试仍通过。

## 9. P3：Kernel Semantic IR

在编译期 `KernelBranch` 和 TilingData reader 之上增加紧凑语义层：

| 节点 | FAG arch35 首批范围 |
| --- | --- |
| `KernelFunction` / `KernelBranch` / `Loop` | entry、Cube、Vec、NZ post、deter |
| `SyncEvent` | `SetFlag`、`WaitFlag`、`PipeBarrier`、跨核 flag |
| `Buffer` / `QueueEvent` | GM/L1/UB/L0 与 alloc/enqueue/dequeue/free |
| `MemoryEvent` | DataCopy、load/store、UB↔L1 |
| `ComputeEvent` | Mmad、vector、reduce、cast、softmax grad |

边类型为 `selected_by`、`parameterized_by`、`controls`、`orders_before`、`reads`、`writes`、
`pairs_with`、`calls`。检查 flag 配对、buffer 生命周期、copy/compute/sync 投影。初期只报告候选
风险；性能结论仍需 profile 或硬件实测。

## 10. P4：diff-hunk PR 影响分析

```text
git diff hunk → changed file + line range → Evidence/SourceSpan
→ 直接节点 → 按边类型、方向、深度传播
→ TilingKey / TilingData / KernelSemantic / TestObligation 报告
```

TPL、host setter、kernel constexpr、TilingData ABI、sync/buffer 变更使用不同传播规则；默认限制
depth/edge kind，报告“直接影响 / 传播影响 / 未证实邻居”，禁止无向遍历整个连通分量。

## 11. 非目标

- 不把所有 Host C++ 翻译成通用数学/SMT 表达式；
- 不以有限枚举未命中、generator 失败、模型或 LLM 结论证明不可达；
- 不以删除 Z3 为由降低 D/R/E 的证据要求；
- 不让 finite backend 静默回退到 legacy Z3；
- 不在 finite backend 替换完成前删除普通 TG 的 legacy 实现；
- 不在无 profile 证据时声称同步/buffer 改动必然优化性能；
- 不在 revision 不一致时复用历史 closure 或性能结论。
