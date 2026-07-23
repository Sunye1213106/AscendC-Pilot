# Compositional source schema

| Kind | Path | Required files |
|---|---|---|
| Policy | `policies/<id>/` | `policy.yaml`, `POLICY.md` |
| Capability | `capabilities/<id>/` | `capability.yaml`, `METHOD.md` |
| Action | `actions/<workflow>/<action>/` | `action.yaml`, `METHOD.md` |
| Role | `roles/<id>/` | `role.yaml` |
| Workflow Skill | `workflows/<id>/` | `SKILL.md` |
| Host | `hosts/<host>.yaml` | frontmatter overlays |

Companion sources:

- `prompts/tasks/<domain>/<task>.md`
- `agents/<agent-id>.yaml`

Runtime artifacts are compiled into `generated/<host>/` only.
