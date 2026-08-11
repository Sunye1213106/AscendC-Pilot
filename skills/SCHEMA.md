# Skills schema

| Kind | Path | Required files |
|---|---|---|
| **Skill** | `skills/<id>/` | `SKILL.md`（≤200 行）；**必须** `references/gotchas.md` |
| Shared refs | `skills/_shared/` | 跨 Skill 共用证据纪律 |
| Policy | `pilot/policies/<id>/` | `policy.yaml`, `POLICY.md` |
| Tool / runtime capability | `tools/**` · `pilot/runtime/**` · `pilot/gates/**` | `capability.yaml`, `METHOD.md` |
| Host | `adapters/hosts/<host>.yaml` | frontmatter overlays |

Cognitive Skill ids：`operator-analysis`、`testcase-generation`、`source-proof`、`code-review`。

## Boundaries

| 层 | 负责 |
|---|---|
| Skill | 怎么思考 / 怎么做 |
| Tool / runtime capability | 怎么拿数据 / 批处理 / 自检 |
| Prompt | 这一次做什么 |
| Action / Workflow | `pilot/.../workflows/specs.py` |

Lint：`python scripts/check_skill_architecture.py`
