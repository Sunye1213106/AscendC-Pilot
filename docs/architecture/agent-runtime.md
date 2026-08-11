# Agent Runtime

## 为什么需要 Agent Runtime

在复杂工程任务中，一个 Agent 不应该同时承担源码理解、方案生成、文件修改、结果验证以及状态推进。

如果所有行为都由单一 Agent 完成，会产生几个问题：

* Agent 的权限边界难以控制；
* 中间结果和最终规范产物无法区分；
* 模型生成的推理结果容易被误认为事实；
* Workflow 状态可能被非确定性行为推进。

因此 AscendC-Pilot 不把 Agent 看作一个直接执行任务的黑盒，而是引入 Runtime Control Plane。

Runtime 负责管理：

* 当前任务处于哪个 Workflow phase；
* 当前 Action 是否允许执行；
* Agent 可以访问和修改哪些资源；
* 输出是否满足 contract；
* 是否可以进入下一状态。

核心原则：

> LLM Agent 负责分析和生成候选结果，Pilot Runtime 负责约束执行、验证结果和推进状态。

---

# Runtime 模型

AscendC-Pilot 将一次任务拆分为多个具有明确输入输出边界的 Action。

整体关系如下：

```text
Workflow -> Action -> {Deterministic Engine, Agent Execution (LLM)}
        -> Contract Check -> Gate -> State Transition
```

Workflow 定义系统允许发生什么。

Action 定义当前一步具体做什么。

Engine 和 Agent 负责产生结果。

Checker 和 Gate 决定结果是否可以成为系统状态。

---

# Runtime 对象

| 对象         | 作用                                    | Source of Truth                          |
| ---------- | ------------------------------------- | ---------------------------------------- |
| Workflow   | 定义 phase、transition、action、gate 和写入范围 | `pilot/ascendc_pilot/workflows/specs.py` |
| Action     | 定义一次可执行任务，包括输入输出 contract             | Workflow specification                   |
| Agent      | 定义稳定身份、角色和权限上限                        | `agents/*.yaml`                          |
| Skill      | 定义领域方法、分析流程和证据要求                      | `skills/*/SKILL.md`                      |
| Prompt     | 定义某一次 Action 的具体任务描述                  | `prompts/tasks/`                         |
| Policy     | 定义运行约束和行为规则                           | `pilot/policies/`                        |
| Capability | 定义 Agent 或 Engine 可以调用的能力             | runtime capability registry              |
| Engine     | 执行确定性逻辑并生成可信产物                        | `engines/`                               |

这些对象的职责不同：

* Workflow 管状态；
* Action 管任务；
* Agent 管身份；
* Skill 管领域方法；
* Prompt 管当前任务；
* Policy 管约束；
* Engine 管确定性计算。

例如：

一个 TG closure 任务中：

* “如何判断不可达”属于 Skill；
* “生成 lemma”属于 Prompt；
* “验证 replay 结果”属于 Engine；
* “是否允许更新 closure ledger”属于 Workflow + Gate。

它们不能混在一个 Agent 中。

---

# Agent、Skill 与 Engine 的边界

AscendC-Pilot 不通过不断增加 Agent 数量解决问题。

一个新的能力应该根据职责选择合适的位置：

```text
确定性计算                    -> Engine
领域推理方法                  -> Skill
一次任务目标                  -> Prompt
状态迁移                      -> Workflow
需要独立身份、权限或隔离上下文 -> Agent
```

例如：

不应该创建：

```
CoverageAgent
```

然后把：

* solver；
* replay；
* lemma；
* referee；

全部放进去。

正确方式是：

```text
TG Workflow -> deterministic closure engine
            -> lemma producer
            -> closure referee
```

每个部分具有明确职责。

---

# 权限模型与 Action Lease

AscendC-Pilot 不直接相信 Agent 自己声明的写入范围。

有效权限由三层约束共同决定：

```text
Agent declared scope

        ∩

Action allowed_write_paths

        ∩

Workflow write_roots

        =

Current Action Lease
```

其中：

* Agent YAML 定义该身份最大能力；
* Action 定义当前任务允许修改的位置；
* Workflow 定义当前阶段允许写入的位置。

Pilot 根据当前 run/action/actor 生成 Action Lease。

只有 Lease 覆盖范围内的路径才能被修改。

因此：

即使一个 Agent 拥有更高权限，也不能在当前 Action 中越界写入。

---

# Action 生命周期

一次 Action 的完整生命周期：

```text
acp next
    |
    v
Workflow selects Action
    |
    v
Build Action Bundle

    |- identity
    |- role
    |- execution mode
    |- prompt
    |- skill
    |- policy
    |- capability
    |- input contract
    |- output contract
    |- read/write scope

    |
    v

Create Action Lease

    |
    v

Execute

    |
    +----------------+
    |                |
    v                v

 Engine          LLM Agent


    |
    v

Staging Artifact

    |
    v

Checker / Referee

    |
    +-------------+
    |             |
 failed        passed
    |             |
    v             v

rework       Finalize

                  |
                  v

                Gate

                  |
                  v

          Workflow State Transition
```

关键设计：

Agent 输出永远不是最终事实。

执行结果首先进入 staging。

只有经过：

* contract validation；
* checker；
* referee；
* gate；

之后，才能写入 canonical artifact。

---

# State Machine

Workflow 状态推进由 Pilot 控制，而不是 Agent 自己决定。

典型流程：

```text
pending -> running -> checking -> passed -> finalize -> gate -> completed
checking -> failed -> rework
```

失败状态可能进入：

* `rework_required`
* `human_required`
* `blocked`
* `failed`

恢复路径必须由 Workflow 显式声明。

Agent 不能通过自然语言要求：

> “认为已经完成，继续下一步”。

---

# Producer / Referee 模型

对于需要推理但又不能直接修改规范状态的任务，Pilot 使用 Producer / Referee 分离。

Producer：

负责生成候选结果。

例如：

* coverage lemma；
* analysis report；
* change suggestion。

Referee：

负责检查：

* 证据是否充分；
* 是否违反 contract；
* 是否满足 policy。

最终：

```text
Producer -> Staging Evidence -> Referee -> Deterministic Finalizer -> Canonical Artifact
```

这种模式避免：

> 模型提出的判断直接成为系统事实。

---

# TG 中的 Runtime 示例

TG 是 Agent Runtime 设计的典型应用。

一次 `/tg-solve` 并不是一个 Agent 自由执行：

```text
tg-solver agent -> 生成覆盖结果
```

而是：

```text
TG Workflow -> Action Bundle -> {Closure Engine, Lemma Producer}
            -> Host Replay -> Observed Evidence -> Closure Referee -> Finalize Ledger
```

其中：

* replay evidence 属于确定事实；
* lemma 属于待审查证据；
* referee 判断 lemma 是否可靠；
* finalizer 才更新 coverage ledger。

因此：

“模型认为不可达”

不会直接变成：

“系统认为不可达”。

---

# Runtime 与 Artifact Authority

AscendC-Pilot 明确区分：

## Canonical Artifact

系统认可的正式结果。

例如：

* verified CodeMap；
* coverage ledger；
* closure certificate。

只能由受控流程写入。

---

## Staging Artifact

Agent 或 Engine 的中间结果。

例如：

* candidate；
* report；
* proposal；
* evidence draft。

可以被修改和重新生成。

---

## Cache / Derived Data

为了效率保存的数据。

不作为事实来源。

---

# 实现与 Reference

Runtime 的精确信息以代码和 generated reference 为准。

主要实现：

* Workflow：

  ```
  pilot/ascendc_pilot/workflows/specs.py
  ```

* Action / execution：

  ```
  pilot/ascendc_pilot/actions/
  ```

* Lease / authorization：

  ```
  pilot/ascendc_pilot/authorize/
  ```

* State machine：

  ```
  pilot/ascendc_pilot/state/
  ```

* Ownership：

  ```
  pilot/ascendc_pilot/ownership.py
  ```

Reference：

* Workflow:
  `docs/reference/workflows.generated.md`

* Agent Matrix:
  `docs/reference/agent-matrix.generated.md`

---

# 总结

AscendC-Pilot 的 Agent Runtime 本质上不是一个 Agent 调度器，而是一个面向工程自动化的控制层：

```text
CodeMap + Workflow + Action Contract + Permission Lease + Deterministic Verification + Bounded LLM Reasoning
```

它解决的问题不是“让 Agent 更聪明”，而是：

> 在复杂工程环境中，让 Agent 的行为可约束、可验证、可恢复，并让模型生成的内容经过验证后才能成为系统事实。

---
