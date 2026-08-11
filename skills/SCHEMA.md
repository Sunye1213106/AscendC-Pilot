# Compositional source schema

| Kind | Path | Required files |
|---|---|---|
| **Domain Skill** | `domain/<id>/` | `SKILL.md`（≤200 行）；**必须** `references/gotchas.md`；可选更多 `references/**`；共用 `domain/_shared/` |
| Policy | `policies/<id>/` | `policy.yaml`, `POLICY.md` |
| Capability | `capabilities/<id>/` | `capability.yaml`, `METHOD.md`（**仅**检索/导航/批处理基础设施） |
| Action | `actions/<workflow>/<action>/` | `action.yaml`, `METHOD.md`（薄：绑定 Domain Skill 或 deterministic） |
| Workflow Skill | `workflows/<id>/` | `SKILL.md`（编排 only + GENERATED Actions） |
| Host | `hosts/<host>.yaml` | frontmatter overlays |

## Boundaries

| 层 | 负责 |
|---|---|
| Workflow | 何时做什么；派发哪个 Domain 任务 |
| Domain Skill | 怎么思考（单一 authority） |
| Capability | 怎么拿数据 / 操作环境 |
| Prompt | 这一次做什么 / 对什么 / 有何证据 |
| Runtime | 身份、写范围、run、contract、finalize |

**禁止**：Domain Skill include 另一 Domain `SKILL.md`；Prompt 承载 Harness 协议；Workflow 复述 E/证明 acceptance；已删除 capability 名残留。

Lint：`python scripts/check_skill_architecture.py`
