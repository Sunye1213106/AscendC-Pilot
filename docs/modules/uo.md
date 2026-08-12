# UO：理解算子

UO（Understand Operator）不是把 AscendC 源码做成普通的调用图。它建立的是一条可追溯的跨层关系：Host 条件如何派生状态、如何写入 TilingKey/TilingData、如何选择模板与 Kernel，以及这些值最终如何影响编译期或运行时分支。这个模型叫作 **Operator CodeMap**。

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

`/uo-init` 分五步，全部由确定性程序执行，**不经大模型**写正式 CodeMap：

| 阶段 | 输入 | 做什么 | 输出 |
| --- | --- | --- | --- |
| `prepare` | 算子目录、目标架构 | 认清目录结构、构建变体，划定要解析的源码范围 | 已校验的源码范围 |
| `extract` | 源码范围 | 用 Clang 抽出编译期可见事实（声明、语法树、调用/写点等） | CompilerFacts（原始事实，尚无业务解释） |
| `analyze` | CompilerFacts | 按固定规则串成跨层关系（TilingKey、TilingData、Kernel 等）；证不全的记下来 | 语义关系图 + unresolved（未闭合项） |
| `commit` | 分析结果 | 写入正式产品文件 | `<op_name>.<arch>.uo` |
| `verify` | `.uo` | 检查结构是否完整、约定视图能否读出 | 已验证的 CodeMap |

---



## 提取与编译原理

UO **不跑**算子仓自己的 CMake/Ninja，也**不用** `compile_commands.json`。它准备一套和目标架构一致的「假编译环境」（CANN 头 + 编译参数），让 Clang 按真实宏/头文件语义读 Host 与 Kernel，再从中抽出可定位的事实。


| 需要什么                                | 干什么                                                                      |
| ----------------------------------- | ------------------------------------------------------------------------ |
| **clang 可执行文件**（必选）                 | 真正按编译参数解析；并用 `-ast-dump` 看到模板实例、`if constexpr` 折叠后的结果（仅靠 libclang 看不到这些） |
| **libclang**（Python 绑定，必选）          | 走 AST、算 include 闭包、抽出函数/调用/写点等 `CompilerFacts`                           |
| `build_context.yaml` + CANN Headers | 提供 `-I/-D` 与 AscendC 类型/API 语义                                           |
| 仓内 `compat/`                        | 少量 shim，免去拖入整套工程构建系统                                                     |


流程可以看成三步：

```text
准备环境（BuildVariant）
    → 看清要解析哪些文件（prepare）
    → Clang 抽出编译期事实（extract）
    → 确定性规则串成 CodeMap（analyze）
```

1. **prepare**：认清算子布局和 `arch`*，用 include 闭包划定 Source Scope（真依赖进、猜的不进），并探针能否解析。
2. **extract**：对范围内文件做 AST 分析，得到调用、写点、控制条件、源码位置等——这时还**没有** AscendC 业务解释；涉及模板折叠时依赖 clang `-ast-dump`。
3. **analyze**：在事实之上跑确定性 passes，得到 TilingKey / TilingData / Kernel 等关系；证不全的记入 `unresolved`。正式 `.uo` 只由这条链路写入，不经 LLM。

换 CANN 版本或架构后应重跑 UO，不要手工改 `.uo`。

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

**提取什么**：算子目录布局、`arch*` 变体、真正参与编译的源文件及其 include 依赖。  
**结果是什么**：当前架构下的 Source Scope（事实边界，不是手点的目录清单）。

算子目录外的 common header 只要确实是编译依赖，就应进入；相邻但不参与当前构建的源码不应凭猜测进入。源码范围失败会让 `/uo-init` 回到 `prepare`。

实现层：`frontend/`（layout / BuildVariant / scope）、`build_context.py`、`scope_scan.py`。

---



## 2. Host Compiler Facts

在 Source Scope 上，UO 用 **libclang + clang 驱动**（`-ast-dump`）在 CANN 编译上下文中抽取 CompilerFacts。

**提取什么**：声明、调用、写点、分支条件、类型线索、看不透的宏守卫，以及对应源码位置。  
**结果是什么**：可定位的编译期事实底座——还不是最终 CodeMap。

实现层：`frontend/clang.py`、`clang_walk.py`、`harness.py`（模板折叠）。

---



## 3. TilingKey

在 Host 侧事实之上，确定性 pass 恢复 TilingKey 的定义与赋值关系。

**提取什么**：TilingKey 有哪些维、怎么打包成最终 key、`SetTilingKey` 写在哪、各维从哪些 Host 输入/派生状态来。  
**结果是什么**：可供 TG 使用的合法 key 集合，以及「Host 条件 → key 某一维」的关系；证不全的记入 unresolved。

实现层：`passes/`（Host TilingKey / def-use）。

---



## 4. TilingData

与 TilingKey 对称，追踪 Host 写入与 Kernel 读取。

**提取什么**：TilingData 有哪些字段、Host 谁写、Kernel 谁读、两侧是否对得上。  
**结果是什么**：`Host 写入 → 字段 → Kernel 读取` 的可追溯链，供 CE 影响分析与后续覆盖使用。

实现层：`passes/`（TilingData host writes / kernel reads）。

---



## 5. Template / Compile-time

AscendC 大量行为由模板参数、宏和编译期分支决定。

**提取什么**：模板参数与实例、相关宏事实、编译期条件如何约束走哪条路径。  
**结果是什么**：编译期选择与 Host/Kernel 实体之间的关系；猜出来的实例不当事实。

实现层：`passes/`（template / compile-time / macro）。

---



## 6. Kernel Identity / Call Boundary

在 Kernel 侧建立身份与调用边界，而不是执行时序仿真。

**提取什么**：有哪些 Kernel、调用边界在哪、如何与 Host / Tiling 绑定、能解析到的调用关系。  
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

**提取什么**：LocalTensor / Buffer / sync 等对象，经项目封装追到 AscendC/CANN 根 API 的路径。  
**结果是什么**：标成已到达 / 未闭合 / 外部依赖，并带上源码位置。

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


| 表                          | 内容                                                                                      |
| -------------------------- | --------------------------------------------------------------------------------------- |
| `meta`                     | 产品元数据：schema、authority、op_name、architecture、生成时间、实体/关系计数、fingerprint 等                  |
| `build_variant`            | 当前架构下的构建变体（宏、include、编译参数等）                                                             |
| `entity`                   | CodeMap 节点：kind、name、status、confidence、源码位置、完整 JSON `data`                              |
| `relation`                 | 有向边：kind、src、dst、status、confidence、完整 JSON `data`                                       |
| `file`                     | 涉及的源文件路径与角色                                                                             |
| `source_span`              | 实体到 `path:line`（及短 snippet）的定位                                                          |
| `attribute`                | 实体属性键值（便于查询）                                                                            |
| `view_blob`                | 导出视图与摘要（JSON），至少含 `summary`；TG 还依赖如 `ir/tg_host_view.yaml`、`ir/operator_graph.yaml` 等投影 |
| `predicate` / `provenance` | 谓词与溯源槽位（schema 预留；随 passes 填充）                                                          |


**实体（节点）典型 kind**：`BUILD_VARIANT`、`TILING_KEY` / `TILING_DATA` / `TILING_FIELD`、`KERNEL`、`TEMPLATE`*、`FUNCTION` / `VARIABLE` / `FIELD`、`BRANCH` / `PREDICATE`、`BUFFER` / `REGISTER` / `OPERATION` 等。

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