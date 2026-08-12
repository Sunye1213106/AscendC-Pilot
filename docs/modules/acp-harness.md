# ACP Harness

## 为什么需要 Harness

AscendC-Pilot 不把 Host 里的 LLM Agent 当成可以自由改仓库、自由宣布成功的黑盒。

如果没有控制面：

* Agent 可以绕过 `acp` 直调领域脚本，或用 bash 改写 `.ascendc-pilot/`；
* Producer 可以越权写入 canonical 产物；
* 失败状态下仍可继续推进 workflow；
* 不同 Host 会各自发明一套权限与指令投影。

因此 Control Plane 以 **ACP Harness** 的形式存在：Pilot Runtime 拥有状态与授权权威；Host Adapter 把同一套规则投影到 OpenCode / Cursor / Codex；Deterministic Engine 只在声明的 Action 下写入可信事实。

核心原则：

> Deterministic Engine 负责事实，LLM Agent 负责推理，ACP Harness 负责约束两者之间的边界。

这与 [Agent Runtime](../architecture/agent-runtime.md) 描述的 Workflow / Action / Lease 模型一致；本文说明这些对象在实现上如何落成 `acp` CLI、authorize 钩子、Engine 与 Host 投影。

---

# 组成

```text
Host (OpenCode / Cursor / Codex)
  -> Host Adapter (compose + plugin/hooks)
       -> Primary Agent / Subagent
            -> acp CLI  (Pilot Runtime)
                 |- start / next / run-action / advance / complete
                 |- authorize  (tool 调用前的软控制面)
                 |- Engine actions (deterministic)
                 |- LLM actions (prepare -> Task -> finalize)
```

| 部件 | 作用 | 非职责 |
| --- | --- | --- |
| Pilot Runtime (`ascendc_pilot`) | workflow 状态、Action prepare/finalize、Lease、gate、context、recovery、`acp` CLI | 不实现领域分析本身 |
| Engines | 确定性计算与 canonical 产物写入 | 不拥有 workflow 权威；不替代 Lease |
| Host Adapters | 安装/生成 skills、agents、prompts、policies、hooks | 不定义领域语义；不改写 workflow 事实 |

Harness 是软控制面，不是 OS 安全边界。从其他 Tab 或外部终端仍可能改文件，但 **拿不到** Pilot 认可的 `passed` / receipt / complete——规范状态只能经 `acp` 与 gate。

---

# Pilot Runtime：`acp` 控制环

Pilot 解析算子工作区，驱动一次 run：

```text
acp start
  -> acp next                 # 选择下一 Action / obligations
  -> acp run-action <id>      # prepare：签发 Lease + Action Bundle
  -> Engine 或 LLM Subagent 执行
  -> acp run-action <id> --finalize
       -> contract / checker / referee / receipt
  -> acp advance / complete   # 仅 gate 通过后推进
```

关键命令的语义：

| 命令 | 作用 |
| --- | --- |
| `acp start` | 启动或复用 workflow run；失败态下的逃生口 |
| `acp next` | 返回当前可执行 Action 与恢复提示 |
| `acp run-action` | **唯一**正式执行入口：prepare 或 `--finalize` |
| `acp authorize` | Host plugin 在 tool 调用前询问的授权裁决 |
| `acp advance` / `complete` | 仅在 gate 通过后推进或结束 |
| `acp rework` / `abort` / `block` | 沿声明边恢复、终止或收敛 |
| `acp status` / `inspect-failure` | 只读观测 |

完整命令表见 [CLI Reference](../reference/cli.generated.md)。

不变量：

* Agent 不能用自然语言宣布 workflow success；
* 只有 finalize + gate 能把 staging 变成规范状态；
* status 决定 authorization mode；Lease 不得把较宽松模式覆盖到更严的 status 上。

---

# 权限模型

## 三层交集：Action Lease

有效写入权限不是 Agent YAML 的自述，而是：

```text
Agent declared write_scopes / forbidden
        ∩
Action allowed_write_paths (+ forbidden)
        ∩
Workflow write_roots
        =
Current Action Lease
```

`acp run-action` prepare 时签发 Lease，并写入：

```text
.ascendc-pilot/<arch>/state/action_lease.yaml
```

同时记录 `active_action.yaml`（action_id / actor_id / lease_id）。finalize 成功或失败收敛后撤销 Lease。

额外约束（实现中强制）：

* **写 ⊆ 读**：Lease 的每个 write path 自动并入 read paths，避免“能写不能回读”；
* **Actor 绑定**：非 primary 的读写必须匹配 `lease.actor_id` / `lease.action_id` / `lease.run_id`；
* **Primary 不写正式产物**：`ir/`、`summary/`、`checks/`、`review/`、TG formal 路径等须由声明的 Producer / Referee / Engine 写入；
* **Role 策略**：`producer`/`controller`/`deterministic_engine` 可写 formal；`referee`/`readonly_reviewer` 仅 review；`deterministic_checker` 仅 checks；`readonly_analyst` 不可写。

Agent YAML 的 `forbidden` 标签有确定性含义，例如：

| Tag | Harness 效果 |
| --- | --- |
| `modify_pilot_state` | 禁止写 `state/` |
| `modify_uo_product` | 禁止写 `.uo` / `uo/summary` / `uo/checks` |
| `declare_workflow_passed` | 禁止用 bash 走 `acp complete` 等“宣布通过”路径 |
| `write_outside_declared_scope` | 空 `write_scopes` 即不可写 |

未知 tool 对 Pilot-family agent **fail-closed**（`TOOL_UNKNOWN`），不再默认放行。

## Status → Authorization Mode

Mode 只由 workflow **status** 推导，不以过期 containment Lease 升级权限：

| Status | Mode | 允许面 |
| --- | --- | --- |
| `running`（及默认） | `normal` | `acp *` 主路径、声明路径上的 Read/Write/Task、只读探查 |
| `rework_required` | `rework` | 重试失败 Action / 声明的 recovery；禁止 advance/complete |
| `human_required` / `blocked` / `failed` | `containment` | 仅恢复类命令（`next`/`status`/`inspect-failure`/`abort`/`start`/…）；默认禁止 Write/Task |

`acp start` 在各 mode 下始终允许，以便开新 run。

## 谁被套用 Harness

仅 **Pilot-family** agent：

* primary：`ascendc-pilot` / `ascendc_agent`；
* 声明的 `uo-*` / `tg-*` / `ce-*` / `deterministic-*` 身份。

OpenCode 的 Build / Plan / General 等 Tab **pass-through**：不套用 Harness，即使目录下残留失败 run。这样人类调试不被 containment 误伤；Pilot Tab 内则继续受约束。

---

# Host 侧执行：authorize 钩子

Host Adapter 安装 plugin/hooks；以 OpenCode 为例，`tool.execute.before` 在工具真正执行前调用：

```text
Agent 发起 tool
  -> AscendCHarnessPlugin
  -> acp authorize --tool … --agent … --action … --path/--command …
  -> allow | deny | ask
```

裁决实现位于 `pilot/ascendc_pilot/authorize/`，插件本身不拥有领域规则。

典型拒绝：

| 场景 | reason（示意） |
| --- | --- |
| bash 直调 `uo-init` / `tg-solve` / 领域脚本 | `DOMAIN_CLI_BYPASS` |
| bash 重定向写入 `.ascendc-pilot/` | `BASH_PROTECTED_WRITE` |
| 写入超出 Lease / Agent scope | `ACTION_WRITE_SCOPE_DENIED` / `AGENT_WRITE_SCOPE` |
| Primary 写 formal IR | `PRIMARY_PROTECTED_WRITE` |
| containment 下写 formal | `HARNESS_ACTION_NOT_AUTHORIZED` |
| Task 派发给未声明子代理 | `TASK_AGENT_UNKNOWN` |
| Task prompt 为空 / `{}` | `TASK_PROMPT_EMPTY` |

默认 bash 策略：优先 `acp *` 与只读探查（`ls`/`pwd`/`rg`/…）；其他 shell 对 primary 为 `ask`，需人工确认。

Cursor / Codex 走同一套 authorize 语义，差异隔离在 adapter 与生成物路径，不在 workflow 权威中分叉。

---

# Engines：确定性执行身份

Engines 是确定性实现包。它们通过 Pilot Action（或显式 developer CLI）生产、校验 canonical artifacts。

| Engine | Package | 职责 |
| --- | --- | --- |
| `common` | `acp-common` | 共享 engine utilities |
| `understand-operator` | `uo_init` | UO CodeMap extraction、analysis、commit、query、dump |
| `testcase-generation` | `testcase_agent` | TG contract、plan、solve、closure、replay |
| `code-engineering` | `code_engineering` | CE impact 与 review 支持 |

规则：

* Engine 只有经声明的 Pilot Action 或显式 developer CLI，才写 canonical products；
* `deterministic-uo-engine`、`deterministic-tg-engine` 等是 **authorization identity**，不是 LLM agent；
* Agent 不得靠阅读/改写 engine 源码绕过 `acp run-action`（authorize 会拒绝相关 engine script 探查路径）。

新增 engine 目录时，必须在本页登记，并通过 docs check。

---

# Host Adapters：同一 Runtime 的投影

Adapter 把同一套 Pilot Runtime 投影到不同 AI coding hosts。

支持的 Host：

* OpenCode
* Cursor
* Codex

职责：

* 安装 generated skills、agents、prompts、policies 与 hooks；
* 把 host-specific path / syntax 隔离在 adapter 层；
* 在不同 host 上保持同一套 workflow 与 Lease 模型。

生成入口：

```bash
python scripts/compose_runtime.py --repo . --host opencode
python scripts/compose_runtime.py --repo . --host cursor
python scripts/compose_runtime.py --repo . --host codex
```

`generated/` 与 host 安装目录中的指令是 **镜像**，不是源文档。人类说明以 `docs/` 为准；模型消费的 Skill / Prompt / Policy 留在 runtime 位置（见 [文档维护](../development/documentation.md)）。

---

# 一次受控 Action（端到端）

以需要 LLM Producer 的 Action 为例：

```text
acp next
  -> acp run-action <action>          # prepare
        |- Action Bundle (prompt/skill/policy/capability/contracts)
        |- issue Action Lease
        |- task_prompt_stub
  -> Primary Task(subagent=declared actor, prompt=stub 原样)
        |- authorize: Task / Read / Write
        |- 仅写 Lease 覆盖的 staging 路径
  -> acp run-action <action> --finalize
        |- session / lease / artifact 绑定校验
        |- contract + checker/referee
        |- receipt；撤销 Lease
  -> Gate -> acp advance（若通过）
```

失败时 status 进入 `rework_required` 或 `human_required` 等；恢复边必须由 Workflow Spec 声明。Agent 不能要求“认为已完成，继续下一步”。

确定性 Action 则跳过 Task：prepare 后由 Pilot 调度 Engine，再 finalize。

---

# 实现与 Reference

| 主题 | 路径 |
| --- | --- |
| CLI | `pilot/ascendc_pilot/cli.py` |
| Workflow Spec | `pilot/ascendc_pilot/workflows/specs.py` |
| Action prepare/finalize | `pilot/ascendc_pilot/actions/` |
| Lease | `pilot/ascendc_pilot/authorize/lease.py` |
| Authorize | `pilot/ascendc_pilot/authorize/__init__.py` |
| Agent ceiling / forbidden | `pilot/ascendc_pilot/agents_registry.py`、`agents/*.yaml` |
| Ownership / path 合同 | `pilot/ascendc_pilot/ownership.py` |
| State machine | `pilot/ascendc_pilot/state/machine.py` |
| Compose | `scripts/compose_runtime.py` |
| Host adapters | `adapters/hosts/{opencode,cursor,codex}.yaml` |
| OpenCode plugin | `opencode-plugin/ascendc-pilot.ts` |
| Install | `install.ps1`、`install.sh` |
| Engines | `engines/{common,understand-operator,testcase-generation,code-engineering}/` |
| Engine identities | `agents/deterministic-uo-engine.yaml`、`agents/deterministic-tg-engine.yaml` |
| 测试 | `pilot/tests/`（含 authorize/harness）、`evals/harness_e2e/` |

Reference：

* [Workflow Reference](../reference/workflows.generated.md)
* [Agent Matrix](../reference/agent-matrix.generated.md)
* [CLI Reference](../reference/cli.generated.md)
* [产物与权威](../architecture/artifacts-and-authority.md)

概念层的 Action 生命周期与 Producer/Referee 分离见 [Agent Runtime](../architecture/agent-runtime.md)。

---

# 总结

ACP Harness 不是“再包一层 Agent 调度器”，而是把 Pilot、Engine 与 Host 接到同一条可验证控制链上：

```text
Host Hook -> acp authorize / run-action
  -> Action Lease (Agent ∩ Action ∩ Workflow)
  -> Engine 事实 或 LLM staging
  -> Finalize + Gate
  -> 规范状态
```

它要保证的是：模型可以推理，但不能单方面改写系统事实；确定性引擎可以写事实，但不能脱离 Action 与 Lease；不同 Host 可以换皮，不能换权威。
