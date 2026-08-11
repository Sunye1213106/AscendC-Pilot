# Agent 系统

Agent 是稳定的 runtime identity。它不是文档容器，也不是 workflow 定义。

## 为什么需要 Agent

只有满足以下至少一条时，才值得保留为独立 Agent：

- 需要和主会话隔离上下文
- 需要并行处理 bounded bundle 或 shard
- 需要更窄的读写权限
- 需要 producer / referee 分离
- 需要 adversarial review

否则，应把内容放到 Skill、Action 或 Engine：Skill 承载方法，Action 承载步骤，Engine 承载确定性程序。

## 角色

| Role | 含义 |
| --- | --- |
| Primary | 面向用户协调 workflow，不能自行宣布通过。 |
| Producer | 写 staging output，等待审查或 finalizer。 |
| Referee | 审查 producer output 或 gate evidence。 |
| Readonly analyst | 只读回答或调查，不修改 canonical product。 |
| Deterministic engine | Python 实现身份，用于 authorization 和 receipt。 |

## 权限模型

```text
Agent write_scopes
  intersect Action allowed_write_paths
  intersect Workflow write_roots
  enforced by Action Lease
```

运行时真正生效的是 Action Lease。Agent YAML 只给上限，Workflow Spec 选择 action，lease 绑定当前 run、action、actor 和允许路径。

## 自动生成 Matrix

当前 matrix 从 `agents/*.yaml` 生成：

- [Agent Matrix](../reference/agent-matrix.generated.md)

修改 agent YAML 后重新生成：

```bash
python scripts/generate_agent_matrix.py
```

## 实现锚点

- `agents/*.yaml`
- `pilot/ascendc_pilot/agents_registry.py`
- `pilot/ascendc_pilot/ownership.py`
- `pilot/ascendc_pilot/authorize/lease.py`
- `scripts/compose_runtime.py`
- `scripts/check_ownership_contracts.py`
