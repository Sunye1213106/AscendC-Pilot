# Compositional source schema

| Kind | Path | Required files |
|---|---|---|
| **Domain Skill** | `domain/<id>/` | `SKILL.md`（≤200 行）；可选 `references/**` |
| Policy | `policies/<id>/` | `policy.yaml`, `POLICY.md` |
| Capability | `capabilities/<id>/` | `capability.yaml`, `METHOD.md`（底层工具纪律；非认知主入口） |
| Action | `actions/<workflow>/<action>/` | `action.yaml`, `METHOD.md`（薄指针） |
| Workflow Skill | `workflows/<id>/` | `SKILL.md`（Harness 极薄入口 + GENERATED Actions） |
| Host | `hosts/<host>.yaml` | frontmatter overlays |

Companion sources:

- `prompts/tasks/<domain>/<task>.md` — 短 Task（targets / context / domain 指针）
- `agents/<agent-id>.yaml` — **runtime authority** for agent identity, scopes, and role label

Runtime artifacts are compiled into `generated/<host>/` only.

## Layer responsibilities

| 层 | 只负责 | 不负责 |
|---|---|---|
| Domain Skill | 怎么做好这类任务 | `run_id` / ACP / finalize / Actions 表 |
| Task Prompt | 这一次 targets / context | 完整 workflow、role 手册、capability 转发链 |
| Action Method | 指向 domain skill + 本 Action I/O 边界 | 领域长文、advance |
| Workflow Skill / Spec / Runtime | actor、state、lease、finalize、Actions 表 | 证明/审查算法 |

**一次跳转规则**：Task Prompt → 一个 Domain `SKILL.md` → 按需 `references/`。禁止 Prompt → Method → Capability → LEMMA → PROOF 扇出。

## Field notes

- **`capability.yaml` → `policies:`** — documentation metadata only. Composer ignores it; Action `policy_ids` come from Workflow Spec.
- **`DEFAULT_CAPABILITY_IDS`** — optional global capability list; default `[]`.
- **Task prompts must not hardcode capability lists** that disagree with Spec `capability_ids`.
- **Domain Skill lint**：`SKILL.md` ≤ 200 行；正文禁止 Harness 词（`run_id`、`action_id`、`finalize`、`advance`、`acp start`、`acp next`）。
