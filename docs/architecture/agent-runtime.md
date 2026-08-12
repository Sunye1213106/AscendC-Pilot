# Agent Runtime

## 为什么需要 Agent Runtime

在复杂工程任务中，一个 Agent 不应该同时承担源码理解、方案生成、文件修改、结果验证以及状态推进。

如果所有行为都由单一 Agent 完成，会产生几个问题：

* Agent 的权限边界难以控制；
* 中间结果和最终规范产物无法区分；
* 模型生成的推理结果容易被误认为事实；
* Workflow 状态可能被非确定性行为推进。

因此 AscendC-Pilot 不把 Agent 看作一个直接执行任务的黑盒，而是引入 Runtime Control Plane（ACP Harness）。

Runtime 负责管理：

* 当前任务处于哪个 Workflow phase；
* 当前 Action 是否允许执行；
* Agent 可以访问和修改哪些资源；
* 输出是否满足 contract；
* 是否可以进入下一状态。

核心原则：

> Deterministic Engine 负责事实，LLM Agent 负责推理，Pilot Runtime 负责约束执行、验证结果和推进状态，Host Adapter 负责传输与派发（Session Driver）。

---

# Runtime 模型

AscendC-Pilot 将一次任务拆分为多个具有明确输入输出边界的 Action。

整体关系如下：

```text
Workflow -> Action -> {Deterministic Engine, Agent Execution (LLM)}
        -> Contract Check -> Gate -> State Transition
```

```text
Host (OpenCode / Cursor / Codex)
  -> Host Adapter (compose + plugin/hooks + Session Driver)
       -> Primary Agent / Subagent
            -> acp CLI  (Pilot Runtime)
                 |- start / next / run-action / advance / complete
                 |- run-action auto / drive  (+ host_step)
                 |- dispatch-result (ticket → finalize → continue drive)
                 |- authorize / serve-authorize
                 |- Engine actions (deterministic)
                 |- LLM actions (prepare -> Task -> finalize)
```

**Host Session Driver**（运行时传输角色）：把 `start → auto → Task → finalize → auto` 从 Primary LLM 挪到 Host Adapter。OpenCode 暴露自定义工具 `pilot_run`；ACP 返回结构化 `host_step`（`dispatch_subagent` / `ask_human` / `done` / `failed`）与一次性 `dispatch_ticket`。Driver 不获得 advance/complete/写 canonical 的权力。

`authorize` 热路径：`acp serve-authorize --ipc-dir …` 常驻进程 + 短 TTL verdict 缓存；失败时回退 `spawnSync acp authorize`。

Workflow 定义系统允许发生什么。Action 定义当前一步具体做什么。Engine 和 Agent 负责产生结果。Checker 和 Gate 决定结果是否可以成为系统状态。

| 部件 | 作用 | 非职责 |
| --- | --- | --- |
| Pilot Runtime (`ascendc_pilot`) | workflow 状态、Action prepare/finalize、Lease、gate、context、recovery、`acp` CLI | 不实现领域分析本身 |
| Engines | 确定性计算与 canonical 产物写入 | 不拥有 workflow 权威；不替代 Lease |
| Host Adapters | **安装期**：compose skills/agents/prompts/hooks；**运行时**：Session Driver（`pilot_run` / `host_step` 派发） | 不定义领域语义；不改写 workflow 事实；不宣布 `passed` |

Harness 是软控制面，不是 OS 安全边界。从其他 Tab 或外部终端仍可能改文件，但拿不到 Pilot 认可的 `passed` / receipt / complete。

---

# Runtime 对象

| 对象 | 作用 | Source of Truth |
| --- | --- | --- |
| Workflow | 定义 phase、transition、action、gate 和写入范围 | `pilot/ascendc_pilot/workflows/specs.py` |
| Action | 定义一次可执行任务，包括输入输出 contract | Workflow specification |
| Agent | 定义稳定身份、角色和权限上限 | `agents/*.yaml` |
| Skill | 定义领域方法、分析流程和证据要求 | `skills/*/SKILL.md` |
| Prompt | 定义某一次 Action 的具体任务描述 | `prompts/tasks/` |
| Policy | 定义运行约束和行为规则 | `pilot/policies/` |
| Capability | 定义 Agent 或 Engine 可以调用的能力 | runtime capability registry |
| Engine | 执行确定性逻辑并生成可信产物 | `engines/` |

职责分离：Workflow 管状态；Action 管任务；Agent 管身份；Skill 管领域方法；Prompt 管当前任务；Policy 管约束；Engine 管确定性计算。

例如在 TG closure 中：“如何判断不可达”属于 Skill；“生成 lemma”属于 Prompt；“验证 replay 结果”属于 Engine；“是否允许更新 closure ledger”属于 Workflow + Gate。它们不能混在一个 Agent 中。

---

# Agent、Skill 与 Engine 的边界

```text
确定性计算                    -> Engine
领域推理方法                  -> Skill
一次任务目标                  -> Prompt
状态迁移                      -> Workflow
需要独立身份、权限或隔离上下文 -> Agent
控制面传输与派发              -> Host Session Driver
```

不应创建把 solver、replay、lemma、referee 全部塞进同一个 `CoverageAgent`。正确方式是：

```text
TG Workflow -> deterministic closure engine
            -> lemma producer
            -> closure referee
```

也不应让 Primary LLM 手搓 ACP 协议环。正确方式是：

```text
User intent -> pilot_run / acp start
            -> acp run-action auto   # 排空确定性 + 返回 host_step
            -> Host 派发 Task(stub) 或 AskQuestion
            -> acp dispatch-result   # finalize + 继续 drive
```

---

# 权限模型与 Action Lease

> 一步任务开始时签发的**临时通行证**（Action Lease）——限定谁可以动、能读/写哪些路径、本步结束或失败后作废。
> 写在 `.ascendc-pilot/<arch>/state/action_lease.yaml`，与 `active_action.yaml` 绑定；`acp run-action` 准备时签发，收尾或失败处理后撤销。
> 这是 Pilot 的软约束（靠 hook 拦越权），不是 OS 沙箱。

## 权限怎么收窄

最终能写什么，取三层交集（再叠加身份禁令）：

```text
Agent 声明的可写范围 / 禁令
        ∩
本步 Action 允许的路径
        ∩
Workflow 允许的根目录
        =
当前 Action Lease（本步通行证）
```

实现上还会强制：

* **能写就能读**：写入路径自动并入可读范围（写完还要能读回来核对）。
* **人对上号**：非主控 Agent 的读写必须匹配通行证上的 `actor_id` / `action_id` / `run_id`。
* **主控不写正式结论**：主控 Agent（`ascendc-pilot`）即使角色叫 controller，也不能直接写正式 IR / summary / checks / review / TG 正式产物；这些由声明的 Producer、Referee 或 Engine 写入。
* **角色只是上限**：例如 `readonly_analyst` 不写正式 domain 产物（`.uo` / TG / CE），但**允许** action-local result / scratch；`referee` 只写 review。最终权限仍以「角色 ∩ Agent 上限 ∩ 本步通行证 ∩ Workflow 根目录 ∩ 身份禁令」为准。
* **prepare 静态闭合（写）**：`direct` 模式下合同产物必须落在 `agent.write_scopes ∩ action.allowed_write_paths`，否则 `OUTPUT_NOT_WRITABLE` 当场失败，不派发子代理。`return_value` 由 finalizer 物化，不要求子代理先 Write。
* **prepare 静态闭合（读）**：`task_prompt_stub` 引用的路径必须存在且落在 lease 可读集合内，否则 `BUNDLE_NOT_READABLE` 当场失败。Cognitive skill 正文与 references 在 prepare 时物化进 action session 的 `method.md` / `refs/`，子代理只读自己的 session dir。
* **scope 命名空间**：`agents/*.yaml` 的 `read_scopes` / `write_scopes` 支持前缀 `pilot:`（`.ascendc-pilot/<arch>/` 相对）、`method:`（host cognitive-skills / skills 树）、`source:`（算子仓源码根）。无前缀旧值按现行语义兼容。
* **run 级 source scope**：`acp start` 解析一次 `allowed_source_roots` 写入 `runs/<run_id>/source_scope.yaml`，后续 action lease 继承；探查性只读不再表现为「没有仓库权限」。
* **containment 只读白名单**：`failed` / `blocked` / `human_required` 下仍禁止推进与写入，但允许读 session `method.md` / `prompt.md` / skill 文本，避免 abort 后连方法都读不了。

Agent YAML 里 `forbidden` 标签的确定含义：

| Tag | 效果 |
| --- | --- |
| `modify_pilot_state` | 禁止写 `state/` |
| `modify_uo_product` | 禁止写 `.uo` / `uo/summary` / `uo/checks` |
| `declare_workflow_passed` | 禁止用 bash 走 `acp complete` 等宣布通过 |
| `write_outside_declared_scope` | 未声明可写范围则不可写 |

对 Pilot 相关 Agent，未知 tool **默认拒绝**（`TOOL_UNKNOWN`）。

## 工作流状态 → 授权模式

授权模式只跟 workflow **status** 走，不会因为旧通行证过期就自动放开权限：

| Status | Mode | 允许做什么 |
| --- | --- | --- |
| `running`（及默认） | `normal` | 正常跑 `acp *`、在声明路径上读写、派 Task、只读探查 |
| `rework_required` | `rework` | 重试失败的那一步 / 声明的恢复动作；禁止 advance/complete |
| `human_required` / `blocked` / `failed` | `containment` | 几乎只能做恢复类命令；默认禁止 Write/Task |

`acp start` 在各 mode 下始终允许。只有 Pilot 相关 Agent（`ascendc-pilot`、`uo-*` / `tg-*` / `ce-*` / `deterministic-*`）走这套约束；普通 Build / Plan / General Tab 不套用。

---

# Action 生命周期

```text
acp next
    |
    v
Workflow selects Action
    |
    v
Build Action Bundle + Create Action Lease（本步通行证）
    |
    +----------------+
    v                v
 Engine          LLM Agent
    |
    v
Staging Artifact -> Checker / Referee
    |
    +-- failed -> rework
    +-- passed -> Finalize -> Gate -> Workflow State Transition
```

Agent 输出永远不是最终事实。只有经过 contract validation、checker、referee、gate 之后，才能写入 canonical artifact。目录与 freshness 规则见 [产物与权威](artifacts-and-authority.md)。

典型状态：

```text
pending -> running -> checking -> passed -> finalize -> gate -> completed
checking -> failed -> rework
```

失败可进入 `rework_required` / `human_required` / `blocked` / `failed`。恢复路径必须由 Workflow 显式声明。Agent 不能通过自然语言宣布完成。

---

# Producer / Referee 模型

需要推理但又不能直接修改规范状态时，使用 Producer / Referee 分离：

```text
Producer -> Staging Evidence -> Referee -> Deterministic Finalizer -> Canonical Artifact
```

这避免模型提出的判断直接成为系统事实。TG 中 lemma 的轮次路由细节见 [TG](../modules/tg.md)；Runtime 只保证：replay 是确定事实，lemma 须经 referee，finalizer 才更新 coverage ledger。

---

# ACP 实现：控制环与 authorize

推荐路径由 **Host Session Driver** 驱动（OpenCode：`pilot_run`），Primary 不再手搓 `start → todo → auto → prepare → Task → finalize`：

```text
pilot_run(workflow, project, …)
  -> acp start
  -> acp run-action auto          # 排空确定性；遇 LLM 步返回 host_step + dispatch_ticket
  -> Host 派发 Task(stub) 或 AskQuestion
  -> acp dispatch-result --ticket …
  -> （循环直至 host_step = done | failed）
```

开发者 / 调试仍可逐步调用：

```text
acp start
  -> acp next
  -> acp run-action <id>           # prepare：发通行证 + 打包任务
  -> Engine 或 LLM Subagent 执行
  -> acp run-action <id> --finalize
  -> acp advance / complete        # 仅 gate 通过后
```

| 命令 | 作用 |
| --- | --- |
| `acp start` | 启动或复用 run；失败态逃生口；全覆盖 NL 可写入 `control/user_goal.yaml`；解析 run 级 `source_scope.yaml` |
| `acp next` | 下一 Action / 恢复提示 |
| `acp run-action` | **workflow run 内**唯一正式执行入口：prepare / `--finalize` / `auto`（drive + `host_step`） |
| `acp dispatch-result` | 消费一次性 `dispatch_ticket`，finalize 后继续 drive |
| `acp scan-architectures` | 启动前快速扫描算子 `op_host`/`op_kernel` 布局与 `arch*` 选项（供 AskQuestion；禁止仓根考古） |
| `acp authorize` / `serve-authorize` | Host plugin 授权裁决；后者为常驻 daemon（IPC），失败回退前者 |
| `acp doctor --host opencode` | Host Session Driver / plugin / cognitive-skills 契约预检 |
| `acp advance` / `complete` | 仅 gate 通过后推进或结束；`complete` 可推进 User Goal 并返回 `recommended_next_workflow` |
| `acp rework` / `abort` / `block` | 沿声明边恢复、终止或收敛 |
| `acp status` / `inspect-failure` | 只读观测（失败卡含给人看的白话摘要） |

完整命令表见 [CLI Reference](../reference/cli.generated.md)。

**人话与 Goal**：Primary 对用户的总结 / AskQuestion / 进度必须带意图与动作（见 `human-voice-invariants.md`）；禁止把 referee 黑话贴给用户。全量 tilingkey case 产品目标串联 init→plan→solve，不把 NL 塞进 `acp route`。Todo 同步与 `return_value` finalize 由 Driver 持有，不要求模型再实现一遍。

Host 侧（以 OpenCode 为例）在工具真正执行前走 `serve-authorize`（或 `authorize`）。常见拒绝：直调领域脚本、用 bash 乱写 `.ascendc-pilot/`、超出本步通行证允许的路径、主控去写正式 IR、派了未声明的子代理。默认 bash 优先走 `acp *` 与只读探查；其他 shell 对主控多为 `ask`。子会话身份靠 session ticket（childSessionID↔actor↔action↔lease），不靠猜环境变量。

LLM Action 端到端：

```text
prepare（物化 method.md / refs + Bundle 读闭合）
  -> Task(stub 原样；cwd=算子仓；注入 ASCENDC_PROJECT_ROOT)
  -> authorize Read/Write
  -> dispatch-result / finalize -> Gate -> advance
```

`uo-query` / `kb_lookup` 是 **claim-driven Explore**：先读 progressive `uo-product-map`，按 claim sufficiency 有界探索。使用 `output_mode: return_value`（Explorer `write_scopes: []`）：子代理在最终消息返回 `kb-answer-v1`；Host Driver 经 `dispatch-result`（或人工 `acp run-action kb_lookup --finalize`）收尾。OpenCode return_value 插件可将 Task 末尾 payload 注入 `ASCENDC_ACTION_RESULT`，**无需手写 scratch / `--result-file`**。Runtime 物化 action-local `answer.yaml` 并注入 identity。`--result-file` 仅人工 fallback。**Explorer 不写；Runtime 物化。** Domain 正式产物仍禁止 LLM 直写。

### `/uo-query` workflow vs delegated `Task(actor=uo-query)`

```text
uo-query Agent
├── /uo-query workflow（kb_lookup：完整 prepare → Task → finalize）
└── Task(actor=uo-query)  ← TG / CE / Primary 委托（共用 Agent/Skill/METHOD/return contract）
```

- **Workflow `/uo-query`**：完整 lifecycle（start → prepare `kb_lookup` → Explore → finalize）。
- **Delegated Task**：TG/CE/Primary **不得**再开完整 `/uo-query` lifecycle；直接 `Task(actor=uo-query)`，共用同一 Agent / Skill / METHOD / `kb-answer-v1`。
- Parent **必须**传入显式 **UO Product Handle**（`op_name` / `architecture` / `path` / `schema` / fingerprint|digest）；禁止子代理自找 `.uo`。构造见 `ascendc_pilot.uo_product_handle.build_uo_product_handle`。

### 复杂多 claim：Primary fan-out

```text
复杂多 claim 问
  → Primary 拆 claim（如 Host / Kernel / Perf，≤4）
  → 并行 Task(actor=uo-query) × N（各单 claim + 同一 UO Product Handle）
  → Primary 合成确切答案：冲突取更严；子答 UNKNOWN/PARTIAL 不得抬成 high
  → 不得用其他 arch 证据闭合当前 arch claim
```

简单单 claim：一个 Task 即可。禁止把 3+ 正交子问塞进同一个 Explorer。
确定性 Action 跳过 Task：prepare 后由 Pilot 调度 Engine，再 finalize。

---

# Engines

| Engine | Package | 职责 |
| --- | --- | --- |
| `common` | `acp-common` | 共享 engine utilities |
| `understand-operator` | `uo_init` | UO CodeMap extraction、analysis、commit、query、dump |
| `testcase-generation` | `testcase_agent` | TG contract、plan、solve、closure、replay |
| `code-engineering` | `code_engineering` | CE impact 与 review 支持 |

规则：Engine 只有经声明的 Pilot Action 或显式 developer CLI 才写 canonical products；`deterministic-*-engine` 是 authorization identity，不是 LLM subagent。新增 engine 目录时须在本表登记并通过 docs check。

---

# Host Adapters

支持 OpenCode、Cursor、Codex。Adapter 有两层职责：

1. **安装期**：compose 生成 skills/agents/prompts/policies/hooks；OpenCode 把 cognitive skills 投影到 `cognitive-skills/`（`compose_runtime` 统一 remap 描述路径）。
2. **运行时（Session Driver）**：传输与派发。OpenCode 实现见 `opencode-plugin/pilot-driver.ts`（工具 `pilot_run`）与 `ascendc-pilot.ts`（authorize daemon、session ticket、Task cwd）。Driver **不是**新权限面：不 advance、不 complete、不写 canonical。

```bash
python scripts/compose_runtime.py --repo . --host opencode
python scripts/compose_runtime.py --repo . --host cursor
python scripts/compose_runtime.py --repo . --host codex
acp doctor --host opencode   # 安装后契约预检
```

CI 侧：`scripts/check_host_driver_contract.py`（workflow `control-plane-contract`）。`generated/` 是镜像，不是源文档。人类说明以 `docs/` 为准；模型消费的 Skill / Prompt / Policy 留在 runtime 位置（见 [文档维护](../development/documentation.md)）。

---

# 实现与 Reference

| 主题 | 路径 |
| --- | --- |
| CLI | `pilot/ascendc_pilot/cli.py` |
| Workflow Spec | `pilot/ascendc_pilot/workflows/specs.py` |
| Action prepare/finalize / dispatch | `pilot/ascendc_pilot/actions/`（含 `dispatch.py`、`method_bundle.py`） |
| Lease / Authorize / cache / daemon | `pilot/ascendc_pilot/authorize/` |
| Agent ceiling / scope 命名空间 | `pilot/ascendc_pilot/agents_registry.py`、`agents/*.yaml` |
| Ownership | `pilot/ascendc_pilot/ownership.py` |
| State machine / drive | `pilot/ascendc_pilot/state/`、`drive.py` |
| Host doctor | `pilot/ascendc_pilot/host_doctor.py` |
| Compose / adapters | `scripts/compose_runtime.py`、`adapters/hosts/` |
| OpenCode plugin + Session Driver | `opencode-plugin/ascendc-pilot.ts`、`pilot-driver.ts` |
| Host Driver CI | `scripts/check_host_driver_contract.py` |
| Engines | `engines/{common,understand-operator,testcase-generation,code-engineering}/` |
| 测试 | `pilot/tests/`、`evals/harness_e2e/` |

Reference：[Workflow](../reference/workflows.generated.md)、[Agent Matrix](../reference/agent-matrix.generated.md)、[CLI](../reference/cli.generated.md)、[产物与权威](artifacts-and-authority.md)。

---

# 总结

```text
Host Session Driver (pilot_run)
  -> acp start / run-action auto / dispatch-result
  -> Host Hook: serve-authorize（Lease 裁决）
  -> Engine 写事实，或 LLM 在 staging / return_value 产出
  -> Finalize + Gate
  -> 正式状态 / 正式产物
```

Agent Runtime 解决的不是“让 Agent 更聪明”，而是：在复杂工程环境中，让 Agent 的行为可约束、可验证、可恢复，并让模型生成的内容经过验证后才能成为系统事实；传输环路由 Host 持有，不占用 Primary LLM 的协议 turn。
