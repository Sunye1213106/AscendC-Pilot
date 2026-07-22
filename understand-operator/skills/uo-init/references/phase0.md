# Phase0（uo-init）

## Purpose

确认分析范围并建立 MCP 窄索引，使后续 extract 只在已确认文件集合上运行。

## Entry / Exit

| | |
|---|---|
| Entry | 用户触发 `/uo-init` |
| Exit | `scope_confirmed.yaml` + `cbm/index_meta.json` 且 `indexed_via: mcp` |

人读 Step 明细：`docs/uo-init-workflow.md` Phase 0。

## Actions

| # | 谁 | 做什么 | 产物 |
|---|---|---|---|
| 1 | 脚本 | `prepare_operator.py` | `$UO_ROOT/`、manifest 骨架、`current_run_id` |
| 2 | 脚本 | `macro_scope_scan.py --architecture arch35` | `runs/<id>/phase0/scope_proposal.yaml` |
| 3 | 人 | AskQuestion：`continue\|revise\|stop\|manual_supplement`；`review_checkpoint.py` | `scope_confirmed.yaml` |
| 4 | 脚本 | `stage_cbm_scope.py` | `$UO_ROOT/cbm/index_stage/` |
| 5 | MCP | `index_repository`(repo_path=`…/index_stage`, mode=fast) | CBM 项目 |
| 6 | 脚本 | `--write-index-meta`（禁 `--force-new-run`）→ `finalize_phase0.py` | `index_meta.json` |

机制：文件系统启发式扫范围（非 AST）。有 sibling `common/` → confirmed 必须含裁剪后非空子集。

## Hard Constraints

- MUST：等人确认；MCP 只索引 `index_stage`
- MUST NOT：自动 `continue`；把父仓当 `repo_path`；确认前开始 Extract

## Failure Handling

- `stop` → `PHASE0_STOPPED`
- stage / MCP 失败 → `TOOL_FAILURE`（禁整仓兜底索引）
