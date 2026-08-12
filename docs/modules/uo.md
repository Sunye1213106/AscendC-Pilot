# UO：理解算子

UO（Understand Operator）不是把 AscendC 源码做成普通的调用图。它建立的是一条可追溯的跨层关系：Host 条件如何派生状态、如何写入 TilingKey/TilingData、如何选择模板与 Kernel，以及这些值最终如何影响编译期或运行时分支。这个模型叫作 **Operator CodeMap**。

## 为什么需要 UO

一个典型算子中的关系可能是：

```text
Host input / condition
  -> derived field
  -> SetTilingKey / SetTilingData
  -> template selection / constexpr
  -> kernel selection / runtime branch
```

这些步骤常跨文件、宏、模板和构建变体。仅靠文本搜索或 call graph 难以判断一条关系是否真实存在、受什么条件约束、是否在当前架构下可达。UO 把可由编译器事实和确定性 pass 证明的部分固化为 CodeMap，让 TG 和 CE 不必从头理解源码。

## 从源码到 CodeMap：主线

```text
Operator + Architecture
  → Source Scope / BuildVariant
  → Host Compiler Facts
  → TilingKey / TilingData
  → Template / Compile-time
  → Kernel Identity / Call Boundary
  → AscendC Root Trace
  → Unified CodeMap + unresolved
```

`/uo-init` 管线阶段：

| Phase | 输入 | 做什么 | 输出 |
| --- | --- | --- | --- |
| `prepare` | operator root、architecture | 发现 layout、构建变体和源码范围 | 已校验的源码范围 |
| `extract` | 源码范围 | 通过 Clang 抽取 CompilerFacts | declaration、AST、编译上下文等事实 |
| `analyze` | CompilerFacts | 运行确定性 CodeMap passes | 语义 IR、relations、unresolved |
| `commit` | analyzed IR | materialize 正式产品 | `<op_name>.<arch>.uo` |
| `verify` | `.uo` | 校验结构、合同和导出视图 | 已验证的 CodeMap |

五个阶段均由 **deterministic execution** 执行（`execution_mode=deterministic`），不经 LLM 生成 canonical CodeMap。

---

## 提取与编译原理

UO **不复现**算子工程的真实 CMake/Ninja 构建，也**不消费** `compile_commands.json`。它用一套 CANN 感知的合成编译上下文，让 Clang 在与目标架构一致的宏/头文件语义下解析 Host 与 Kernel TU，再从 AST 抽出可定位事实。

```text
build_context.yaml  +  CANN Headers  +  Clang/libclang
        │
        ▼
  BuildVariant（-I / -D / -std / target …）
        │
        ├─ prepare：layout → include 闭包 → probe 可解析性
        ├─ extract：libclang AST walk → CompilerFacts（可选 clang -ast-dump 折叠模板）
        └─ analyze：确定性 CodeMap passes（不经 LLM）
```

| 组件 | 作用 |
| --- | --- |
| `spec/build_context.yaml` | 手写/仓内维护的 Host、Kernel 编译参数模板（include、define、flags） |
| CANN Headers | AscendC / 运行时头文件；提供真实类型与 API 语义（见 [安装](../getting-started/installation.md)） |
| **libclang**（`clang.cindex`） | 主路径：解析 TU、诊断、include 闭包、AST walk → `CompilerFacts` |
| **clang 驱动**（可选） | `clang -fsyntax-only -Xclang -ast-dump`：补 libclang 看不到的模板显式实例 / `if constexpr` 折叠 |
| 仓内 `compat/` prelude | 补齐解析所需 shim，避免把整份算子工程构建系统拖进来 |

**prepare（范围，不是抽关系）**

1. 发现算子 layout 与 `arch*`，写入 `BuildVariant`。
2. 用 libclang 的 include 闭包确定 Source Scope（真实编译依赖，不是目录点选）。
3. 对 Host TU / Kernel entry 做 probe（可跳过函数体）；算子源码侧 fatal / error 则失败并回到 `prepare`。

**extract（编译期事实）**

1. 按 `BuildVariant` 拼出 `host_args` / `kernel_args`，对范围内 TU 做完整 AST walk。
2. 产出 `CompilerFacts`：函数、call site、写点、控制流守卫、字段/局部声明、不透明宏守卫、源位置等——**尚无 AscendC 语义解释**。
3. 需要折叠模板实例时，另跑 clang `-ast-dump`；TU walk 结果可落盘缓存（`uo/cache/tu/`）。

**analyze（语义关系）**

在 CompilerFacts 上跑确定性 passes，得到 TilingKey / TilingData / template / Kernel / Root Trace 等关系；证不全的写入 `unresolved.yaml`。Canonical `.uo` 只由这条确定性链路写入。

要点：解析语义 ≈「当前架构 + CANN 头 + build_context」下的 Clang 视图；换 CANN 版本或架构应重跑 UO，而不是手工改 `.uo`。

---

## 1. Source Scope / BuildVariant

UO 从 operator root 和 architecture 开始，但不会把“用户手选的目录列表”当作完整输入。

```text
operator root + architecture
  -> layout discovery
  -> 构建变体 / compile context
  -> include and dependency closure
  -> 源码范围
```

**提取什么**：算子布局、`arch*` 变体、真实参与编译的 TU 与 include 闭包。  
**结果是什么**：当前架构下的 Source Scope——事实边界，不是目录清单。

算子目录外的 common header 只要确实是编译依赖，就应进入；相邻但不参与当前构建的源码不应凭猜测进入。源码范围失败会让 `/uo-init` 回到 `prepare`。

实现层：`frontend/`（layout / BuildVariant / scope）、`build_context.py`、`scope_scan.py`。

---

## 2. Host Compiler Facts

在 Source Scope 上，UO 用 **libclang**（必要时辅以 clang `-ast-dump`）在 CANN 编译上下文中抽取 CompilerFacts。

**提取什么**：声明、AST 可观察的 call/write/control、类型与符号线索、宏不透明守卫、源位置。  
**结果是什么**：可在当前 BuildVariant 语义下定位的编译期事实层——后续关系的证据底座，不是最终 CodeMap。

实现层：`frontend/clang.py`、`clang_walk.py`（可选 `harness.py` 做模板折叠）。

---

## 3. TilingKey

在 Host 侧事实之上，确定性 pass 恢复 TilingKey 的定义与赋值关系。

**提取什么**：key schema / packing、`SetTilingKey` 与相关 Host producer、维度与编码方式、与输入/派生状态的关联。  
**结果是什么**：TG 可消费的 legal key domain 与 “Host 条件 → key 维” 关系；无法闭合处记入 unresolved。

实现层：`passes/`（Host TilingKey / def-use）。

---

## 4. TilingData

与 TilingKey 对称，追踪 Host 写入与 Kernel 读取。

**提取什么**：TilingData 字段、Host 写点、Kernel 读点、字段完整性和跨侧绑定。  
**结果是什么**：`Host write → TilingData field → Kernel read` 可追溯链，供 CE 影响分析与 TG L3 使用。

实现层：`passes/`（TilingData host writes / kernel reads）。

---

## 5. Template / Compile-time

AscendC 大量行为由模板参数、宏和编译期分支决定。

**提取什么**：模板 schema / 实例、宏展开相关事实、constexpr / 编译期条件对路径选择的约束。  
**结果是什么**：编译期选择与 Host/Kernel 实体之间的关系；不把猜出来的实例当成事实。

实现层：`passes/`（template / compile-time / macro）。

---

## 6. Kernel Identity / Call Boundary

在 Kernel 侧建立身份与调用边界，而不是执行时序仿真。

**提取什么**：Kernel 实体身份、调用边界、与 Host / tiling 的绑定、可解析范围内的 call 关系。  
**结果是什么**：Kernel 入口与边界视图，以及通往 AscendC/CANN API 的调用线索。

实现层：`passes/`（kernel identity / call boundary）。

---

## 7. AscendC Root Trace

Kernel 分析与 Host 对称：回答对象 / 类型 / 调用能否追到 AscendC / CANN root。

```text
source facts
  -> compiler-grounded type / alias / member / call relations
  -> AscendC / CANN root seeds
  -> single reverse fixed-point
  -> REACHED / UNRESOLVED / EXTERNAL
```

**提取什么**：LocalTensor / Buffer / sync 等对象经项目 wrapper 到 root 的路径。  
**结果是什么**：REACHED / UNRESOLVED / EXTERNAL 标注及源码位置。

Canonical Kernel UO **不**做执行时序分析：不推断 exec_rank、RAW/WAR/WAW、sync pairing、CopyIn/Compute/CopyOut pipeline、buffer lifecycle 或引擎调度。无法可靠闭合的路径保持为 unresolved。

实现层：`passes/`（root trace）。

---

## 8. Unified CodeMap 与 `.uo` 产品

各层关系归一到统一 IR，并由 `commit` materialize 为正式产品：

```text
.ascendc-pilot/uo/<op_name>.<arch>.uo
```

### `.uo` 是什么

`<op>.<arch>.uo` 是 **SQLite 数据库**（schema：`codemap-uo/v1`），不是 YAML/JSON 文本。它是对外唯一的 canonical Operator CodeMap：Query / TG / CE 都读它；只有 UO 确定性 `commit` 可写。

可用普通 SQLite 工具打开（只读排查），但不要手工改库内容——应走 `/uo-init` 或 `/uo-update`。

### 库里有什么

| 表 | 内容 |
| --- | --- |
| `meta` | 产品元数据：schema、authority、op_name、architecture、生成时间、实体/关系计数、fingerprint 等 |
| `build_variant` | 当前架构下的构建变体（宏、include、编译参数等） |
| `entity` | CodeMap 节点：kind、name、status、confidence、源码位置、完整 JSON `data` |
| `relation` | 有向边：kind、src、dst、status、confidence、完整 JSON `data` |
| `file` | 涉及的源文件路径与角色 |
| `source_span` | 实体到 `path:line`（及短 snippet）的定位 |
| `attribute` | 实体属性键值（便于查询） |
| `view_blob` | 导出视图与摘要（JSON），至少含 `summary`；TG 还依赖如 `ir/tg_host_view.yaml`、`ir/operator_graph.yaml` 等投影 |
| `predicate` / `provenance` | 谓词与溯源槽位（schema 预留；随 passes 填充） |

**实体（节点）典型 kind**：`BUILD_VARIANT`、`TILING_KEY` / `TILING_DATA` / `TILING_FIELD`、`KERNEL`、`TEMPLATE*`、`FUNCTION` / `VARIABLE` / `FIELD`、`BRANCH` / `PREDICATE`、`BUFFER` / `REGISTER` / `OPERATION` 等。

**关系（边）典型 kind**：`WRITES` / `READS` / `CALLS`、`DERIVES` / `FLOWS_TO` / `CONTROLS`、`BINDS` / `INSTANTIATES`、`SELECTS` / `LAUNCHES`、`WRAPS` / `ROOTED_AT` 等——把 Host 条件、Tiling、Kernel、AscendC root 串成可追溯图。

```text
meta + BuildVariant
  + entities / relations（跨层图）
  + source_span（证据定位）
  + view_blob（summary + TG/CE 投影）
  = 一个可查询的 Operator CodeMap
```

**Unresolved 是正式结果**：静态证据不足、关系含糊、依赖外部系统或不受支持时，应记录为 unresolved，而不是由 LLM 补写 canonical `.uo`。调查 Agent 可以分类并产出 bounded report；确定性引擎仍是规范 CodeMap 的唯一写入者。

实现层：`store/schema.py`、`store/writer.py`、`ir/`、`workflow.py`（commit / verify）；query/update 见下文。

---

## 四条 UO 工作流

```text
Source -> CodeMap -> {/uo-query 只读消费 | /uo-update 受控增量刷新 | /uo-investigate 调查 gap}
```

`/uo-init` 从源码建立新的 CodeMap：`prepare -> extract -> analyze -> commit -> verify`。

`/uo-update` 在源码或 build 指纹变化后执行 `detect -> plan -> apply -> export -> diff`。基于 fingerprint 的受控刷新，不是在 YAML 上随意打补丁；只需查看变化时可走 `diff_only`。

`/uo-query` 经过 `route -> lookup -> answer` 回答已有 CodeMap 上的问题。可借助模型解释，但不得改写 canonical CodeMap。

`/uo-investigate` 调查 unresolved residual：分类根因、指出确定性引擎还缺什么能力，产出 bounded report。不修改 canonical `.uo`。

---

## 与 TG、CE 的衔接

TG 消费 CodeMap、TilingKey domain、Host/Kernel projection 与 unresolved 来建立义务账本。CE 消费 relation view 分析改动对 Host 状态、TilingData、predicate 和 Kernel 分支的影响。二者都不应重新建立完整源码权威。

UO 负责如实交付可证明关系及其未知部分；TG 决定哪些测试义务可通过 replay 或可靠排除关闭。

---

## 失败、恢复与实现

源码范围问题回到 `prepare`；抽取问题回到 `extract`；完整性或 gap 问题回到 `analyze` 或 `commit`；验证失败按原因重跑对应阶段。恢复边由 workflow spec 声明。

实现入口：`engines/understand-operator/src/uo_init/workflow.py`、`frontend/`、`passes/`、`ir/`、`update/`、`query/`；运行时合同位于 `pilot/ascendc_pilot/workflows/specs.py`。精确阶段见 [Workflow Reference](../reference/workflows.generated.md)。
