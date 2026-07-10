---
name: uo-update
description: >-
  Incrementally update an AscendC operator knowledge base from code changes since
  the last KB snapshot. Use when the user runs /uo-update, understand_operator_update,
  or asks to refresh/patch the KB after code changes.
disable-model-invocation: true
argument-hint: "[path] [--op-name <name>]"
---

# uo-update — Incremental KB Update

Detect code changes since the last KB state and **incrementally** update affected artifacts. Prefer patching over full rebuild.

## Variables（禁止全盘搜索脚本）

- `THIS_SKILL`: 本 `SKILL.md` 所在目录。
- `SCRIPT_DIR`: **优先** `THIS_SKILL/../understand-operator`（须含 `prepare_operator.py`）。
- `PLUGIN_ROOT` / `PROMPT_DIR`: 见 `prompts/00_path_resolution.md`。
- `PROJECT_ROOT`: 算子仓库根。
- `OP_NAME`: `--op-name` 或仓库名。
- `UO_ROOT`: `$PROJECT_ROOT/.understand-operator/$OP_NAME`.

OpenCode：`%USERPROFILE%\.config\opencode\skills\understand-operator\prepare_operator.py`。  
**禁止**全盘 `Get-ChildItem C:\ -Recurse`。

## Global rule

Follow `$PROMPT_DIR/00_cbm_first_rule.md`:
**MCP first for source lookups; on MCP failure, then read source.**

**默认语言：中文。** 见 `$PROMPT_DIR/00_language.md`。TodoWrite / 进度 / 审阅摘要用中文标题。

## Preconditions

- `$UO_ROOT` must exist (from a prior `/uo-init`). If missing → tell user to run `/uo-init`.
- Prefer existing `index.yaml` + `route.md` + `cbm/index_meta.json` as the previous KB baseline.

## Workflow

### 1. Refresh MCP index + detect delta（强制 MCP）

1. MCP `index_repository` — `repo_path=$PROJECT_ROOT`, `mode=fast`（或用户要求 full）  
   （让 MCP 更新 graph DB；不要跑 `update_operator.py` 里的 CLI 索引。）
2. MCP `detect_changes` — `repo_path=$PROJECT_ROOT`
3. 把变更摘要写入 / 更新：
   - `cbm/change_set.yaml`（可由你根据 MCP 结果整理）
   - `archive/runs/update_plan.yaml`
4. 若 project 名有变，刷新 meta：

```powershell
python "$SCRIPT_DIR/prepare_operator.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --write-index-meta --cbm-project "<MCP_PROJECT_NAME>"
```

可选：若只需本地写 plan 骨架且 MCP 已查完，可再跑脚本做 YAML 落盘；**不要**依赖脚本去调 CLI CBM。

The local plan now also writes:

- `archive/runs/update_plan.yaml` with `artifact_invalidations`, `derived_views_to_mark_stale`, `dependency_hash`, and `generator_version`.
- `archive/runs/stale_artifacts.yaml` with stale canonical slices.

Use these stale lists to patch only affected partitions. Do not default to full rebuild unless the plan says `full_rebuild_recommended: true` or the affected scope is unknown and review confirms rebuild.

### 2. Plan impacted phases

| Changed area | Refresh |
|---|---|
| proto / host IO / entry | Phase 1 → `operator.yaml` |
| tiling / host dispatch | host extraction (`tiling/*`) |
| compute / data move / golden semantics | flow extraction (`flow/*`) |
| kernel impl / path | `kernel/paths.yaml` + pipeline/resources |
| accuracy / coverage contract | `test/contract.yaml` + flow golden/numerical |

Canonical v2 partitions:

| Changed area | Also refresh / mark stale |
|---|---|
| operator IO / attrs | `registry/symbols.yaml`, `registry/variables.yaml`, `contracts/query.yaml` |
| host tiling | `cross_layer/input_to_tiling.yaml`, `variable_lineage.yaml`, `contracts/testcase.yaml`, `query/routes.yaml` |
| kernel compile/path | `kernel/compile_model.yaml`, `kernel/variables.yaml`, `kernel/branches.yaml`, `cross_layer/tiling_to_kernel.yaml`, `impact_graph.yaml` |
| cross-layer mapping | `contracts/code_change.yaml`, `contracts/pr_review.yaml`, `contracts/testcase.yaml`, `query/routes.yaml` |

### 3. Incremental re-run

- Re-run **only** impacted phases using the same prompts as `uo-init`.
- Keep human review gates when boundary or kernel dispatch plans materially change.
- After patches: run `quality_gate.py` and update `index.yaml` / `route.md` if needed.
- Before accepting canonical v2 patches, run the deterministic KB compiler (`uo-compile-kb` or quality gate) and inspect `archive/runs/kb_compile_report.yaml`.

### 4. Parallel points

Same as init: only `uo-host-extraction`+`uo-flow-extraction`, and `uo-kernel-path` × N when impacted. Barrier required.

## Report

- What changed in code
- Which KB artifacts were updated vs left untouched
- MCP index / detect_changes 是否成功
