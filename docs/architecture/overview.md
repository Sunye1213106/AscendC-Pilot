# 架构总览

AscendC 算子的关键语义通常跨越 Host、TilingKey、TilingData、Kernel 模板、编译期分支和运行时分支。它们分散在不同源文件和构建上下文中，普通调用图无法完整说明“一个输入为何会影响某个 Kernel 行为”。让每个 Agent 重新通读整个算子仓，既昂贵也容易遗漏跨层关系。

AscendC-Pilot 的做法是先将源码事实转为可查询、可复用的 **Operator CodeMap**，再让测试生成和代码审查消费这份模型。源码理解只建立一次；下游工作流只读取经过验证的关系和产物。

## 产品数据流

```text
                     AscendC Operator
                           |
              +------------+------------+
              |                         |
             Host                     Kernel
              |                         |
              +----- CompilerFacts -----+
                           |
                           v
                  Understand Operator (UO)
                           |
                           v
                     Operator CodeMap
                    /        |        \
                   v         v         v
              UO Query       TG        CE
                            |           |
                    obligations     impact analysis
                            |
                    solver / replay
                            |
                     coverage evidence
```

UO 是数据平面的起点：它发现实际参与编译的源码范围，抽取编译器事实，运行确定性分析，并保留无法可靠确定的关系。TG 将 CodeMap 转化为可审计的覆盖义务；CE 以同一份语义关系解释改动的影响传播。

## 运行时控制流

```text
User
  |
  v
Host Adapter -> Primary Agent -> Pilot Workflow
                                   |
                                   v
                            Action Bundle + Lease
                              /             \
                             v               v
                    Deterministic Engine   Bounded LLM Agent
                                                |
                                      Skill / Prompt / Policy
                              \             /
                               v           v
                           staging -> checker / referee -> gate
                                                        |
                                                        v
                                                workflow transition
```

控制平面不负责替代领域分析。它负责选择工作流和动作、组装上下文、限制读写范围、验证输出，并且只在 gate 通过后推进状态。完整生命周期见 [Agent Runtime](agent-runtime.md)。

## 主要组成

| 组件 | 回答的问题 | 主要实现 |
| --- | --- | --- |
| UO | 源码中的跨层语义关系是什么？ | `engines/understand-operator/` |
| TG | 哪些义务已被 replay 证明，哪些可被可靠排除？ | `engines/testcase-generation/` |
| CE | 这次改动影响了哪些状态、不变量和可观测行为？ | `engines/code-engineering/` |
| Pilot | 哪个动作可以执行、谁能写哪里、何时可推进？ | `pilot/ascendc_pilot/` |
| Host Adapter | 如何将 host 的交互入口接到 Pilot？ | `adapters/`、`generated/` |

## 事实与说明的边界

实现是事实权威：工作流形状在 `pilot/ascendc_pilot/workflows/specs.py`，路径和归属在 `pilot/ascendc_pilot/paths/` 与 `ownership.py`，Agent 上限在 `agents/*.yaml`。本目录解释设计动机、边界和因果关系；由代码生成的 Reference 则提供精确投影。

因此，`SKILL.md`、prompt、policy 和生成的 host 文件仍留在 runtime 附近。它们会被系统执行，不应被误当成项目说明文档的副本。

## 建议阅读顺序

第一次了解项目时，先读 [UO](../modules/uo.md) 和 [TG](../modules/tg.md)，再读 [Agent Runtime](agent-runtime.md)。需要定位持久化产物与写入权时，查看 [产物与权威](artifacts-and-authority.md)。
