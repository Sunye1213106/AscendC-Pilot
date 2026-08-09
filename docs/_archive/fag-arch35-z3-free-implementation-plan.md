# FlashAttentionScoreGrad（arch35）优化计划：Z3-free 实施版

## 1. 决策、范围与基线

本文件是 FAG arch35 的唯一实施依据。目标是以有限域 predicate、确定性输入构造、Host replay 和
源码引理证书闭合 TilingKey 覆盖；FAG 的生产路径不允许加载或回退到 Z3。现有 `memory/` 模块不是
CBM，保留；`D:\TEST\ops-transformer\attention\flash_attention_score_grad\.ascendc-pilot` 是可再生
缓存，不能作为代码事实或验收来源。

| 基线 | revision |
| --- | --- |
| AscendC-Pilot | `c099dd12c879a75dae393a31ac0419a438dd91c6` |
| FAG arch35 工作树 | `4e09c2ec15a414f6e312caf5b3da16cd965af07b` |

## 2. D/R/E 的严格定义与失效规则

```text
D_tpl = 所有已声明、可 decode 的 ARGS_SEL packed key
D = { k in D_tpl | 所有“可精确解释”的 TPL relation/pruning 对 k 为 TRUE }
R = 真实 Host 完整执行且实际观测到的 witness key
E = 有完整源码引理证书、经反例策略验证的不可达 key
U = D - R - E
完成条件：U = ∅ 且 R ∩ E = ∅
```

`UNKNOWN` 或 `UNSUPPORTED` 绝不可从 `D` 剔除，也不能写入 `E`。`matched(D) ∩ R = ∅` 和 replay
仅是证书的必要条件，不能单独证明不可达。

| 变更 | 必须失效 / 重算 | 历史产物用途 |
| --- | --- | --- |
| TPL、ARGS_SEL、encode/decode | `D`；相关 `E` 全量复验 | `R` 降为 replay corpus |
| Host setter / 控制流 | 受影响 `R` replay；依赖符号的 `E` 复验 | 未重放 `R` 不算当前事实 |
| InputSemantics / repair | 全部受影响历史输入 replay | 旧 `R` 不可直接复用 |
| Oracle protocol | 全量 replay | 旧结果仅可审计 |
| Kernel-only | Kernel IR/fold/profile | 不失效 Host `D/R/E` |
| header/macro/template | 其 include/macro/template 依赖闭包 | 按闭包复验 |
| 文档、注释、非语义测试 | 无 | 无 |

## 3. 有限域 predicate 与 Oracle 账本

### 3.1 四值解释器

结果固定为 `TRUE`、`FALSE`、`UNKNOWN`、`UNSUPPORTED`。schema 必须规定 missing/null、enum、bool、
整数宽度和 signedness；`and/or/not/implies` 使用四值传播表，`requires/mutex/compatible_set` 具有
固定字段结构。每次判断保存 rule id、输入、类型转换、子表达式路径和最终证据。异常、未知和不支持
都不能转换成 false、unreachable 或 covered。

### 3.2 Oracle accounting

每批次同时记录 `generated`、`normalised_unique`、`serialized`、`driver_started`、
`accepted`、`rejected`、`crashed`、`not_run`、`parse_failed`，并强制：

```text
requested = accepted + rejected + crashed + not_run + parse_failed
judged = accepted + rejected
actually_run = accepted + rejected + crashed
```

只有实际 Host observed key 可写 `R`；`not_run`、crash、parse failure 和构造失败均不是模型负例。

## 4. 源码引理证书

每个 `E` 规则包含 key predicate、可读结论、源码定位/hash 和以下字段：

```text
proof_scope: target_dimensions, relevant_functions, assignments, guards
assumptions
completeness_evidence: assignment_sites_complete, call_closure_complete,
                       alias_state_exact, macro_context_complete
counterexample_strategy: D enumeration, R conflict, boundary/nearest replay
```

缺任意 `completeness_evidence` 即为 `needs_evidence`，不能激活。证书变更/依赖变更后先撤销到
`needs_reverify`；有限域枚举、`R` 冲突检查和边界 replay 都通过，且反例策略没有找到 witness，才可
重新进入 `E`。

## 5. SourceCorpus、缓存与 CBM 退役

`SourceCorpus` 只持久化文件清单、文本/bytes、content hash、line index、include graph 与 role/span
index。TU、cursor、token 和 native pointer 只存在于不可持久化、不可跨进程共享的
`ProcessLocalClangCache`。函数缓存 fingerprint 至少含 function token hash、transitive include hash、
macro hash、template/NTTP、编译 flags、Clang/CANN header/extractor/schema 版本；调用 SCC 使用 fixpoint
失效。

### 5.1 CBM 删除 / 替换清单

| 类别 | 实施动作 |
| --- | --- |
| DELETE | `cbm_client.py`、`cbm_lookup.py`、`cbm_metadata.py`、`test_cbm_lookup_cli.py`、CLI CBM 命令、`--cbm-project`、doctor 的 CBM 检查、安装器 CBM 下载/帮助、`.tmp-cbm-install/` 忽略项 |
| REPLACE_WITH_UO | symbol/span → SourceCorpus；calls/impact → UO 图；window → `SourceSpan` 有界读取；SQLite → `uo/kb_graph.sqlite` |
| MIGRATE_ARTIFACT | `uo/cbm/index_meta.json`、`cbm_project`、`cbm_db_path` 等协议字段全部去除；不提供迁移器，只给安全清理说明 |
| KEEP_NON_CBM | `pilot/ascendc_pilot/memory/` |

完成时添加 negative gate：对生产代码、安装器、配置、runtime prompts/skills 执行 CBM 正则扫描，只有
专用 allowlist（本计划/历史迁移说明）可命中；fresh install 不安装、不调用 CBM，也不触碰用户外部
CBM 数据。

## 6. 分阶段实施与切换条件

```text
P0.0 CBM 审计、删除、替换、negative gate
P0.1 Oracle integrity 与 FAG 基线
P0.2 四值 finite predicate core
P0.3 D/R/E artifact + certificate schema
P1   seed / pairwise / mutation / residual diagnostics
P2.1 skeleton 并行实现
P2.2 skeleton vs deep 差分门禁
P2.3 FAG 默认切 skeleton
P2.4 停止生成 deep artifact
P2.5 export/cache/fold 优化
P2.6 finite backend shadow
P2.7 FAG finite 默认
P2.8 operator allowlist 扩大
P2.9 删除 legacy Z3 依赖
P3   Kernel Semantic IR
P4   双边 diff-hunk impact
```

绝不在 P2.2 差分门禁前删除 deep 路径或产物。跨算子迁移严格经过 A shadow、B FAG default、C
allowlist、D global finite、E delete Z3 五阶段。

### 6.1 P0–P1 验收

- 19 维 key decode 后 encode 必须回等；`D` 不依赖 solver。
- P0 基线输出分段耗时、峰值内存、文件/字节数和 Oracle 全量账本。
- 所有 sampling 字段必须被 `InputSemantics.knob_schema()` 消费或显式 alias；未知字段失败。
- 固定 seed 可复现；统计口径为 normalised 后唯一输入；派生 key 只能当目标，不能伪造输入。

### 6.2 P2 skeleton 与 finite 验收

skeleton 仅生成 source/provenance、free variable、def site、guard、abstract exactness 与
`FeatureTerm`；不得“先造 value_expr 再剥离”。抽象域为 `CONSTANT`、`DIRECT_INPUT`、
`DERIVED_INPUT`、`INPUT_DERIVED_HOST_STATE`、`PARTIAL_HOST_STATE`、`LOOP_ELEMENT`、
`PLATFORM_FIXED`、`UNKNOWN`、`CONFLICT`，并单调传播。深路径抽样差分可以保守超集，但不得产生
false-positive `input_derivable=true`。

finite 与 legacy 在固定 seed/预算下，按 obligation kind 对比：`R` 数量、义务覆盖、可执行 case 比、
每 Host 调用新增 `R`、normalised unique、unsupported rate、最差退化和复现性。FAG 强制类别的
unsupported 必须为零；否则不能切换默认。

### 6.3 Z3 包装与最终删除

迁移期保留 `legacy-solver = ["z3-solver>=4.12"]`，默认安装不带 solver extra。同步修改
`engines/testcase-generation/pyproject.toml`、`install.ps1`、`install.sh`、README、CI 和 lockfile。
P2.9 前必须证明生产代码无 `z3` import/Z3Backend 调用、无 solver extra/lock entry，且在无 Z3 环境
通过 UO、TG、closure、query 全套测试。

## 7. Kernel IR 与 PR 双边影响

Kernel IR 首批抽取 pipeline、pipe、event、template args、loop iteration、pingpong、buffer identity、
cross-core 及 macro/wrapper 展开。无法唯一配对的同步关系输出 `UNRESOLVED_SYNC_PAIRING` 或
`MULTIPLE_PAIR_CANDIDATES`，不得报确定缺陷。

PR impact 以 `OldSourceSpan`/`NewSourceSpan` 和 add/delete/modify/move/rename 为输入，同时保留
old/new 图，按 include、macro、template 依赖传播；输出直接影响、传播影响、未证实邻居，禁止把整个
连通分量当作影响范围。

## 8. 本轮执行边界

本轮从 P0.0 开始：删除真实 CBM 依赖、以 UO/SourceCorpus 替换接口、增加防回归扫描，并执行相应
单元/CLI 回归。不会删除 Z3 或修改 FAG 数值 kernel；后续阶段须以本文件的差分数据与门禁为前提。
