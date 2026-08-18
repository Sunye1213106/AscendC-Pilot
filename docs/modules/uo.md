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
| `verify` | `.uo` | 检查结构是否完整、约定视图能否读出；写入 `uo/checks/integrity.yaml` 与 `uo/checks/quality.yaml` | 已验证的 CodeMap |

Host 把 TilingKey packing 实参分类时走已有的 C++ ExprIR（字面量、编译期符号、成员、cast），而不是扫 identifier token。TilingData 字段按已注册的类型身份补齐，不靠文件名猜测。

---



## 提取与编译原理

UO **不跑**算子仓自己的 CMake/Ninja，也**不用** `compile_commands.json`。它准备一套和目标架构一致的「假编译环境」（CANN 头 + 编译参数），让 Clang 按真实宏/头文件语义读 Host 与 Kernel，再从中抽出可定位的事实。


| 需要什么                                | 干什么                                                                      |
| ----------------------------------- | ------------------------------------------------------------------------ |
| **clang 可执行文件**（必选）                 | 真正按编译参数解析；并用 `-ast-dump` 看到模板实例、`if constexpr` 折叠后的结果（仅靠 libclang 看不到这些） |
| **libclang**（Python 绑定，必选）          | 走 AST、算 include 闭包、抽出函数/调用/写点等 `CompilerFacts`                           |
| `build_context.yaml` + CANN Headers | 提供基线 `-I/-D` 与 AscendC 类型/API 语义。Kernel `-D`（`__NPU_ARCH__` / `__DAV_*` / `__CCE_AICORE__`）按 `arch_dir` 表注入，不在 yaml 里冻一份。prepare 的 **include-heal** 按缺头文件在 CANN/ops 树补 runtime `-I`（并把 `lib/matrix/matmul/` 映射到现存的 `lib/matmul/`），写入 `uo/summary/build_context_extras.yaml`；extract 经 `apply_saved_extras` 合并进 clang `-I`。脚本仍找不到时才进入 `heal`：LLM 只写 staging，`heal_promote` 校验后追加 extras（`source: heal_promote`）。不要手改 extras 或共享 `spec/build_context.yaml`。prepare 还会生成 kernel tiling stub（packed POD + `GET_TILING_DATA*`）并 force-include，使未手写专用 tiling 头的算子 TU 也能看见类型。 |
| 仓内 `compat/`                        | 少量 shim，免去拖入整套工程构建系统。prelude **不** stub `RegTensor`/`VecReg`（与 CANN 撞车）；Host 另 force-include `host_prelude.h`（`using std::string`），kernel 不加。 |


流程可以看成三步：

```text
准备环境（BuildVariant）
    → 看清要解析哪些文件（prepare）
    → Clang 抽出编译期事实（extract）
    → 确定性规则串成 CodeMap（analyze）
```

1. **prepare**：认清算子布局和 `arch`*，用 include 闭包划定 Source Scope（真依赖进、猜的不进），并探针能否解析。
2. **extract**：对范围内文件做 AST 分析，得到调用、写点、控制条件、源码位置等——这时还**没有** AscendC 业务解释；涉及模板折叠时依赖 clang `-ast-dump`。默认 `UO_INIT_PROFILE=fast`（`init_profile.py`：未设置即 `fast`）：`closure_mode=keypath`，**1 个 kernel dtype**，不跑 explicit-instantiation fold，不开 API clang。全量（全部声明 dtype + fold + API clang + full closure）需显式 `UO_INIT_PROFILE=full`。精度 / UT 若需要全 dtype 事实，用 `full`，不要假定默认已经折完。
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

实现层：`frontend/`（layout / BuildVariant / scope）、`build_context.py`、`scope_scan.py`。Bisheng 关键字（`__simt_callee__` 等）由 erase 成空；Catlass `[aicore]` 由 prelude 关掉 `macros.hpp` 护卫。探针把诊断路径 resolve 后再判断是否落在 `op_dir` 下（家族 `3rd/` / CANN 头不算算子源码错误）。

---



## 2. Host Compiler Facts

在 Source Scope 上，UO 用 **libclang + clang 驱动**（`-ast-dump`）在 CANN 编译上下文中抽取 CompilerFacts。

**提取什么**：声明、调用、写点、分支条件、类型线索、看不透的宏守卫，以及对应源码位置。  
**结果是什么**：可定位的编译期事实底座——还不是最终 CodeMap。

实现层：`clang_walk.py` 经 `host_ir.py` / `kernel_ir.py` 抽取；模板折叠见 `harness.py`。

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

**提取什么**：LocalTensor / Buffer / register，以及有明确类型或调用实参证据的 pipe / event / queue；经项目封装追到 AscendC/CANN 根 API 的路径。  
**结果是什么**：标成已到达 / 未闭合 / 外部依赖，并带上源码位置。OPERATION 保留 catalog 根 API（DataCopy / Alloc / EnQue / SetFlag / Cast / LoadAlign / SetGlobalBuffer 等）以及带 `file:line` 与稳定 identity 的调用。工程符号在**接收者类型唯一**（含 `std::conditional<Cond, Then, Else>::type` 里只有一侧有该方法，以及类外 `Owner::Method` 作用域里的类成员）且所选 kernel 文件里对该类型只有一个同名方法时，`BINDS` 到声明根（例如 `MutexBuffersPolicyDB::Get`），`status=extracted`，**不**把 `root_status` 标成 AscendC。`Selector::TYPE` 展开后多个类型都有该方法则不绑。自由函数仅当定义只出现在一个文件时绑定（`commondef::AlignTo16`）。短名单独不能证明成员调用。`PRECEDES` 只连接同步相关 API。Flag 同步（SetFlag / WaitFlag、CrossCore*、IB*）在 event identity 是简单标识符时记录 `SIGNALS` / `AWAITS`，并做 **identity 级成对出现**（同一 identity 缺一侧记 `UNPAIRED_FLAG_SYNC`）。EnQue / DeQue 是 CANN **TQue**（内部封装 SetFlag/WaitFlag，只挂 QUEUE，不进 Flag 配对）。InitBuffer / FetchEventID / GetTPipePtr 是 **TPipe**，不是 TQue。

Canonical Kernel UO 提供的是 sync **facts**：operation、参数、pipe/event/queue 实体；Flag 的 `SIGNALS` / `AWAITS` 与 identity 级成对出现；TQue 的 QUEUE 绑定。**不**做 timing simulation、exec_rank、RAW/WAR/WAW、happens-before、CopyIn/Compute/CopyOut pipeline inference、buffer lifecycle 或引擎调度。哪一次 Wait 等哪一次 Set，属于 CE + referee。无法可靠闭合的路径保持为 unresolved。

实现层：`passes/`（root trace）。

---



## 8. Unified CodeMap 与 `.uo` 产品

各层关系归一到统一 IR，并由 `commit` materialize 为正式产品：

```text
.ascendc-pilot/<arch>/uo/<op_name>.<arch>.uo
```



### `.uo` 是什么

`<op>.<arch>.uo` 是 **SQLite 数据库**（schema：`codemap-uo/v2`，兼容读取 `codemap-uo/v1`），不是 YAML/JSON 文本。它是对外唯一的 canonical Operator CodeMap：Query / TG / CE 都读它；只有 UO 确定性 `commit` 可写。v2 边带 `trust`（authoritative / derived / advisory / legacy_unknown）；Query 默认不沿 `advisory` 边闭合。v1 产品读入后标 `legacy_unknown`，不会被推断成 lexical。

可用普通 SQLite 工具打开（只读排查），但不要手工改库内容——应走 `/uo-init` 或 `/uo-update`。

### 库里有什么


| 表                          | 内容                                                                                      |
| -------------------------- | --------------------------------------------------------------------------------------- |
| `meta`                     | 产品元数据：schema、authority、op_name、architecture、生成时间、实体/关系计数、fingerprint / canonical_graph_digest 等 |
| `build_variant`            | 当前架构下的构建变体（宏、include、编译参数等）                                                             |
| `entity`                   | CodeMap 节点：kind、name、status、confidence、源码列；`data` 只存业务 attrs（不含 kind/file 副本，不含 `type_text`） |
| `relation`                 | 有向边：kind、src、dst、status、confidence；`data` 只存业务 attrs                                       |
| `file`                     | 涉及的源文件路径与角色                                                                             |
| `source_span`              | 实体到 `path:line`（及短 snippet）的定位；无 snippet 时不写行                                         |
| `attribute`                | schema 预留；commit 不再写入键值副本（查属性读 `entity.data`）                                          |
| `view_blob`                | 可重建投影与摘要（JSON）；须带 provenance（digest + counts + builder）；mismatch → `VIEW_STALE` → engine fallback；TG 依赖如 `ir/tg_host_view.yaml` 等 |
| `predicate` / `provenance` | 谓词与溯源槽位（schema 预留；随 passes 填充）                                                          |


**实体（节点）典型 kind**：`BUILD_VARIANT`、`TILING_KEY` / `TILING_DATA` / `TILING_FIELD`、`KERNEL`、`TEMPLATE`*、`FUNCTION` / `VARIABLE` / `FIELD`、`BRANCH` / `PREDICATE`、`BUFFER` / `REGISTER` / `PIPE` / `EVENT` / `QUEUE` / `OPERATION` 等。

**关系（边）典型 kind**：日常查询默认走有用边 `WRITES` / `READS` / `CALLS` / `CONTROLS` / `DERIVES` / `SELECTS` / `LAUNCHES` / `SIGNALS` / `AWAITS` / `FLOWS_TO` / `BINDS`。图中还可有 `INSTANTIATES`、`WRAPS` / `ROOTED_AT`，以及同步相关的 `PRECEDES`。Host 条件、Tiling、Kernel、AscendC root 靠这些边串成可追溯图。

Query 与 CE 读回的是按 kind 投影后的 evidence hit（`id/kind/name/file/line` + 少量 `facts`），不是整份 `entity.data`。跨层邻域由 `uo-query` 四种形态给出；`uo/diff/impact.yaml` 是 `/uo-update` 的引擎产物，不是 agent API。`legal_key` 在磁盘上按维列存，读取时再展开成 `dims` 字典。

```text
meta + BuildVariant
  + entities / relations（跨层图）
  + source_span（证据定位）
  + view_blob（summary + TG/CE 投影）
  = 一个可查询的 Operator CodeMap
```

**Unresolved 是正式结果**：静态证据不足、关系含糊、依赖外部系统或不受支持时，应记录为 unresolved，而不是由 LLM 补写 canonical `.uo`。调查 Agent 可以分类并产出 bounded report；确定性引擎仍是规范 CodeMap 的唯一写入者。

实现层：`store/schema.py`、`store/writer.py`、`ir/`、`codemap_engines.py` / `build.py`（commit / verify）；query/update 见下文。

---



## 四条 UO 入口

```text
Source -> CodeMap -> {/uo-query 只读提问（直接查询或同一轮委派） | /uo-update 受控增量刷新 | /uo-investigate 调查 gap}
```

`/uo-init` 从源码建立新的 CodeMap：`prepare -> extract -> analyze -> commit -> verify`。

`/uo-update` 在源码或 build 指纹变化后执行 `detect -> plan -> apply -> export -> diff`。基于 fingerprint 的受控刷新，不是在 YAML 上随意打补丁；只需查看变化时可走 `diff_only`。

`/uo-query` 只读回答已有 CodeMap 上的问题。可借助模型解释，但不得改写 canonical CodeMap。

### `/uo-query`（可见 LLM 路由，禁止 Host Session Driver）

查询不是 Host Driver 工作流（`host_driver=False` ≠ 没有 bundle）：不要 `pilot_run workflow=uo-query`。主控先阅读短地图，简单查询直接调用 `pilot_cli` `uo-query`（禁止单独一轮只宣布路数）；复杂查询同一轮委派 `Task(agent=uo-query)`。禁止仅为问题分类而委派子代理。建库 leftover 不能拦 `Task(agent=uo-query)`：查询子代不是当前 Host 阶段的 declared actor。

身份一律 `uo-query`。推理入口：

- 短地图 [`uo-product-map.md`](../../skills/operator-analysis/references/uo-product-map.md)
- 子代 METHOD：`skills/operator-analysis/capabilities/uo-query/METHOD.md`
- 主控路由：`skills/operator-analysis/routing/uo-query.md`
- 交付：简单查询 = 当前会话 stdout；复杂查询 = 子代 Task 全文（主控综合）。子代不要 Write `answer.yaml`。

`readonly_analyst`：**禁止改 domain 正式产物**（`.uo` / TG / CE）。子代理不写正式产物。

高置信源码窗：查询命中里的 `snippet` 已算读过。只有窗被截断才 `pilot_cli` `inspect evidence-window --project … --path … --lines A-B`。

结构化查询（`pilot_cli` `uo-query`，默认 `--limit 8`）走 SQLite 索引，不 hydrate 全图：

- 标识符：实体卡片（定义点 + 按边类型分组的邻居 + `next`）
- `Dim=V`：模板覆盖（`dim_coverage` / `matching_block_count` / `total_matched`）
- `--file --line`：从位点走图
- 无参数：算子索引（launch 阶段、维名、TilingData、gaps 计数）

这四种形态是 CE / TG / 主控的**唯一查询面**。`uo/diff/impact.yaml` 是 `/uo-update` 的引擎产物，不是 agent API。不要传 `--mode`。禁止 `explain-*`、`search`、`locate`。

与官方 cannbot 的适配（CodeMap 作为源码结构底座，含 FAG arch35 覆盖验证）见下文 [与官方 cannbot 的适配](#与官方-cannbot-的适配)。

`/uo-investigate` 调查 unresolved residual：分类根因、指出确定性引擎还缺什么能力，产出 bounded report。不修改 canonical `.uo`。

---



## 与 TG、CE 的衔接

TG 消费 CodeMap、TilingKey domain、Host/Kernel projection 与 unresolved 来写 `tg/plan.md` 义务。CE 用上述四种 `uo-query` 形态读图，不另走 impact API。二者都不应重新建立完整源码权威。

UO 负责如实交付可证明关系及其未知部分；TG 决定哪些测试义务可通过 replay 或可靠排除关闭。

---

## 与官方 cannbot 的适配

UO 不替代 cannbot。cannbot 的 code-review、runtime-debug、crash-debug、precision-debug、whitebox-design、issue-handler 在源码里反复要的是同一类**定位点**：`file:line`、字段写点 / 读点、Buffer / Queue、同步与搬运 API。`/uo-init` 把这些写进 CodeMap；`uo-query` 按名字查出 **结构事实 + `file:line` + 源码窗**。这和 TG、CE 一样：下游读图，不重新解析整份算子。

```text
以前：问题 → Grep / Read 大量源码 → 建立局部理解 → cannbot 判断
现在：问题 → UO 一次查询（定位点 + 源码窗）→ cannbot 判断
```

下表把 cannbot skill 要的源码点对齐到 **CodeMap 已实现的投影**（`query/evidence.py` 的 facts 与有用边；内部桶名见 [`uo-product-map.md`](../../skills/operator-analysis/references/uo-product-map.md)）。**Agent / CE 技能不得按表中的 `locate` / `search` / `impact` 去调 CLI**——对外只有 `uo-query` 四种形态。`impact` 列表示图邻域分桶，对应磁盘 `uo/diff/impact.yaml` 时也只是 uo-update 产物。

| cannbot skill 要的源码点 | 典型 skill | UO 查询 | CodeMap 给出 |
| --- | --- | --- | --- |
| 符号 / 入口 / 字段的 **file:line** | code-review 概要、issue-handler Step 3 | `locate` | `file` + `line_start`/`line_end`；字段/维还会展开 packing / writer / `check_sites` |
| Host **函数声明** `file:line`（`CheckShapeValid` 等） | code-review 按函数名开窗 | `locate`（`kinds=FUNCTION`） | FUNCTION 实体带声明 span（clang `FuncRecord.file/line` → `FuncSummary` → `from_host_ir`）。`OP_CHECK` 行仍走 BRANCH `host_check` / `facts.check_sites`，不是靠函数名 |
| TilingData **写点**（`set_` / `xxx =`） | code-review「TilingData 值域溯源」 | `field` / `tiling_data` | `writers[]`（`WRITES`/`DERIVES`）、`facts.host_writer_sites`、短 `facts.rhs` |
| TilingData **读点**（`tilingData->xxx`） | 同上 | `field` | `readers[]`（`READS`） |
| `OP_CHECK_IF` / 变量校验行 | code-review 校验策略、变量溯源 | `locate` → `facts.check_sites` | 宏、guard、`file:line`，绑到字段或 INPUT |
| Buffer / Queue / `tposition` | code-review Buffer 规划；crash-debug 卡死 | `buffer` | BUFFER/QUEUE：`tposition`（VECIN/VECOUT）、`memory_space` |
| 同步 API：`EnQue`/`DeQue`、`SetFlag`/`WaitFlag`、`CrossCoreSetFlag`/`CrossCoreWaitFlag`、`PipeBarrier`、`AllocTensor`/`FreeTensor`、`InitBuffer` | crash-debug；code-review 同步契约 | `kernel_api` | OPERATION：`callee`、`function`、`args`、`file:line`；Flag 为 `facts.sync`（`SIGNALS`/`AWAITS`）+ `flag_paired`；TQue 为 `facts.queue` + `mechanism=tque`；TPipe InitBuffer 为 `mechanism=tpipe` |
| 搬运 / 精度 API：`DataCopy`/`DataCopyPad`/`Cast` | precision-debug；code-review API 索引 | `kernel_api` | 同上；`impact` 分到 precision / memory |
| TilingKey 声明与 packing 点 | runtime-debug 561002；whitebox | `tiling_key` | `value_domain`、`packing_value_sites`（按写出式排序，`[0]` 为真实 packing；snippet 对着写出点） |
| 接口 dtype | runtime-debug 561003；precision-debug 多 dtype | `search --kind INPUT,OUTPUT` | `facts.dtype`（REG_OP `TensorType`） |
| Kernel 分支 / 合法 Key 组合 | whitebox-design 路径覆盖 | `kernel_branch` / `legal_key` | 第一页最多 3 条样例（条件体排序）+ `functions` 目录；模板可接纳组合 |
| 改动碰到哪些路径 | issue-handler / PR 检视 | `impact` | 有向有用边邻居，分桶 dispatch / layout / memory / **sync** / precision / contract |

`kernel_api` 的 catalog 与投影一致：Flag 同步（Set/WaitFlag、CrossCore*、IB*）、**TQue**（EnQue/DeQue、Alloc/Free，CANN 封装交接）、**TPipe**（InitBuffer、FetchEventID、GetTPipePtr）、barrier（PipeBarrier 等），精度/搬运侧 `_PRECISION_CALLEES`（Cast、DataCopy、DataCopyPad），以及 LoadAlign / SetGlobalBuffer。`field` 回 `candidates`（最多 3 个写出点）/ writers / readers / edges，不回无向 neighbors。

Flag 同步在 identity 已知时记录 `SIGNALS`/`AWAITS`，并检查成对出现（缺一侧 `UNPAIRED_FLAG_SYNC`）。这不是 happens-before。EnQue/DeQue 是 **TQue**：`TQueBind` 内部才 SetFlag/WaitFlag，UO 只给调用点与 QUEUE `tposition`，不抽 Flag 边、不进 Flag 配对。InitBuffer 是 **TPipe** 方法。条例、golden、精度是否过线仍由 cannbot 判断。

> **UO 解决「代码里事实在哪里、彼此怎么关联」；cannbot 解决「这些事实在当前问题下意味着什么」。**

### FAG arch35：cannbot 常见查询覆盖验证

查询走 SQLite 索引（见 [benchmark.md](../benchmark.md)「查询」节），不再 hydrate 全图。下表覆盖口径来自 FAG arch35 已 commit 产品；当前墙钟以现网 `.uo` 上的 `acp uo-query` 为准。

产品路径：`<op>/.ascendc-pilot/arch35/uo/flash_attention_score_grad.arch35.uo`

| 定位点 | UO 命中 |
| --- | --- |
| `file:line` | `locate s1Inner` → 声明 `op_kernel/arch35/flash_attention_score_grad_tiling_data_regbase.h:197`，另有 packing/writer 行；KERNEL 入口 `op_kernel/flash_attention_score_grad_apt.cpp:39` |
| 写点 | TILING_FIELD **163**，其中 **147** 有 `rhs`；`s1Inner` writer `op_host/arch35/flash_attention_score_grad_tiling_normal_regbase.cpp:1900`；`formerDqNum.rhs = aivNum` |
| 读点 | TilingData 可达读 **327** 处，unresolved **0**；consumed fields **136/136** |
| 校验点 | **117** 条可定位 `OP_CHECK`；`softmaxMaxShape == nullptr` → `…/tiling_common_regbase.cpp:27`；`coreNum.check_sites` → `tiling_normal_regbase.cpp:403` |
| Buffer / Queue | QUEUE **16** 条带 `tposition`：`attenMaskOrYInQue` VECIN、`dSOutQue` VECOUT（`flash_attention_score_grad_block_vec.h:147-150`） |
| 同步 API | EnQue **38** / DeQue **36**（全部 `mechanism=tque`，**0** 条 Flag 边）；InitBuffer **44**（全部 `mechanism=tpipe`）；SetFlag **18** / WaitFlag **22**；CrossCoreSetFlag **101** / CrossCoreWaitFlag **86**。identity 已知 Flag **15** 对全部成对，`UNPAIRED_FLAG_SYNC` **0** |
| 搬运 / Cast / Reg | DataCopy **66** 全部 REACHED；Cast **153**；DataCopyPad **32**；LoadAlign **239** 全部 REACHED；SetGlobalBuffer **84** 全部 REACHED |
| TilingKey packing | **19/19** 声明/packing/producer/root；`SplitAxis` 声明 `:56`，packing `tiling_normal_regbase.cpp:1444`，值域 `{0,1,5}` |
| dtype | **27** 条 INPUT 有 `facts.dtype`；`query` → `op_graph/flash_attention_score_grad_proto.h:87` `[DT_FLOAT8_E5M2, DT_FLOAT8_E4M3FN, DT_FLOAT16, DT_BF16, DT_FLOAT32]` |
| Host 函数声明 | 同日 pass6 `fast` 冷启动：`locate CheckShapeValid` → `op_host/arch35/flash_attention_score_grad_tiling_common_regbase.cpp:194`；`CheckSoftmaxMaxShape` `:23`、`CheckSoftmaxSumShape` `:50`。BRANCH `host_check` **117/117** 有 span。按函数名 locate 是加分项，cannbot 主门仍是 Key / Field / Kernel / Input / `check_sites` |

```text
acp uo-query --project <op> s1Inner
acp uo-query --project <op> attenMaskOrYInQue
acp uo-query --project <op> EnQue
acp uo-query --project <op> InitBuffer
acp uo-query --project <op> DataCopy
acp uo-query --project <op> CheckShapeValid
acp uo-query --project <op> SplitAxis
acp uo-query --project <op> SplitAxis=1,IsTnd=1
```

---



## 失败、恢复与实现

源码范围问题回到 `prepare`；抽取问题回到 `extract`；完整性或 gap 问题回到 `analyze` 或 `commit`；验证失败按原因重跑对应阶段。恢复边由 workflow spec 声明。

实现入口：`engines/understand-operator/src/uo_init/codemap_engines.py`、`pilot_engines.py`、`build.py`、`frontend/`、`passes/`、`ir/`、`update/`、`query/`；运行时合同位于 `pilot/ascendc_pilot/workflows/specs.py`。精确阶段见 [Workflow Reference](../reference/workflows.generated.md)。当前版本 FAG arch35 提取/查询耗时与未闭合项见 [benchmark.md](../benchmark.md)。禁止把 `operator_report.py` 或 sqlite `kb_graph` 当作 `/uo-init` 产品路径。