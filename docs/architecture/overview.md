# 设计动机与系统架构

## 为什么需要 AscendC-Pilot

大模型 Agent 正逐渐成为软件开发流程中的重要工具，但对于复杂工程场景，Agent 面临的核心问题并不是简单的代码生成能力，而是如何获得高质量、低成本、可持续复用的代码理解。

AscendC 算子就是一个典型场景。一个算子的实际行为通常不是由某一个函数决定，而是由多个阶段共同决定：

```
Input -> Host Logic -> Tiling Decision -> TilingKey -> TilingData -> Kernel Template -> Runtime Execution
```

这些关系分散在 Host 代码、Tiling 实现、Kernel 模板、公共头文件以及构建配置中。同时 AscendC 大量依赖模板参数、宏展开、编译期变量和条件编译，这些信息往往决定最终生成和执行的 Kernel 路径。

传统代码理解工具通常能够很好地解决“代码在哪里”“函数如何调用”等问题，但难以回答：

> 一个输入为什么会导致某个 Kernel 实例被选择？
> 某个 Host 条件修改后，会影响哪些 Device 侧行为？

对于当前的大模型 Agent 来说，如果每次任务都重新阅读整个算子仓库，不仅会消耗大量上下文窗口，也容易因为检索范围有限而丢失跨文件、跨阶段的语义关系。

因此 AscendC-Pilot 采用了一种不同的方式：

> 不让每个 Agent 临时理解整个算子，而是在任务开始前建立一次算子级知识模型，让后续 Agent 基于这个模型完成分析、测试生成和代码工程任务。

这个知识模型就是 Operator CodeMap。

---

# 从通用 Code Graph 到 Operator CodeMap

近年来，CodeGraph、Codebase-Memory MCP 等代码智能系统已经证明，将源码转换成结构化知识可以显著降低 Agent 的上下文成本。

这类系统通常通过 AST、LSP 或静态分析建立代码关系，例如：

```
File -> Symbol -> Function Call -> Reference
```

它们能够帮助 Agent 快速定位代码位置，减少无目的源码搜索。

但是 AscendC 算子的核心复杂性并不主要来自函数调用关系，而来自编译和生成过程。

例如，一个 Kernel 的最终实例可能由：

```
TilingKey + Template Argument + Macro Definition + Compile Condition
```

共同决定。

普通代码图通常不会深入处理：

* 宏展开后的语义；
* constexpr 分支；
* 编译期变量；
* 模板实例化结果；
* 条件编译路径；
* Host 生成的运行配置。

这些信息对于普通 C++ 工程可能不是主要关注点，但对于 AscendC 算子，它们直接决定最终执行行为。

因此 AscendC-Pilot 并不是构建一个通用代码关系图，而是构建面向算子执行语义的 Operator CodeMap。

CodeMap 描述的不是简单的：

```
A 调用了 B
```

而是：

```
Input -> Host Condition -> Tiling Field -> TilingKey -> Template Instance -> Kernel Behavior
```

这样的跨层语义链。

---

# 从 PR 覆盖分析到自动化测试生成

AscendC-Pilot 最初的设计来源于算子工程中的一个实际问题：

当一个算子发生代码修改时，如何确定真正受到影响的范围，并生成足够覆盖的测试 Case？

传统方式依赖开发者经验：

```
PR Diff -> 人工分析 -> 补充测试
```

但是 AscendC 算子的影响传播并不局限于修改文件本身。

例如修改一个 Host 判断：

```
if (condition)
```

可能影响：

```
Host -> Tiling Parameter -> TilingKey -> Kernel Template -> Runtime Branch
```

如果没有完整的跨层关系模型，测试覆盖只能依赖经验补充。

因此 AscendC-Pilot 首先解决的问题不是“如何生成测试”，而是：

> 如何建立一个能够解释算子行为传播关系的模型。

这推动了 UO（Understand Operator）的设计。

---

# UO：构建 Operator CodeMap

UO 是 AscendC-Pilot 的知识构建阶段。

它并不是简单扫描源码目录，而是在真实编译上下文中理解算子。

整体流程如下：

```
AscendC Source + 构建变体 + CANN Environment -> Clang -> Compiler Facts -> Semantic Analysis -> Operator CodeMap
```

UO 首先根据目标 BuildVariant、编译参数以及 CANN 环境确定真实参与编译的源码范围。

这是因为 AscendC 算子的关键语义经常来自公共头文件和模板代码：

```
Operator Source -> common headers + CANN headers + template implementation
```

仅分析算子目录本身，无法得到完整语义。

随后 UO 使用 Clang 解析源码，并结合 CANN 提供的编译环境，提取 Compiler Facts，包括 AST、类型信息、符号关系、模板实例、宏和条件编译信息等。

这些信息本身并不是最终答案，而是后续语义分析的基础。

在 Compiler Facts 之上，UO 通过确定性分析建立：

```
Host State -> Tiling Decision -> TilingKey -> TilingData -> Kernel Instance -> Execution Path
```

最终生成 Operator CodeMap，并保留每条关系的来源和无法确定的部分。

---

# TG：基于 CodeMap 的覆盖闭环

TG（Testcase Generation）建立在 UO 生成的 CodeMap 之上。

它并不是直接随机生成测试输入，而是首先理解算子的行为空间。

整体流程：

```
Operator CodeMap -> Coverage Obligation -> Candidate Planning -> Candidate Input -> Host Replay -> Runtime Observation -> Coverage Evidence
```

CodeMap 中描述的 TilingKey、Kernel 分支和运行条件会被转换为测试义务。

对于一个目标路径，TG 会尝试寻找满足条件的输入，并通过 Host replay 验证真实执行结果。

Replay 的作用是连接：

```
Static Analysis + Real Execution
```

静态分析可以推导“理论可能路径”，但只有 replay 才能证明实际运行行为。

Replay 过程中会观察：

* 实际选择的 TilingKey；
* 生成的 TilingData；
* Runtime 状态；
* Kernel 分支结果。

对于无法通过测试触发的路径，TG 不会简单认为“没有问题”，而是引入 lemma 和 referee 机制，通过证明不可达性形成 exclusion evidence。

最终覆盖闭环：

```
Coverage Domain = Replay Evidence + Sound Exclusion Proof
```

---

# 当前系统架构

AscendC-Pilot 当前由两个部分组成：

## Data Plane

负责构建和消费算子知识。

```
AscendC Operator -> UO -> Operator CodeMap -> {TG, CE}
```

UO 提供统一语义基础。

TG 基于 CodeMap 进行覆盖闭环。

CE 基于 CodeMap 分析代码修改影响。

---

## Control Plane

负责管理 Agent 的执行过程。

```
User -> Host Adapter -> Primary Agent -> Pilot Workflow -> Action Bundle
Action Bundle -> Engine -> Checker / Referee -> Gate -> Workflow State
Action Bundle -> LLM Agent -> Skill / Prompt -> Checker / Referee -> Gate -> Workflow State
```

Control Plane 不负责替代领域分析，而负责保证 Agent 在正确边界内工作。

它管理：

* Workflow；
* Action；
* Context；
* Permission；
* Artifact；
* Validation。

核心原则：

> Deterministic Engine 负责事实，LLM Agent 负责推理，Harness 负责约束两者之间的边界。

---

# 设计原则

AscendC-Pilot 的核心设计可以概括为：

```
Compiler-aware Knowledge + Deterministic Verification + Bounded Agent Reasoning
```

通过提前建立 Operator CodeMap，减少 Agent 对源码的重复理解；通过 Harness 限制 Agent 的执行范围；通过 replay 和 proof 保证最终结果具有工程可信度。

---
