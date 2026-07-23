# scope_confirmation — 范围确认（领域方法）

> 勿在本文件推进 Harness 阶段；只执行 `harness next` 给出的 `scope_confirmation`。

## Purpose

确认分析范围并建立 MCP 窄索引，使后续 extract 只在已确认文件集合上运行。

## Actions

| # | 谁 | 做什么 | 产物 |
|---|---|---|---|
| 1 | 脚本 | `prepare_operator.py` | `$UO_ROOT/`、manifest 骨架、`current_run_id` |
| 2 | 脚本 | `macro_scope_scan.py --architecture arch35` | `scope_proposal.yaml` + stdout 含/不含表 |
| 3 | 人 | AskQuestion：原样转述脚本计数表 → `continue\|revise\|stop\|manual_supplement`；`review_checkpoint.py` | `scope_confirmed.yaml` |
| 4 | 脚本 | `stage_cbm_scope.py` | `$UO_ROOT/cbm/index_stage/` |
| 5 | MCP | `index_repository`(repo_path=`…/index_stage`, mode=fast) | CBM 项目 |
| 6 | 脚本 | `--write-index-meta`（禁 `--force-new-run`）→ `finalize_scope.py` | `index_meta.json` + `runs/*/scope/receipt.yaml` |

机制：文件系统启发式扫范围（非 AST）。有 sibling `common/` → confirmed 必须含裁剪后非空子集。  
默认：**tests / examples / ut / st 不进候选**。

## Hard Constraints

- MUST：等人确认；MCP 只索引 `index_stage`
- MUST：AskQuestion 前转述脚本 INCLUDE/EXCLUDE 表（禁自编 op_host 数）
- MUST NOT：自动 `continue`；把父仓当 `repo_path`；确认前开始结构抽取
- MUST NOT：范围确认阶段派 `explore` / `generalPurpose` 预扫；范围只信 `macro_scope_scan`

## Failure Handling

- `stop` → `SCOPE_STOPPED`
- stage / MCP 失败 → `TOOL_FAILURE`（禁整仓兜底索引）
