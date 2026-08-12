# 设计动机与系统架构

## 为什么需要 AscendC-Pilot

大模型 Agent 正逐渐成为软件开发流程中的重要工具，但对于复杂工程场景，核心问题往往不是代码生成能力，而是如何获得高质量、低成本、可持续复用的代码理解。

AscendC 算子的行为通常由多阶段共同决定：

```text
Input -> Host Logic -> Tiling Decision -> TilingKey -> TilingData -> Kernel Template -> Runtime Execution
```

这些关系分散在 Host、Tiling、Kernel 模板、公共头文件和构建配置中，并大量依赖模板参数、宏、编译期变量和条件编译。传统调用图难以回答：

> 一个输入为什么会导致某个 Kernel 实例被选择？
> 某个 Host 条件修改后，会影响哪些 Device 侧行为？

若每次任务都让 Agent 重读整个算子仓库，既昂贵又容易丢失跨层语义。因此 AscendC-Pilot 采用：

> 不让每个 Agent 临时理解整个算子，而是先建立一次算子级知识模型，再基于该模型完成分析、测试生成和代码工程。

这个模型就是 **Operator CodeMap**。

---

# 从通用 Code Graph 到 Operator CodeMap

通用代码图通常建立 `File -> Symbol -> Call -> Reference`。AscendC 的关键复杂性更多来自编译与生成：模板实例、宏展开、constexpr、条件编译、Host 生成的运行配置。CodeMap 描述的是跨层语义链：

```text
Input -> Host Condition -> Tiling Field -> TilingKey -> Template Instance -> Kernel Behavior
```

而不是简单的“A 调用了 B”。如何建图见 [UO](../modules/uo.md)。

---

# 三模块与控制面

```text
AscendC Source → UO → Operator CodeMap
                         ├→ Query
                         ├→ TG → Coverage
                         └→ CE → Review / Impact

User / Host
    ↓
ACP Harness (Pilot Runtime)
    ↓
Workflow / Engine / Agent
```

| 模块 | 一句话 |
| --- | --- |
| UO | 知识构建：compiler-aware CodeMap |
| TG | 证据闭环：Replay + 经审查的 exclusion |
| CE | 变更分析：沿 CodeMap 做跨层影响 |
| ACP | 执行控制：约束 Agent / Engine 边界 |

Data Plane：`Operator → UO → CodeMap → {TG, CE}`。

Control Plane：`User → Host Adapter → Primary → Pilot Workflow → Engine 或 LLM → Gate → State`。

核心原则：

> Deterministic Engine 负责事实，LLM Agent 负责推理，Harness 负责约束两者之间的边界。

覆盖如何闭环见 [TG](../modules/tg.md)；Agent 如何受约束见 [Agent Runtime](agent-runtime.md)；文件放哪见 [产物与权威](artifacts-and-authority.md)。

---

# 设计原则

```text
Compiler-aware Knowledge + Deterministic Verification + Bounded Agent Reasoning
```

通过提前建立 Operator CodeMap，减少 Agent 对源码的重复理解；通过 Harness 限制执行范围；通过 replay 和 proof 保证结果具有工程可信度。
