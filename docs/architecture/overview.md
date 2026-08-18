# 设计动机与系统架构

## 为什么需要 AscendC-Pilot

AscendC-Pilot 最初要解决的问题：

> 根据一次 PR / 代码改动，自动判断影响范围，并生成足够覆盖的测试用例。

传统路径依赖人工经验：

```text
PR Diff → 人工分析影响面 → 凭经验补测试
```

但在 AscendC 算子上，这条路很难走通。算子代码量大、跨 Host / Tiling / Kernel 多层，影响往往不落在改动文件本身：改一个 Host 条件，可能牵动 TilingKey、模板实例和 Device 侧路径。直接把「读 PR + 翻源码 + 出用例」交给大模型 Agent，常见结果是：上下文塞满仍读不全、同一问题多次回答不一致、补出来的用例对不上真实触发路径。

问题于是从「怎么生成测试」前移成了：

> 怎样先获得一份高质量、低成本、可复用的算子理解，再让 Agent 在这份理解上做分析与用例生成？

对复杂工程来说，上下文窗口十分宝贵——每一轮都重读整仓既贵又易丢跨层关系。后来引入的通用 Coding Agent / Code Graph 能帮定位符号，但仍盖不住 AscendC 依赖的宏与编译期语义（详见下一节）。

因此项目逐步收敛到今天的形态：先用确定性流水线建立算子级知识模型 **Operator CodeMap**，再在其上做查询、测试覆盖（TG）与变更审查（CE）；Agent 负责受约束的推理，而不是每次临时「重新理解整个算子」。

算子行为通常由多阶段共同决定：

```text
Input -> Host Logic -> Tiling Decision -> TilingKey -> TilingData -> Kernel Template -> Runtime Execution
```

CodeMap 要能支撑快速定位源码证据，并回答这类问题：

> 一个输入为什么会导致某个 Kernel 实例被选择？
> 某个 Host 条件修改后，会影响哪些 Device 侧行为？

---

# 从通用 Code Graph 到 Operator CodeMap

随着 Coding Agent 的普及，把仓库编成可检索知识、压低上下文消耗的项目越来越多。例如通用代码图谱 [codegraph](https://github.com/colbymchenry/codegraph)（约 6 万+ star）、各类 LSP/AST 索引、Aider 的 repo map、Cursor / Continue 一类 codebase indexing，以及把图谱/记忆交给 Agent 的 MCP 服务如 [codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp)（约 3 万+ star）。它们通常建的是：

```text
File -> Symbol -> Function Call -> Reference
```

这很擅长快速定位符号与调用关系，减少无目的全仓翻找——**但基本停在“源码表面结构”**：不会系统处理宏展开后的语义、编译期模板实例化、`constexpr` / 条件编译路径，以及 Host 侧生成的运行配置。对一般应用仓往往够用；对 AscendC 不够。

AscendC 的关键复杂性来自**编译与生成**，而不是普通调用边。一个 Kernel 实例往往由下式共同决定：

```text
TilingKey + Template Argument + Macro Definition + Compile Condition
```

这些对通用 Code Graph 多半是盲区，对算子却直接决定最终执行路径。因此 AscendC-Pilot 不另做一套通用代码关系图，而是构建面向算子执行语义的 **Operator CodeMap**——不是“A 调用了 B”，而是跨层语义链：

```text
Input -> Host Condition -> Tiling Field -> TilingKey -> Template Instance -> Kernel Behavior
```

如何建图见 [UO](../modules/uo.md)。

---

# 三模块与控制面

```text
AscendC Source → UO → Operator CodeMap
                         ├→ Query
                         ├→ TG → Coverage
                         └→ CE → Plan / Apply / Review

User
  ├─ 自然语言 → Primary 读编排 skill（slash I/O + 流水线）→ pilot_run(workflow=当前缺的那一步)
  └─ Slash /uo /tg /ce → Primary → pilot_run(workflow=<该 id>)
    ↓
Host Adapter（安装期 compose + 运行时 Session Driver）
    ↓
ACP Harness（单步 lease / 派领域子代理；下一步回 Primary + skill 图）
    ↓
Engine（事实：clone / Clang / replay）或 LLM Agent（推理；不推进状态）
```

自然语言 **对照编排 skill 选下一步**，不要 `workflow=auto` 再开一轮 Intent LLM，也不要用 Python TaskPlan 平行 DAG。显式 slash 只跑该节点。查询仍走 `pilot_cli` / `uo-query`，不进 Harness。没有独立 change-impact 角色：问变更影响 = 带着 diff 做 `/uo-query`。

| 模块 | 一句话 |
| --- | --- |
| UO | 知识构建：compiler-aware CodeMap |
| TG | 证据闭环：Replay + 经审查的 exclusion |
| CE | 命名计划、按 todo 改码、只读审查 |
| ACP | 执行控制：约束 Agent / Engine 边界 |
| Host Adapter | 安装期投影 + **运行时传输**（Session Driver） |

Data Plane：`Operator → UO → CodeMap → {TG, CE}`。

Control Plane：`User → Host Adapter (Driver) → Pilot Workflow → Engine 或 LLM → Gate → State`。

核心原则：

> Deterministic Engine 负责事实，LLM Agent 负责推理，Harness 负责约束两者之间的边界，**Host Adapter 负责传输与派发**（建库 / TG / CE 不再由 Primary LLM 手工编排 ACP 协议环）。**只读查询例外**：主控直接 `pilot_cli` `uo-query` 或同一轮原生 Task，不走 `pilot_run`。

覆盖如何闭环见 [TG](../modules/tg.md)；Agent 如何受约束见 [Agent Runtime](agent-runtime.md)；各 workflow 阶段图见 [工作流流程图](workflows.md)；文件放哪见 [产物与权威](artifacts-and-authority.md)。

---

# 设计原则

```text
Compiler-aware Knowledge + Deterministic Verification + Bounded Agent Reasoning + Host-owned Transport
```

通过提前建立 Operator CodeMap，减少 Agent 对源码的重复理解、把上下文留给真正需要推理的地方；通过 Harness 限制执行范围；通过 Host Session Driver 把建库 / TG / CE 的 `start → auto → Task → finalize` 从 LLM turn 挪到 Host；只读查询由主控直接执行或同一轮委派，不进该环；通过 replay 和 proof 保证结果具有工程可信度。
