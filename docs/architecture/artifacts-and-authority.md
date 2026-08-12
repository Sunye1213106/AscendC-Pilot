# 产物模型与权威边界

AscendC-Pilot 在目标算子仓中维护自己的运行状态和分析产物。UO、TG、CE 以及 Pilot Runtime 都通过同一个 `.ascendc-pilot/` 工作区交换数据，而不是在各自模块中维护独立副本。

这样可以保证一条明确的数据链：

```text
Source → UO CodeMap → TG / CE
              │
              └→ Pilot state / run records
```

下游模块只消费已经生成并通过相应检查的产物。模型生成的候选结果、中间缓存和正式结果使用不同的目录和写入规则，避免中间推理被误当成系统事实。

## 工作区布局

所有算子级产物位于：

```text
<operator-repo>/.ascendc-pilot/
```

典型结构如下：

```text
.ascendc-pilot/
├── uo/
│   └── <op_name>.<arch>.uo        # Operator CodeMap
└── <arch>/
    ├── uo/                        # UO projections / receipts
    ├── tg/                        # contract / plan / closure / replay
    ├── ce/                        # review / impact analysis
    ├── state/                     # workflow state / lease
    ├── runs/                      # bundle / staging / receipt
    ├── context/                   # context packages
    ├── memory/                    # reusable runtime memory
    ├── local/                     # operator-local extensions
    └── cache/                     # rebuildable cache
```

顶层 `uo/<op_name>.<arch>.uo` 是 UO 对外提供的 CodeMap 产品。TG、CE 和 `/uo-query` 以它及其投影为主要语义输入。

`<arch>/uo/` 保存 UO workflow 在具体架构下生成的投影和执行记录；`<arch>/tg/` 和 `<arch>/ce/` 分别保存测试生成和代码工程阶段的产物。

`state/` 和 `runs/` 属于 Pilot Runtime。前者保存当前 workflow 状态和权限信息，后者保存一次 Action 的执行过程。`context/`、`memory/` 和 `cache/` 主要用于提高运行效率，可以在不改变领域事实的情况下重新生成。

`local/` 用于保存与具体算子或工程环境相关的扩展，例如 testcase builder、replay adapter 或 TilingData decoder。这些扩展属于目标算子仓，不进入 AscendC-Pilot 的通用实现。

---

## 产物分层

并不是 `.ascendc-pilot/` 中的所有文件都具有相同可信度。AscendC-Pilot 将产物分为正式结果、中间结果和执行记录。

### Canonical Artifact

Canonical Artifact 是系统当前认可的正式结果，可以作为其他 workflow 的输入。

典型的 Canonical Artifact 包括：

* UO 生成并验证后的 Operator CodeMap；
* TG 的 contract 和 coverage closure 状态；
* Pilot 当前 workflow state；
* 经过验证并已经写入正式位置的结果。

Canonical Artifact 必须有明确的 producer 和写入路径。LLM Agent 不能因为“认为结果正确”就直接修改这些文件。

例如：

```text
UO deterministic commit → Operator CodeMap → TG / CE
TG verified evidence     → closure ledger   → coverage result
```

正式状态的修改由确定性 Action 或 finalizer 完成，并受到 Workflow、Action Contract 和写入权限约束。

### Staging Artifact

Staging Artifact 保存尚未被系统接受的候选结果。

例如：

* Agent 生成的分析结果；
* lemma proposal；
* testcase candidate；
* source evidence；
* review draft。

Staging 只说明“某个执行者产生了这个结果”，不说明该结果已经成立。

一个候选结果通常经过：

```text
Producer → Staging → Check / Review → Finalize → Canonical
```

如果检查失败，原结果仍然保留在当前 run 中用于分析和重试，但不会进入正式产物。

### Receipt

Receipt 记录一次 Action 是如何完成的。

它通常包含执行身份、Action、输入、输出、Contract、检查结果等信息，用于审计、恢复和问题定位。

Receipt 可以证明：

> 某个 Action 在某个输入和运行条件下产生了某个结果。

但它本身不等同于领域结论。例如一次 replay 的 receipt 可以记录实际返回的 TilingKey，但只有经过 TG workflow 认可后，相应观测才会用于更新 coverage 状态。

---

## 模块之间如何交换产物

UO 是 TG 和 CE 的语义基础。

```text
                ┌→ /uo-query
Source → UO → CodeMap ─→ TG → Coverage
                └──────→ CE → Review / Impact
```

UO 负责从源码和编译上下文中建立 CodeMap。TG 不重新建立一套源码模型，而是从 UO 提供的关系中构造测试义务；CE 同样以 CodeMap 为基础分析修改的传播范围。

主要产物关系如下：

| 产物                      | 主要生产者                   | 主要消费者                  | 性质                   |
| ----------------------- | ----------------------- | ---------------------- | -------------------- |
| `uo/<op>.<arch>.uo`     | UO deterministic engine | UO Query、TG、CE         | Canonical            |
| `<arch>/uo/**`          | UO workflow             | UO、TG、CE               | Projection / Receipt |
| `<arch>/tg/contract/**` | TG init                 | TG plan / solve        | Canonical            |
| `<arch>/tg/plan/**`     | TG plan                 | TG solve               | Workflow Product     |
| `<arch>/tg/replay/**`   | Replay pipeline         | TG closure             | Evidence             |
| `<arch>/tg/closure/**`  | TG finalizer            | TG、Regression          | Canonical            |
| `<arch>/ce/**`          | CE workflow             | Developer              | Analysis Result      |
| `<arch>/state/**`       | Pilot Runtime           | Pilot Runtime          | Canonical State      |
| `<arch>/runs/**`        | Pilot / current Action  | Checker、Recovery、Debug | Execution Record     |
| `<arch>/context/**`     | Pilot                   | Current Action         | Rebuildable          |
| `<arch>/cache/**`       | Pilot / Engine          | Runtime                | Rebuildable          |
| `<arch>/local/**`       | User / Local Extension  | UO、TG、CE               | Local Authority      |

这里的关键不是每个文件叫什么，而是数据只能沿声明的方向流动。

TG 和 CE 可以读取 UO 结果，但不能修改 UO CodeMap；Agent 可以生成 staging evidence，但不能直接修改 closure ledger；Runtime 可以维护 workflow state，但领域 Agent 不应手工修改 `state/` 来跳过流程。

---

## 写入权与事实权威

AscendC-Pilot 将“能够分析某件事”和“能够把它写成正式结果”分开。

LLM Agent 可以执行需要推理的工作，例如分析 unresolved、寻找源码证据、提出不可达条件或生成 review finding。但这些结果首先是候选信息。

Canonical 状态的修改必须经过对应 workflow。

TG 的 lemma 流程就是一个典型例子（穿插在每轮 Round Analysis 中，不是搜索收尾补丁）：

```text
Replay Round → Round Analysis
  → (expected growth) Lemma Producer → Staging Evidence → Referee → Finalizer → E
  → (unexpected growth) directed construct from discovered R + source
```

Producer 可以提出“某个 TilingKey 不可达”的证明和源码依据；Referee 检查证据是否成立；只有 finalizer 才能将通过的 exclusion 应用到正式 closure 状态。

因此：

> 模型的判断不是事实，经过系统验证并写入正式产物的结果才是事实。

UO 采用相同原则。无法通过确定性分析确认的关系保留为 unresolved，而不是由 Agent 为了“补全 CodeMap”直接写入正式图。

---

## 产物新鲜度

Operator CodeMap 不是与源码无关的长期缓存。

它建立在具体的 Source Scope、BuildVariant、目标架构和编译环境之上，并通过 fingerprint 与这些输入建立关联。

当源码或构建条件发生变化时：

```text
Source / Build Change → /uo-update or /uo-init → Fresh CodeMap → TG / CE
```

UO 负责判断已有 CodeMap 是否仍然匹配当前源码，并重新生成受影响部分或完整重建。

TG 和 CE 不应该在 UO 已过期时自行从源码推导新的正式语义。它们首先要求一个有效的 UO 输入，再继续自己的 workflow。

同样，TG 的 contract、plan 和 closure 也依赖对应的 UO 版本以及 replay 条件。如果上游语义输入变化，旧的 coverage 结论不能无条件继续沿用。

---

## 可重建数据与持久状态

并非所有产物都需要长期保留。

`context/` 和 `cache/` 主要用于提高运行效率，通常可以从源码、CodeMap 和当前 Workflow Input 重新生成。

`runs/` 保存执行过程，主要用于审计、调试和恢复。一个旧 run 不代表当前状态，但它应保留足够信息说明当时发生了什么。

真正需要稳定管理的是：

```text
Source / Build identity
        +
Canonical CodeMap
        +
Workflow State
        +
Validated TG / CE Products
```

这种分层避免将大量临时数据长期当作知识库，同时保留必要的可追溯性。

---

## 失败与恢复

当 Action、Checker 或 Gate 失败时，Pilot 不通过直接修改正式文件继续执行。

失败结果和相关 receipt 保留在当前 run 中，Workflow 根据 reason code 进入声明的恢复路径，例如重新执行当前 Action、返回前一个 phase，或者要求人工处理。

```text
Action → Check
          ├─ pass → Finalize → Next Phase
          └─ fail → Rework / Human / Blocked
```

恢复的原则是保留已有证据，只重新执行失效或失败的部分。

如果问题来自源码或 BuildVariant 变化，应回到 UO 更新语义基础；如果问题来自 TG candidate 或 proof，则只处理对应测试义务，不需要重新建立整套 CodeMap。

不应该通过手工修改 canonical 文件、state 或 ledger 来绕过失败状态。

---

## 实现边界

产物模型由 Runtime 和各 Engine 共同实现，但权威定义仍然来自代码。

主要实现位置包括：

* `pilot/ascendc_pilot/paths/`：工作区和路径定义；
* `pilot/ascendc_pilot/ownership.py`：Action 读写边界；
* `pilot/ascendc_pilot/workflows/specs.py`：Workflow、Action 和写入根；
* `pilot/ascendc_pilot/state/`：运行状态；
* `pilot/ascendc_pilot/authorize/`：Action Lease 和权限检查；
* `engines/understand-operator/`：UO 产品生成；
* `engines/testcase-generation/`：TG contract、replay 和 closure；
* `engines/code-engineering/`：CE 分析产物。

由实现生成的 Reference 用于查看精确路径和当前合同；本页只描述稳定的设计边界。

---

## 设计总结

AscendC-Pilot 的产物模型遵循一个简单原则：

```text
Source → Deterministic Facts → Canonical Product → Downstream Workflow
                              ↑
                    validated staging only
```

UO 建立算子语义事实，TG 和 CE 消费这些事实；Agent 可以帮助分析和生成候选结果，但正式产物只能通过受控 Workflow 更新。

这种设计使 CodeMap、coverage 和工程分析都具有明确来源，同时保留了 Agent 推理的灵活性和整个执行过程的可追溯性。
