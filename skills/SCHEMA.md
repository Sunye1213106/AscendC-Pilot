# Compositional source schema

| Kind | Path | Required files |
|---|---|---|
| Policy | `policies/<id>/` | `policy.yaml`, `POLICY.md` |
| Capability | `capabilities/<id>/` | `capability.yaml`, `METHOD.md` |
| Action | `actions/<workflow>/<action>/` | `action.yaml`, `METHOD.md` |
| Workflow Skill | `workflows/<id>/` | `SKILL.md` |
| Host | `hosts/<host>.yaml` | frontmatter overlays |

Companion sources:

- `prompts/tasks/<domain>/<task>.md`
- `agents/<agent-id>.yaml` — **runtime authority** for agent identity, scopes, and role label (Composer reads these; there is no separate `skills/roles/` tree)

Runtime artifacts are compiled into `generated/<host>/` only.

## Field notes

- **`capability.yaml` → `policies:`** — documentation metadata only. Composer ignores it; Action `policy_ids` come from Workflow Spec (`DEFAULT_POLICY_IDS` / per-action overrides) and are injected at compose time.
- **`DEFAULT_CAPABILITY_IDS`** (`pilot/ascendc_pilot/workflows/specs.py`) — optional global capability list merged (prepended, de-duped) into every action’s `capability_ids` inside `_act()`. Default is `[]`; add an id here only when it is truly universal.
- **Task prompts must not hardcode capability lists** that disagree with the Action’s `capability_ids` in `WORKFLOWS`. Prefer “follow Action-composed capabilities”; `scripts/check_contracts.py` scans for backtick-listed capability ids vs Spec.
