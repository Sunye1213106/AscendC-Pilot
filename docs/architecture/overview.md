# 架构总览

这是唯一的 Overall Architecture 文档。模块内部细节分别放在 [UO](../modules/uo.md)、[TG](../modules/tg.md)、[CE](../modules/ce.md) 和 [Pilot Runtime](../modules/pilot-runtime.md)。

## 系统流

```text
User
  -> Host Adapter
  -> Composer-generated host runtime
  -> Primary Agent
  -> Pilot Runtime / Harness
  -> Action Bundle
       -> deterministic engine
       -> bounded LLM agent
            -> Domain Skill
            -> references
  -> Artifact
  -> Gate / Referee
```

## 分层

| 层 | 权威 | 示例 |
| --- | --- | --- |
| Host adapter | Host 相关调用入口 | `adapters/hosts/*.yaml`, `opencode-plugin/` |
| Composer | 生成 host runtime | `scripts/compose_runtime.py`, `generated/` |
| Primary agent | 用户侧协调 | `agents/ascendc-pilot.yaml` |
| Pilot runtime | workflow、state、gate、lease | `pilot/ascendc_pilot/` |
| Workflow spec | action 顺序与 contract 权威 | `pilot/ascendc_pilot/workflows/specs.py` |
| Engine | 确定性产物生产 | `engines/understand-operator/`, `engines/testcase-generation/`, `engines/code-engineering/` |
| LLM agent | 有边界的分析或审查 | `agents/*.yaml` |
| Skill | 领域方法与证据规则 | `skills/*/SKILL.md`, `skills/*/references/` |
| Artifact | 算子本地持久化状态 | `.ascendc-pilot/` |

## 权威规则

每类职责只允许一个可编辑权威：

- Workflow 形状：`pilot/ascendc_pilot/workflows/specs.py`
- Action 写范围：`pilot/ascendc_pilot/ownership.py` 与 action spec override
- Agent 上限：`agents/*.yaml`
- Runtime 权限：Action Lease
- 领域方法：`skills/*/SKILL.md` 与本地 references
- 人类说明：`docs/`

Generated files 和 runtime session prompts 只是这些权威的镜像，不应成为新的 source of truth。
