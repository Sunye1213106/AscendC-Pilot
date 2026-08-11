# Agent Runtime

一个 Agent 不应包办源码理解、写入、审查和状态推进。这样既难以限制权限，也无法把“产出一份建议”和“确认该建议可成为规范产物”区分开。Pilot 将一次工作拆成带合同的 Action，并在动作之间保留可审计的状态。

## 运行时对象

| 对象 | 含义 | 权威位置 |
| --- | --- | --- |
| Workflow | phase、transition、action、gate 和写入根的声明 | `workflows/specs.py` |
| Action | 可执行的最小步骤，带输入/输出合同 | workflow spec |
| Agent | 稳定的 runtime identity 与权限上限 | `agents/*.yaml` |
| Skill | 领域方法、证据规则与按需参考 | `skills/*/SKILL.md` |
| Prompt | 某个 Action 的任务说明 | `prompts/tasks/` |
| Policy | 所有或部分 Action 的运行时约束 | `pilot/policies/` |
| Capability | 可调用工具或 runtime 方法的合同 | `pilot/runtime/`、`tools/` |
| Engine | 可重复执行的确定性程序 | `engines/` |

Skill 不是 Agent 的替代品：前者描述如何推理，后者提供独立身份、上下文边界或权限边界。确定性计算进入 Engine；一次任务说明进入 Prompt；状态迁移进入 Workflow；只有确实需要独立身份、隔离上下文或对抗性审查时才新增 Agent。

## 角色与权限

| 角色 | 可做的事 | 不能做的事 |
| --- | --- | --- |
| Primary | 协调用户意图和 workflow | 自行宣布 workflow 通过 |
| Deterministic engine | 生产或校验规范产物 | 绕过 action 合同写任意路径 |
| Producer | 写入 staging，提供候选证据 | 直接写 canonical final product |
| Referee | 审查 producer 的证据或报告 | 替代 finalizer 写入规范结果 |
| Readonly analyst | 查询、解释、调查 unresolved | 修改 canonical CodeMap |

实际权限是三层交集：Agent YAML 的写入上限、Action 的 `allowed_write_paths` 与 Workflow 的 `write_roots`。Pilot 为当前 run/action/actor 签发 Action Lease，只有 lease 覆盖的路径可写。

```text
Agent write scopes
       intersect
Action allowed_write_paths
       intersect
Workflow write_roots
       = Action Lease 的有效权限
```

## 一个 Action 如何完成

```text
acp next
  |
  v
Workflow 选择 Action
  |
  v
组装 Action Bundle
  |- identity / role / execution mode
  |- prompt / skill / policy / capability
  |- input contract / output contract
  `- read and write paths
  |
  v
签发 Action Lease -> 执行 Engine 或 LLM Agent
  |
  v
staging output -> deterministic checker / referee
  |                         |
  | failed                  | passed
  v                         v
rework                 finalize -> gate -> state transition
```

LLM 的输出先是候选结果。检查器或 referee 只能评估其合同和证据；最终由 Pilot finalizer 与 gate 决定是否写入规范位置并推进 phase。失败时状态进入 `rework_required`、`human_required`、`blocked` 或 `failed`，恢复必须沿 workflow 已声明的边进行。

## TG 示例

`tg-solve` 同时使用确定性 closure/replay 引擎、lemma producer 和 closure referee。producer 可提交 staging 中的 source evidence；referee 审查它；确定性 finalizer 才能将通过的 exclusion 应用到 ledger。这样“模型提出的不可达判断”不会直接变成覆盖结论。

## 实现与 Reference

- 工作流精确状态、动作和 gate： [Workflow Reference](../reference/workflows.generated.md)
- Agent 身份与 scope： [Agent Matrix](../reference/agent-matrix.generated.md)
- 实现锚点：`pilot/ascendc_pilot/workflows/specs.py`、`authorize/lease.py`、`ownership.py`、`actions/runtime.py`、`state/machine.py`
