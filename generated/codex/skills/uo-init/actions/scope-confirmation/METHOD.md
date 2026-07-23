# scope_confirmation — 范围确认（领域方法）

> 勿在本文件推进 Harness 阶段；只执行 `harness next` 给出的 `scope_confirmation`。

## Purpose

确认分析范围并建立 MCP 窄索引，使后续 extract 只在已确认文件集合上运行。  
架构中立入口（路径无 `/archNN/`）必须保留；目标架构只约束有效实现分支。

## Actions

| # | 谁 | 做什么 | 产物 |
|---|---|---|---|
| 1 | 脚本 | `prepare_operator.py` | `$UO_ROOT/`、manifest 骨架、`current_run_id` |
| 2 | 脚本 | `macro_scope_scan.py --architecture <arch>` | `scope_proposal.yaml`（含 `candidate_source_files` / `candidate_build_files`） |
| 3 | 人 | AskQuestion：原样转述脚本计数表 → `continue\|revise\|stop\|manual_supplement`；`review_checkpoint.py` | `scope_confirmed.yaml`（`confirmed_source_files` + `confirmed_build_files`） |
| 4 | 脚本 | `extract_build_evidence.py` | `ir/build_evidence.yaml`（CMake 不进 CBM） |
| 5 | 脚本 | `source_closure.py`（受控 restage；有轮次/文件数/allowed_roots 上限） | 更新 confirmed + 可选 restage |
| 6 | 脚本 | `stage_cbm_scope.py` | `$UO_ROOT/cbm/index_stage/`（**仅 source files**） |
| 7 | MCP | `index_repository`(repo_path=`…/index_stage`, mode=fast) | CBM 项目 |
| 8 | 脚本 | `--write-index-meta`（禁 `--force-new-run`）→ `finalize_scope.py` | `index_meta.json` + receipt |

机制：文件系统启发式扫范围（非 AST）。有 sibling `common/` → confirmed 必须含裁剪后非空子集。  
默认：**tests / examples / ut / st 不进候选**。CMake 走 build evidence，不进 CBM。

## Hard Constraints

- MUST：等人确认；MCP 只索引 `index_stage` 中的 **source** 文件
- MUST：AskQuestion 前转述脚本 INCLUDE/EXCLUDE 表（禁自编 op_host 数）
- MUST NOT：自动 `continue`；把父仓当 `repo_path`；确认前开始结构抽取
- MUST NOT：范围确认阶段派 `explore` / `generalPurpose` 预扫；范围只信 `macro_scope_scan` + 受控 closure
- MUST NOT：扫描全部 sibling 算子或整个父仓

## Failure Handling

- `stop` → `SCOPE_STOPPED`
- stage / MCP 失败 → `TOOL_FAILURE`（禁整仓兜底索引）
- 闭包超限 → `missing_scope_dependency*` unresolved（诚实保留）
