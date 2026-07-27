# Host / Tiling Contract 重构记录

本文档记录 Understand-Operator（UO）Host 侧语义提取重构：Host Configuration Graph、Tiling Contract Graph、主链切流，以及以 FlashAttentionScoreGrad（FAG）为验收算子的端到端评估。

**不写入** `uo-init-联调问题与修复.md`；联调与重构结论以本文为准。

---

## 1. 目标与边界

### 1.1 目标

建立权威主链：

```text
operator_boundary + entrypoint_graph + confirmed scope + AscendC macro contracts
  → macro_facts.yaml
  → host_configuration_graph.yaml
  → tiling_contract_graph.yaml
  → extract_plan.yaml（仅物化视图，可删可重建）
```

权威方向固定为：**Host/Tiling facts → graphs → extract_plan**。禁止用 `extract_plan` 的 role 反推是否提取 Host field/key。

### 1.2 本轮范围

- 只做 Host 编译期/运行期配置、TilingData、TilingKey。
- 不做 Kernel CFG、测试求解、Impact。
- 可 AscendC / CANN 官方特化；**禁止算子名 / 算子仓特化**。

### 1.3 宏登记策略（硬约束）

| 来源 | 是否写入 `ascendc_macro_contracts.yaml` | 处理方式 |
|------|------------------------------------------|----------|
| CANN / AscendC 官方宏（`REG_OP`、`IMPL_OP_OPTILING`、`ASCENDC_TPL_*`、`BEGIN_TILING_DATA_DEF`、`GET_TPL_TILING_KEY` 等） | **是** | 合同 + 源码 invocation 物化 |
| 算子仓 `#define` 自定义宏（如 FAG 的 `TND_TILING_DATA_COMMON_ASSIGN` / `BASE_TILING_DATA_COMMON_ASSIGN`） | **否** | 源码发现：形态匹配 `recv = &root->nested` 后参数替换 |
| 业务维度名 / layout 语义（如 `IsTnd`） | **否** | 作为 Key 声明产物出现，不是 AscendC 特有宏 |

原则：**能在算子源码里找到定义的宏，一律不登记合同。**

---

## 2. 架构与产物

### 2.1 核心模块

| 阶段 | 模块 | 产物 |
|------|------|------|
| Schema / 宏 | `host_contract_schema.py`、`macro_token_scanner.py`、`ascendc_macro_facts.py`、`macro_entrypoint_projection.py` | `ir/macro_facts.yaml` |
| 编译上下文 | `host_compile_context.py` + 可选 Clang adapter | `ir/host_compile_context.yaml` |
| Host 图 | `host_configuration_builder.py` | `ir/host_configuration_graph.yaml` |
| Tiling 合同 | `tiling_data_*`、`tiling_key_*`、`tiling_contract_builder.py`、`receiver_binding.py` | `ir/tiling_contract_graph.yaml` |
| 缺口与视图 | `resolve_host_contract_gaps.py`、`materialize_extract_plan_view.py`、`host_contract_pipeline.py` | `ir/extract_plan.yaml`（view） |
| 门禁 / 解释 | `host_contract_gates.py`、`host_contract_explain.py`；CLI `explain-host-value` / `explain-tiling-field` / `explain-key-dimension` | — |

### 2.2 图状态语义

- `contract_status: producer_only` — 本轮只生产 Host/Tiling producer 侧合同，不含 kernel consumer。
- `kb_status: partial` — 允许 unresolved；完整性由 gates 与 pending capabilities 显式标记。
- `pending_capabilities` 典型：`kernel_variant`、`kernel_execution`、`bridge_consumer`。

---

## 3. FAG Host 端到端评估

验收路径：

`TEST/ops-transformer/attention/flash_attention_score_grad`  
（公共代码：`TEST/ops-transformer/attention/common`）

IR 快照目录：

`.../flash_attention_score_grad/.ascendc-pilot/uo/ir/`

### 3.1 正确性（骨架正确，闭合不足）

**正确的部分：**

1. **主链方向正确**：`macro_facts → host_configuration → tiling_contract → extract_plan(view)`，`extract_plan.materialized_view: true`，`authoritative` 不在 plan 侧。
2. **官方宏识别正确**：FAG 上可见 `IMPL_OP_OPTILING`、`REGISTER_TILING_TEMPLATE_WITH_ARCH`、`BEGIN/END_TILING_DATA_DEF`、`TILING_DATA_FIELD_DEF`、`ASCENDC_TPL_*`、`GET_TPL_TILING_KEY` 等（约 196 次 invocation / 27 文件）。
3. **Schema / Field / Key 骨架正确**：
   - TilingSchema / Variant 各约 25；
   - TilingField 299；
   - FieldWrite 128；
   - KeyDimension 19（含 `IsTnd`、`IsTndSwizzle` 等**业务维度名**，属于 FAG Key 声明内容，不是 AscendC 合同宏）；
   - RegisteredTemplatePattern 65；ObservedKeyComposition / KeyReturnComposer 各 7。
4. **状态标记诚实**：`producer_only` + `partial`，未假装已打通 kernel。

**不正确 / 不完整的部分：**

1. **跨过程调用闭合弱**：Host Configuration 有 699 条 unresolved，**全部为** `HOST_CALL_TARGET_AMBIGUOUS`。实体虽多（597），边仅 138，说明大量 callee 未能锚定。
2. **Field 绑定与取值链未闭合**：Tiling Contract 573 unresolved，主要分布：
   - `VALUE_SOURCE_UNRESOLVED` ≈ 221
   - `RECEIVER_IDENTITY_AMBIGUOUS` ≈ 145
   - `TILING_SCHEMA_VARIANT_AMBIGUOUS` ≈ 124
   - `TILING_KEY_ARGUMENT_UNGROUNDED` ≈ 78
   - `TILING_KEY_ARITY_MISMATCH` ≈ 5
3. **extract_plan 物化偏瘦**：仅约 12 writers / 4 receivers（tiling_writer 11 + key_writer 1），远少于 FieldWrite(128) 与 Key 组合(7)。说明 view 目前是保守投影，不是完整 Host 合同导出。
4. **Clang 编译上下文降级**：`host_compile_context` 仍可用，但深度类型/调用图依赖不足，加剧 call-target 歧义。

**总评（正确性）：** 骨架与官方宏路径正确；**端到端“值从 InputRoot 落到 Field/Key”的闭合尚未正确完成**，当前更接近「可解释的部分图」，不是可依赖的完整 Host 合同。

### 3.2 完整性

| 能力 | 状态 | 说明 |
|------|------|------|
| 官方宏事实 | 较完整 | FAG 关键宏类覆盖好 |
| Entrypoint / template 注册 | 较完整 | Normal/Varlen Regbase 等可见 |
| TilingData schema 声明 | 较完整 | BEGIN/FIELD/END + nested |
| Receiver binding（含算子仓宏） | 部分 | 依赖同文件 `#define` 发现 + 参数替换；曾误用 `TND_` 硬编码，已改为源码发现 |
| HostValue 跨过程 | 不完整 | 几乎全部 call 目标歧义 |
| FieldWrite ← HostValue | 不完整 | VALUE_SOURCE / RECEIVER / VARIANT 三类缺口最大 |
| Key 参数接地 | 部分 | 维度声明在；实参 ungrounded 仍多 |
| Kernel / Bridge | 未做 | 明确 pending |

**总评（完整性）：** Host 贯通目标完成约 **40%–55%**（骨架 + 声明侧偏强，赋值/跨过程闭合偏弱）。不足以宣称 FAG Host 合同已端到端完整。

### 3.3 速度

基于同一 IR 快照的 `timing_ms`（种子 scope，非全仓无脑扫描）：

| 阶段 | 耗时（约） |
|------|------------|
| `host_compile_context` | ~1.2 s |
| `macro_facts` | ~6.3 s |
| `host_configuration_graph` | ~2.3 s |
| `tiling_contract_graph` | ~12.8 s |
| **Host 合同主链合计** | **约 20–25 s 量级** |

观感：

- 种子 / confirmed scope 下 **可接受**（数十秒内出图）。
- 瓶颈在 **tiling_contract_builder**（~13 s）与 **macro_facts**（~6 s）。
- 若放大到全量 `attention/common` + 无过滤 scope，耗时会明显上升；历史全量 scope smoke 曾出现挂起，生产路径应坚持 confirmed/seed scope。
- Clang 降级时“快但不准”；若启用完整 AST，预期变慢但有助于降低 `HOST_CALL_TARGET_AMBIGUOUS`。

**总评（速度）：** 当前种子路径速度可用；完整性不足主要不是“跑得慢”，而是 **调用解析与 binding 闭合算法深度不够**。优先补正确性，再谈加速。

---

## 4. TND / 算子仓宏：禁止特化

### 4.1 问题

`TND_` / `BASE_TILING_DATA_COMMON_ASSIGN` **不是** AscendC 官方宏，而是 FAG（及同类算子）在仓内 `#define` 的便捷包装，展开形态仍是：

```cpp
params_ = &(tilingData)->tndBaseParams;
```

曾在 `receiver_binding.py` 用 `(?:TND_|BASE_)?TILING_DATA_COMMON_ASSIGN` 硬编码，属于**算子仓特化**，违反“可 AscendC 特化、禁止算子特化”。

### 4.2 修正

- `receiver_binding.py`：扫描源码 function-like `#define`，仅当宏体（含 `##` 拼接经哑元替换后）呈 `recv = &root->nested` 时视为 binding 宏；对 invocation 做参数替换后产出 binding。
- `semantic_observations.py` / `relation_evidence.py`：去掉对 `COMMON_ASSIGN_MACRO_RE` 硬编码名的依赖，改为 `list_discovered_binding_macro_names`。
- `ascendc_macro_contracts.yaml`：notes 明确**只登记 CANN 包官方宏**；不登记任何算子仓宏。

`IsTnd` 等出现在 `declared_key_space.dimensions` 中是 **Key 声明事实**，不是宏合同条目。

---

## 5. 已知缺口与后续优先级

1. **降低 `HOST_CALL_TARGET_AMBIGUOUS`**：加强 HostFunctionSummary / 同 TU 符号表 / 可选 Clang；这是 HostValue 链闭合的主阻塞。
2. **收紧 receiver → schema variant**：减少 `RECEIVER_IDENTITY_AMBIGUOUS` / `TILING_SCHEMA_VARIANT_AMBIGUOUS`（同文件宏发现已覆盖一类；跨文件 define 需 include 闭包合并）。
3. **FieldWrite 值源接地**：把已解析 HostValue 挂到更多 FieldWrite，压降 `VALUE_SOURCE_UNRESOLVED`。
4. **Key 实参接地**：对齐 `GET_TPL_TILING_KEY` arity 与维度选择，压降 ungrounded / arity mismatch。
5. **extract_plan view**：在图闭合改善后，按边（WRITES_FIELD / COMPOSES_KEY）物化更完整的 writers，而不是过瘦列表。
6. **Kernel / Bridge**：本轮明确不做；待 producer 侧 unresolved 可控后再开。

---

## 6. 测试与验收

- 通用：`engines/understand-operator/tests/test_host_contract_phase1..5.py`
- FAG smoke：`tests/test_host_contract_fag_smoke.py`（路径参数化，生产代码无 FAG 硬编码）
- 相关：`test_semantic_relation_graph.py`（binding 宏观测改为源码发现）

验收口令：

- 合同 YAML 中**不得**出现 `TND_` / `BASE_TILING_DATA_COMMON_ASSIGN` 等算子仓宏名。
- 同类 binding 宏仅当源码可见 `#define` 时被解析。
- FAG IR 可再生产 `producer_only` / `partial`，且主链四件套存在。

---

## 7. 结论（给决策用）

| 维度 | 结论 |
|------|------|
| 正确性 | 主链与官方宏骨架正确；跨过程与 Field/Key 值链**尚未正确闭合** |
| 完整性 | 声明侧较好，赋值/调用侧缺口大；整体约半程 |
| 速度 | 种子 scope ~20–25 s，可用；全量 scope 需继续约束 |
| 特化纪律 | TND 类改为源码发现；合同仅 CANN 官方宏 |

当前结果：**适合作为 Host 合同重构的可运行基线与可解释中间态，不适合作为“FAG Host 端到端已正确完整”的交付结论。**

---

## 8. 闭合优化轮次（未闭合 &lt;50）

### 8.1 目标

- `hcg.counts.unresolved + tcg.counts.unresolved` **&lt; 50**，目标个位数
- `skipped_external_calls` 单独计数，不计入 unresolved
- 禁止算子名 / 仓内宏名特化；仓内 binding 宏继续源码发现

### 8.2 策略摘要

1. **HCG 调用分类**：stdlib / `OP_*` / GE accessor / setter → `skipped_external_calls`；仅 `internal_candidate` 做跨过程；miss→`NOT_FOUND`，多候选→`AMBIGUOUS`
2. **启用 GETTER_RE + 调用图闭包摘要**；`FUNC_DEF_RE` 排除控制关键字伪函数
3. **Include 闭包 Macro/GTD 索引**；整文件 binding；嵌套 `root->nested.set_x`；过滤本地聚合 `fBaseParams.x=` 假 FieldWrite
4. **Key 按 ARGS_DECL 作用域 + 实参 arity 选组**；禁止跨 TU 用最大无关 DECL；cast/成员实参不强制 HostValue
5. **FAG smoke 门禁**：默认 `sum < 50`（`UO_HOST_UNRESOLVED_LIMIT` 可调）

### 8.3 FAG 结果（本轮）

| 指标 | 基线（§3） | 本轮 |
|------|------------|------|
| HCG unresolved | 699 | **0** |
| TCG unresolved | 573 | **0** |
| 合计 | ~1272 | **0** |
| skipped_external_calls | — | ~1124 |

门禁与单测：`tests/test_host_contract_fag_smoke.py`、`tests/test_host_contract_closure.py`。

### 8.4 说明

合计到 0 表示**当前种子 scope 下 producer 侧未闭合项已清零**，不代表 Kernel/Bridge 已完成，也不代表任意全仓 scope 仍为 0。扩大 scope 或换算子时应继续看 reason 分布，禁止靠清空 unresolved 过门禁。
