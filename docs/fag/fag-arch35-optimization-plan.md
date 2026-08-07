# FlashAttentionScoreGrad（arch35）优化计划（已废弃）

> 本文保留为第一版设计记录，**不再是执行依据**。已由完全 Z3-free 的主方案
> [fag-arch35-z3-free-optimization-plan.md](fag-arch35-z3-free-optimization-plan.md) 替代。
> 新方案以有限域 predicate、finite realization backend、Host replay 与源码引理证书完成
> D/R/E 闭合；FAG 禁止回退到 legacy Z3。

## 1. 目的、范围与版本口径

本计划面向 D:\TEST\ops-transformer\attention\flash_attention_score_grad 的 arch35 实现，
以及 AscendC-Pilot 的 UO、TG 和 full-tilingkey-closure 路径。目标是：

1. 使 FAG 的默认 UO、测试生成和 full closure 完全不依赖 Z3。
2. 以真实 Host replay 和源码级引理建立可审计的 TilingKey 闭合。
3. 修复 FAG cold start、定向生成和有限域 realization 的覆盖瓶颈。
4. 缩短 UO 初始化、导出和增量更新时间。
5. 扩展为 kernel 同步、buffer 和流水语义图，为性能和 PR 影响分析打底。

| 对象 | 版本 / 状态 | 使用方式 |
| --- | --- | --- |
| AscendC-Pilot | c099dd12c879a75dae393a31ac0419a438dd91c6 | 本计划的引擎基线 |
| FAG 工作树 | 4e09c2ec15a414f6e312caf5b3da16cd965af07b | 本地 arch35 源码勘察基线 |
| FAG .ascendc-pilot/ | 未跟踪，manifest 指向 4e09c2e | 仅作可再生缓存和样例，非提交事实 |

若 FAG revision、TPL schema、BuildContext、InputSemantics 或 Host oracle protocol 变化，必须重建 D、
重新验证引理并废弃旧 R/E 结论及缓存。

### FAG arch35 已确认的输入面

- flash_attention_score_grad_template_tiling_key.h 的 ARGS_SEL 是合法 TilingKey 集合的唯一权威来源；
  它声明 19 个维度，包括 SplitAxis、dtype、PSE、dropout、rope、模板梯度、DeterType、TND/NZ 和
  regbase 开关。
- flash_attention_score_grad_tiling_data_regbase.h 定义 core 切分、形状、稀疏、PSE、dropout、
  token、buffer size 等 TilingData 字段。
- 首批 kernel 语义提取范围为 entry/main flow、FAGBlockCube、FAGBlockVec、NZ post、deterministic
  分支、cube_api/mutex_* 和 vector_api/*；它们使用大量 flag、queue、buffer 与 copy/compute 操作。

## 2. 总体设计原则

### 2.1 FAG full closure 的 Z3-free 口径

~~~text
D = 由 TPL ARGS_SEL 展开的有限合法 TilingKey 集合
R = 真实 Host 完整执行成功、且返回该 key 的 witness 集合
E = 具备源码级证明并已通过全部 R 反例检查的不可达 Key 集合
U = D - R - E
完成条件：U = ∅，且 R ∩ E = ∅
~~~

- D 只由模板声明、选择组和 encode/decode 得出，绝不依赖 solver。
- R 只由完整、可归因的 Host replay 写入；静态预测 key 不可替代 observed key。
- E 的唯一权威来源是源码引理证书，不是 SAT/UNSAT。
- surrogate、随机搜索、LLM、统计规律、有限域枚举和生成器失败，只能发现或排序候选、帮助定位
  证明；它们均不能缩小 U、更不能写入 E。
- 结构化引理直接在有限 D 上以确定性 predicate 枚举适用集合。每条引理激活前必须验证
  matched(D) ∩ R = ∅，并在可构造时对边界及最近 witness 做 Host 反例 replay。
- 不支持的 predicate、缺失源码证据、找不全赋值点、无法构造或 Host 未运行，状态必须保持
  unknown，不得视为 false、unreachable 或 covered。

### 2.2 Z3 退役策略

FAG 主流程不得导入或初始化 Z3。普通 TG 仍有旧代码使用 Z3 将 coverage obligation 转成 CSV
candidate，因此不能先删依赖；先实现 finite realization backend，再将 Z3 变成：

~~~text
默认 backend：finite
FAG allow_z3_fallback：false
旧 Z3 backend：legacy，仅开发期显式对比
~~~

其他算子在 finite 尚未覆盖时可显式选用 legacy Z3，但系统不得静默回退。finite backend 完成验收、
生产路径不再导入 Z3 后，才删除旧后端和 z3-solver。

### 2.3 变更边界

计划先优化分析、测试生成和证书，不修改 FAG 数值算法、TilingKey 编码或 TilingData ABI。任何涉及
GetTilingKey、同步、buffer 生命周期或 kernel 行为的变更，都必须另做编译、精度、性能回归。

## 3. 目标工作流

~~~text
P0.1  Oracle integrity 与 D/R/E 证书基线
P1    Z3-free FAG 测试生成与真实 replay 覆盖
P2    UO skeleton、有限 predicate/realization、导出性能与 Z3 退役
P3    Kernel Semantic IR
P4    diff-hunk PR impact
~~~

~~~text
ARGS_SEL → D ─────────────────────────────────────────────┐
                                                          │
open Key / coverage obligation → finite realization → Case → Host replay → R
                                                          │
源码引理 → finite predicate → matched(D) → R 反例检查 → E ┘
                                                          ↓
                                                 U = D - R - E
~~~

## 4. P0.1：可复现基线、Oracle integrity 与证书门禁

### 工作项

1. 每个 UO/TG run 写入 FAG revision、UO graph fingerprint、TPL header hash、host/kernel source hash、
   BuildContext fingerprint、InputSemantics hash 和 oracle protocol version。
2. 区分权威输入、可再生缓存和证书：
   - 权威输入：FAG 源码、TPL header、operator 配置；
   - 缓存：.ascendc-pilot/uo、fold、SQLite、临时中间件；
   - 证书：per-key closure CSV、witness、引理、certificate、基准报告。
3. 对 Oracle 执行完整性计数：
   judged + crashed + not_run + parse_failed = requested。不完整批次不能贡献 R。
4. 固定基准记录 discover、parse、skeleton、materialize、export、index、seed、replay、lemma validation
   的 wall time、峰值内存、文件数和字节数。

### 硬门禁

1. packed key 按 19 维 decode 后重新 encode 必须等于原 key。
2. D 仅来自 TPL 声明。
3. 每条 E 均有源码证书，且 E ∩ R = ∅。
4. closure 产物中不存在以 SAT/UNSAT 表示可达性或不可达性的字段。
5. 默认 FAG run 不导入或初始化 Z3。
6. 默认 UO 不产生 value_expr、expanded 或 expr shard。

## 5. P1：Z3-free 的 FAG 测试生成

### 5.1 生成链路

~~~text
Coverage obligation / open Key
→ 直接 Binding
→ named binding
→ special generator
→ ladder / presence / bool 构造
→ host-state compensation
→ nearest accepted witness mutation
→ 有限域受限枚举
→ InputSemantics.from_knobs
→ repair / normalised
→ 去重
→ Host replay
→ observed Key 写入 R
~~~

SplitAxis、IsBn2MultiBlk、DeterType 等派生 key 只能作为目标，不可错误地直接用于 input pairwise。
pairwise 只作用于可直接赋值的输入旋钮；全部统计均以 normalised 后的唯一 Case 为准。

### 5.2 修复 sampling schema 和冷启动

修改 operators/flash_attention_score_grad/arch35/search_hints.yaml：删除未消费的 tokens，改为
Case 实际消费的 pre_tokens、next_tokens；补齐 pse、rope、deterministic 与 d1 的有限取值。
closure/generate.py 增加 schema 校验：每个 grid key 必须由 knob_schema() 消费，或显式声明 alias/
展开规则；未知字段直接失败，不可静默忽略。

首 batch 采用可配置的分层预算：

- 50% deterministic feature seed：layout、dtype、optional input、rope、mask、dropout、deterministic、
  sparse mode、d == d1 / d != d1、token band、S1/S2/D 梯度；
- 30% input-level pairwise：例如 rope × DTemplateNum、DeterType × sparse_mode、mask × layout、
  dropout × dtype 的可构造输入前提；
- 20% fresh random：保留探索。

有 accepted witness 后，根据各来源“每次 Host 调用新增 R key 数”动态调节 witness mutation 和
fresh exploration 比例。

### 5.3 residual 与 construction gap

扩展 nearest_knobs、construction hints 和 host-state compensation，覆盖 token band、d1、
IsTndSwizzle、IsNzOut。对无法直接写入的 host-state key 必须输出：尝试输入、repair 后输入、
Host reject、未运行原因和最近 witness 距离。

生成失败统一记录为 construction_gap，不能产生 unreachable 结论。

### 验收

- 固定 seed 可复现，且第一批对关键旋钮含非默认取值。
- 所有 sampling key 均可消费。
- 每个派生 key 的构造尝试都可追溯。
- 固定 Host 预算下以实际新增 R 比较改造前后收益。
- 不存在由 construction failure、预测值或有限枚举未命中写入 E 的路径。

## 6. P2：UO skeleton、有限域引擎与导出性能

### P2.1 删除默认 deep expression/Z3 路径

将 Key 派生改为 provenance skeleton abstract interpretation。默认只生成：

~~~text
TPL domain / ARGS_SEL / encode-decode
host encode binding
input roots
parent/provenance edges
free variables / def_sites / guard categories
status / abstract exactness / input_derivable / cut reason
predicate FeatureTerm
~~~

定义保守抽象域：

~~~text
CONSTANT
DIRECT_INPUT
DERIVED_INPUT
INPUT_DERIVED_HOST_STATE
PARTIAL_HOST_STATE
LOOP_ELEMENT
PLATFORM_FIXED
UNKNOWN
CONFLICT
~~~

抽象传播必须单调。仅当所有必要依赖均闭合到输入或固定平台量时，才能产生
input_derivable=true；遇到 unknown/free/cycle 不能升级为 exact。auxiliary 闭合可降低 partial，
但必须记录证据。skeleton 与旧 deep 路径仅做抽样差分：roots 可保守超集，但不得产生
false-positive input_derivable=true。

默认彻底取消 value_expr、expanded、tiling/expr shards 和 UO Key reachability Z3。若保留开发
调试接口，只允许显式针对单维生成短期表达式；它不进入 full-closure 权威产物，也不作为验收依赖。

### P2.2 SourceCorpus、流式 materialize 与增量缓存

引入 SourceCorpus，统一保存 role 文件清单、文本、content hash、line index 和 Clang TU/token cache，
供 HostIR、VariableModel、TilingData、kernel reader、常量扫描和 PR evidence 复用。

TemplateBlock 以 generator 展开、分类并流式写入单一权威明细存储（JSONL 或 SQLite 二选一）；
YAML 只保留 schema、摘要、fingerprint 和 index path。序列化直接对内存 bytes 求 hash，hash 未变
不落盘；impact_graph.yaml 不再复制全量 edge。

函数级 controllability 缓存 key 为 function source hash、callee summary hash、VariableModel
fingerprint 和 BuildContext fingerprint。交互/PR 只重算变更函数及反向调用闭包/keypath；最终 gate
仍运行 closure_mode=full。

### P2.3 消除重复 export/index/integrity 与按需 fold

export_operator_kb(..., rebuild_index=False, write_integrity=False) 仅写基础图；workflow 只运行一次
build_index 和一次 export_integrity，并由测试断言一轮运行的 SQLite rebuild 与 integrity write
各恰为一次。

日常 UO、问答和 PR impact 使用未实例化 kernel_ir；仅 TG kernel coverage、最终 CI 或显式请求时
执行 pairwise fold。fold cache key 至少含 kernel source hash、TPL schema hash、dtype variant 和
compile-context fingerprint；clang/entry/header 缺失只能记录 skipped，不得伪造分支。

### P2.4 finite predicate engine

新增不依赖 Z3 的轻量解释器，仅支持：

~~~text
eq、ne、in、not_in
and、or、not
implies、requires、mutex、compatible_set、compile_time_fixed
离散域与明确整数边界
~~~

它用于 D 上的 pruning/relation、引理匹配、coverage target、candidate 静态校验和 E/R 冲突检查。
结果必须可复现，携带 rule id 和求值路径；不支持、异常或越界一律返回 unsupported/unknown，
绝不转换为 false、unreachable 或 covered。对几千级 D 直接集合枚举，不引入符号求解。

### P2.5 finite TG realization backend 与 legacy 退役

finite backend 把 coverage obligation 转为候选 Case：

1. 编译 obligation 为有限 predicate。
2. 提取直接等值赋值和 target Key pattern。
3. 查询 realization map、named binding、operator construction hints。
4. 构造一个或多个 knob assignment，随后 repair/normalise。
5. 用 finite predicate 作静态目标检查。
6. Host replay 裁决，只有 observed key 更新覆盖。

首批支持 optional_input_mode、csv_domain_cover、tiling_key_field_value、有限 tiling_key_relation、
dtype_layout_class、离散 runtime_variable_state、可映射 kernel_branch 和 L2 expected TilingKey pattern。

无法完成时明确输出 UNSUPPORTED_FINITE_REALIZATION、NO_CONSTRUCTION_PATH、AMBIGUOUS_BINDING、
HOST_REJECTED、NOT_RUN；不输出 SAT/UNSAT，也不把无候选解释为不可达。

finite 尚未覆盖的普通算子可显式使用 legacy Z3 做开发期对比；FAG 禁止 fallback。finite 验收通过前，
不物理删除旧 Z3 文件。

### P2 验收

- FAG 默认 UO/TG/closure 不导入 Z3，不构造 deep expr。
- finite predicate 对不支持操作保守失败。
- finite realization 的静态预测无法替代 Host observed key。
- 相同输入可命中缓存，任何相关 fingerprint 变化都会失效。
- 默认 UO 的内存、序列化字节数和 wall time 相对 P0 下降。
- 无重复 index/integrity 写入。
- legacy Z3 与 finite 比较结果有明确差异分类，而非静默回退。

## 7. 源码引理证书与 E 的激活

每条 E 规则定义机器可审计 schema：

~~~text
id / status / key pattern 或 predicate / human-readable statement
source refs / dependent symbols / source hash / TPL schema hash
matched D count / conflicting R count
boundary replay count / counterexample count
created revision / last verified revision
~~~

激活流程：

~~~text
结构校验
→ source ref/hash 校验
→ 在有限 D 上枚举适用 Key
→ 检查与全部 R 的冲突
→ 构造边界与最近 witness 的反例
→ Host replay
→ 激活或撤销
~~~

源码、TPL、BuildContext、InputSemantics 或 oracle protocol 改变时，相关引理自动进入
needs_reverify，在重新验证前不能继续作为 E 的权威来源。可选 solver 交叉检查不得成为独立权威，
也不得单独写入 E。

## 8. P3：Kernel Semantic IR

现有 KernelBranch 侧重 if constexpr，TilingData reader 仍有文本扫描成分，不能可靠回答同步、buffer
流转和性能瓶颈。P3 建立紧凑语义层：

| 节点 | 首批 FAG arch35 范围 |
| --- | --- |
| KernelFunction / KernelBranch / Loop | entry、Cube、Vec、NZ post、deter |
| SyncEvent | SetFlag、WaitFlag、PipeBarrier、跨核 flag |
| Buffer / QueueEvent | GM/L1/UB/L0 与 AllocTensor/EnQue/DeQue/FreeTensor |
| MemoryEvent | DataCopy、Load/Store、UB↔L1 搬运 |
| ComputeEvent | Mmad、vector、reduce、cast、softmax grad |

边类型为 selected_by、parameterized_by、controls、orders_before、reads、writes、pairs_with 和 calls。
首批检查只报告候选风险：flag 配对、buffer 生命周期、copy/compute/sync 时序；不确定项保持 unknown，
性能结论必须经 profile、仿真或硬件实测确认。

## 9. P4：基于 diff hunk 的 PR 影响分析

~~~text
git diff hunk
→ changed file + line range
→ Evidence/SourceSpan 命中
→ 直接受影响节点
→ 按边类型、方向、深度传播
→ TilingKey / TilingData / KernelSemantic / TestObligation 报告
~~~

按类型传播：TPL 变更影响 D、TemplateBlock、encode/decode、KernelBranch 与 coverage；host setter
影响 TilingData、predicate、roots 与 reader；kernel constexpr 影响控制维度和 branch coverage；
TilingData ABI 影响读写和布局兼容；sync/buffer 变更仅在 P3 语义边可用时传播。报告区分直接影响、
传播影响和未证实邻居，限制 depth/edge kind，禁止无向扫完整连通分量。

## 10. 执行顺序、交付物与删除标准

| 顺序 | 阶段 | 交付物 |
| --- | --- | --- |
| 1 | P0.1 | Oracle integrity、D/R/E 基线、证书 schema、分阶段性能报告 |
| 2 | P1.1 | sampling schema 校验和未消费字段失败测试 |
| 3 | P1.2–P1.4 | normalization-aware seed、input pairwise、mutation/residual diagnostics |
| 4 | P2.1–P2.2 | skeleton UO、SourceCorpus、流式产物、增量缓存 |
| 5 | P2.3–P2.5 | 去重 export/fold、finite predicate、finite realization、legacy 对比 |
| 6 | P3 | Kernel Semantic IR 与风险报告 |
| 7 | P4 | hunk 级 PR impact 报告 |

P2.4/P2.5 可与部分 P2 性能优化并行，但 finite backend 验收前不得删除 Z3 文件。

满足以下条件后删除 Z3：

1. FAG L0/L1/L2 和 full closure 默认路径不导入 Z3。
2. 固定预算下 finite 的真实新增 R 不低于旧流程。
3. legacy 能生成而 finite 不能生成的 obligation 全部具有明确 unsupported 分类。
4. 不存在由 Z3 UNSAT 生成 E 的代码。
5. 全部生产测试通过。
6. 删除 z3-solver 后 UO、TG、closure 和 query 测试仍通过。

## 11. 非目标

- 不把所有 Host C++ 翻译成通用数学/SMT 表达式。
- 不追求复杂循环、容器和程序点语义的完整 SMT 编码。
- 不将有限枚举未命中、生成器失败或 Host 未运行解释成不可达。
- 不以删除 Z3 为理由降低 D/R/E 的证据标准。
- 不要求 finite backend 对无限整数域给出完备证明。
- 不允许 finite backend 静默回退到 legacy Z3。
- 不在 finite 替代完成前直接删除普通 TG 的 legacy Z3 实现。
- 不在没有实测证据时宣称同步或 buffer 改动必然提升性能。
