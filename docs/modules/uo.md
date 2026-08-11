# UO：理解算子

UO（Understand Operator）不是把 AscendC 源码做成普通的调用图。它建立的是一条可追溯的跨层关系：Host 条件如何派生状态、如何写入 TilingKey/TilingData、如何选择模板与 Kernel，以及这些值最终如何影响编译期或运行时分支。这个模型叫作 **Operator CodeMap**。

## 为什么需要 UO

一个典型算子中的关系可能是：

```text
Host input / condition
  -> derived field
  -> SetTilingKey / SetTilingData
  -> template selection / constexpr
  -> kernel execution / runtime branch
```

这些步骤常跨文件、宏、模板和构建变体。仅靠文本搜索或 call graph 难以判断一条关系是否真实存在、受什么条件约束、是否在当前架构下可达。UO 把可由编译器事实和确定性 pass 证明的部分固化为 CodeMap，让 TG 和 CE 不必从头理解源码。

## 源码范围：事实边界而非目录清单

UO 从 operator root 和 architecture 开始，但不会把“用户手选的目录列表”当作完整输入。它先发现布局与构建变体，再结合 Clang 编译上下文追踪 include 和依赖闭包，形成实际的源码范围。

```text
operator root + architecture
  -> layout discovery
  -> 构建变体 / compile context
  -> include and dependency closure
  -> 源码范围
```

因此，算子目录外的 common header 只要确实是编译依赖，就应进入源码范围；反之，位于相邻目录但不参与当前构建的源码不应凭猜测进入事实集。源码范围失败会让 `/uo-init` 回到 `prepare`，而不是用不完整输入继续生成看似可信的 CodeMap。

## 从源码到 CodeMap

`/uo-init` 是一个确定性管线。每个阶段都有明确输入与输出：

| Phase | 输入 | 做什么 | 输出 |
| --- | --- | --- | --- |
| `prepare` | operator root、architecture | 发现 layout、构建变体和源码范围 | 已校验的源码范围 |
| `extract` | 源码范围 | 通过 Clang 抽取 CompilerFacts | declaration、AST、编译上下文等事实 |
| `analyze` | CompilerFacts | 运行确定性 CodeMap passes | 语义 IR、relations、unresolved |
| `commit` | analyzed IR | materialize 正式产品 | `operator.<arch>.uo` |
| `verify` | `.uo` | 校验结构、合同和导出视图 | 已验证的 CodeMap |

```text
Source -> CompilerFacts -> normalized IR -> derived fields and relations -> Operator CodeMap
derived fields and relations -> Host -> TilingKey
derived fields and relations -> Input -> derived state
derived fields and relations -> TilingData -> Kernel
derived fields and relations -> Host condition -> Kernel branch
```

CompilerFacts 是建立可追溯关系的依据，而非为了“用 Clang 而用 Clang”。它让 UO 可在当前构建变体的语义下识别声明、引用、模板、宏和源位置；后续的确定性 pass 将这些事实规范化并推导可消费关系。

## Kernel 执行模型

UO 的 Kernel 分析已经从“找到入口和分支”扩展为更完整的执行模型。它会在选定架构下重建 Kernel 入口、模板参数、ABI、调用边界、TilingData 读取与 Host 写入者关系，并用严格 closure 指标判断 `TILING_DATA -> KERNEL` 证据是否成立。

在可解析范围内，Kernel Execution Model 会抽取 AscendC primitive operation、LocalTensor / GlobalTensor / TQue / TBuf / register 等存储对象、同步事件、执行顺序、RAW / WAR / WAW 数据依赖，以及 CopyIn / Compute / CopyOut / Sync 等 pipeline 派生视图。这些信息进入 CodeMap 和 TG-facing views，用于 runtime branch 覆盖、TilingData 义务设计和 CE 影响分析。

无法唯一绑定的内部调用、字段读写或外部依赖仍进入 unresolved，而不是由模型补写 canonical CodeMap。

## 三条 UO 工作流

```text
Source -> CodeMap -> {/uo-query 只读消费 | /uo-update 受控增量刷新}
```

`/uo-init` 从源码建立新的 CodeMap，依次经过 `prepare -> extract -> analyze -> commit -> verify`。

`/uo-query` 经过 `route -> lookup -> answer` 回答已有 CodeMap 上的问题，例如“这个 TilingKey 来自哪个输入”或“哪个 Host 条件控制某个 Kernel 分支”。它可以借助模型解释，但不得改写 canonical CodeMap。

`/uo-update` 在源码或 build 指纹变化后执行 `detect -> plan -> apply -> export -> diff`。它不是在 YAML 上随意打补丁，而是基于当前 source fingerprint 与已有 CodeMap 的受控刷新；只需查看变化时可走 `diff_only`。

## Unresolved 是正式结果

UO 不以猜测换取一张看似闭合的图。当前静态证据不足、关系含糊、依赖外部系统或不受支持时，应记录为 unresolved，而不是由 LLM 补写 canonical `.uo`。调查 Agent 可以分类、寻找额外证据并产出 bounded report；确定性引擎仍是规范 CodeMap 的唯一写入者。

这也解释了 UO 与 TG 的边界：UO 负责如实交付可证明关系及其未知部分；TG 决定哪些测试义务可通过 replay 观察或可靠排除来关闭。

## 与 TG、CE 的衔接

TG 消费 UO 的 CodeMap、TilingKey domain、Host/Kernel projection 与 unresolved 信息来建立义务账本。CE 消费 relation view 分析一个改动对 Host 状态、TilingData、predicate 和 Kernel 分支的影响传播。二者都不应重新建立完整源码权威。

## 失败、恢复与实现

源码范围问题回到 `prepare`；抽取问题回到 `extract`；完整性或 gap 问题回到 `analyze` 或 `commit`；验证失败按原因重新执行对应阶段。所有恢复边由 workflow spec 声明。

实现入口：`engines/understand-operator/src/uo_init/workflow.py`、`frontend/`、`passes/`、`ir/`、`update/`、`query/`；运行时合同位于 `pilot/ascendc_pilot/workflows/specs.py`。精确阶段和 action 见 [Workflow Reference](../reference/workflows.generated.md)。
