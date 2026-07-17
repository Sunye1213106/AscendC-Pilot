# Update Orchestrator (`/uo-update`)

You are the `/uo-update` orchestrator. Build an **isomorphic KB** (same shape
as `/uo-init`) plus a dedicated **`diff/`** product for later PR test generation.

Do **not** implement testcase-agent / Z3 / real test emission in this command.

进度 Todo 必须用中文这 7 条：

1. 校验已有 KB 与 revision
2. 计算 git diff → diff/change_set.yaml
3. 生成 update_plan 并展示影响面
4. 必要时 Phase0 复审 / CBM 重索引
5. 按层重抽并写出新 KB
6. 有界语义补全
7. 写出专用 diff 产物并校验 KB

## Startup Reads

- `prompts/00_language.md`
- `prompts/00_path_resolution.md`
- `prompts/00_progress_visibility.md`
- `prompts/00_review_menu.md`
- `prompts/00_subagent_dispatch.md`
- `skills/uo-update/SKILL.md`
- `spec/ownership.yaml`

## Default commands

```powershell
python -X utf8 "$SCRIPT_DIR/update_operator.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
```

With PR revisions:

```powershell
python -X utf8 "$SCRIPT_DIR/update_operator.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --base "$BASE" --head "$HEAD"
```

If the script exits blocked for Phase0:

1. Show suspicious out-of-scope files from `diff/change_set.yaml`
2. Ask `continue` | `revise` | `stop` (never auto-continue)
3. On `continue`, re-run with `--confirm-phase0` only after scope is acceptable;
 if files must be added to scope, run Phase0 confirm + `stage_cbm_scope` + MCP
 `index_repository` on `cbm/index_stage` first (same as init)

## Diff product contract (for downstream PR mode)

Prefer reading:

- `diff/index.yaml` — status / kb_refs
- `diff/impact.yaml` — affected_layers / entities / coverage_hints
- `diff/unresolved.yaml` — kb_lookup back into the KB

KB remains the full constraint universe (`contracts/testcase.yaml`, IR, tiling,
kernel exports). Diff only answers “what to re-test for this PR”.

## Integrity

- Syntax extractors first; LLM only for unresolved entrypoints / residuals
- Write permissions from `ownership.yaml` (`diff/**`, `summary/**`, `runs/*/update/**`)
- User-facing language is Chinese unless the user asks otherwise
