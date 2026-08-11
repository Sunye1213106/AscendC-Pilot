# Skills、Prompts 与 Policies

Skill、Prompt 和 Policy 是 runtime input。它们继续放在被 runtime 消费的位置，不复制进 `docs/`。

## 边界

| Asset | 位置 | 职责 |
| --- | --- | --- |
| Skill | `skills/*/SKILL.md` | 领域方法与 progressive disclosure 路由。 |
| Skill reference | `skills/*/references/*.md` | 自包含的 evidence、completeness、gotcha 规则。 |
| Prompt | `prompts/tasks/**/*.md` | Action 级任务说明。 |
| Policy | `pilot/policies/**` | 全局 runtime 约束。 |
| Capability | `tools/**/capability.yaml`, `pilot/runtime/**/capability.yaml` | 工具或 runtime 方法契约。 |
| Generated host instruction | `generated/<host>/` | 安装到 host 的 runtime 投影。 |

`skills/_shared/` 已废弃。Agent 必须读取的共享规则，应复制到相关 skill bundle 内部。

## 权威规则

`docs/` 之外的 Markdown 必须是可执行的 runtime input，而不是项目说明文档。若某个 Markdown 主要给开发者解释项目，应迁移到 `docs/`。

## 实现锚点

- `skills/operator-analysis/`
- `skills/testcase-generation/`
- `skills/source-proof/`
- `skills/code-review/`
- `prompts/tasks/`
- `pilot/policies/`
- `scripts/compose_runtime.py`
- `scripts/check_skill_architecture.py`
