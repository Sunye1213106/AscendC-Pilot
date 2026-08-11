# Harness 与权限

Harness 是包在 Agent 工作外面的确定性合同。它准备 Action Bundle，签发 Action Lease，校验输出，并且只通过 gate 推动 workflow 状态变化。

## 核心对象

| 对象 | 作用 |
| --- | --- |
| Workflow Spec | 定义 phase、action、gate、actor、output contract 和 write root。 |
| Action Bundle | 单个 action 的 runtime 包，包含 prompt、method、policy、capability、identity 和 contract context。 |
| Action Lease | 单个 run/action/actor 的活动权限令牌。 |
| Gate | 推进 phase 或 workflow 前必须通过的确定性条件。 |
| Referee | 当确定性检查不足时，用有边界的 reviewer 审查证据。 |
| Receipt | 表明 action 在预期 identity 和 contract 下 finalize 的签名证据。 |

## Fail Closed

Agent 和 Skill 不能把 workflow 标记为 passed。状态推进由 Pilot finalizer 和 gates 负责。

失败会停留在当前 phase，并把状态切到 `rework_required`、`human_required`、`blocked` 或 `failed`。Rework 只能沿 `WORKFLOWS` 中声明的边走。

## Lease 模式

| Mode | 状态来源 | 用途 |
| --- | --- | --- |
| `normal` | `running` | 正常 prepare / finalize action。 |
| `rework` | `rework_required` | 重试失败 action 或声明的恢复路径。 |
| `containment` | `human_required`, `blocked`, `failed` | recovery、status、debug、abort 或启动新 run。 |

## 实现锚点

- `pilot/ascendc_pilot/workflows/specs.py`
- `pilot/ascendc_pilot/authorize/lease.py`
- `pilot/ascendc_pilot/ownership.py`
- `pilot/ascendc_pilot/actions/runtime.py`
- `pilot/ascendc_pilot/actions/action_dispatch.py`
- `pilot/ascendc_pilot/gates/`
- `pilot/tests/test_authorize_harness_phase1.py`
- `pilot/tests/test_key_action_boundaries.py`
